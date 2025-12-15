import os
import re
import time
import random
import logging
import threading
import signal
import sys
from datetime import datetime, timezone, timedelta
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from utils.health_server import start_health_server, controller_state
from utils.reconciler import reconcile_all
from utils.metrics import (
    start_metrics_server, set_controller_info,
    controller_is_leader, controller_healthy, controller_ready
)

# ---------------- Logging Setup ----------------

class SafeFormatter(logging.Formatter):
    def format(self, record):
        for key in ["crd_name", "node", "ip", "zone", "trace", "leader"]:
            if not hasattr(record, key):
                setattr(record, key, "")
        return super().format(record)

base_logger = logging.getLogger("ip-address-controller")
base_logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = SafeFormatter(
    'ts=%(asctime)s level=%(levelname)s msg="%(message)s" crd=%(crd_name)s '
    'node=%(node)s ip=%(ip)s zone=%(zone)s trace=%(trace)s leader=%(leader)s'
)
handler.setFormatter(formatter)
base_logger.addHandler(handler)

class ContextLoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger, identity):
        super().__init__(logger, {})
        self.context = {"crd_name": "", "node": "", "ip": "", "zone": "", "trace": "", "leader": identity}
    def set_context(self, **kwargs):
        self.context.update(kwargs)
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        combined = {**self.context, **extra}
        for k in ["crd_name", "node", "ip", "zone", "trace", "leader"]:
            combined.setdefault(k, "")
        kwargs["extra"] = combined
        return msg, kwargs

# ---------------- K8s Config ----------------
_temp_logger = logging.getLogger("ip-address-controller")
_temp_logger.setLevel(logging.INFO)
_temp_logger.addHandler(handler)

try:
    config.load_incluster_config()
    _temp_logger.info("Using in-cluster config")
except config.ConfigException:
    config.load_kube_config()
    _temp_logger.info("Using local kubeconfig")


v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
crd_api = client.CustomObjectsApi()
coordination_v1 = client.CoordinationV1Api()

# ---------------- Metadata / Identity ----------------

def get_own_pod_name_from_k8s():
    try:
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
            namespace = f.read().strip()
        pod_ip = os.popen("hostname -i").read().strip().split()[0]
        pods = v1.list_namespaced_pod(namespace)
        for pod in pods.items:
            if pod.status.pod_ip == pod_ip:
                return pod.metadata.name
    except Exception as e:
        _temp_logger.warning("Failed to detect pod name via Kubernetes API: {e}")
    return os.uname()[1]

POD_NAME = get_own_pod_name_from_k8s()
IDENTITY = POD_NAME
logger = ContextLoggerAdapter(base_logger, IDENTITY)
logger.info(f"Pod started with identity {IDENTITY}")

# ---------------- Constants ----------------

LEASE_NAME = os.getenv("LEASE_NAME", "ip-address-controller-leader")
LEASE_DURATION = int(os.getenv("LEASE_DURATION", "60"))
SKEW_GRACE = int(os.getenv("LEASE_SKEW_GRACE_SEC", "2"))
RENEW_EVERY = max(1, LEASE_DURATION // 3)
CONTROLLER_VERSION = os.getenv("CONTROLLER_VERSION", "1.0.0")
METRICS_PORT = int(os.getenv("METRICS_PORT", "9999"))

try:
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
        NAMESPACE = f.read().strip()
except Exception:
    NAMESPACE = "default"

controller_state.update({
    "healthy": True,
    "ready": False,
    "last_reconcile_ok": None,
    "leader": False,
    "bootstrapped": False,
    "lease_loop_last_tick": None,
    "lease_duration_seconds": LEASE_DURATION,
})

# ---------------- Health Server ----------------

start_health_server(port=8080, logger=logger)

# ---------------- Metrics Server ----------------

start_metrics_server(port=METRICS_PORT, logger=logger)
set_controller_info(version=CONTROLLER_VERSION, pod_name=POD_NAME)

# ---------------- Helper Functions ----------------

RFC3339_RE = re.compile(
    r"^(?P<prefix>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?P<fraction>\.\d+)?(?P<tz>Z|[+-]\d{2}:\d{2})$"
)

def _now(): return datetime.now(timezone.utc)

def _parse_rfc3339(val):
    if not val: return None
    s = str(val).strip().replace("Z", "+00:00")
    m = RFC3339_RE.match(s)
    if not m: return None
    prefix, fraction, tz = m.group("prefix"), m.group("fraction") or "", m.group("tz")
    us = (fraction[1:] + "000000")[:6]
    try:
        return datetime.fromisoformat(prefix + "." + us + tz)
    except Exception:
        return None

def _to_seconds(val, default):
    try:
        if val is None: return default
        return int(str(val).rstrip("sS"))
    except Exception:
        return default

def _lease_expired(renewed_at, duration):
    if not renewed_at:
        return False
    now = _now()
    if renewed_at > now:
        return False
    buffer = timedelta(seconds=duration + max(SKEW_GRACE, 5))
    return now > renewed_at + buffer

def _pod_exists(pod_name):
    try:
        v1.read_namespaced_pod(pod_name, NAMESPACE)
        return True
    except ApiException as e:
        return e.status != 404

def _annotate_leader(is_leader: bool):
    try:
        body = {"metadata": {"annotations": {"controller-leader": "true" if is_leader else None}}}
        v1.patch_namespaced_pod(POD_NAME, NAMESPACE, body)
        logger.info(f"Updated pod annotation: controller-leader={is_leader}")
    except Exception as e:
        logger.warning(f"Failed to patch leader annotation: {e}")

def _update_controller_metrics():
    """Update controller status metrics."""
    controller_is_leader.labels(pod_name=POD_NAME).set(1 if controller_state.get("leader") else 0)
    controller_healthy.labels(pod_name=POD_NAME).set(1 if controller_state.get("healthy") else 0)
    controller_ready.labels(pod_name=POD_NAME).set(1 if controller_state.get("ready") else 0)

# ---------------- Lease Management ----------------

def _create_lease():
    now = _now()
    body = client.V1Lease(
        metadata=client.V1ObjectMeta(name=LEASE_NAME, namespace=NAMESPACE),
        spec=client.V1LeaseSpec(
            holder_identity=IDENTITY,
            lease_duration_seconds=LEASE_DURATION,
            acquire_time=now,
            renew_time=now,
            lease_transitions=0,
        )
    )
    coordination_v1.create_namespaced_lease(NAMESPACE, body)
    logger.info("Acquired leadership (created lease)")
    return True

def _renew_lease():
    lease = coordination_v1.read_namespaced_lease(LEASE_NAME, NAMESPACE)
    lease.spec.holder_identity = IDENTITY
    lease.spec.renew_time = _now()
    coordination_v1.replace_namespaced_lease(LEASE_NAME, NAMESPACE, lease)
    logger.info("Leader lease renewed")

def _try_takeover(lease):
    now = _now()
    lease.spec.holder_identity = IDENTITY
    lease.spec.acquire_time = now
    lease.spec.renew_time = now
    try:
        coordination_v1.replace_namespaced_lease(LEASE_NAME, NAMESPACE, lease)
        logger.info("Acquired leadership (takeover)")
        return True
    except ApiException as e:
        if e.status == 409:
            return False
        raise

def evaluate_leadership():
    try:
        lease = coordination_v1.read_namespaced_lease(LEASE_NAME, NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            controller_state["bootstrapped"] = True
            return _create_lease()
        raise

    holder = lease.spec.holder_identity or ""
    duration = _to_seconds(lease.spec.lease_duration_seconds, LEASE_DURATION)
    renewed_at = _parse_rfc3339(lease.spec.renew_time)
    expired = _lease_expired(renewed_at, duration)

    logger.info(f"Lease held by {holder}, renewTime={renewed_at}, expired={expired}")
    controller_state["bootstrapped"] = True

    if holder == IDENTITY and not expired:
        return True
    if holder and holder != IDENTITY and _pod_exists(holder) and not expired:
        return False
    return _try_takeover(lease)

# ---------------- Graceful Shutdown ----------------

def shutdown_handler(signum, frame):
    logger.info("Shutdown initiated")
    if controller_state.get("leader"):
        logger.info("Pod was leader, cleaning up")
        _annotate_leader(False)
        controller_state["leader"] = False
        controller_state["ready"] = False
        _update_controller_metrics()
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

# ---------------- Loops ----------------

def lease_renewal_loop():
    while True:
        try:
            controller_state["lease_loop_last_tick"] = _now()
            is_leader = evaluate_leadership()
            controller_state["leader"] = is_leader
            _annotate_leader(is_leader)
            _update_controller_metrics()

            if is_leader:
                try:
                    _renew_lease()
                except Exception as e:
                    logger.error(f"Failed to renew lease: {e}")
                    controller_state["leader"] = False
                    _annotate_leader(False)
                    _update_controller_metrics()

            time.sleep(RENEW_EVERY * random.uniform(0.8, 1.2))
        except Exception as e:
            controller_state["leader"] = False
            _annotate_leader(False)
            _update_controller_metrics()
            logger.error(f"Lease renewal error: {e}")
            time.sleep(RENEW_EVERY)

def controller_loop():
    while True:
        try:
            _update_controller_metrics()
            if controller_state["leader"]:
                logger.info("This instance is leader, starting reconciliation loop")
                try:
                    reconcile_all(v1, apps_v1, crd_api, logger)
                    controller_state["ready"] = True
                    controller_state["last_reconcile_ok"] = _now()
                except Exception as e:
                    logger.error(f"Reconciliation failed: {e}")
                    controller_state["ready"] = False
            else:
                if controller_state["ready"]:
                    logger.info("Lost leadership; marking not ready")
                controller_state["ready"] = False
                logger.info("Not leader, skipping reconciliation")

            _update_controller_metrics()
            time.sleep(5)
        except Exception as e:
            controller_state["ready"] = False
            _update_controller_metrics()
            logger.error(f"Controller main loop error: {e}")
            time.sleep(5)

# ---------------- Entry Point ----------------

if __name__ == "__main__":
    threading.Thread(target=lease_renewal_loop, daemon=True).start()
    controller_loop()

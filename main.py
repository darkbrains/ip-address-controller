import logging
from reconciler import reconcile_all
from kubernetes import client, config

# ---------------- Structured logger ----------------
base_logger = logging.getLogger("ip-address-controller")
base_logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    'ts=%(asctime)s level=%(levelname)s msg="%(message)s" node=%(node)s ip=%(ip)s crd=%(crd_name)s zone=%(zone)s trace=%(trace)s'
)
handler.setFormatter(formatter)
base_logger.handlers = [handler]

# Adapter for structured logging
class DefaultLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        defaults = {"node": "", "ip": "", "crd_name": "", "zone": "", "trace": ""}
        extra = {**defaults, **extra}
        kwargs["extra"] = extra
        return msg, kwargs

logger = DefaultLoggerAdapter(base_logger, {})

# ---------------- Load Kubernetes config ----------------
try:
    config.load_incluster_config()
    logger.info("Using in-cluster config")
except config.ConfigException:
    config.load_kube_config()
    logger.info("Using local kubeconfig")

# ---------------- Create API clients ----------------
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
crd_api = client.CustomObjectsApi()

if __name__ == "__main__":
    reconcile_all(v1, apps_v1, crd_api, logger)

import logging
from kubernetes import client, config
from reconciler import reconcile_all
from health_server import start_health_server, controller_state

# ---------------- Structured logger ----------------
base_logger = logging.getLogger("ip-address-controller")
base_logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    'ts=%(asctime)s level=%(levelname)s msg="%(message)s" crd=%(crd_name)s node=%(node)s ip=%(ip)s zone=%(zone)s trace=%(trace)s'
)
handler.setFormatter(formatter)
base_logger.handlers = [handler]

# Adapter for structured logging
class ContextLoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger):
        super().__init__(logger, {})
        self.context = {"crd_name":"", "node":"", "ip":"", "zone":"", "trace":""}

    def set_context(self, **kwargs):
        self.context.update(kwargs)

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        combined = {**self.context, **extra}

        # Ensure all required logging fields exist
        for key in ["crd_name", "node", "ip", "zone", "trace"]:
            combined.setdefault(key, "")

        kwargs["extra"] = combined
        return msg, kwargs

logger = ContextLoggerAdapter(base_logger)


# Start health server early
start_health_server(port=8080)

# Mark controller as alive
controller_state["healthy"] = True

# ---------------- Load Kubernetes config ----------------
try:
    config.load_incluster_config()
    logger.set_context()
    logger.info("Using in-cluster config")
except config.ConfigException:
    config.load_kube_config()
    logger.set_context()
    logger.info("Using local kubeconfig")

# ---------------- Create API clients ----------------
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
crd_api = client.CustomObjectsApi()


try:
    v1.get_api_resources()  # quick ping to API server
    controller_state["ready"] = True
    logger.info("Controller is ready to reconcile")
except Exception as e:
    logger.error(f"Kubernetes API not ready: {e}")
    controller_state["ready"] = False

if __name__ == "__main__":
    while True:
        try:
            reconcile_all(v1, apps_v1, crd_api, logger)
            controller_state["ready"] = True  # ready only if reconciliation succeeds
        except Exception as e:
            logger.error(f"Reconciliation failed: {e}")
            controller_state["ready"] = False

import logging
from kubernetes import client, config
from reconciler import reconcile_all

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

if __name__ == "__main__":
    reconcile_all(v1, apps_v1, crd_api, logger)

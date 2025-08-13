import logging
from reconciler import reconcile_all
from kubernetes import client, config

# ---------------- Structured logger ----------------
logger = logging.getLogger("ip-address-controller")
handler = logging.StreamHandler()
formatter = logging.Formatter(
    'ts=%(asctime)s level=%(levelname)s msg="%(message)s"'
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

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
    reconcile_all(v1, apps_v1, crd_api)

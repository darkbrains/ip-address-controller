import time
from kubernetes import config
from reconciler import reconcile_all

# Load Kubernetes config
config.load_kube_config()  # or config.load_incluster_config()

if __name__ == "__main__":
    reconcile_all()

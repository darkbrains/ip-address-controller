import time
import logging
from kubernetes import client as k8s_client
from k8s_utils import list_nodes, patch_node_label, patch_deployment_strategy
from cloud import attach_ip

CRD_GROUP = "netinfra.darkbrains.com"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "reservedipdeployments"

crd_api = k8s_client.CustomObjectsApi()

RECONCILE_INTERVAL_DEFAULT = 30  # seconds
last_reconcile = {}

# Structured key-value logging
logger = logging.getLogger("ip-address-controller")
handler = logging.StreamHandler()
formatter = logging.Formatter(
    '{"ts": "%(asctime)s", "level": "%(levelname)s", "msg": "%(message)s"}'
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def reconcile(crd):
    name = crd['metadata']['name']
    namespace = crd['metadata']['namespace']
    spec = crd['spec']

    reserved_ips = spec['reservedIPs']
    node_selector = spec.get('nodeSelector', {})
    deployment_ref = spec['deploymentRef']
    cloud_spec = spec['cloud']
    strategy = spec.get("strategy", {})

    logger.info(f"Reconciling CRD", extra={"crd_name": name, "namespace": namespace})

    # 1. List nodes in pool
    nodes = list_nodes(node_selector)
    node_names = [n.metadata.name for n in nodes]
    logger.info(f"Nodes in pool", extra={"nodes": node_names})

    # 2. Attach IPs
    assigned_nodes = {}
    free_nodes = set(node_names)
    for ip in reserved_ips:
        attached = False
        for node in nodes:
            if attach_ip.node_has_ip(node, ip, cloud_spec):
                assigned_nodes[ip] = node.metadata.name
                free_nodes.discard(node.metadata.name)
                attached = True
                break
        if not attached:
            if not free_nodes:
                logger.warning(
                    f"No free nodes available for IP {ip}",
                    extra={"ip": ip}
                )
                continue
            target_node = free_nodes.pop()
            attach_ip.attach_ip_to_node(cloud_spec, ip, target_node)
            patch_node_label(target_node, {"ip.ready": "true"})
            assigned_nodes[ip] = target_node
            logger.info(
                f"Labeled node as ip.ready",
                extra={"node": target_node, "ip": ip}
            )

    # 3. Patch Deployment strategy only
    patch_deployment_strategy(deployment_ref, strategy)
    logger.info(
        "Patched deployment strategy",
        extra={"deployment": deployment_ref['name'], "strategy": strategy}
    )


def reconcile_all():
    while True:
        crds = crd_api.list_cluster_custom_object(
            CRD_GROUP, CRD_VERSION, CRD_PLURAL
        )['items']
        now = time.time()
        for crd in crds:
            interval = crd['spec'].get('reconcileInterval', RECONCILE_INTERVAL_DEFAULT)
            last = last_reconcile.get(crd['metadata']['name'], 0)
            if now - last >= interval:
                try:
                    reconcile(crd)
                    last_reconcile[crd['metadata']['name']] = now
                except Exception as e:
                    logger.error(
                        "Error during reconcile",
                        extra={"crd_name": crd['metadata']['name'], "error": str(e)}
                    )
        time.sleep(5)

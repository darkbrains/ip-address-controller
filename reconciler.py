import time
import logging
import traceback
from cloud import gcp_attach_ip, gcp_node_has_ip
from k8s_utils import list_nodes, patch_node_label, patch_deployment_strategy

CRD_GROUP = "netinfra.darkbrains.com"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "netipallocations"
RECONCILE_INTERVAL_DEFAULT = 30  # seconds

# ---------------- Structured Logger ----------------
logger = logging.getLogger("ip-address-controller")
handler = logging.StreamHandler()
formatter = logging.Formatter(
    'ts=%(asctime)s level=%(levelname)s msg="%(message)s"'
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ---------------- Reconcile Functions ----------------
def reconcile(crd, v1_client, apps_v1_client):
    name = crd['metadata']['name']
    namespace = crd['metadata'].get('namespace', 'default')
    spec = crd['spec']

    reserved_ips = spec['reservedIPs']
    node_selector = spec.get('nodeSelector', {})
    deployment_ref = spec['deploymentRef']
    cloud_spec = spec['cloud']
    strategy = spec.get("strategy", {})

    logger.info(f"Reconciling CRD",
                extra={"crd_name": name, "namespace": namespace})

    # 1. List nodes in pool
    try:
        nodes = list_nodes(v1_client, node_selector)
        node_names = [n.metadata.name for n in nodes]
        logger.info("Nodes in pool",
                    extra={"nodes": node_names, "crd_name": name})
    except Exception as e:
        tb = traceback.format_exc().replace("\n", " | ")
        logger.error("Failed to list nodes",
                     extra={"error": str(e), "trace": tb, "crd_name": name})
        return

    # 2. Attach IPs and label nodes
    assigned_nodes = {}
    free_nodes = set(node_names)
    for ip in reserved_ips:
        attached = False
        for node in nodes:
            if gcp_node_has_ip(node, ip, cloud_spec):
                assigned_nodes[ip] = node.metadata.name
                free_nodes.discard(node.metadata.name)
                attached = True
                break

        if not attached:
            if not free_nodes:
                logger.warning("No free nodes available for IP",
                               extra={"ip": ip, "crd_name": name})
                continue
            target_node = free_nodes.pop()
            try:
                gcp_attach_ip(cloud_spec, ip, target_node)
                patch_node_label(v1_client, target_node, {"ip.ready": "true"})
                assigned_nodes[ip] = target_node
                logger.info("IP attached and node labeled ip.ready",
                            extra={"node": target_node, "ip": ip, "crd_name": name})
            except Exception as e:
                tb = traceback.format_exc().replace("\n", " | ")
                logger.error("Failed to attach IP or label node",
                             extra={"ip": ip, "node": target_node, "error": str(e), "trace": tb, "crd_name": name})

    # 3. Patch Deployment strategy only
    try:
        patch_deployment_strategy(apps_v1_client, deployment_ref, strategy)
        logger.info("Patched deployment strategy",
                    extra={"deployment": deployment_ref['name'], "strategy": strategy, "crd_name": name})
    except Exception as e:
        tb = traceback.format_exc().replace("\n", " | ")
        logger.error("Failed to patch deployment strategy",
                     extra={"deployment": deployment_ref['name'], "error": str(e), "trace": tb, "crd_name": name})


def reconcile_all(v1_client, apps_v1_client, crd_api_client):
    last_reconcile = {}

    while True:
        try:
            crds = crd_api_client.list_cluster_custom_object(
                CRD_GROUP, CRD_VERSION, CRD_PLURAL
            )['items']
        except Exception as e:
            tb = traceback.format_exc().replace("\n", " | ")
            logger.error("Failed to list CRDs",
                         extra={"error": str(e), "trace": tb})
            time.sleep(10)
            continue

        now = time.time()
        for crd in crds:
            interval = crd['spec'].get('reconcileInterval', RECONCILE_INTERVAL_DEFAULT)
            last = last_reconcile.get(crd['metadata']['name'], 0)
            if now - last >= interval:
                try:
                    reconcile(crd, v1_client, apps_v1_client)
                    last_reconcile[crd['metadata']['name']] = now
                except Exception as e:
                    tb = traceback.format_exc().replace("\n", " | ")
                    logger.error("Error during reconcile",
                                 extra={"crd_name": crd['metadata']['name'], "error": str(e), "trace": tb})

        time.sleep(5)

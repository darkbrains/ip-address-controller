import time
import traceback
from k8s_utils import list_nodes, patch_node_label, patch_deployment_strategy
from cloud.gcp import attach_ip_to_node, node_has_ip, get_gcp_credentials

CRD_GROUP = "netinfra.darkbrains.com"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "netipallocations"
RECONCILE_INTERVAL_DEFAULT = 30  # seconds

def reconcile(crd, v1_client, apps_v1_client, logger):
    name = crd['metadata'].get('name', '')
    spec = crd.get('spec', {})
    reserved_ips = spec.get('reservedIPs', [])
    node_selector = spec.get('nodeSelector', {})
    deployment_ref = spec.get('deploymentRef', {})
    cloud_spec = spec.get('cloud', {})
    strategy = spec.get("strategy", {})

    logger.info("Reconciling CRD", extra={"crd_name": name})

    creds, project = get_gcp_credentials()
    nodes = list_nodes(v1_client, node_selector, logger)
    node_names = [n.metadata.name for n in nodes]
    logger.info("Nodes in pool", extra={"crd_name": name, "node": node_names})

    assigned_nodes = {}
    free_nodes = set(node_names)

    for ip in reserved_ips:
        attached = False
        logger.info("Processing reserved IP", extra={"crd_name": name, "ip": ip})

        for node in nodes:
            try:
                if node_has_ip(node, ip, cloud_spec, creds, project):
                    assigned_nodes[ip] = node.metadata.name
                    free_nodes.discard(node.metadata.name)
                    attached = True
                    logger.info("IP already attached to node", extra={
                        "crd_name": name, "ip": ip, "node": node.metadata.name,
                        "zone": node.metadata.labels.get("topology.kubernetes.io/zone", "")
                    })
                    break
            except Exception:
                tb = traceback.format_exc()
                logger.error("Error checking IP", extra={"crd_name": name, "ip": ip, "node": node.metadata.name, "trace": tb})

        if not attached:
            if not free_nodes:
                logger.warning("No free nodes available for IP", extra={"crd_name": name, "ip": ip})
                continue
            target_node = free_nodes.pop()
            try:
                attach_ip_to_node(cloud_spec, ip, target_node, creds, project, crd_name=name)
                patch_node_label(v1_client, target_node, {"ip.ready": "true"}, logger)
                assigned_nodes[ip] = target_node
                logger.info("IP attached and node labeled ip.ready", extra={"crd_name": name, "ip": ip, "node": target_node})
            except Exception:
                tb = traceback.format_exc()
                logger.error("Error attaching IP to node", extra={"crd_name": name, "ip": ip, "node": target_node, "trace": tb})

    # Patch deployment strategy
    try:
        patch_deployment_strategy(apps_v1_client, deployment_ref, strategy, logger)
        logger.info("Patched deployment strategy", extra={"crd_name": name})
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to patch deployment strategy", extra={"crd_name": name, "trace": tb})

def reconcile_all(v1_client, apps_v1_client, crd_api_client, logger):
    last_reconcile = {}
    while True:
        try:
            crds = crd_api_client.list_cluster_custom_object(CRD_GROUP, CRD_VERSION, CRD_PLURAL).get('items', [])
        except Exception:
            tb = traceback.format_exc()
            logger.error("Failed to list CRDs", extra={"trace": tb})
            time.sleep(10)
            continue

        now = time.time()
        for crd in crds:
            interval = crd.get('spec', {}).get('reconcileInterval', RECONCILE_INTERVAL_DEFAULT)
            last = last_reconcile.get(crd['metadata'].get('name'), 0)
            if now - last >= interval:
                try:
                    reconcile(crd, v1_client, apps_v1_client, logger)
                    last_reconcile[crd['metadata'].get('name')] = now
                except Exception:
                    tb = traceback.format_exc()
                    logger.error("Error during reconcile", extra={"crd_name": crd['metadata'].get('name'), "trace": tb})
        time.sleep(5)

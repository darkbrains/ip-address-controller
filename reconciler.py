import time
import traceback
from k8s_utils import list_nodes, patch_node_label, patch_deployment_strategy
from cloud.gcp import attach_ip_to_node, node_has_ip

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

    logger.set_context(crd_name=name)
    logger.info("Reconciling CRD")

    try:
        nodes = list_nodes(v1_client, node_selector, crd_name=name)
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to list nodes", extra={"trace": tb})
        return

    assigned_nodes = {}
    free_nodes = set(n.metadata.name for n in nodes)

    # Log nodes and zones
    node_names = [n.metadata.name for n in nodes]
    node_zones = [n.metadata.labels.get("topology.kubernetes.io/zone", "") for n in nodes]
    logger.set_context(crd_name=name, node=",".join(node_names), zone=",".join(node_zones))
    logger.info("Listed nodes in pool")

    for ip in reserved_ips:
        logger.set_context(crd_name=name, ip=ip)
        logger.info("Processing reserved IP")
        attached = False
        for node in nodes:
            try:
                node_zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")
                if node_has_ip(node, ip, cloud_spec):
                    assigned_nodes[ip] = node.metadata.name
                    free_nodes.discard(node.metadata.name)
                    attached = True
                    logger.info("IP already attached to node", extra={"node": node.metadata.name, "ip": ip, "zone": node_zone})
                    break
            except Exception:
                tb = traceback.format_exc()
                logger.error("Error checking IP on node", extra={"node": node.metadata.name, "ip": ip, "trace": tb})

        if not attached:
            if not free_nodes:
                logger.warning("No free nodes available for IP", extra={"ip": ip})
                continue
            target_node = free_nodes.pop()
            try:
                attach_ip_to_node(cloud_spec, ip, target_node)
                patch_node_label(v1_client, target_node, {"ip.ready": "true"}, crd_name=name)
                assigned_nodes[ip] = target_node
                logger.info("IP attached and node labeled ip.ready", extra={"node": target_node, "ip": ip})
            except Exception:
                tb = traceback.format_exc()
                logger.error("GCP API error attaching IP to node", extra={"node": target_node, "ip": ip, "trace": tb})

    # Patch deployment only if needed
    try:
        patch_deployment_strategy(apps_v1_client, deployment_ref, strategy, crd_name=name)
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to patch deployment strategy", extra={"deployment": deployment_ref.get('name'), "trace": tb})

    # Final summary log
    nodes_ready = [n.metadata.name for n in nodes if n.metadata.labels.get("ip.ready")=="true"]
    logger.set_context(crd_name=name)
    logger.info("CRD reconcile summary", extra={"assigned_ips": assigned_nodes, "nodes_ready": nodes_ready})

def reconcile_all(v1_client, apps_v1_client, crd_api_client, logger):
    while True:
        try:
            crds = crd_api_client.list_cluster_custom_object(
                group=CRD_GROUP, version=CRD_VERSION, plural=CRD_PLURAL
            ).get("items", [])
            for crd in crds:
                reconcile(crd, v1_client, apps_v1_client, logger)
        except Exception:
            tb = traceback.format_exc()
            logger.set_context(trace=tb)
            logger.error("Failed to list CRDs or reconcile")
        time.sleep(RECONCILE_INTERVAL_DEFAULT)

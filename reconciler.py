import time
import traceback
from k8s_utils import list_nodes, patch_node_label
from cloud.gcp import attach_ip_to_node, detach_ip_from_node, node_has_ip

CRD_GROUP = "netinfra.darkbrains.com"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "netipallocations"
RECONCILE_INTERVAL_DEFAULT = 30  # seconds


def safe_extra(**kwargs):
    """Ensure logging extra has crd_name and ip keys to prevent KeyError."""
    if "crd_name" not in kwargs:
        kwargs["crd_name"] = None
    if "ip" not in kwargs:
        kwargs["ip"] = None
    return kwargs


def is_node_schedulable(node):
    """Return True if node is schedulable (not cordoned)."""
    return not getattr(node.spec, "unschedulable", False)


def is_node_drained(node, v1_client, controller_label="app", logger=None):
    """Determine if a node is drained."""
    if is_node_schedulable(node):
        return False

    node_name = node.metadata.name
    pods = v1_client.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}").items
    for pod in pods:
        labels = pod.metadata.labels or {}
        if labels.get(controller_label):
            return False
    if logger:
        logger.info("Node drained, safe to detach IP", extra=safe_extra(node=node_name))
    return True


def reconcile(crd, v1_client, apps_v1_client, logger):
    name = crd.get('metadata', {}).get('name', '')
    spec = crd.get('spec', {})
    reserved_ips = spec.get('reservedIPs', [])
    node_selector = spec.get('nodeSelector', {})
    cloud_spec = spec.get('cloud', {})

    logger.set_context(crd_name=name)
    logger.info("Reconciling CRD")

    try:
        nodes = list_nodes(v1_client, node_selector, crd_name=name)
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to list nodes", extra={"trace": tb, "crd_name": name})
        return

    assigned_nodes = {}
    free_nodes = set(n.metadata.name for n in nodes)

    for ip in reserved_ips:
        logger.set_context(crd_name=name, ip=ip)
        logger.info("Processing reserved IP")
        attached = False

        for node in nodes:
            node_zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")
            try:
                if node_has_ip(node, ip, creds=cloud_spec.get("credentials")):
                    if is_node_drained(node, v1_client, controller_label="app", logger=logger):
                        detach_ip_from_node(
                            ip, node.metadata.name, v1_client,
                            creds=cloud_spec.get("credentials"),
                            crd_name=name
                        )
                        logger.info("Detached IP from drained node", extra=safe_extra(node=node.metadata.name, ip=ip))
                    else:
                        assigned_nodes[ip] = node.metadata.name
                        attached = True
                        logger.info(
                            "IP already attached to node",
                            extra=safe_extra(node=node.metadata.name, ip=ip, crd_name=name)
                        )
                    break
            except Exception:
                tb = traceback.format_exc()
                logger.error("Error checking IP on node", extra=safe_extra(node=node.metadata.name, ip=ip, trace=tb))

        if not attached:
            free_nodes_schedulable = [n for n in nodes if is_node_schedulable(n) and n.metadata.name in free_nodes]
            if not free_nodes_schedulable:
                logger.warning("No schedulable free nodes available for IP", extra=safe_extra(ip=ip, crd_name=name))
                continue

            target_node = free_nodes_schedulable.pop(0)
            free_nodes.remove(target_node.metadata.name)
            try:
                attach_ip_to_node(
                    ip, target_node.metadata.name,
                    creds=cloud_spec.get("credentials"),
                    crd_name=name
                )
                patch_node_label(v1_client, target_node.metadata.name, {"ip.ready": "true"}, crd_name=name)
                assigned_nodes[ip] = target_node.metadata.name
                logger.info("IP attached and node labeled ip.ready", extra=safe_extra(node=target_node.metadata.name, ip=ip, crd_name=name))
            except Exception:
                tb = traceback.format_exc()
                logger.error("GCP API error attaching IP to node", extra=safe_extra(node=target_node.metadata.name, ip=ip, trace=tb))


def reconcile_all(v1_client, apps_v1_client, crd_api_client, logger):
    """Continuously reconcile all CRDs in the cluster."""
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

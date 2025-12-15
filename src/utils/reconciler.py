import time
import traceback
from utils.k8s_utils import list_nodes, patch_node_label
from cloud.gcp import attach_ip_to_node, detach_ip_from_node, node_has_ip, has_deployment_pods_on_node
from utils.metrics import (
    crd_status, crd_reserved_ips_total, crd_attached_ips_total, crd_unattached_ips_total,
    ip_attached, node_ip_ready, node_cordoned,
    reconcile_total, ip_attach_total, ip_detach_total,
    reconcile_duration_seconds, gcp_api_errors_total
)

CRD_GROUP = "netinfra.darkbrains.com"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "netipallocations"
RECONCILE_INTERVAL_DEFAULT = 30


def safe_extra(**kwargs):
    if "crd_name" not in kwargs:
        kwargs["crd_name"] = None
    if "ip" not in kwargs:
        kwargs["ip"] = None
    if "node" not in kwargs:
        kwargs["node"] = None
    return kwargs


def node_has_any_reserved_ip(node, reserved_ips, creds=None, crd_name=None):
    for ip in reserved_ips:
        if node_has_ip(node, ip, creds=creds, crd_name=crd_name):
            return True
    return False


def is_node_schedulable(node):
    return not getattr(node.spec, "unschedulable", False)


def is_node_drained(node, v1_client, controller_label="app", logger=None, deployment_ref=None):
    """Check if node is drained (no relevant workload pods running)."""
    if is_node_schedulable(node):
        return False

    node_name = node.metadata.name
    pods = v1_client.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}").items
    for pod in pods:
        if pod.metadata.namespace in ("kube-system", "gke-system", "istio-system"):
            continue

        owner_refs = pod.metadata.owner_references or []
        is_daemonset = any(ref.kind == "DaemonSet" for ref in owner_refs)
        if is_daemonset:
            continue

        if deployment_ref:
            dep_name = deployment_ref.get("name", "")
            dep_namespace = deployment_ref.get("namespace", "default")

            for ref in owner_refs:
                if ref.kind == "ReplicaSet" and dep_name in ref.name:
                    if pod.metadata.namespace == dep_namespace:
                        if pod.status.phase in ("Running", "Pending") and not pod.metadata.deletion_timestamp:
                            if logger:
                                logger.info(f"Found deployment pod {pod.metadata.name} on node", extra=safe_extra(node=node_name))
                            return False
        else:
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
    deployment_ref = spec.get("deploymentRef", {})

    logger.set_context(crd_name=name)
    logger.info("Reconciling CRD")

    # Record metrics - reserved IPs count
    crd_reserved_ips_total.labels(crd_name=name).set(len(reserved_ips))

    start_time = time.time()
    attached_count = 0
    unattached_count = 0
    reconcile_success = True

    try:
        nodes = list_nodes(v1_client, node_selector, crd_name=name)
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to list nodes", extra={"trace": tb, "crd_name": name})
        reconcile_total.labels(crd_name=name, status='error').inc()
        crd_status.labels(crd_name=name).set(0)
        return

    # Update node cordoned metrics
    for node in nodes:
        is_cordoned = not is_node_schedulable(node)
        node_cordoned.labels(node=node.metadata.name).set(1 if is_cordoned else 0)

    assigned_nodes = {}
    free_nodes = set(n.metadata.name for n in nodes)

    for ip in reserved_ips:
        logger.set_context(ip=ip, crd_name=name)
        logger.info("Processing reserved IP")
        logger.info(f"DEBUG: Checking {len(nodes)} nodes: {[n.metadata.name for n in nodes]}")
        attached = False

        for node in nodes:
            node_name = node.metadata.name
            logger.set_context(node=node_name)
            # Check if node is cordoned (use different variable name to avoid shadowing import)
            is_node_cordoned = not is_node_schedulable(node)
            try:
                has_ip = node_has_ip(node, ip, creds=cloud_spec.get("credentials"), crd_name=name)
                has_label = node.metadata.labels.get("ip.ready") == "true"

                if has_ip:
                    logger.info(f"DEBUG: Found IP on node, cordoned={is_node_cordoned}", extra=safe_extra(node=node_name, ip=ip))
                    # Update metrics
                    ip_attached.labels(crd_name=name, ip=ip, node=node_name).set(1)
                    node_ip_ready.labels(node=node_name, crd_name=name).set(1 if has_label else 0)

                    node_drained = is_node_drained(node, v1_client, logger=logger, deployment_ref=deployment_ref)

                    should_detach = False
                    if node_drained:
                        should_detach = True
                        logger.info("Node is drained, will detach IP", extra=safe_extra(node=node_name, ip=ip))
                    elif is_node_cordoned:
                        if not has_deployment_pods_on_node(node_name, deployment_ref, v1_client, logger):
                            should_detach = True
                            logger.info("Node is cordoned with no deployment pods, will detach IP", extra=safe_extra(node=node_name, ip=ip))
                        else:
                            logger.info("Node is cordoned but deployment pods still running, keeping IP", extra=safe_extra(node=node_name, ip=ip))

                    if should_detach:
                        try:
                            detach_ip_from_node(
                                ip, node_name, v1_client,
                                creds=cloud_spec.get("credentials"),
                                crd_name=name,
                                deployment_ref=deployment_ref,
                            )
                            patch_node_label(v1_client, node_name, {"ip.ready": None}, crd_name=name)
                            logger.info("Detached IP and removed label from node", extra=safe_extra(node=node_name, ip=ip))
                            # Update metrics
                            ip_detach_total.labels(crd_name=name, status='success').inc()
                            ip_attached.labels(crd_name=name, ip=ip, node=node_name).set(0)
                            node_ip_ready.labels(node=node_name, crd_name=name).set(0)
                        except Exception:
                            tb = traceback.format_exc()
                            logger.error("Failed to detach IP", extra=safe_extra(node=node_name, ip=ip, trace=tb))
                            ip_detach_total.labels(crd_name=name, status='error').inc()
                            gcp_api_errors_total.labels(operation='detach', error_type='api_error').inc()
                            reconcile_success = False
                    else:
                        if not has_label:
                            patch_node_label(v1_client, node_name, {"ip.ready": "true"}, crd_name=name)
                            logger.info("Restored missing ip.ready label", extra=safe_extra(node=node_name, ip=ip))
                            node_ip_ready.labels(node=node_name, crd_name=name).set(1)
                        assigned_nodes[ip] = node_name
                        attached = True
                        attached_count += 1
                        logger.info("IP already attached to node", extra=safe_extra(node=node_name, ip=ip))
                        break

                elif has_label:
                    if not node_has_any_reserved_ip(node, reserved_ips, creds=cloud_spec.get("credentials"), crd_name=name):
                        logger.warning("Node has ip.ready label but has none of the reserved IPs, removing label", extra=safe_extra(node=node_name, ip=ip))
                        patch_node_label(v1_client, node_name, {"ip.ready": None}, crd_name=name)
                        node_ip_ready.labels(node=node_name, crd_name=name).set(0)
                    else:
                        logger.debug("Node has different reserved IP, skipping label removal", extra=safe_extra(node=node_name, ip=ip))

            except Exception:
                tb = traceback.format_exc()
                logger.error("Error checking IP on node", extra=safe_extra(node=node_name, ip=ip, trace=tb))
                gcp_api_errors_total.labels(operation='check_ip', error_type='api_error').inc()
                reconcile_success = False

        if not attached:
            free_nodes_schedulable = [n for n in nodes if is_node_schedulable(n) and n.metadata.name in free_nodes]
            if not free_nodes_schedulable:
                logger.warning("No schedulable free nodes available for IP", extra=safe_extra(ip=ip))
                unattached_count += 1
                ip_attached.labels(crd_name=name, ip=ip, node='none').set(0)
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
                attached_count += 1
                logger.info("IP attached and node labeled ip.ready", extra=safe_extra(node=target_node.metadata.name, ip=ip))
                # Update metrics
                ip_attach_total.labels(crd_name=name, status='success').inc()
                ip_attached.labels(crd_name=name, ip=ip, node=target_node.metadata.name).set(1)
                node_ip_ready.labels(node=target_node.metadata.name, crd_name=name).set(1)
            except Exception:
                tb = traceback.format_exc()
                logger.error("GCP API error attaching IP to node", extra=safe_extra(node=target_node.metadata.name, ip=ip, trace=tb))
                ip_attach_total.labels(crd_name=name, status='error').inc()
                gcp_api_errors_total.labels(operation='attach', error_type='api_error').inc()
                unattached_count += 1
                reconcile_success = False

    # Record final metrics for this CRD
    duration = time.time() - start_time
    reconcile_duration_seconds.labels(crd_name=name).observe(duration)
    crd_attached_ips_total.labels(crd_name=name).set(attached_count)
    crd_unattached_ips_total.labels(crd_name=name).set(unattached_count)

    if reconcile_success and unattached_count == 0:
        crd_status.labels(crd_name=name).set(1)
        reconcile_total.labels(crd_name=name, status='success').inc()
    else:
        crd_status.labels(crd_name=name).set(0)
        reconcile_total.labels(crd_name=name, status='error').inc()

    # --- CLEANUP NODES WITH INVALID LABEL ---
    logger.info("Checking for incorrectly labeled nodes", extra={"crd_name": name})

    try:
        all_nodes = v1_client.list_node().items
        for node in all_nodes:
            node_name = node.metadata.name
            labels = node.metadata.labels or {}
            if labels.get("ip.ready") != "true":
                continue

            try:
                has_valid_ip = node_has_any_reserved_ip(
                    node, reserved_ips,
                    creds=cloud_spec.get("credentials"),
                    crd_name=name
                )
            except Exception:
                has_valid_ip = False
                logger.warning("Could not validate node IPs", extra=safe_extra(node=node_name))

            if not has_valid_ip:
                logger.warning("Node is labeled ip.ready but has no valid reserved IP", extra=safe_extra(node=node_name))
                try:
                    patch_node_label(v1_client, node_name, {"ip.ready": None}, crd_name=name)
                    logger.info("Removed ip.ready label from node", extra=safe_extra(node=node_name))
                    node_ip_ready.labels(node=node_name, crd_name=name).set(0)
                except Exception:
                    logger.error("Failed to remove ip.ready label", extra=safe_extra(node=node_name))

                try:
                    if deployment_ref:
                        deploy_name = deployment_ref.get("name")
                        deploy_ns = deployment_ref.get("namespace", "default")
                        if deploy_name and deploy_ns:
                            pods = v1_client.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}").items
                            for pod in pods:
                                owners = pod.metadata.owner_references or []
                                for owner in owners:
                                    if (
                                        owner.kind == "ReplicaSet" and
                                        owner.name.startswith(deploy_name) and
                                        pod.metadata.namespace == deploy_ns
                                    ):
                                        pod_name = pod.metadata.name
                                        v1_client.delete_namespaced_pod(pod_name, pod.metadata.namespace, grace_period_seconds=0)
                                        logger.warning(f"Evicted pod {deploy_ns}/{pod_name} from invalid node", extra=safe_extra(node=node_name))
                except Exception:
                    tb = traceback.format_exc()
                    logger.error("Error evicting pods from invalid node", extra=safe_extra(node=node_name, trace=tb))

    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to cleanup invalid nodes", extra={"trace": tb, "crd_name": name})


def reconcile_all(v1_client, apps_v1_client, crd_api_client, logger):
    last_reconcile_time = {}

    while True:
        now = time.time()
        try:
            crds = crd_api_client.list_cluster_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                plural=CRD_PLURAL
            ).get("items", [])

            for crd in crds:
                crd_name = crd.get("metadata", {}).get("name", "")
                spec = crd.get("spec", {})
                interval = spec.get("reconcileInterval", RECONCILE_INTERVAL_DEFAULT)

                try:
                    interval = int(interval)
                except (ValueError, TypeError):
                    interval = RECONCILE_INTERVAL_DEFAULT

                last_ts = last_reconcile_time.get(crd_name, 0)
                if now - last_ts < interval:
                    continue

                last_reconcile_time[crd_name] = now
                reconcile(crd, v1_client, apps_v1_client, logger)

        except Exception:
            tb = traceback.format_exc()
            logger.set_context(trace=tb)
            logger.error("Failed to list CRDs or reconcile")

        time.sleep(5)

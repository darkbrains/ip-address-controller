import os
import logging
import traceback
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from google.auth import default
from google.auth.transport.requests import Request
from kubernetes import client as k8s_client

logger = logging.getLogger("ip-address-controller")


def build_compute_service(creds):
    """Create the Compute Engine API client."""
    # Modern google-api-python-client works fine with just credentials=
    return build("compute", "v1", credentials=creds)


def get_gcp_credentials():
    """Detect GCP credentials (JSON key, Workload Identity, or node default)."""
    if hasattr(get_gcp_credentials, "cached"):
        return get_gcp_credentials.cached

    try:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            creds = service_account.Credentials.from_service_account_file(
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
            )
            project = creds.project_id
        else:
            creds, project = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            # Refresh if needed (e.g., Workload Identity)
            if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
                creds.refresh(Request())

        get_gcp_credentials.cached = (creds, project)
        return creds, project
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to get GCP credentials", extra={"trace": tb})
        raise


def node_has_ip(node, ip, creds=None, project=None, crd_name=""):
    """Return True if this node already has the specific external IP."""
    try:
        if creds is None or project is None:
            creds, project = get_gcp_credentials()

        zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")
        instance_name = node.metadata.name
        service = build_compute_service(creds)

        instance = service.instances().get(
            project=project, zone=zone, instance=instance_name
        ).execute()

        for iface in instance.get("networkInterfaces", []):
            for ac in iface.get("accessConfigs", []):
                if ac.get("natIP") == ip:
                    return True
        return False
    except HttpError:
        tb = traceback.format_exc()
        logger.error(
            "GCP API error checking IP",
            extra={"crd_name": crd_name, "node": node.metadata.name, "ip": ip, "zone": zone, "trace": tb},
        )
        return False
    except Exception:
        tb = traceback.format_exc()
        logger.error(
            "Unexpected error in node_has_ip",
            extra={"crd_name": crd_name, "node": node.metadata.name, "ip": ip, "zone": zone, "trace": tb},
        )
        return False


# Optional helper: use this from your reconciler if you want at most ONE reserved IP per node.
def node_has_any_reserved_ip(node, reserved_ips, creds=None, project=None, crd_name=""):
    """Return True if the node already has any IP from the reserved pool."""
    try:
        if creds is None or project is None:
            creds, project = get_gcp_credentials()

        zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")
        instance_name = node.metadata.name
        service = build_compute_service(creds)

        instance = service.instances().get(
            project=project, zone=zone, instance=instance_name
        ).execute()

        reserved_set = set(reserved_ips or [])
        for iface in instance.get("networkInterfaces", []):
            for ac in iface.get("accessConfigs", []):
                if ac.get("natIP") in reserved_set:
                    return True
        return False
    except Exception:
        tb = traceback.format_exc()
        logger.error(
            "Error checking any reserved IP on node",
            extra={"crd_name": crd_name, "node": node.metadata.name, "zone": node.metadata.labels.get("topology.kubernetes.io/zone", ""), "trace": tb},
        )
        return False


def attach_ip_to_node(ip, node_name, creds=None, project=None, crd_name=""):
    """Attach a static external IP to a GKE node (replace existing NAT if present)."""
    try:
        if creds is None or project is None:
            creds, project = get_gcp_credentials()

        v1 = k8s_client.CoreV1Api()
        node = v1.read_node(node_name)
        zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")
        service = build_compute_service(creds)

        # Get the instance and NIC
        instance = service.instances().get(
            project=project, zone=zone, instance=node_name
        ).execute()
        iface = instance["networkInterfaces"][0]
        iface_name = iface["name"]
        access_configs = iface.get("accessConfigs", [])

        # If there's an existing ONE_TO_ONE_NAT, delete it first (natIP is immutable)
        for ac in access_configs:
            if ac.get("type") == "ONE_TO_ONE_NAT":
                service.instances().deleteAccessConfig(
                    project=project,
                    zone=zone,
                    instance=node_name,
                    networkInterface=iface_name,
                    accessConfig=ac["name"],
                ).execute()
                break  # only one external IP per NIC in GKE

        # Add the static external IP
        body = {"name": "external-nat", "type": "ONE_TO_ONE_NAT", "natIP": ip}
        service.instances().addAccessConfig(
            project=project,
            zone=zone,
            instance=node_name,
            networkInterface=iface_name,
            body=body,
        ).execute()

        logger.info(
            "Attached static external IP successfully",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone},
        )

    except HttpError:
        tb = traceback.format_exc()
        logger.error(
            "GCP API error attaching IP",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone, "trace": tb},
        )
        raise
    except Exception:
        tb = traceback.format_exc()
        logger.error(
            "Unexpected error in attach_ip_to_node",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone, "trace": tb},
        )
        raise


def is_node_cordoned(node):
    """Check if node is cordoned (unschedulable)."""
    return getattr(node.spec, 'unschedulable', False) or False


def has_deployment_pods_on_node(node_name, deployment_ref, v1_client, logger):
    """Check if the referenced deployment has pods running on this node."""
    if not deployment_ref:
        return False

    dep_name = deployment_ref.get("name")
    dep_namespace = deployment_ref.get("namespace", "default")
    if not dep_name:
        return False
    try:
        pods = v1_client.list_namespaced_pod(
            namespace=dep_namespace,
            field_selector=f"spec.nodeName={node_name}",
        )

        for pod in pods.items:
            owner_refs = pod.metadata.owner_references or []
            pod_labels = pod.metadata.labels or {}
            for owner in owner_refs:
                if owner.kind == "ReplicaSet" and dep_name in owner.name:
                    if pod.status.phase in ("Running", "Pending") and not pod.metadata.deletion_timestamp:
                        logger.info(
                            f"Found running pod {pod.metadata.name} from deployment {dep_name} on node {node_name}",
                            extra={"node": node_name, "pod": pod.metadata.name, "deployment": dep_name},
                        )
                        return True
            if pod_labels.get("app") == dep_name or pod_labels.get("app.kubernetes.io/name") == dep_name:
                if pod.status.phase in ("Running", "Pending") and not pod.metadata.deletion_timestamp:
                    logger.info(
                        f"Found running pod {pod.metadata.name} (label match) from deployment {dep_name} on node {node_name}",
                        extra={"node": node_name, "pod": pod.metadata.name, "deployment": dep_name},
                    )
                    return True

        return False
    except Exception:
        tb = traceback.format_exc()
        logger.error(
            f"Error checking deployment pods on node",
            extra={"node": node_name, "deployment": dep_name, "namespace": dep_namespace, "trace": tb},
        )
        return True


def detach_ip_from_node(ip, node_name, v1_client, creds=None, project=None, crd_name="", controller_label="app", deployment_ref=None, node_selector=None):
    """Detach the specific static external IP from a drained or cordoned node and re-attach to healthy node."""
    from utils.reconciler import is_node_drained
    node = v1_client.read_node(node_name)
    zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")

    node_cordoned = is_node_cordoned(node)
    node_drained = is_node_drained(node, v1_client, controller_label=controller_label, logger=logger)

    if not node_cordoned and not node_drained:
        logger.info(
            f"Node {node_name} is not cordoned or drained; skipping IP detach",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone},
        )
        return

    if node_cordoned and not node_drained:
        if has_deployment_pods_on_node(node_name, deployment_ref, v1_client, logger):
            logger.info(
                f"Node {node_name} is cordoned but deployment pods still running; skipping IP detach",
                extra={
                    "crd_name": crd_name,
                    "node": node_name,
                    "ip": ip,
                    "zone": zone,
                    "deployment": deployment_ref.get("name") if deployment_ref else None,
                },
            )
            return

    logger.info(
        f"Node {node_name} is ready for IP detach (cordoned={node_cordoned}, drained={node_drained})",
        extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone},
    )

    try:
        if creds is None or project is None:
            creds, project = get_gcp_credentials()
        service = build_compute_service(creds)
        instance = service.instances().get(
            project=project, zone=zone, instance=node_name
        ).execute()
        iface = instance["networkInterfaces"][0]
        access_configs = iface.get("accessConfigs", [])

        ip_detached = False
        for ac in access_configs:
            if ac.get("natIP") == ip:
                service.instances().deleteAccessConfig(
                    project=project,
                    zone=zone,
                    instance=node_name,
                    networkInterface=iface["name"],
                    accessConfig=ac["name"],
                ).execute()
                logger.info(
                    "Detached NAT access config",
                    extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone},
                )
                ip_detached = True
                break

        if not ip_detached:
            logger.info(
                "IP not found on node; nothing to detach",
                extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone},
            )
            return
        new_node = find_healthy_node(v1_client, node_selector, exclude_node=node_name)
        if new_node:
            attach_ip_to_node(ip, new_node.metadata.name, creds=creds, project=project, crd_name=crd_name)
            logger.info(
                "Re-attached IP to healthy node",
                extra={"crd_name": crd_name, "ip": ip, "old_node": node_name, "new_node": new_node.metadata.name},
            )
        else:
            logger.warning(
                "No healthy node found to re-attach IP",
                extra={"crd_name": crd_name, "ip": ip},
            )

    except HttpError:
        tb = traceback.format_exc()
        logger.error(
            "GCP API error detaching IP",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone, "trace": tb},
        )
        raise
    except Exception:
        tb = traceback.format_exc()
        logger.error(
            "Unexpected error in detach_ip_from_node",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone, "trace": tb},
        )
        raise

def find_healthy_node(v1_client, node_selector=None, exclude_node=None):
    """Find a healthy node matching the selector."""
    try:
        nodes = v1_client.list_node()

        for node in nodes.items:
            node_name = node.metadata.name
            if exclude_node and node_name == exclude_node:
                continue

            if is_node_cordoned(node):
                continue
            node_ready = False
            for condition in node.status.conditions or []:
                if condition.type == "Ready" and condition.status == "True":
                    node_ready = True
                    break
            if not node_ready:
                continue
            if node_selector:
                node_labels = node.metadata.labels or {}
                if not all(node_labels.get(k) == v for k, v in node_selector.items()):
                    continue
            return node

        return None
    except Exception:
        tb = traceback.format_exc()
        logger.error("Error finding healthy node", extra={"trace": tb})
        return None

import os
import logging
import traceback

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from google.auth import default
from google.auth.transport.requests import Request
from kubernetes import client as k8s_client
from utils.reconciler import is_node_drained


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


def detach_ip_from_node(ip, node_name, v1_client, creds=None, project=None, crd_name="", controller_label="app"):
    """Detach the specific static external IP from a drained node."""

    node = v1_client.read_node(node_name)

    if not is_node_drained(node, v1_client, controller_label=controller_label, logger=logger):
        logger.info(
            f"Node {node_name} is not drained; skipping IP detach",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": node.metadata.labels.get("topology.kubernetes.io/zone", "")},
        )
        return

    try:
        if creds is None or project is None:
            creds, project = get_gcp_credentials()

        zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")
        service = build_compute_service(creds)

        instance = service.instances().get(
            project=project, zone=zone, instance=node_name
        ).execute()
        iface = instance["networkInterfaces"][0]
        access_configs = iface.get("accessConfigs", [])

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
                return

        logger.info(
            "IP not found on node; nothing to detach",
            extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone},
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

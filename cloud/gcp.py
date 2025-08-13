import logging
import traceback
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.auth import default
from kubernetes import client as k8s_client
import os

logger = logging.getLogger("ip-address-controller")

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
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
        get_gcp_credentials.cached = (creds, project)
        return creds, project
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Failed to get GCP credentials", extra={"trace": tb})
        raise

def node_has_ip(node, ip, cloud_spec, creds=None, project=None):
    """Check if a node already has this IP attached."""
    try:
        if creds is None or project is None:
            creds, project = get_gcp_credentials()
        zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")
        instance_name = node.metadata.name
        service = build("compute", "v1", credentials=creds)

        instance = service.instances().get(project=project, zone=zone, instance=instance_name).execute()
        for iface in instance.get("networkInterfaces", []):
            for ac in iface.get("accessConfigs", []):
                if ac.get("natIP") == ip:
                    return True
        return False
    except HttpError as e:
        tb = traceback.format_exc()
        logger.error("GCP API error checking IP", extra={
            "node": node.metadata.name, "ip": ip, "zone": zone, "trace": tb
        })
        return False
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Unexpected error in node_has_ip", extra={
            "node": node.metadata.name, "ip": ip, "zone": zone, "trace": tb
        })
        return False

def attach_ip_to_node(cloud_spec, ip, node_name, creds=None, project=None, crd_name=""):
    """Attach a static public IP to a GKE node."""
    try:
        if creds is None or project is None:
            creds, project = get_gcp_credentials()
        v1 = k8s_client.CoreV1Api()
        node = v1.read_node(node_name)
        zone = node.metadata.labels.get("topology.kubernetes.io/zone", "")

        service = build("compute", "v1", credentials=creds)
        instance = service.instances().get(project=project, zone=zone, instance=node_name).execute()
        iface_name = instance["networkInterfaces"][0]["name"]
        access_configs = instance["networkInterfaces"][0].get("accessConfigs", [])

        # Update existing NAT
        for ac in access_configs:
            if ac["type"] == "ONE_TO_ONE_NAT":
                ac["natIP"] = ip
                service.instances().updateAccessConfig(
                    project=project,
                    zone=zone,
                    instance=node_name,
                    networkInterface=iface_name,
                    accessConfig=ac["name"],
                    body=ac
                ).execute()
                logger.info("Updated existing NAT with static IP", extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone})
                return

        # Insert new NAT if none
        body = {"name": "external-nat", "type": "ONE_TO_ONE_NAT", "natIP": ip}
        service.instances().addAccessConfig(
            project=project,
            zone=zone,
            instance=node_name,
            networkInterface=iface_name,
            body=body
        ).execute()
        logger.info("Added new NAT access config with static IP", extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone})
    except HttpError as e:
        tb = traceback.format_exc()
        logger.error("GCP API error attaching IP", extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone, "trace": tb})
        raise
    except Exception:
        tb = traceback.format_exc()
        logger.error("Unexpected error in attach_ip_to_node", extra={"crd_name": crd_name, "node": node_name, "ip": ip, "zone": zone, "trace": tb})
        raise

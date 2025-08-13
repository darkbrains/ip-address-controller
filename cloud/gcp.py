import os
import logging
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.auth import default

logger = logging.getLogger("ip-address-controller")

def get_gcp_credentials():
    """
    Detect credentials:
      1. JSON key (GOOGLE_APPLICATION_CREDENTIALS)
      2. In-cluster ServiceAccount token (Workload Identity)
      3. Node default SA
    Returns (credentials, project_id)
    """
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        creds = service_account.Credentials.from_service_account_file(
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        )
        project = creds.project_id
        logger.info("Using GCP JSON key credentials", extra={"project": project})
    else:
        creds, project = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        logger.info("Using in-cluster or node default GCP credentials", extra={"project": project})

    return creds, project

def attach_ip_to_node(cloud_spec, ip, node_name):
    creds, project = get_gcp_credentials()
    region = cloud_spec["region"]

    service = build('compute', 'v1', credentials=creds)
    # TODO: Implement actual Compute Engine API call
    logger.info("Attaching IP to node",
                extra={"ip": ip, "node": node_name, "region": region, "project": project})

def node_has_ip(node, ip, cloud_spec):
    creds, project = get_gcp_credentials()
    region = cloud_spec["region"]

    service = build('compute', 'v1', credentials=creds)
    # TODO: Implement actual check
    logger.info("Checking if node has IP",
                extra={"ip": ip, "node": node.metadata.name, "region": region, "project": project})
    return False  # placeholder

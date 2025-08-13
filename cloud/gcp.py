import traceback
from googleapiclient.discovery import build
from google.oauth2 import service_account
from httplib2 import Http

def get_compute_service(creds, timeout=60):
    """
    Returns GCP Compute Engine service client with proper timeout to avoid httplib2 warnings.
    """
    http = Http(timeout=timeout)
    return build("compute", "v1", credentials=creds, cache_discovery=False, http=http)

def attach_ip_to_node(cloud_spec, ip, node_name):
    zone = cloud_spec.get("zone")
    project = cloud_spec.get("project")
    try:
        # Example attach call
        creds = cloud_spec.get("credentials")
        compute = get_compute_service(creds)
        # This is simplified example; actual API call depends on your IP attachment logic
        # compute.instances().addAccessConfig(...).execute()
    except Exception:
        tb = traceback.format_exc()
        # Make sure zone is always defined for logging
        zone_log = zone if zone else "unknown"
        node_log = node_name if node_name else "unknown"
        print(f"Error attaching IP: node={node_log}, ip={ip}, zone={zone_log}\n{tb}")
        # Optionally raise or log using your logger
        raise


def node_has_ip(node, ip, cloud_spec):
    """
    Return True if node already has the IP assigned.
    """
    # Example logic; replace with actual check
    node_ips = getattr(node.status, "addresses", [])
    for addr in node_ips:
        if getattr(addr, "address", None) == ip:
            return True
    return False

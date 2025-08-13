def attach_ip_to_node(cloud_spec, ip, node_name):
    # TODO: Implement GCP Compute API call to attach the IP
    print(f"[GCP] Attaching IP {ip} to node {node_name} in region {cloud_spec['region']}")

def node_has_ip(node, ip, cloud_spec):
    # TODO: Implement check via GCP API if the IP is attached
    return False  # Placeholder

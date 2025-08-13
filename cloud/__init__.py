# cloud/__init__.py
from .gcp import attach_ip_to_node as gcp_attach_ip, node_has_ip as gcp_node_has_ip
from .aws import attach_ip_to_node as aws_attach_ip, node_has_ip as aws_node_has_ip
from .azure import attach_ip_to_node as azure_attach_ip, node_has_ip as azure_node_has_ip

__all__ = [
    "gcp_attach_ip", "gcp_node_has_ip",
    "aws_attach_ip", "aws_node_has_ip",
    "azure_attach_ip", "azure_node_has_ip",
]

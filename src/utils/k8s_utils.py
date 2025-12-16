
import traceback

def list_nodes(v1_client, label_selector, logger=None, crd_name=""):
    try:
        selector = ",".join([f"{k}={v}" for k,v in label_selector.items()])
        nodes = v1_client.list_node(label_selector=selector).items
        if logger:
            logger.set_context(crd=crd_name)
            logger.info("Listed nodes in pool", extra={"nodes": [n.metadata.name for n in nodes]})
        return nodes
    except Exception:
        tb = traceback.format_exc()
        if logger:
            logger.set_context(crd=crd_name, trace=tb)
            logger.error("Failed to list nodes")
        raise

def patch_node_label(v1_client, node_name, labels, logger=None, crd_name=""):
    try:
        body = {"metadata":{"labels": labels}}
        v1_client.patch_node(node_name, body)
        if logger:
            logger.set_context(crd=crd_name, node=node_name)
            logger.info("Patched node labels", extra={"labels": labels})
    except Exception:
        tb = traceback.format_exc()
        if logger:
            logger.set_context(crd=crd_name, node=node_name, trace=tb)
            logger.error("Failed to patch node labels")
        raise

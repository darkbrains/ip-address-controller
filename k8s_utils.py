from kubernetes import client
import logging

logger = logging.getLogger("ip-address-controller")

def list_nodes(v1_client, label_selector):
    selector = ",".join([f"{k}={v}" for k, v in label_selector.items()])
    nodes = v1_client.list_node(label_selector=selector).items
    node_names = [n.metadata.name for n in nodes]
    logger.info(f"Listed nodes in pool", extra={"nodes": node_names})
    return nodes

def patch_node_label(v1_client, node_name, labels):
    body = {"metadata": {"labels": labels}}
    v1_client.patch_node(node_name, body)
    logger.info(f"Patched node labels", extra={"node": node_name, "labels": labels})

def patch_deployment_strategy(apps_v1_client, deployment_ref, strategy):
    dep_name = deployment_ref['name']
    dep_namespace = deployment_ref['namespace']
    dep = apps_v1_client.read_namespaced_deployment(dep_name, dep_namespace)

    if dep.spec.strategy.type is None:
        dep.spec.strategy.type = "RollingUpdate"

    rolling_update = dep.spec.strategy.rolling_update or client.V1RollingUpdateDeployment()
    rolling_update.max_surge = strategy.get("maxSurge", rolling_update.max_surge)
    rolling_update.max_unavailable = strategy.get("maxUnavailable", rolling_update.max_unavailable)

    dep.spec.strategy.rolling_update = rolling_update
    apps_v1_client.patch_namespaced_deployment(dep_name, dep_namespace, dep)
    logger.info("Patched deployment strategy", extra={"deployment": dep_name, "strategy": strategy})

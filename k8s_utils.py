from kubernetes import client
import traceback

def list_nodes(v1_client, label_selector, logger):
    try:
        selector = ",".join([f"{k}={v}" for k, v in label_selector.items()])
        nodes = v1_client.list_node(label_selector=selector).items
        node_names = [n.metadata.name for n in nodes]
        zones = [n.metadata.labels.get("topology.kubernetes.io/zone", "") for n in nodes]
        logger.info("Listed nodes in pool", extra={"nodes": node_names, "zone": zones})
        return nodes
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to list nodes", extra={"trace": tb})
        raise

def patch_node_label(v1_client, node_name, labels, logger):
    try:
        body = {"metadata": {"labels": labels}}
        v1_client.patch_node(node_name, body)
        logger.info("Patched node labels", extra={"node": node_name, "labels": labels})
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to patch node labels", extra={"node": node_name, "labels": labels, "trace": tb})
        raise

def patch_deployment_strategy(apps_v1_client, deployment_ref, strategy, logger):
    try:
        dep_name = deployment_ref.get('name')
        dep_namespace = deployment_ref.get('namespace', 'default')
        dep = apps_v1_client.read_namespaced_deployment(dep_name, dep_namespace)

        if dep.spec.strategy.type is None:
            dep.spec.strategy.type = "RollingUpdate"

        rolling_update = dep.spec.strategy.rolling_update or client.V1RollingUpdateDeployment()
        rolling_update.max_surge = strategy.get("maxSurge", rolling_update.max_surge)
        rolling_update.max_unavailable = strategy.get("maxUnavailable", rolling_update.max_unavailable)

        dep.spec.strategy.rolling_update = rolling_update
        apps_v1_client.patch_namespaced_deployment(dep_name, dep_namespace, dep)
        logger.info("Patched deployment strategy", extra={"deployment": dep_name, "strategy": strategy})
    except Exception:
        tb = traceback.format_exc()
        logger.error("Failed to patch deployment strategy", extra={"deployment": deployment_ref.get('name'), "trace": tb})
        raise

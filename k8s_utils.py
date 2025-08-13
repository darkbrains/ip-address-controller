from kubernetes import client

apps_v1 = client.AppsV1Api()
v1 = client.CoreV1Api()

def list_nodes(label_selector):
    selector = ",".join([f"{k}={v}" for k,v in label_selector.items()])
    return v1.list_node(label_selector=selector).items

def patch_node_label(node_name, labels):
    body = {"metadata": {"labels": labels}}
    v1.patch_node(node_name, body)

def patch_deployment_strategy(deployment_ref, strategy):
    dep_name = deployment_ref['name']
    dep_namespace = deployment_ref['namespace']
    dep = apps_v1.read_namespaced_deployment(dep_name, dep_namespace)

    if dep.spec.strategy.type is None:
        dep.spec.strategy.type = "RollingUpdate"

    rolling_update = dep.spec.strategy.rolling_update or client.V1RollingUpdateDeployment()
    rolling_update.max_surge = strategy.get("maxSurge", rolling_update.max_surge)
    rolling_update.max_unavailable = strategy.get("maxUnavailable", rolling_update.max_unavailable)

    dep.spec.strategy.rolling_update = rolling_update
    apps_v1.patch_namespaced_deployment(dep_name, dep_namespace, dep)

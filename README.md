# ip-address-controller

This is a Kubernetes controller that manages static external IPs for cloud VM nodes based on custom CRDs. It is designed for GCP, AWS, and Azure, with built-in leader election and node management.

---

## ✨ Features

- Automatically attaches static external IPs to nodes.
- Leader election ensures only one active controller.
- Labels nodes with `ip.ready` when IP is attached.
- Evicts pods from misconfigured nodes.
- Supports GCP, AWS, and Azure.
- Configurable reconciliation interval.

---

## 📦 CRD: `NetIPAllocation`

You define a `NetIPAllocation` resource that looks like this:

```yaml
apiVersion: netinfra.darkbrains.com/v1alpha1
kind: NetIPAllocation
metadata:
  name: example-allocation
spec:
  reservedIPs:
    - 34.123.45.67
    - 34.123.45.68
  deploymentRef:
    name: my-app
    namespace: default
  nodeSelector:
    role: external-ip-node
  cloud:
    provider: gcp
    region: us-west1
    zones:
      - us-west1-a
      - us-west1-b
  strategy:
    maxSurge: 1
    maxUnavailable: 1
  reconcileInterval: 60
```

## ☸️ Deploy to Kubernetes

First you need to install CRDs:

```bash
kubectl apply -f crds/
```

Then you need to install controller in the Kubernetes:
```bash
kubectl apply -f k8s/
```

## 🧪 Health Endpoints

- `GET /healthz` – Liveness probe

- `GET /readyz` – Readiness probe

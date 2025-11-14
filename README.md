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

## ❤️ Support this project

If you’d like to support **Dark Brains**, you can sponsor us directly on GitHub:
👉 [**Sponsor via GitHub**](https://github.com/sponsors/darkbrains)

Or donate via crypto:

- 💰 **Bitcoin**: [136Ypsq1db3kAFBZFJ4r887cHB95cqxfFa](https://www.blockchain.com/btc/address/136Ypsq1db3kAFBZFJ4r887cHB95cqxfFa)
- 💎 **Ethereum**: [0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888](https://etherscan.io/address/0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888)
- 💵 **USDT (ERC20)**: [0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888](https://etherscan.io/token/0xdac17f958d2ee523a2206206994597c13d831ec7?a=0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888)

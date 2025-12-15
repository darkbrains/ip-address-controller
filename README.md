# 🌐 IP Address Controller

A Kubernetes controller that manages static external IPs for cloud VM nodes based on custom CRDs. Automatically allocates, reallocates, and monitors public IP addresses across your cluster with built-in leader election and comprehensive observability.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **Automatic IP Allocation** | Attaches static external IPs to nodes automatically |
| 🏷️ **Node Labeling** | Labels nodes with `ip.ready=true` when IP is attached |
| 🔁 **Smart Reallocation** | Detaches IPs from cordoned/drained nodes and reallocates to healthy nodes |
| 👑 **Leader Election** | Ensures only one active controller via Kubernetes Lease |
| 🚀 **Pod Eviction** | Evicts pods from misconfigured nodes |
| ☁️ **Multi-Cloud** | Supports GCP, AWS, and Azure |
| 📊 **Prometheus Metrics** | Built-in metrics for monitoring and alerting |
| ⚙️ **Configurable** | Per-CRD reconciliation intervals and strategies |

---

## 📦 CRD: `NetIPAllocation`

Define a `NetIPAllocation` resource to manage your static IPs:
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

### Spec Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reservedIPs` | `[]string` | ✅ | List of static external IPs to manage |
| `deploymentRef` | `object` | ❌ | Reference to deployment for pod-aware reallocation |
| `deploymentRef.name` | `string` | ✅ | Deployment name |
| `deploymentRef.namespace` | `string` | ❌ | Deployment namespace (default: `default`) |
| `nodeSelector` | `map[string]string` | ❌ | Node labels to filter eligible nodes |
| `cloud.provider` | `string` | ✅ | Cloud provider: `gcp`, `aws`, or `azure` |
| `cloud.region` | `string` | ❌ | Cloud region |
| `cloud.zones` | `[]string` | ❌ | Availability zones |
| `strategy.maxSurge` | `int` | ❌ | Max extra IPs during reallocation |
| `strategy.maxUnavailable` | `int` | ❌ | Max unavailable IPs during reallocation |
| `reconcileInterval` | `int` | ❌ | Reconciliation interval in seconds (default: `30`) |

---

## 🚀 Quick Start

### 1. Install CRDs
```bash
kubectl apply -f crds/
```

### 2. Deploy Controller
```bash
kubectl apply -f k8s/
```

### 3. Create NetIPAllocation
```bash
kubectl apply -f - <<EOF
apiVersion: netinfra.darkbrains.com/v1alpha1
kind: NetIPAllocation
metadata:
  name: my-app-ips
spec:
  reservedIPs:
    - 34.123.45.67
  deploymentRef:
    name: my-app
    namespace: default
  nodeSelector:
    role: public-node
  cloud:
    provider: gcp
    region: us-central1
  reconcileInterval: 30
EOF
```

### 4. Verify
```bash
# Check CRD status
kubectl get netipallocations

# Check node labels
kubectl get nodes -l ip.ready=true

# Check controller logs
kubectl logs -l app=ip-address-controller -f
```

---

## 📊 Observability

### Health Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /healthz` | Liveness probe - controller is running |
| `GET /readyz` | Readiness probe - controller is ready to reconcile |
| `GET /metrics` | Prometheus metrics endpoint (port 9090) |

### Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `netipallocation_crd_status` | Gauge | CRD health (1=healthy, 0=unhealthy) |
| `netipallocation_reserved_ips_total` | Gauge | Total reserved IPs per CRD |
| `netipallocation_attached_ips_total` | Gauge | Currently attached IPs per CRD |
| `netipallocation_unattached_ips_total` | Gauge | Unattached IPs per CRD |
| `netipallocation_ip_attached` | Gauge | IP attachment status per node |
| `netipallocation_node_cordoned` | Gauge | Node cordon status |
| `netipallocation_node_ip_ready` | Gauge | Node ip.ready label status |
| `netipallocation_controller_is_leader` | Gauge | Leader election status |
| `netipallocation_controller_ready` | Gauge | Controller readiness |
| `netipallocation_reconcile_total` | Counter | Reconciliation runs by status |
| `netipallocation_ip_attach_total` | Counter | IP attach operations by status |
| `netipallocation_ip_detach_total` | Counter | IP detach operations by status |
| `netipallocation_gcp_api_errors_total` | Counter | GCP API errors by operation |
| `netipallocation_reconcile_duration_seconds` | Histogram | Reconciliation duration |

### Example Prometheus Queries
```promql
# Overall health - all CRDs healthy
sum(netipallocation_crd_status) == count(netipallocation_crd_status)

# IP attachment rate
sum(netipallocation_attached_ips_total) / sum(netipallocation_reserved_ips_total) * 100

# Reconciliation error rate
rate(netipallocation_reconcile_total{status="error"}[5m]) / rate(netipallocation_reconcile_total[5m])

# Average reconcile duration
avg(rate(netipallocation_reconcile_duration_seconds_sum[5m]) / rate(netipallocation_reconcile_duration_seconds_count[5m]))

# Cordoned nodes with IPs (potential issue)
netipallocation_node_cordoned == 1 and netipallocation_ip_attached == 1
```

### Recommended Alerts

| Alert | Severity | Condition |
|-------|----------|-----------|
| `NetIPAllocationNoLeader` | Critical | No leader for 2m |
| `NetIPAllocationCRDUnhealthy` | Critical | CRD status=0 for 5m |
| `NetIPAllocationUnattachedIPs` | Warning/Critical | Unattached IPs for 5m/10m |
| `NetIPAllocationGCPAPIErrors` | Warning | GCP API errors detected |
| `NetIPAllocationNodeCordonedWithIP` | Warning | Cordoned node still has IP |

---

## 🔄 How It Works
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           IP Address Controller                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Leader Election                                   │
│                    (Kubernetes Lease in namespace)                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Reconciliation Loop                                 │
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ List CRDs   │───▶│ List Nodes  │───▶│ Check IPs   │───▶│ Attach/     │  │
│  │             │    │ (selector)  │    │ on Nodes    │    │ Detach IPs  │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Node State Handling                                │
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ Healthy Node     │  │ Cordoned Node    │  │ Drained Node     │          │
│  │ ──────────────── │  │ ──────────────── │  │ ──────────────── │          │
│  │ Keep IP attached │  │ Check if pods    │  │ Detach IP        │          │
│  │ Label ip.ready   │  │ still running    │  │ Remove label     │          │
│  │                  │  │ → Yes: Keep IP   │  │ Reallocate       │          │
│  │                  │  │ → No: Detach IP  │  │                  │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Reallocation Flow

1. **Node Cordoned** → Controller detects `spec.unschedulable: true`
2. **Check Pods** → If deployment pods still running, keep IP
3. **No Pods** → Detach IP from cordoned node
4. **Find Healthy Node** → Select schedulable node matching `nodeSelector`
5. **Attach IP** → Attach IP to new node via cloud API
6. **Label Node** → Add `ip.ready=true` label
7. **Pod Scheduling** → Pods with `nodeAffinity` for `ip.ready=true` can now schedule

---

## ☁️ Cloud Provider Setup

### GCP

The controller uses Workload Identity or service account credentials.

**Required IAM Permissions:**
```
compute.instances.get
compute.instances.addAccessConfig
compute.instances.deleteAccessConfig
```

**Workload Identity Setup:**
```bash
# Create GCP service account
gcloud iam service-accounts create ip-controller-sa

# Grant permissions
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:ip-controller-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/compute.instanceAdmin.v1"

# Bind to Kubernetes service account
gcloud iam service-accounts add-iam-policy-binding ip-controller-sa@PROJECT_ID.iam.gserviceaccount.com \
  --member="serviceAccount:PROJECT_ID.svc.id.goog[NAMESPACE/ip-address-controller]" \
  --role="roles/iam.workloadIdentityUser"
```

### AWS (Coming Soon)

### Azure (Coming Soon)

---

## 🛠️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LEASE_NAME` | `ip-address-controller-leader` | Kubernetes Lease name |
| `LEASE_DURATION` | `60` | Lease duration in seconds |
| `METRICS_PORT` | `9090` | Prometheus metrics port |
| `CONTROLLER_VERSION` | `1.0.0` | Controller version for metrics |

### RBAC Requirements

The controller needs the following permissions:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ip-address-controller
rules:
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["get", "list", "watch", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch", "delete"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["netinfra.darkbrains.com"]
    resources: ["netipallocations"]
    verbs: ["get", "list", "watch"]
```

---

## 🧪 Development

### Local Testing
```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (uses kubeconfig)
python main.py
```

### Build Docker Image
```bash
docker build -t ip-address-controller:latest .
```

### Run Tests
```bash
pytest tests/
```

---

## 📝 Troubleshooting

### Common Issues

**IP not attaching to node:**
```bash
# Check controller logs
kubectl logs -l app=ip-address-controller

# Verify node has correct labels
kubectl get nodes -l role=your-selector

# Check GCP permissions
gcloud compute instances describe NODE_NAME --zone=ZONE
```

**Controller not becoming leader:**
```bash
# Check lease
kubectl get lease ip-address-controller-leader -n NAMESPACE -o yaml

# Check if old leader pod exists
kubectl get pods -l app=ip-address-controller
```

**IPs stuck on cordoned node:**
```bash
# Check if deployment pods are still running
kubectl get pods -o wide | grep NODE_NAME

# Force reconciliation by restarting controller
kubectl rollout restart deployment/ip-address-controller
```

---

## 📄 License

Apache License 2.0

---

## ❤️ Support This Project

If you'd like to support **Dark Brains**, you can sponsor us directly on GitHub:

👉 [**Sponsor via GitHub**](https://github.com/sponsors/darkbrains)

Or donate via crypto:

| Currency | Address |
|----------|---------|
| 💰 **Bitcoin** | [`136Ypsq1db3kAFBZFJ4r887cHB95cqxfFa`](https://www.blockchain.com/btc/address/136Ypsq1db3kAFBZFJ4r887cHB95cqxfFa) |
| 💎 **Ethereum** | [`0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888`](https://etherscan.io/address/0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888) |
| 💵 **USDT (ERC20)** | [`0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888`](https://etherscan.io/token/0xdac17f958d2ee523a2206206994597c13d831ec7?a=0xcfdc4b4c12a743e35c2906317dfe4f58dd8c0888) |

---

<div align="center">

**Built with 🧠 by [Dark Brains](https://github.com/darkbrains)**

[![GitHub Stars](https://img.shields.io/github/stars/darkbrains/ip-address-controller?style=social)](https://github.com/darkbrains/ip-address-controller)

</div>

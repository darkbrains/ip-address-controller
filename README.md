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
| 📈 **Grafana Dashboard** | Pre-built dashboard with cluster filtering |
| ⚙️ **Configurable** | Per-CRD reconciliation intervals |
| 🔀 **Multiple Workload Types** | Supports Deployment, StatefulSet, and DaemonSet |

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
  workloadRef:
    kind: Deployment
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
  reconcileInterval: 60
```

### Spec Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reservedIPs` | `[]string` | ✅ | List of static external IPs to manage |
| `workloadRef` | `object` | ❌ | Reference to workload for pod-aware reallocation |
| `workloadRef.kind` | `string` | ✅ | Workload type: `Deployment`, `StatefulSet`, or `DaemonSet` |
| `workloadRef.name` | `string` | ✅ | Workload name |
| `workloadRef.namespace` | `string` | ❌ | Workload namespace (default: `default`) |
| `nodeSelector` | `map[string]string` | ❌ | Node labels to filter eligible nodes |
| `cloud.provider` | `string` | ✅ | Cloud provider: `gcp`, `aws`, or `azure` |
| `cloud.region` | `string` | ❌ | Cloud region |
| `cloud.zones` | `[]string` | ❌ | Availability zones |
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
  workloadRef:
    kind: Deployment
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

## 🔀 Workload Types

The controller supports multiple Kubernetes workload types for pod-aware IP reallocation:

### Deployment
```yaml
workloadRef:
  kind: Deployment
  name: my-deployment
  namespace: default
```

### StatefulSet
```yaml
workloadRef:
  kind: StatefulSet
  name: my-statefulset
  namespace: default
```

### DaemonSet
```yaml
workloadRef:
  kind: DaemonSet
  name: my-daemonset
  namespace: default
```

The controller checks if pods from the referenced workload are still running on a node before detaching its IP during cordon/drain operations.

---

## 📊 Observability

### Health Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /healthz` | Liveness probe - controller is running |
| `GET /readyz` | Readiness probe - controller is ready to reconcile |
| `GET /metrics` | Prometheus metrics endpoint (port 9999) |

### Prometheus Metrics

All metrics support an optional `cluster` label for multi-cluster environments. Set the `CLUSTER_NAME` environment variable to enable it.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `netipallocation_crd_status` | Gauge | `cluster`, `crd_name` | CRD health (1=healthy, 0=unhealthy) |
| `netipallocation_reserved_ips_total` | Gauge | `cluster`, `crd_name` | Total reserved IPs per CRD |
| `netipallocation_attached_ips_total` | Gauge | `cluster`, `crd_name` | Currently attached IPs per CRD |
| `netipallocation_unattached_ips_total` | Gauge | `cluster`, `crd_name` | Unattached IPs per CRD |
| `netipallocation_ip_attached` | Gauge | `cluster`, `crd_name`, `ip`, `node` | IP attachment status per node |
| `netipallocation_node_cordoned` | Gauge | `cluster`, `node` | Node cordon status |
| `netipallocation_node_ip_ready` | Gauge | `cluster`, `node`, `crd_name` | Node ip.ready label status |
| `netipallocation_controller_is_leader` | Gauge | `cluster`, `pod_name` | Leader election status |
| `netipallocation_controller_ready` | Gauge | `cluster`, `pod_name` | Controller readiness |
| `netipallocation_controller_healthy` | Gauge | `cluster`, `pod_name` | Controller health status |
| `netipallocation_reconcile_total` | Counter | `cluster`, `crd_name`, `status` | Reconciliation runs by status |
| `netipallocation_ip_attach_total` | Counter | `cluster`, `crd_name`, `status` | IP attach operations by status |
| `netipallocation_ip_detach_total` | Counter | `cluster`, `crd_name`, `status` | IP detach operations by status |
| `netipallocation_gcp_api_errors_total` | Counter | `cluster`, `operation`, `error_type` | GCP API errors by operation |
| `netipallocation_reconcile_duration_seconds` | Histogram | `cluster`, `crd_name` | Reconciliation duration |

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

# Filter by cluster
sum(netipallocation_crd_status{cluster="gke-prod"})

# Find the leader pod
netipallocation_controller_is_leader == 1
```

### Prometheus Alerts

Deploy the PrometheusRule for alerting:
```bash
kubectl apply -f monitoring/prometheusrule.yaml
```

| Alert | Severity | Condition |
|-------|----------|-----------|
| `NetIPAllocationNoLeader` | Critical | No leader for 2m |
| `NetIPAllocationCRDUnhealthy` | Critical | CRD status=0 for 5m |
| `NetIPAllocationUnattachedIPsWarning` | Warning | Unattached IPs for 5m |
| `NetIPAllocationUnattachedIPsCritical` | Critical | Unattached IPs for 10m |
| `NetIPAllocationGCPAPIErrors` | Warning | GCP API errors detected |
| `NetIPAllocationNodeCordonedWithIP` | Warning | Cordoned node still has IP for 5m |
| `NetIPAllocationHighReconcileErrorRate` | Warning | Error rate > 10% for 5m |
| `NetIPAllocationSlowReconciliation` | Warning | p95 reconcile time > 30s |
| `NetIPAllocationControllerNotReady` | Warning | Controller not ready for 5m |

---

## 📈 Grafana Dashboard

A pre-built Grafana dashboard is included with the following features:

- **Controller Overview**: Leader status, ready/healthy pods, CRD count, IP stats
- **Leader Election History**: Timeline of leader changes
- **CRD Status Table**: Health, reserved/attached/unattached IPs per CRD
- **IP Allocation**: Attachment rate gauge, IP-to-node mapping
- **Node Status**: Cordoned nodes, ip.ready label status
- **Operations & Errors**: Reconciliation rate, duration percentiles, API errors
- **Cluster Filtering**: Optional filter when `CLUSTER_NAME` is set

### Install via ConfigMap (Grafana Sidecar)
```bash
kubectl apply -f monitoring/grafana-dashboard-configmap.yaml
```

The ConfigMap uses the `grafana_dashboard: "1"` label for automatic discovery by Grafana's sidecar.

### Manual Import

1. Go to Grafana → Dashboards → Import
2. Upload `monitoring/grafana-dashboard.json`
3. Select your Prometheus datasource

### Dashboard Preview
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ IP Address Controller                                                        │
│ Datasource: [Prometheus ▼]    Cluster: [All ▼]                              │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────────────────┤
│  Leader  │  Ready   │ Healthy  │   CRDs   │ Reserved │     Unattached       │
│  Active  │    2     │    2     │    3     │    5     │         0            │
├──────────┴──────────┴──────────┴──────────┴──────────┴──────────────────────┤
│ Leader Election History          │ Controller Pods Status                    │
│ ┌────────────────────────┐       │ ┌──────────────────────────────────────┐ │
│ │ ▁▁▁▁▁▁▁▁▁▁▁▁▁█████████│       │ │ Pod          │Leader│Ready│Healthy │ │
│ │              pod-abc   │       │ │ pod-abc      │ Yes  │ Yes │  Yes   │ │
│ │ ████████████▁▁▁▁▁▁▁▁▁▁│       │ │ pod-xyz      │ No   │ Yes │  Yes   │ │
│ │ pod-xyz                │       │ └──────────────────────────────────────┘ │
│ └────────────────────────┘       │                                          │
├──────────────────────────────────┴──────────────────────────────────────────┤
│ CRD Status Overview                                                          │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ CRD                    │ Status  │ Reserved │ Attached │ Unattached     ││
│ │ kamailio-dev-pool      │ Healthy │    1     │    1     │     0          ││
│ │ kamailio-prod-pool     │ Healthy │    2     │    2     │     0          ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

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
2. **Check Pods** → If workload pods still running, keep IP
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
| `METRICS_PORT` | `9999` | Prometheus metrics port |
| `CONTROLLER_VERSION` | `1.0.0` | Controller version for metrics |
| `CLUSTER_NAME` | `` | Optional cluster name for metrics labeling |

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
    verbs: ["get", "list", "watch", "delete", "patch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["netinfra.darkbrains.com"]
    resources: ["netipallocations"]
    verbs: ["get", "list", "watch"]
```

### PodMonitor (Prometheus Operator)
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: ip-address-controller
  namespace: monitoring
  labels:
    app: ip-address-controller
    release: prometheus-stack
spec:
  jobLabel: app
  selector:
    matchLabels:
      app: ip-address-controller
  namespaceSelector:
    matchNames:
      - kube-system
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
      interval: 30s
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
# Check if workload pods are still running
kubectl get pods -o wide | grep NODE_NAME

# Force reconciliation by restarting controller
kubectl rollout restart deployment/ip-address-controller
```

**Metrics not showing in Prometheus:**
```bash
# Verify metrics endpoint
kubectl port-forward -n kube-system pod/$(kubectl get pod -n kube-system -l app=ip-address-controller -o jsonpath='{.items[0].metadata.name}') 9999:9999
curl http://localhost:9999/metrics

# Check PodMonitor is discovered
kubectl get podmonitor -n monitoring
```

**Grafana dashboard not loading:**
```bash
# Check ConfigMap exists
kubectl get configmap ip-address-controller-dashboard -n monitoring

# Check Grafana sidecar logs
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboard
```

---

## 🔄 Migration from v1.0.x

If you're upgrading from v1.0.x, update your CRD from `deploymentRef` to `workloadRef`:

**Before (v1.0.x):**
```yaml
spec:
  deploymentRef:
    name: my-app
    namespace: default
```

**After (v1.1.0+):**
```yaml
spec:
  workloadRef:
    kind: Deployment
    name: my-app
    namespace: default
```

> **Note:** The old `deploymentRef` format is still supported for backwards compatibility but is deprecated.

---

## 📁 Project Structure
```
ip-address-controller/
├── src/
│   ├── main.py
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── utils/
│   │   ├── reconciler.py
│   │   ├── k8s_utils.py
│   │   ├── health_server.py
│   │   └── metrics.py
│   └── cloud/
│       └── gcp.py
├── crds/
│   └── netipallocation.yaml
├── k8s/
│   ├── deployment.yaml
│   ├── rbac.yaml
│   ├── podmonitor.yaml
│   ├── prometheusrule.yaml
│   └── grafana-dashboard-configmap.yaml
└── README.md
```

---

## 📄 License

Apache License 2.0

---

## ❤️ Support This Project

If you'd like to support **Dark Brains**, you can sponsor us directly on GitHub:

👉 [**Sponsor via GitHub**](https://github.com/sponsors/darkbrains)

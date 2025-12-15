from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server

# ============== Gauges (current state) ==============

crd_status = Gauge(
    'netipallocation_crd_status',
    'Status of NetIPAllocation CRD (1=healthy, 0=unhealthy)',
    ['crd_name']
)

crd_reserved_ips_total = Gauge(
    'netipallocation_reserved_ips_total',
    'Total number of reserved IPs in CRD',
    ['crd_name']
)

crd_attached_ips_total = Gauge(
    'netipallocation_attached_ips_total',
    'Number of IPs currently attached to nodes',
    ['crd_name']
)

crd_unattached_ips_total = Gauge(
    'netipallocation_unattached_ips_total',
    'Number of IPs not attached to any node',
    ['crd_name']
)

ip_attached = Gauge(
    'netipallocation_ip_attached',
    'Whether IP is attached to a node (1=attached, 0=not attached)',
    ['crd_name', 'ip', 'node']
)

node_ip_ready = Gauge(
    'netipallocation_node_ip_ready',
    'Whether node has ip.ready=true label (1=ready, 0=not ready)',
    ['node', 'crd_name']
)

node_cordoned = Gauge(
    'netipallocation_node_cordoned',
    'Whether node is cordoned (1=cordoned, 0=schedulable)',
    ['node']
)

controller_is_leader = Gauge(
    'netipallocation_controller_is_leader',
    'Whether this controller instance is the leader (1=leader, 0=not leader)',
    ['pod_name']
)

controller_healthy = Gauge(
    'netipallocation_controller_healthy',
    'Whether controller is healthy (1=healthy, 0=unhealthy)',
    ['pod_name']
)

controller_ready = Gauge(
    'netipallocation_controller_ready',
    'Whether controller is ready (1=ready, 0=not ready)',
    ['pod_name']
)

# ============== Counters (cumulative) ==============

reconcile_total = Counter(
    'netipallocation_reconcile_total',
    'Total number of reconciliation runs',
    ['crd_name', 'status']
)

ip_attach_total = Counter(
    'netipallocation_ip_attach_total',
    'Total number of IP attach operations',
    ['crd_name', 'status']
)

ip_detach_total = Counter(
    'netipallocation_ip_detach_total',
    'Total number of IP detach operations',
    ['crd_name', 'status']
)

gcp_api_errors_total = Counter(
    'netipallocation_gcp_api_errors_total',
    'Total number of GCP API errors',
    ['operation', 'error_type']
)

# ============== Histograms (latency) ==============

reconcile_duration_seconds = Histogram(
    'netipallocation_reconcile_duration_seconds',
    'Time spent in reconciliation',
    ['crd_name'],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
)

gcp_api_duration_seconds = Histogram(
    'netipallocation_gcp_api_duration_seconds',
    'Time spent in GCP API calls',
    ['operation'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# ============== Info ==============

controller_info = Info(
    'netipallocation_controller',
    'Controller information'
)


def start_metrics_server(port=9999, logger=None):
    """Start the Prometheus metrics HTTP server."""
    try:
        start_http_server(port)
        if logger:
            logger.info(f"Prometheus metrics server started on port {port}")
    except Exception as e:
        if logger:
            logger.error(f"Failed to start metrics server: {e}")


def set_controller_info(version="1.0.0", pod_name="unknown"):
    """Set controller info metric."""
    controller_info.info({
        'version': version,
        'pod_name': pod_name,
    })

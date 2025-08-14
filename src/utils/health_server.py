# health_server.py
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone, timedelta
import threading

controller_state = {
    "healthy": False,
    "leader": False,
    "ready": False,
    "bootstrapped": False,
    "lease_loop_last_tick": None,
    "lease_duration_seconds": None,
    "last_reconcile_ok": None,
    "started_at": datetime.now(timezone.utc),
}

_state_lock = threading.Lock()

def _now(): return datetime.now(timezone.utc)

def _as_bool(v):
    if isinstance(v, bool): return v
    if v is None: return False
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _evaluate_readiness(now: datetime):
    with _state_lock:
        healthy = _as_bool(controller_state.get("healthy"))
        bootstrapped = _as_bool(controller_state.get("bootstrapped"))
        last_tick = controller_state.get("lease_loop_last_tick")
        lease_sec = controller_state.get("lease_duration_seconds") or 15

    if not healthy: return False, "unhealthy=false"
    if not bootstrapped: return False, "not-bootstrapped"
    if not isinstance(last_tick, datetime): return False, "election-loop-no-heartbeat"

    threshold = max(5, lease_sec) * 2
    if (now - last_tick) > timedelta(seconds=threshold):
        return False, f"election-loop-stalled>{threshold}s"

    return True, "ok"

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._ok("ok") if _as_bool(controller_state.get("healthy")) else self._fail("unhealthy")
            return
        if self.path == "/readyz":
            ready, reason = _evaluate_readiness(_now())
            self._ok("ready") if ready else self._fail(f"not-ready: {reason}")
            return
        self.send_error(404, "not found")

    def _ok(self, msg):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(msg.encode())

    def _fail(self, msg):
        self.send_response(503)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, *args): return

def start_health_server(port: int = 8080, logger=None):
    srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, name="health-server", daemon=True)
    t.start()
    if logger:
        logger.info(f"Health server listening on :{port}")
    return srv

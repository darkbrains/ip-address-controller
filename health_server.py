import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Controller readiness/health state
controller_state = {
    "healthy": False,  # process is alive
    "ready": False,    # controller is ready to reconcile
}

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            if controller_state["healthy"]:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok\n")
            else:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"unhealthy\n")

        elif self.path == "/readyz":
            if controller_state["ready"]:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ready\n")
            else:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"not ready\n")

        else:
            self.send_response(404)
            self.end_headers()

def start_health_server(port=8080):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

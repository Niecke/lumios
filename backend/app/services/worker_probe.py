"""
Kubelet probes of a worker pod: a tiny HTTP server in a daemon thread.

Stdlib only (no Flask, no app import) so the probes cost nothing: an exec probe
would start a second Python that imports the whole app inside the pod's memory
limit. The port is only reached by the kubelet; there is no Service or Ingress.

    GET /live   200 while the process runs and the database answered recently.
                The schema does not matter: a missing schema must not restart
                the pod in a loop, that would hide the cause.
    GET /ready  200 once the schema is at or past this code's head, else 503.

The state is held in memory and refreshed in the background, never per request.
Responses carry no revision ids; the worker log names them.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# /live turns 503 when no database check succeeded for this long (the startup
# grace counts from the creation of the state).
LIVE_MAX_AGE_SECONDS = 300


class ProbeState:
    def __init__(self, live_max_age: float = LIVE_MAX_AGE_SECONDS):
        self._lock = threading.Lock()
        self._live_max_age = live_max_age
        self._ready = False
        self._last_db_ok = time.monotonic()

    def mark_db_ok(self) -> None:
        with self._lock:
            self._last_db_ok = time.monotonic()

    def set_ready(self, ready: bool) -> None:
        with self._lock:
            self._ready = ready

    def is_ready(self) -> bool:
        with self._lock:
            return self._ready

    def is_live(self) -> bool:
        with self._lock:
            return time.monotonic() - self._last_db_ok < self._live_max_age


def start_probe_server(
    state: ProbeState, port: int, host: str = "0.0.0.0"
) -> ThreadingHTTPServer:
    """Serve /live and /ready from a daemon thread; stop it with ``shutdown()``."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/live":
                ok, body = state.is_live(), b"live"
            elif path == "/ready":
                ok, body = state.is_ready(), b"ready"
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "text/plain")
            if not ok:
                body = b"not " + body
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # The kubelet probes every few seconds: keep the log for real events.
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="worker-probe", daemon=True).start()
    return server

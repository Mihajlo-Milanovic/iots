"""Minimalni HTTP /health endpoint da Docker Compose ima healthcheck."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger("analytics.health")

_state = {
    "mqtt_connected": False,
    "nats_connected": False,
    "mlaas_reachable": None,
    "readings_seen": 0,
    "predictions_published": 0,
    "predictions_correct": 0,
    "mlaas_errors": 0,
    "nats_errors": 0,
}


def set_state(**kwargs) -> None:
    _state.update(kwargs)


def bump(key: str, amount: int = 1) -> None:
    _state[key] = _state.get(key, 0) + amount


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        healthy = _state.get("mqtt_connected", False) and _state.get("nats_connected", False)
        body = json.dumps({"status": "UP" if healthy else "DOWN", **_state}).encode()
        self.send_response(200 if healthy else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):   # utišaj pristupni log
        pass


def start(port: int) -> None:
    server = HTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("health endpoint na 0.0.0.0:%s/health", port)

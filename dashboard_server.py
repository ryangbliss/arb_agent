"""
dashboard_server.py — lightweight HTTP server for the dashboard.

Serves static dashboard/index.html and a /state endpoint that returns
the live state.json written by the main loop.

Runs in a daemon thread so it doesn't block the scanner.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import config


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access log

    def do_GET(self):
        if self.path.startswith("/state"):
            self._serve_state()
        else:
            self._serve_file()

    def _serve_state(self):
        try:
            data = config.STATE_JSON.read_text()
        except FileNotFoundError:
            data = "{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data.encode())

    def _serve_file(self):
        path = self.path.split("?")[0].lstrip("/") or "index.html"
        file_path = config.DASHBOARD_DIR / path
        if not file_path.exists():
            file_path = config.DASHBOARD_DIR / "index.html"
        try:
            content = file_path.read_bytes()
            ext = file_path.suffix
            ctype = {"html": "text/html", "js": "application/javascript",
                     "css": "text/css", "json": "application/json"}.get(ext.lstrip("."), "text/plain")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_response(404)
            self.end_headers()


def start(port: int = None) -> None:
    port = port or config.DASHBOARD_PORT
    server = HTTPServer(("localhost", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"  📊 Dashboard: http://localhost:{port}")

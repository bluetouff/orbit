#!/usr/bin/env python3
"""Loopback-only development preview using Orbit's public snapshot and logos.

No provider credentials or API requests. Existing timestamps are preserved.
Only web assets are served, never repository files or environment files.
"""
import argparse
import http.server
import json
import mimetypes
from pathlib import Path
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

WEB = Path(__file__).resolve().parents[1] / "web"
ORIGIN = "https://orbit.l0g.fr"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PublicCache:
    def __init__(self, snapshot_file=None, logo_dir=None):
        self.snapshot_file = snapshot_file
        self.logo_dir = logo_dir
        self.lock = threading.Lock()
        self.snapshot_lock = threading.Lock()
        self.downloads = threading.BoundedSemaphore(6)
        self.snapshot = None
        self.attempted = 0
        self.logos = OrderedDict()
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def fetch(self, path, limit):
        request = urllib.request.Request(ORIGIN + path, headers={"User-Agent": "Orbit2-local-preview/1.0"})
        with self.opener.open(request, timeout=10) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Response too large")
        return body

    def get(self, path):
        if path == "/data.json":
            if self.snapshot_file:
                try:
                    with self.snapshot_file.open("rb") as file:
                        raw = file.read(6_000_001)
                    if len(raw) > 6_000_000 or not isinstance(json.loads(raw).get("coins"), list):
                        raise ValueError("Invalid snapshot")
                    return raw, "application/json"
                except (OSError, ValueError, AttributeError):
                    return None, "application/json"
            with self.snapshot_lock:
                if time.monotonic() - self.attempted > 30:
                    self.attempted = time.monotonic()
                    try:
                        raw = self.fetch(path, 6_000_000)
                        if not isinstance(json.loads(raw).get("coins"), list):
                            raise ValueError("Invalid snapshot")
                        self.snapshot = raw
                    except (OSError, ValueError, AttributeError):
                        pass
                return self.snapshot, "application/json"
        if re.fullmatch(r"/logos/[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\.png", path):
            if self.logo_dir:
                file = (self.logo_dir / path.rsplit("/", 1)[-1]).resolve()
                if file.is_relative_to(self.logo_dir) and file.is_file():
                    with file.open("rb") as stream:
                        raw = stream.read(2_000_001)
                    return (raw if len(raw) <= 2_000_000 else None), "image/png"
            with self.downloads:
                with self.lock:
                    if path in self.logos:
                        return self.logos[path], "image/png"
                try:
                    raw = self.fetch(path, 250_000)
                except (OSError, ValueError):
                    raw = None
                with self.lock:
                    self.logos[path] = raw
                    if len(self.logos) > 100:
                        self.logos.popitem(last=False)
                return raw, "image/png"
        return None, "text/plain"


class Handler(http.server.BaseHTTPRequestHandler):
    cache = PublicCache()
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            self.send_error(403)
            return
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/web/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not path.startswith("/web/"):
            self.send_error(404)
            return
        relative = path[4:]
        if relative == "/data.json" or relative.startswith("/logos/"):
            body, content_type = self.cache.get(relative)
        else:
            file = (WEB / relative.lstrip("/")).resolve()
            if file.is_dir():
                file = file / "index.html"
            if not file.is_relative_to(WEB) or file.suffix not in {".html", ".js", ".css", ".svg"} or not file.is_file():
                self.send_error(404)
                return
            body = file.read_bytes()
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if body is None:
            self.send_error(503, "Public source unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_):
        pass


class PreviewServer(http.server.ThreadingHTTPServer):
    request_queue_size = 128


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--snapshot", type=Path, help="Read a real local snapshot instead of the public feed")
    parser.add_argument("--logos", type=Path, help="Directory of local provider logos")
    args = parser.parse_args()
    Handler.cache = PublicCache(args.snapshot.resolve() if args.snapshot else None, args.logos.resolve() if args.logos else None)
    server = PreviewServer(("127.0.0.1", args.port), Handler)
    print(f"Orbit2 preview: http://127.0.0.1:{server.server_port}/web/", flush=True)
    print("Data: local snapshot; original timestamps preserved." if args.snapshot else "Data: public orbit.l0g.fr snapshot, cached for 30s. No direct provider requests.", flush=True)
    server.serve_forever()

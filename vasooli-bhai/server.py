"""Local runner for Vasooli Bhai. Run: python3 server.py  →  http://localhost:8000

Serves index.html and hands /api/* to api/index.py, the same code Vercel runs.
Reads SARVAM_API_KEY from .env or the environment; without it, the app runs in
a clearly labelled scripted text demo mode.
"""
import os
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent

if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from api.index import handler, key  # noqa: E402


class Local(handler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            return super().do_GET()
        page = (ROOT / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Vasooli Bhai on http://localhost:{port}  key={'configured' if key() else 'missing (text demo only)'}")
    ThreadingHTTPServer(("0.0.0.0", port), Local).serve_forever()

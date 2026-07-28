"""Render the real Luna frontend with a committed case result for documentation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PORTRAIT = ROOT / "assets" / "luna.jpeg"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

DEMO_RESULT = {
    "status": "solved",
    "solved": True,
    "baseline": {"passed": 1655, "failed": 2, "error": 0, "skipped": 25},
    "target": [
        "tests/test_basic.py::test_choice_argument_optional_metavar",
        "tests/test_basic.py::test_datetime_argument_optional_metavar",
    ],
    "fixed": [
        "tests/test_basic.py::test_choice_argument_optional_metavar",
        "tests/test_basic.py::test_datetime_argument_optional_metavar",
    ],
    "regressions": [],
    "still_failing": [],
    "branch": "luna/click-3578",
    "base_sha": "22fcb764",
    "steps": 8,
    "cost": 0.2112,
    "wall": 38.7,
    "diff": """diff --git a/src/click/core.py b/src/click/core.py
index d2db291..cd642b5 100644
--- a/src/click/core.py
+++ b/src/click/core.py
@@ -3573,7 +3573,7 @@ class Argument(Parameter):
-        if not self.required:
+        if not self.required and not (var.startswith("[") and var.endswith("]")):
             var = f"[{var}]"
""",
    "untracked": [],
}


def _demo_script() -> bytes:
    result = json.dumps(DEMO_RESULT, ensure_ascii=False)
    script = f"""
setTimeout(function() {{
  log().innerHTML = '';
  msg('me', '修复 Click #3578：可选参数的帮助文本出现了重复方括号');
  const row = document.createElement('div');
  row.className = 'msg bot';
  const avatar = document.createElement('div');
  avatar.className = 'ava';
  catFill(avatar);
  const bubble = document.createElement('div');
  bubble.className = 'bub rc';
  row.appendChild(avatar);
  row.appendChild(bubble);
  log().appendChild(row);
  renderResult(bubble, {result});
}}, 150);
"""
    return script.encode("utf-8")


class DemoHandler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send((WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/style.css":
            self._send((WEB / "style.css").read_bytes(), "text/css; charset=utf-8")
        elif self.path == "/app.js":
            body = (WEB / "app.js").read_bytes() + _demo_script()
            self._send(body, "text/javascript; charset=utf-8")
        elif self.path == "/portrait":
            self._send(PORTRAIT.read_bytes(), "image/jpeg")
        elif self.path == "/whoami":
            self._send(b'{"name":"Xinrui","suggested":"Xinrui"}', "application/json")
        else:
            self.send_error(404)

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="docs/web-result.png")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not CHROME.is_file():
        raise SystemExit(f"Google Chrome not found at {CHROME}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="luna-chrome-") as profile:
            command = [
                str(CHROME), "--headless=new", "--hide-scrollbars",
                "--disable-background-networking", "--disable-component-update",
                "--no-default-browser-check", "--no-first-run",
                "--window-size=1440,1000", "--force-device-scale-factor=1",
                "--virtual-time-budget=2000", f"--user-data-dir={profile}",
                f"--screenshot={output}",
                f"http://127.0.0.1:{server.server_port}/",
            ]
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if not output.is_file():
                raise RuntimeError("Chrome exited without writing the screenshot")
    finally:
        server.shutdown()
        thread.join()
    print(output)


if __name__ == "__main__":
    main()

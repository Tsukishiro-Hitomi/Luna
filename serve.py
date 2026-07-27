"""卢娜 —— fixpoint 的本地聊天前端（入口）。

跑法：.venv/bin/python serve.py  →  打开 http://127.0.0.1:8000
分工：前端静态资源在 web/，后端逻辑在 web_backend.py，本文件只管收发 HTTP。
换立绘：把图片存成 assets/luna.png（.jpg/.webp 也行），刷新即用；没有就用内置 SVG 猫娘。
⚠️ 仅本地自用：/run 会在你机器上执行目标仓库的测试命令（= 任意代码执行），
   只对你【信任的】仓库用。服务只绑 127.0.0.1、不对外。
"""
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()

import web_backend

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")

# 可直接取的静态文件白名单（顺带防目录穿越）：URL → web/ 下的文件名
_STATIC = {
    "/": "index.html",
    "/index.html": "index.html",
    "/style.css": "style.css",
    "/app.js": "app.js",
}


def _content_type(path):
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype.endswith(("javascript", "json", "xml")):
        ctype += "; charset=utf-8"
    return ctype


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        with open(path, "rb") as f:
            self._send(200, _content_type(path), f.read())

    def do_GET(self):
        name = _STATIC.get(self.path)
        if name:
            self._send_file(os.path.join(WEB_DIR, name))
        elif self.path == "/portrait":
            p = web_backend.portrait_path()
            if p:
                self._send_file(p)
            else:
                self._send(404, "text/plain", b"no portrait")
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path != "/run":
            self._send(404, "text/plain", b"not found")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, "application/json",
                       json.dumps({"status": "error", "message": "bad request"}).encode())
            return
        payload = web_backend.handle_run(req)
        self._send(200, "application/json",
                   json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def log_message(self, *args):  # 安静
        pass


def main():
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"卢娜（fixpoint 代码助手）已就位：http://127.0.0.1:{port}   （仅本地；Ctrl-C 停）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()

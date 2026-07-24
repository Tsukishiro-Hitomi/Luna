"""fixpoint 聊天前端（本地）：在聊天里贴一个 git 仓库路径，agent 把它失败的测试修到绿。

跑法：.venv/bin/python serve.py  →  打开 http://127.0.0.1:8000
⚠️ 仅本地自用：/run 会在你机器上执行目标仓库的测试命令（= 任意代码执行），
   只对你【信任的】仓库用。服务只绑 127.0.0.1、不对外。
薄封装：后端唯一逻辑就是调 eval.run_repo.run_repo —— 与 CLI 同一条流水线、同一套判定。
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()

from agent import profile
from agent.config import Config
from eval.run_repo import run_repo

HTML = """<!doctype html>
<html lang='zh'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>fixpoint</title>
<style>
  :root { color-scheme: light dark; --bg:#f5f6f8; --card:#fff; --ink:#1a1a1a; --sub:#666;
          --me:#2563eb; --bot:#eceef1; --ok:#16a34a; --bad:#dc2626; --line:#e2e4e8; }
  @media (prefers-color-scheme: dark){ :root{ --bg:#0f1115; --card:#171a21; --ink:#e8eaed;
          --sub:#9aa0a6; --bot:#232833; --line:#2a2f3a; } }
  *{box-sizing:border-box} body{margin:0;font:15px/1.55 -apple-system,system-ui,sans-serif;
    background:var(--bg);color:var(--ink);height:100vh;display:flex;flex-direction:column}
  header{padding:12px 16px;border-bottom:1px solid var(--line);font-weight:600}
  header small{font-weight:400;color:var(--sub)}
  #log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
  .row{display:flex;gap:8px} .row.me{justify-content:flex-end}
  .bub{max-width:80%;padding:10px 13px;border-radius:14px;white-space:pre-wrap;word-break:break-word}
  .me .bub{background:var(--me);color:#fff;border-bottom-right-radius:4px}
  .bot .bub{background:var(--bot);border-bottom-left-radius:4px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;max-width:80%}
  .card h4{margin:0 0 6px} .card .ok{color:var(--ok)} .card .bad{color:var(--bad)}
  .meta{color:var(--sub);font-size:13px;margin-top:6px}
  pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px;
     overflow-x:auto;font-size:12px;max-height:280px}
  .dots::after{content:'';animation:d 1.2s infinite} @keyframes d{0%{content:''}33%{content:'.'}66%{content:'..'}100%{content:'...'}}
  form{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line);background:var(--card)}
  input,textarea{flex:1;font:inherit;padding:9px 12px;border:1px solid var(--line);
     border-radius:10px;background:var(--bg);color:var(--ink)}
  #task{flex:2} button{padding:9px 16px;border:0;border-radius:10px;background:var(--me);
     color:#fff;font:inherit;cursor:pointer} button:disabled{opacity:.5;cursor:default}
</style></head>
<body>
  <header>fixpoint <small>—— 贴一个有失败测试的 git 仓库路径，我来修</small></header>
  <div id='log'></div>
  <form id='f'>
    <input id='repo' placeholder='/path/to/your/git/repo' autocomplete='off' required>
    <input id='task' placeholder='（可选）补充说明' autocomplete='off'>
    <button id='send'>修</button>
  </form>
<script>
function bubble(who, text){ const r=document.createElement('div'); r.className='row '+who;
  const b=document.createElement('div'); b.className='bub'; b.textContent=text; r.appendChild(b);
  document.getElementById('log').appendChild(r); scroll(); return b; }
function scroll(){ const l=document.getElementById('log'); l.scrollTop=l.scrollHeight; }
fetch('/whoami').then(r=>r.json()).then(d=>{
  bubble('bot', '你好，'+(d.name||'there')+'！贴一个 git 仓库路径（工作区要干净），我会新开一个分支把失败的测试修到绿，改动留给你审。');
});
const short = t => t.split('::').pop();
function renderResult(host, d){
  host.className='card';
  const S = d.baseline || {};
  if (['not_git_repo','not_repo_root','dirty_tree','mid_operation','no_tests_collected','baseline_error','error'].includes(d.status)){
    host.innerHTML = "<h4 class='bad'>✗ 没能开始（"+d.status+"）</h4>"+ (d.message||''); scroll(); return;
  }
  const base = '基线：'+(S.passed||0)+' passed / '+(S.failed||0)+' failed / '+(S.error||0)+' error';
  if (d.status==='no_failing_tests'){ host.innerHTML="<h4>没有失败的测试</h4>"+base+"<div class='meta'>我只修红测试，不主动找 bug。</div>"; scroll(); return; }
  let h = d.solved ? "<h4 class='ok'>✅ 修好了</h4>" : "<h4 class='bad'>❌ 没完全修好</h4>";
  h += base + "<br>目标 "+(d.target||[]).length+" 个 · fixed "+(d.fixed||[]).length+" · 回归 "+(d.regressions||[]).length;
  if ((d.regressions||[]).length) h += "<br>回归："+d.regressions.map(short).join('、');
  if ((d.still_failing||[]).length) h += "<br>仍红："+d.still_failing.map(short).join('、');
  h += "<div class='meta'>分支 "+(d.branch||'?')+" @ "+(d.base_sha||'')+" · "+d.steps+" 步 · $"+d.cost+" · "+d.wall+"s</div>";
  if (d.diff) h += "<details><summary>查看改动 diff</summary><pre>"+d.diff.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))+"</pre></details>";
  h += "<div class='meta'>改动留在分支上，未提交。保留就切到该分支；丢弃：git checkout . &amp;&amp; git clean -fd</div>";
  host.innerHTML = h; scroll();
}
document.getElementById('f').addEventListener('submit', async e=>{
  e.preventDefault();
  const repo=document.getElementById('repo').value.trim(); const task=document.getElementById('task').value.trim();
  if(!repo) return;
  bubble('me', repo + (task? '\\n（'+task+'）':''));
  document.getElementById('task').value='';
  const btn=document.getElementById('send'); btn.disabled=true;
  const r=document.createElement('div'); r.className='row bot';
  const b=document.createElement('div'); b.className='bub'; b.innerHTML="修复中<span class='dots'></span>";
  r.appendChild(b); document.getElementById('log').appendChild(r); scroll();
  try{
    const res=await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({repo, task})});
    renderResult(b, await res.json());
  }catch(err){ b.className='card'; b.innerHTML="<h4 class='bad'>✗ 请求失败</h4>"+err; }
  btn.disabled=false;
});
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        elif self.path == "/whoami":
            self._send(200, "application/json",
                       json.dumps({"name": profile.resolve_name()}).encode("utf-8"))
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

        repo = (req.get("repo") or "").strip()
        if not repo:
            self._send(200, "application/json", json.dumps(
                {"status": "error", "message": "请给一个 git 仓库路径"}, ensure_ascii=False).encode())
            return
        task = (req.get("task") or "").strip() or None
        if req.get("name"):
            profile.set_name(str(req["name"]).strip())

        config = Config.from_env()
        config.stream = False  # 网页端非流式：成本记账准确
        venv_py = os.path.join(os.path.realpath(repo), ".venv", "bin", "python") if repo else ""
        if venv_py and os.path.exists(venv_py):
            config.test_python = venv_py

        try:
            r = run_repo(repo, config, task=task, allow_dirty=bool(req.get("allow_dirty")))
            payload = {
                "status": r.status, "solved": r.solved, "message": r.message,
                "baseline": r.baseline_summary, "target": r.target_tests,
                "fixed": r.fixed, "regressions": r.regressions, "still_failing": r.still_failing,
                "branch": r.branch, "base_sha": (r.base_sha or "")[:8],
                "steps": r.steps, "cost": round(r.cost_usd, 4), "wall": round(r.wall_s, 1),
                "diff": (r.diff or "")[:6000], "untracked": r.untracked,
            }
        except Exception as e:
            payload = {"status": "error", "message": f"{type(e).__name__}: {e}"}
        self._send(200, "application/json",
                   json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def log_message(self, *a):  # 安静
        pass


def main():
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fixpoint 聊天前端：http://127.0.0.1:{port}   （仅本地；Ctrl-C 停）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()

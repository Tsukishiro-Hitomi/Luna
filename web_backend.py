"""卢娜前端的后端逻辑，不碰 HTTP。

serve.py 只管收发请求，判断都在这里：一条消息里认得出仓库路径，就调
``eval.run_repo`` 修 bug；认不出，就用卢娜的人设闲聊。输入输出都是普通 dict，
方便离线测试。
"""
import glob
import os
import re
import sys

# 便于被 serve.py 之外的地方（如测试）直接 import：确保仓库根在 sys.path 上。
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agent import profile
from agent.config import Config
from agent.llm import LLMClient
from eval.run_repo import run_repo

ASSETS_DIR = os.path.join(_ROOT, "assets")


# ---------------------------------------------------------------------------
# 从自然语言里抠仓库路径
# ---------------------------------------------------------------------------
_PATH_RE = re.compile(r"~?/[^\s，,。；;、:：\"'`（）()【】\[\]<>]+")


def parse_message(text):
    """从一句话里抠出仓库路径（绝对路径或 ~/…）；如果除了路径还剩别的字，
    就把整句原文当补充说明（task）一起带出来。"""
    m = _PATH_RE.search(text or "")
    if not m:
        return "", None
    repo = os.path.expanduser(m.group(0))
    rest = text[:m.start()] + text[m.end():]
    task = text.strip() if any(c.isalnum() for c in rest) else None
    return repo, task


# ---------------------------------------------------------------------------
# 普通对话
# ---------------------------------------------------------------------------
_LUNA_PERSONA = (
    "你是卢娜，一只温柔又俏皮的猫娘代码助手，你的主人叫心瑞。"
    "你平时帮主人把 git 仓库里失败的测试修好（把红测试改绿）。"
    "现在主人在和你闲聊，请用可爱、亲昵、简短的中文回复（一两句就好），"
    "称呼对方「主人」，语气软萌、可以偶尔带个「喵」或颜文字。"
    "如果主人想让你修 bug 或提到某个项目，就温柔提醒他把仓库的绝对路径发给你。"
    "不要夸大能力，也不要编造你并没有做过的事。"
)


def chat_reply(text):
    """普通对话：用卢娜的人设让 LLM 回一句短话；出问题就用兜底话，绝不把闲聊变成报错。"""
    try:
        config = Config.from_env()
        client = LLMClient(config, config.model_haiku)   # 闲聊用便宜快的模型
        msg = client.create(
            messages=[{"role": "user", "content": text}],
            system=_LUNA_PERSONA,
            stream=False,
        )
        reply = "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        ).strip()
        return reply or "喵？我在的哦，主人～"
    except Exception:
        return "喵～ 我好像有点没接上话，不过我一直在这儿。想让我修 bug 的话，把仓库的路径发我就好呀 (=^･ω･^=)"


# ---------------------------------------------------------------------------
# 修复：调 run_repo，整理成前端要的 payload
# ---------------------------------------------------------------------------
def run_fix(repo, task, allow_dirty=False):
    """在 ``repo`` 上跑一遍修复流程，返回给前端的结果 dict（异常也兜成 dict，不外抛）。"""
    config = Config.from_env()
    config.stream = False  # 网页端非流式：成本记账准确
    venv_py = os.path.join(os.path.realpath(repo), ".venv", "bin", "python")
    if os.path.exists(venv_py):
        config.test_python = venv_py
    try:
        r = run_repo(repo, config, task=task, allow_dirty=allow_dirty)
        return {
            "status": r.status, "solved": r.solved, "message": r.message,
            "baseline": r.baseline_summary, "target": r.target_tests,
            "fixed": r.fixed, "regressions": r.regressions, "still_failing": r.still_failing,
            "branch": r.branch, "base_sha": (r.base_sha or "")[:8],
            "steps": r.steps, "cost": round(r.cost_usd, 4), "wall": round(r.wall_s, 1),
            "diff": (r.diff or "")[:6000], "untracked": r.untracked,
        }
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 分流入口：一条请求 → 一份 payload
# ---------------------------------------------------------------------------
def handle_run(req):
    """POST /run 的全部逻辑：有路径 → 修复；没路径 → 闲聊。req/返回都是普通 dict。"""
    text = (req.get("message") or "").strip()
    repo = (req.get("repo") or "").strip()
    task = (req.get("task") or "").strip() or None
    if not repo and text:
        repo, parsed_task = parse_message(text)
        task = task or parsed_task
    if not repo:
        # 没给路径 → 当普通聊天，用卢娜的人设回一句
        reply = chat_reply(text) if text else "喵？主人有什么想让我帮忙的吗～"
        return {"status": "chat", "reply": reply}
    return run_fix(repo, task, allow_dirty=bool(req.get("allow_dirty")))


def portrait_path():
    """用户自带的立绘 assets/luna.*（没有就返回 None，前端回落到内置 SVG）。"""
    for p in sorted(glob.glob(os.path.join(ASSETS_DIR, "luna.*"))):
        if os.path.isfile(p):
            return p
    return None


def whoami():
    """给前端判断是不是初次运行。name 是显式设过的名字（没设过就是 None，前端据此
    弹出「怎么称呼你」），suggested 是个默认猜测（git/$USER），用来预填输入框。跟 CLI
    共用 ~/.config/luna/profile.json。"""
    return {"name": profile.get_name(), "suggested": profile.resolve_name()}


def save_name(name):
    """初次运行时把用户的名字存下来（存哪儿跟 whoami 一致），返回存好的名字。"""
    name = (name or "").strip()[:50]
    if name:
        profile.set_name(name)
    return {"name": profile.get_name()}

"""个性化：记住用户名字 + 问候语。

存机器级 home（``~/.config/luna/profile.json``，
**绝不**落进目标仓库 / diff / 记分卡 / 日志 / system prompt。
"""
import json
import os
import subprocess
from typing import Optional


def _profile_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "luna", "profile.json")


def get_name() -> Optional[str]:
    try:
        with open(_profile_path(), encoding="utf-8") as f:
            return json.load(f).get("name") or None
    except Exception:
        return None


def set_name(name: str) -> None:
    try:
        p = _profile_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"name": name}, f, ensure_ascii=False)
    except Exception:
        pass


def resolve_name() -> str:
    """profile.json → `git config --global user.name` → $USER → "there"。
    """
    name = get_name()
    if name:
        return name
    try:
        r = subprocess.run(["git", "config", "--global", "user.name"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USER") or "there"


def greeting(name: str) -> str:
    """问候。"""
    return f"你好，{name}！Luna 已就位。"

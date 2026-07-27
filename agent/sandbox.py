"""沙箱与路径封闭。

给每个任务开一份干净、独立、用完即丢的 fixture 副本（建/清/打补丁），
以及 resolve_in_workdir 这个把路径钉死在工作目录里的安全判定。。
"""

import logging
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class SandboxError(Exception):
    """工作区搭建 / 清理 / 打补丁失败。
    """


class PathEscape(SandboxError):
    """路径越界：resolve_in_workdir 发现用户路径逃出了 workdir。
    """


# --------------------------------------------------------------------------- #
# 路径封闭
# --------------------------------------------------------------------------- #
def resolve_in_workdir(workdir: str, user_path: str) -> str:
    """ user_path 解析成一个落在 workdir 里的规范绝对路径。
    """
    root = os.path.realpath(workdir)
    candidate = user_path if os.path.isabs(user_path) else os.path.join(root, user_path)
    candidate = os.path.realpath(candidate)

    # 等于 root，或以 root/ 开头，才算位于工作区内
    if candidate == root or candidate.startswith(root + os.sep):
        return candidate
    else:
        raise PathEscape(f"{user_path}解析后的绝对路径为{candidate}，不在工作区{workdir}内")


# --------------------------------------------------------------------------- #
# 工作区生命周期
# --------------------------------------------------------------------------- #
def make_workspace(fixture_dir: str, patch_path: Optional[str] = None) -> str:
    """拷一份干净、独立、可丢弃的 fixture 副本，可选地打上 break.patch 制造坏状态。
    """
    temp_dir = tempfile.mkdtemp(prefix="luna_task_")   # 随机名保证多任务并发互不干扰
    work_dir = os.path.realpath(temp_dir)   # 转为规范绝对路径

    try:
        shutil.copytree(fixture_dir, work_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)    # 拷贝，跳过字节缓存
    except Exception as e:
        raise SandboxError(f"工作树拷贝失败：{fixture_dir} -> {work_dir}: {e}") from e

    # 手动打 bug 制造“坏”状态
    if patch_path is not None:
        result = subprocess.run(
            ["git", "apply", "-p1", patch_path],
            cwd=work_dir,              
            capture_output=True,  
            text=True,                   
        )
        
        if result.returncode != 0:
            cleanup_workspace(work_dir)
            raise SandboxError(f"git apply 失败：{result.stderr}")

    return work_dir

def cleanup_workspace(workdir: str) -> None:
    """尽力删掉一个 make_workspace 建出的工作区。
    """
    try:
        shutil.rmtree(workdir)
    except Exception as e:
        logger.warning(f"清理工作区{workdir}失败：{e}")

@contextmanager
def task_sandbox(
    fixture_dir: str, patch_path: Optional[str] = None
) -> Iterator[str]:
    """工作区生命周期的上下文管理器。
    """
    work_dir = make_workspace(fixture_dir, patch_path)
    try:
        yield work_dir
    finally:
        cleanup_workspace(work_dir)


"""v2 编排器：把 agent 原地指向【真实 git 仓库】，以其当前失败的测试为目标修到绿。

判据同 fixpoint 一贯口径（解读 A）：失败的测试就是目标；solved = 原本红的转绿 且
原本绿的没变红。**没有失败测试就不动**（不主动找 bug）。复用 eval.run_bench 的
run_pytest / judge（零改动）。安全网 = git 新分支 + 不自动提交 + 跑完打印 diff
（符合"个人 demo 不做容器隔离"的约束）。这也是将来 web 前端唯一要调的接口缝。
"""
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import List, Optional

from agent.config import Config
from agent.loop import run_agent
from eval.run_bench import run_pytest, judge

_PYENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


@dataclass
class RepoFixResult:
    """一次 run_repo 的结果（cli 展示 / 将来 web 返回都用它）。"""

    status: str          # solved|unsolved|no_failing_tests|no_tests_collected|
                         # not_git_repo|not_repo_root|dirty_tree|mid_operation|
                         # baseline_error|agent_error
    solved: bool = False
    mode: str = "pytest"                       # "pytest" | "generic"
    target_tests: List[str] = field(default_factory=list)
    fixed: List[str] = field(default_factory=list)
    still_failing: List[str] = field(default_factory=list)
    regressions: List[str] = field(default_factory=list)
    baseline_summary: dict = field(default_factory=dict)
    branch: Optional[str] = None
    base_sha: Optional[str] = None
    base_ref: Optional[str] = None
    diff: str = ""
    untracked: List[str] = field(default_factory=list)
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    wall_s: float = 0.0
    stop_reason: Optional[str] = None
    message: str = ""


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def _summary(outcomes: dict) -> dict:
    s = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for v in outcomes.values():
        if v in s:
            s[v] += 1
    return s


def _is_test_file(rel: str) -> bool:
    b = os.path.basename(rel)
    return (b.startswith("test_") and b.endswith(".py")) or b.endswith("_test.py") or b == "conftest.py"


def _repo_pytest(repo: str, config: Config) -> dict:
    """就地在真实仓库跑测试（不 copytree，免破坏 editable install / rootdir）。"""
    if config.test_cmd:  # generic 逃生舱：rc-only，单伪 node 承载
        r = subprocess.run(shlex.split(config.test_cmd), cwd=repo, capture_output=True,
                           text=True, timeout=config.judge_timeout_s, env=_PYENV)
        return {"<suite>": "passed" if r.returncode == 0 else "failed"}
    return run_pytest(repo, config.judge_timeout_s, python=config.test_python, scope=None)


def _build_task(target: List[str], summary: dict, mode: str,
                config: Config, user_task: Optional[str]) -> str:
    head = ("这个仓库有测试在失败。请定位并修复源码，让它们通过。不要修改测试文件本身。\n"
            f"当前测试态：{summary.get('passed', 0)} passed / {summary.get('failed', 0)} failed / "
            f"{summary.get('error', 0)} error / {summary.get('skipped', 0)} skipped。")
    if mode == "generic":
        body = f"目标：让测试命令 `{config.test_cmd}` 退出码为 0。"
    else:
        listed = "\n".join(f"  - {t}" for t in target[:30])
        extra = f"\n  …（另有 {len(target) - 30} 个）" if len(target) > 30 else ""
        body = "要修绿的目标测试：\n" + listed + extra
    tail = f"\n补充说明：{user_task}" if user_task else ""
    return f"{head}\n{body}{tail}"


def run_repo(repo_path: str, config: Config, *, task: Optional[str] = None,
             targets: Optional[List[str]] = None, allow_dirty: bool = False,
             branch: Optional[str] = None, on_text=None) -> RepoFixResult:
    repo = os.path.realpath(repo_path)

    # —— preflight：git 安全（全部 git -C <repo>，不靠 cwd 隐式向上发现）——
    if not os.path.isdir(repo):
        return RepoFixResult(status="not_git_repo", message=f"路径不存在：{repo_path}")
    if _git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return RepoFixResult(status="not_git_repo", message="不是 git 仓库（v2 只接受 git 仓库）")
    top = _git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    if not top or os.path.realpath(top) != repo:
        return RepoFixResult(status="not_repo_root",
                             message=f"请指到仓库根目录（当前根为 {top}）")
    gitdir = os.path.join(repo, ".git")
    if any(os.path.exists(os.path.join(gitdir, m)) for m in ("MERGE_HEAD", "rebase-merge", "rebase-apply")):
        return RepoFixResult(status="mid_operation", message="仓库正处于 merge/rebase 中，请先处理完")
    if _git(repo, "status", "--porcelain").stdout.strip() and not allow_dirty:
        return RepoFixResult(status="dirty_tree",
                             message="工作区不干净，请先 commit/stash（或加 --allow-dirty，但绝不会 reset 你的改动）")
    base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    base_ref = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip() or None

    mode = "generic" if config.test_cmd else "pytest"

    # —— baseline：干净树上就地跑一次 ——
    try:
        baseline = _repo_pytest(repo, config)
    except subprocess.TimeoutExpired:
        return RepoFixResult(status="baseline_error", mode=mode, base_sha=base_sha,
                             base_ref=base_ref, message="基线测试超时；用 --timeout 调大或 --test-cmd 收窄范围")
    summary = _summary(baseline)
    if not baseline:
        return RepoFixResult(status="no_tests_collected", mode=mode, baseline_summary=summary,
                             base_sha=base_sha, base_ref=base_ref,
                             message="没收集到任何测试（检查 --python / 依赖是否装好 / --test-cmd）")

    # —— target = 失败的测试（或 --target 覆盖）；为空 → 早退，绝不建分支/跑 agent ——
    target = list(targets) if targets else sorted(k for k, v in baseline.items() if v in ("failed", "error"))
    if not target:
        return RepoFixResult(status="no_failing_tests", solved=False, mode=mode,
                             baseline_summary=summary, base_sha=base_sha, base_ref=base_ref,
                             message="没有失败的测试——fixpoint 只修红测试，不主动找 bug")

    # —— 建新分支（agent 就地改、不提交；安全网 = 分支 + 未提交 diff）——
    br = branch or f"fixpoint/fix-{int(time.time())}"
    co = _git(repo, "checkout", "-b", br)
    if co.returncode != 0:
        return RepoFixResult(status="agent_error", mode=mode, base_sha=base_sha, base_ref=base_ref,
                             target_tests=target, baseline_summary=summary,
                             message=f"建分支失败：{co.stderr.strip()}")

    # —— 跑 agent（workdir = 真实仓库；工具经 resolve_in_workdir 封闭在仓库内）——
    desc = _build_task(target, summary, mode, config, task)
    t0 = time.perf_counter()
    try:
        result = run_agent(repo, desc, config, on_text=on_text)
    except Exception as e:
        return RepoFixResult(status="agent_error", mode=mode, branch=br, base_sha=base_sha,
                             base_ref=base_ref, target_tests=target, baseline_summary=summary,
                             wall_s=time.perf_counter() - t0, message=f"agent 出错：{e}")
    wall = time.perf_counter() - t0

    # —— 反作弊：把 agent 改过的测试文件还原到 base_sha（用 git diff 过滤，规避 node_id 歧义）——
    changed = _git(repo, "diff", "--name-only").stdout.splitlines()
    test_files = [p for p in changed if _is_test_file(p)]
    if test_files:
        _git(repo, "checkout", base_sha, "--", *test_files)

    # —— 复判：就地复跑 + judge（零改动复用）——
    try:
        post = _repo_pytest(repo, config)
    except subprocess.TimeoutExpired:
        post = {}
    solved, regressions = judge(post, baseline, target)
    passing_now = {k for k, v in post.items() if v == "passed"}
    fixed = sorted(t for t in target if t in passing_now)
    still = sorted(t for t in target if t not in passing_now)

    diff = _git(repo, "diff", base_sha).stdout
    untracked = [ln[3:] for ln in _git(repo, "status", "--porcelain").stdout.splitlines()
                 if ln.startswith("??")]

    return RepoFixResult(
        status="solved" if solved else "unsolved", solved=solved, mode=mode,
        target_tests=target, fixed=fixed, still_failing=still, regressions=regressions,
        baseline_summary=summary, branch=br, base_sha=base_sha, base_ref=base_ref,
        diff=diff, untracked=untracked,
        steps=result.num_steps, input_tokens=result.total_input_tokens,
        output_tokens=result.total_output_tokens, cost_usd=result.total_cost_usd or 0.0,
        wall_s=wall, stop_reason=result.stop_reason,
    )

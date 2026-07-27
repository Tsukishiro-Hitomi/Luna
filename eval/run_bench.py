"""评测 harness：luna 的裁判和记分系统。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Dict, List, Optional, Tuple

from agent.config import Config
from agent.sandbox import make_workspace, cleanup_workspace, task_sandbox
from agent.loop import run_agent

# judge 复跑禁写 .pyc：避免"打补丁→跑→还原"同秒内 pyc 按秒失效误用旧字节码
_PYENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


# ─────────────────────────────────────────────────────────────────────────────
# Task 对象
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Task:
    """一道题的表示。
    """

    id: str
    title: str
    kind: str
    description: str
    target_tests: List[str]
    dir: str
    break_patch: str


# ─────────────────────────────────────────────────────────────────────────────
# 任务发现与工作区准备
# ─────────────────────────────────────────────────────────────────────────────

def discover_tasks(tasks_dir: str) -> List[Task]:
    """扫描任务目录，解析成按 id 排序的 Task 列表。
    """
    tasks = []
    for name in sorted(os.listdir(tasks_dir)):
        d = os.path.join(tasks_dir, name)
        if name == "fixture" or not os.path.isdir(d) or not name[:1].isdigit():
            continue
        tj = os.path.join(d, "task.json")
        try:
            with open(tj, encoding="utf-8") as f:
                meta = json.load(f)
            for k in ("id", "title", "kind", "description", "target_tests"):
                if k not in meta:
                    raise ValueError(f"缺字段 {k}")
            if meta["kind"] not in ("fix_bug", "implement_stub"):
                raise ValueError(f"kind 非法：{meta['kind']}")
            if not meta["target_tests"]:
                raise ValueError("target_tests 为空")
            tasks.append(Task(
                id=meta["id"], title=meta["title"], kind=meta["kind"],
                description=meta["description"], target_tests=list(meta["target_tests"]),
                dir=os.path.abspath(d),
                break_patch=os.path.abspath(os.path.join(d, "break.patch")),
            ))
        except Exception as e:
            print(f"[discover_tasks] 跳过坏任务 {name}：{e}", file=sys.stderr)
    return sorted(tasks, key=lambda t: t.id)


def prepare_workspace(task: Task, dest_root: Optional[str] = None) -> str:
    """给一道题准备打好 break.patch 的隔离工作副本。
    """
    fixture_dir = os.path.join(os.path.dirname(task.dir), "fixture")
    return make_workspace(fixture_dir, task.break_patch)


# ─────────────────────────────────────────────────────────────────────────────
# 基线采集与 pytest 复跑
# ─────────────────────────────────────────────────────────────────────────────

def capture_baseline(fixture_dir: str) -> Dict[str, str]:
    """在纯净 fixture 的临时副本上采一次全量 pytest 基线。
    """
    with task_sandbox(fixture_dir, None) as wd:
        return run_pytest(wd, 60)


def run_pytest(workspace: str, timeout_s: int, *,
               python: Optional[str] = None, scope: Optional[str] = "tests/") -> Dict[str, str]:
    """在工作副本上独立起子进程复跑 pytest，返回每个用例的判定 {node_id: outcome}。
    """
    fd, xml_path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    cmd = [python or sys.executable, "-m", "pytest",
           "-p", "no:cacheprovider", "--continue-on-collection-errors",
           "--junitxml", xml_path, "-q"]
    if scope:
        cmd.append(scope)
    try:
        subprocess.run(
            cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout_s, env=_PYENV,
        )
        outcomes: Dict[str, str] = {}
        for tc in ET.parse(xml_path).iter("testcase"):
            name = tc.get("name")
            # 优先用 junit 的 file 属性（已是仓库相对路径）；缺失才由 classname 点分还原
            file = tc.get("file") or ((tc.get("classname") or "").replace(".", "/") + ".py")
            if not name or not file:
                continue
            if tc.find("failure") is not None:
                oc = "failed"
            elif tc.find("error") is not None:
                oc = "error"
            elif tc.find("skipped") is not None:
                oc = "skipped"
            else:
                oc = "passed"
            outcomes[f"{file}::{name}"] = oc
        return outcomes
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


def restore_pristine_tests(workspace: str, fixture_dir: str) -> None:
    """反作弊：跑判分前，用纯净测试覆盖工作副本里的测试。

    用 fixture_dir 的 tests/ 和 conftest.py 覆盖 workspace 里的同名文件。时机是 run_agent
    之后、run_pytest 之前。
    """
    shutil.copytree(os.path.join(fixture_dir, "tests"),
                    os.path.join(workspace, "tests"), dirs_exist_ok=True)
    shutil.copy(os.path.join(fixture_dir, "conftest.py"),
                os.path.join(workspace, "conftest.py"))


# ─────────────────────────────────────────────────────────────────────────────
# 判分（只依赖 pytest 结果与基线）
# ─────────────────────────────────────────────────────────────────────────────

def judge(post: Dict[str, str], baseline: Dict[str, str],
          target_tests: List[str]) -> Tuple[bool, List[str]]:
    """按回归规则裁决 solved，并列出回归的用例。
    """
    passing_now = {k for k, v in post.items() if v == "passed"}
    baseline_ok = {k for k, v in baseline.items() if v == "passed"}
    regressions = sorted(baseline_ok - passing_now)
    solved = all(t in passing_now for t in target_tests) and not regressions
    return solved, regressions


# ─────────────────────────────────────────────────────────────────────────────
# 单任务生命周期与整轮 bench
# ─────────────────────────────────────────────────────────────────────────────

def run_one_task(task: Task, config: Config, baseline: Dict[str, str]) -> dict:
    """跑完一道题的完整生命周期，返回一个 TaskResult dict。

    准备副本 → 计时跑 run_agent 求解 → 还原纯净测试 → 独立复判 pytest → judge 判分，
    最后无论成败都 cleanup 工作区。wall_s 只算 agent 主循环那段，不含准备副本和判定复跑，
    度量的是 agent 本身；成本直接读 result.total_cost_usd，不在这边重算。
    """
    fixture_dir = os.path.join(os.path.dirname(task.dir), "fixture")
    tr = {
        "task_id": task.id, "status": "ok", "solved": False,
        "steps": 0, "input_tokens": 0, "output_tokens": 0, "tokens": 0,
        "cost_usd": 0.0, "wall_s": 0.0, "stop_reason": None,
        "target_tests": task.target_tests, "regressions": [],
    }
    try:
        workdir = prepare_workspace(task)
    except Exception as e:
        tr["status"] = "patch_failed"
        print(f"[run_one_task] {task.id} patch_failed：{e}", file=sys.stderr)
        return tr

    try:
        t0 = perf_counter()
        try:
            result = run_agent(workdir, task.description, config)
        except Exception as e:
            tr["status"], tr["wall_s"] = "agent_error", perf_counter() - t0
            print(f"[run_one_task] {task.id} agent_error：{e}", file=sys.stderr)
            return tr
        tr["wall_s"] = perf_counter() - t0
        tr["steps"] = result.num_steps
        tr["input_tokens"] = result.total_input_tokens
        tr["output_tokens"] = result.total_output_tokens
        tr["tokens"] = result.total_input_tokens + result.total_output_tokens
        tr["cost_usd"] = result.total_cost_usd or 0.0
        tr["stop_reason"] = result.stop_reason

        restore_pristine_tests(workdir, fixture_dir)
        try:
            post = run_pytest(workdir, config.judge_timeout_s)
        except subprocess.TimeoutExpired:
            tr["status"] = "judge_timeout"
            return tr
        tr["solved"], tr["regressions"] = judge(post, baseline, task.target_tests)
        return tr
    finally:
        cleanup_workspace(workdir)


def run_bench(tasks_dir: str, config: Config, label: str) -> dict:
    """跑完整个任务集，把结果落盘并返回一个 BenchResult dict。
    """
    fixture_dir = os.path.join(tasks_dir, "fixture")
    baseline = capture_baseline(fixture_dir)
    tasks = discover_tasks(tasks_dir)

    task_results = []
    for t in tasks:
        print(f"[bench] ▶ {t.id} …", file=sys.stderr)
        tr = run_one_task(t, config, baseline)
        print(f"[bench]   {t.id}: {'SOLVED' if tr['solved'] else tr['status']} "
              f"(steps={tr['steps']}, ${tr['cost_usd']:.4f})", file=sys.stderr)
        task_results.append(tr)

    n = len(task_results)
    n_solved = sum(1 for tr in task_results if tr["solved"])

    def avg(key):
        return (sum(tr[key] for tr in task_results) / n) if n else 0.0

    summary = {
        "n_tasks": n, "n_solved": n_solved,
        "solve_rate": (n_solved / n) if n else 0.0,
        "pass_at_1": (n_solved / n) if n else 0.0,
        "avg_steps": avg("steps"), "avg_tokens": avg("tokens"),
        "avg_cost_usd": avg("cost_usd"),
        "total_cost_usd": sum(tr["cost_usd"] for tr in task_results),
        "avg_wall_s": avg("wall_s"),
    }

    root = os.path.dirname(os.path.abspath(tasks_dir.rstrip(os.sep)))
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=root, capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        commit = "unknown"

    bench = {
        "label": label,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "repo_commit": commit,
        "config_snapshot": {
            "model": config.model,
            "enable_retrieval": config.enable_retrieval,
            "self_correction": config.self_correction,
            "max_steps": config.max_steps,
            "cost_budget_usd": config.cost_budget_usd,
            "run_tests_timeout_s": config.run_tests_timeout_s,
            "judge_timeout_s": config.judge_timeout_s,
        },
        "tasks": task_results,
        "summary": summary,
    }

    results_dir = os.path.join(root, "eval", "results")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, f"{label}.json"), "w", encoding="utf-8") as f:
        json.dump(bench, f, ensure_ascii=False, indent=2)
    return bench


def render_scorecard(results: List[dict], out_path: str = "eval/scorecard.md") -> None:
    """把一份或多份 BenchResult 渲染成 Markdown 记分卡。
    """
    if not results:
        return
    primary = results[0]
    cs = primary["config_snapshot"]
    sm = primary["summary"]
    L = []
    L.append("# Luna scorecard\n")
    L.append(f"- date: `{primary['timestamp']}`  ·  commit: `{primary['repo_commit']}`")
    L.append(f"- model: `{cs['model']}`  ·  retrieval: `{cs['enable_retrieval']}`  ·  "
             f"self-correction: `{cs['self_correction']}`")
    L.append(f"- guardrails: max_steps=`{cs['max_steps']}`, cost_budget=`${cs['cost_budget_usd']}`, "
             f"run_tests_timeout=`{cs['run_tests_timeout_s']}s`, judge_timeout=`{cs['judge_timeout_s']}s`")
    L.append("")

    # 每任务明细
    L.append(f"## Per-task ({primary['label']})\n")
    L.append("| task | solved | steps | tokens | cost($) | wall(s) | stop_reason | regressions |")
    L.append("|---|:--:|--:|--:|--:|--:|---|---|")
    for tr in primary["tasks"]:
        flag = "✅" if tr["solved"] else ("⚠️ " + tr["status"] if tr["status"] != "ok" else "❌")
        regs = ", ".join(t.split("::")[-1] for t in tr["regressions"]) or "-"
        L.append(f"| {tr['task_id']} | {flag} | {tr['steps']} | {tr['tokens']} | "
                 f"{tr['cost_usd']:.4f} | {tr['wall_s']:.1f} | {tr['stop_reason'] or '-'} | {regs} |")
    L.append("")

    # 汇总
    L.append("## Summary\n")
    L.append(f"- **pass@1 = {sm['n_solved']}/{sm['n_tasks']} = {sm['solve_rate']:.0%}**")
    L.append(f"- avg steps: {sm['avg_steps']:.1f}  ·  avg tokens: {sm['avg_tokens']:.0f}  ·  "
             f"avg cost: ${sm['avg_cost_usd']:.4f}  ·  total cost: ${sm['total_cost_usd']:.2f}  ·  "
             f"avg wall: {sm['avg_wall_s']:.1f}s")
    L.append("")

    # 消融对比（全部 results）
    if len(results) > 1:
        L.append("## Ablations\n")
        L.append("| variant | model | retrieval | self-corr | pass@1 | avg steps | avg cost($) | total($) |")
        L.append("|---|---|:--:|:--:|:--:|--:|--:|--:|")
        for r in results:
            c, s = r["config_snapshot"], r["summary"]
            L.append(f"| {r['label']} | {c['model'].split('/')[-1]} | {c['enable_retrieval']} | "
                     f"{c['self_correction']} | {s['solve_rate']:.0%} | {s['avg_steps']:.1f} | "
                     f"{s['avg_cost_usd']:.4f} | {s['total_cost_usd']:.2f} |")
        L.append("")
        L.append("> 小任务集 + 采样随机性下，条件间的小差异可能是噪声；n_attempts=1。")
        L.append("")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

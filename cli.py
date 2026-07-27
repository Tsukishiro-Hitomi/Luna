"""Luna 的命令行入口。

三个子命令：
  · solve <task_id> —— 单任务：从纯净 fixture 拉一份隔离副本、打上该任务的
    break.patch（此刻目标测试是红的），跑一遍 agent 主循环并流式打印，给人看
    「红 → 迭代 → 绿」的过程。
  · bench —— 整轮评测：遍历任务集，产出 eval/scorecard.md（解决率、平均步数、
    token、成本）。
  · run <repo> —— 对着真实 git 仓库，把它失败的测试修到绿。

启动顺序很讲究：先 load_dotenv() 把 .env 读进环境，再 Config.from_env() 叠加非密钥
旋钮，最后解析参数分发。密钥（ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL）由 anthropic
SDK 自己从环境读，这里不碰——不硬编码、不打印、不写日志、不进 Config。

用法：
    python cli.py solve 001_mul_precedence
    python cli.py bench [--label NAME] [--tasks tasks/] [--keep] [--render-only]
"""

import argparse
import glob
import json
import os
import sys
from typing import Optional, Sequence

from dotenv import load_dotenv

from agent import profile
from agent.config import Config
from agent.sandbox import task_sandbox
from agent.loop import run_agent
from eval.experiment import run_experiment
from eval.run_bench import discover_tasks, run_bench, render_scorecard, validate_task_dataset
from eval.run_repo import run_repo


# 任务集根目录默认值（discover_tasks 会跳过其中的 fixture/）。
DEFAULT_TASKS_DIR = "tasks"
# 记分卡默认落点（入库的展示产物，README 指向它）。
DEFAULT_SCORECARD = "eval/scorecard.md"


def build_parser() -> argparse.ArgumentParser:
    """搭 solve / bench / run 三个子命令的 argparse 解析器。

    这里只描述 CLI 的形状——子命令、位置参数、开关、默认值，不掺任何求解/评测
    逻辑（那些在 cmd_* 和 main 里）。
    """
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Luna — a test-driven autonomous coding agent.",
    )
    sub = parser.add_subparsers(
        dest="command", required=True, metavar="{solve,bench,experiment,validate,run}"
    )

    # —— solve ——（入参是任务目录名/id，与 discover_tasks 一致）
    p_solve = sub.add_parser(
        "solve",
        help="Solve a single task: apply its break.patch to a pristine fixture copy "
             "and run the agent loop until it stops.",
    )
    p_solve.add_argument(
        "task_id",
        help="Task id = task directory name, e.g. 001_mul_precedence.",
    )
    p_solve.add_argument(
        "--tasks",
        default=DEFAULT_TASKS_DIR,
        metavar="DIR",
        help="Task-set root containing fixture/ and NNN_*/ (default: %(default)s).",
    )

    # —— bench ——
    p_bench = sub.add_parser(
        "bench",
        help="Run the whole task set and write eval/scorecard.md.",
    )
    p_bench.add_argument(
        "--label",
        default="baseline",
        metavar="NAME",
        help="Run label; writes eval/results/<NAME>.json, overwriting if it exists "
             "(default: %(default)s).",
    )
    p_bench.add_argument(
        "--tasks",
        default=DEFAULT_TASKS_DIR,
        metavar="DIR",
        help="Task-set root (default: %(default)s).",
    )
    p_bench.add_argument(
        "--keep",
        action="store_true",
        help="Keep each task's temp workspace for debugging instead of cleaning it up.",
    )
    p_bench.add_argument(
        "--render-only",
        action="store_true",
        help="Skip running; just rebuild eval/scorecard.md from existing "
             "eval/results/*.json (loss-lessly re-renders, incl. the ablation table).",
    )
    # —— 消融旋钮（V9）：相对 baseline 只翻一个，各跑一次 --label ——
    p_bench.add_argument(
        "--model",
        metavar="ID",
        help="Override the model for this run (e.g. anthropic/claude-haiku-4.5). "
             "Default: config.model.",
    )
    p_bench.add_argument(
        "--self-correction",
        action="store_true",
        help="Enable the self-correction system-prompt section (ablation).",
    )
    p_bench.add_argument(
        "--retrieval",
        action="store_true",
        help="Enable embedding retrieval (V8): prepend relevant code to the first message.",
    )
    p_validate = sub.add_parser(
        "validate",
        help="Validate every fixture and break patch offline; never calls the model.",
    )
    p_validate.add_argument(
        "--tasks", default=DEFAULT_TASKS_DIR, metavar="DIR",
        help="Task-set root (default: %(default)s).",
    )
    p_validate.add_argument(
        "--timeout", type=int, default=60, metavar="SEC",
        help="Per-pytest timeout during validation (default: %(default)s).",
    )
    p_experiment = sub.add_parser(
        "experiment",
        help="Run or resume an auditable repeated benchmark campaign.",
    )
    p_experiment.add_argument(
        "--campaign", required=True, metavar="NAME",
        help="Stable campaign name used for its artifact directory.",
    )
    p_experiment.add_argument(
        "--attempts", type=int, default=3, metavar="N",
        help="Independent attempts per task and variant (default: %(default)s).",
    )
    p_experiment.add_argument(
        "--variants", default="baseline,haiku,retrieval", metavar="LIST",
        help="Comma-separated subset of baseline,haiku,retrieval.",
    )
    p_experiment.add_argument(
        "--tasks", default=DEFAULT_TASKS_DIR, metavar="DIR",
        help="Task-set root (default: %(default)s).",
    )
    p_experiment.add_argument(
        "--cost-cap", type=float, default=40.0, metavar="USD",
        help="Stop launching attempts after this campaign cost (default: %(default)s).",
    )
    p_experiment.add_argument(
        "--publish", action="store_true",
        help="Write versionable eval/artifacts output; requires a clean Git worktree.",
    )
    # —— run（v2）：指向真实 git 仓库，以其失败的测试为目标修到绿 ——
    p_run = sub.add_parser(
        "run",
        help="Point the agent at a real git repo with failing tests and fix them to green.",
    )
    p_run.add_argument("repo_path", help="Target git repo root (must be the repo root, clean tree).")
    p_run.add_argument("task", nargs="?", default=None,
                       help="Optional natural-language context (does NOT affect the oracle).")
    p_run.add_argument("--test-cmd", metavar="CMD",
                       help="Generic escape hatch: run this literal command, judge by exit code only "
                            "(no per-test verdict/regression). Default: pytest mode.")
    p_run.add_argument("--python", metavar="INTERP",
                       help="Interpreter for pytest (target repo's venv). Default: <repo>/.venv if present, else this python.")
    p_run.add_argument("--target", action="append", metavar="NODE_ID", default=None,
                       help="Narrow the oracle to specific failing node id(s); repeatable.")
    p_run.add_argument("--branch", metavar="NAME", help="Work branch name (default: luna/fix-<ts>).")
    p_run.add_argument("--allow-dirty", action="store_true", help="Proceed on a dirty tree (never resets your changes).")
    p_run.add_argument("--name", metavar="NAME", help="Remember your name for the greeting.")
    p_run.add_argument("--model", metavar="ID", help="Override model.")
    p_run.add_argument("--max-steps", type=int, metavar="N", help="Raise the step guardrail (real repos need more).")
    p_run.add_argument("--budget", type=float, metavar="USD", help="Raise the per-run cost budget.")
    p_run.add_argument("--timeout", type=int, metavar="SEC", help="Test timeout (run_tests + judge).")
    p_run.add_argument("--stream", action="store_true", help="Stream model text live (cost becomes a lower bound).")
    return parser


def cmd_solve(args: argparse.Namespace, config: Config) -> int:
    """跑 solve：把一个任务从红做到绿。纯 CLI 装配，真正的活在 agent 循环里。

    流程是：在 <tasks>/fixture 上按 id 找到目标任务（找不到就报错、返回非零），
    用 task_sandbox 上下文管理器拉一份纯净副本并打上 break.patch（此刻测试是红的），
    跑 run_agent，with 退出时自动清理副本。开了流式，模型文本边生成边显示，长任务
    不至于黑屏干等。最后打印轨迹和一行摘要。

    注意 solve 不做 solved 判定——它只给人看过程，判分是 bench / harness 的事。
    """
    task = next((t for t in discover_tasks(args.tasks) if t.id == args.task_id), None)
    if task is None:
        print(f"错误：找不到任务 {args.task_id}（在 {args.tasks}/ 下）", file=sys.stderr)
        return 1

    config.stream = True  # V7：solve 开流式，模型文本边生成边显示
    print(f"▶ solve {task.id} · {task.title}\n")
    with task_sandbox(task.fixture_dir, task.break_patch) as workdir:
        result = run_agent(
            workdir, task.description, config,
            on_text=lambda t: print(t, end="", flush=True),  # 实时打印模型文本
        )
        print("\n\n—— 轨迹 ——")
        for s in result.steps:
            names = "、".join(tc.name for tc in s.tool_calls) or "（收尾）"
            print(f"  #{s.index}: {names}")

    print(f"\nstop_reason={result.stop_reason}  steps={result.num_steps}  "
          f"tokens={result.total_input_tokens}/{result.total_output_tokens}  "
          f"cost=${result.total_cost_usd:.4f}")
    if result.total_output_tokens == 0 and result.num_steps > 0:
        print("（注：流式下本网关不回传 output tokens；成本为下界，准确值见 `cli.py bench`）")
    if result.final_text.strip():
        print("summary:", result.final_text.strip())
    return 0


def cmd_bench(args: argparse.Namespace, config: Config) -> int:
    """跑 bench：整轮评测再渲染记分卡。纯 CLI 装配，真正的活在 eval 层。

    --render-only 时不重跑，直接把 eval/results/*.json 读回来重建记分卡（含消融
    对比表）；否则先 run_bench 落一份 eval/results/<label>.json，再连同已有结果一起
    渲染。--keep 透传给 eval 侧，让每个任务的临时工作副本留着方便调试（默认清理）。

    消融的玩法：每个条件相对 baseline 只翻一个旋钮、各跑一次 bench --label ...，
    最后 bench --render-only 汇成对比表。
    """
    config.stream = False  # bench 关流式：本网关流式不回传 output_tokens，非流式才准
    if args.model:
        config.model = args.model                 # V9 消融：换脑（opus↔haiku）
    if args.self_correction:
        config.self_correction = True             # V9 消融：开反思段
    if args.retrieval:
        config.enable_retrieval = True            # V8 消融：开 embedding 检索

    def _load_all():
        files = sorted(glob.glob(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "eval", "results", "*.json")))
        rs = []
        for fp in files:
            with open(fp, encoding="utf-8") as f:
                rs.append(json.load(f))
        rs.sort(key=lambda r: (r.get("label") != "baseline", r.get("label", "")))
        return rs

    if args.render_only:
        results = _load_all()
        if not results:
            print("错误：eval/results/ 下没有结果可渲染（先跑一次 bench）", file=sys.stderr)
            return 1
        render_scorecard(results, DEFAULT_SCORECARD)
        print(f"已从 {len(results)} 组结果重建 {DEFAULT_SCORECARD}")
        return 0

    run_bench(args.tasks, config, args.label)
    results = _load_all()
    render_scorecard(results, DEFAULT_SCORECARD)
    print(f"记分卡写入 {DEFAULT_SCORECARD}（{len(results)} 组结果）")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Run the dataset's green/red/reverse-patch gates without model access."""
    try:
        report = validate_task_dataset(args.tasks, timeout_s=args.timeout)
    except Exception as e:
        print(f"Dataset validation failed: {e}", file=sys.stderr)
        return 1
    if not report["valid"]:
        print(f"INVALID: {report['n_tasks']} tasks across {report['n_fixtures']} fixtures")
        for error in report["errors"]:
            print(f"  - {error}")
        return 1
    print(f"VALID: {report['n_tasks']} tasks across {report['n_fixtures']} fixtures")
    return 0


def cmd_experiment(args: argparse.Namespace, config: Config) -> int:
    variants = [item.strip() for item in args.variants.split(",") if item.strip()]
    try:
        summary = run_experiment(
            args.tasks, config, args.campaign, args.attempts, variants,
            args.cost_cap, publish=args.publish,
            command=["python", "cli.py", *sys.argv[1:]],
        )
    except Exception as e:
        print(f"Experiment failed: {e}", file=sys.stderr)
        return 1
    print(
        f"Campaign {args.campaign}: {summary['n_attempt_records']} attempts, "
        f"estimated cost ${summary['total_cost_usd']:.2f}"
    )
    return 0


def cmd_run(args: argparse.Namespace, config: Config) -> int:
    """执行 `run` 子命令：真实 git 仓库修红测试（v2，行为在 eval/run_repo.py）。"""
    # 解释器：--python > <repo>/.venv/bin/python > 默认；agent 与 harness 共用同一个
    if args.python:
        config.test_python = args.python
    else:
        venv_py = os.path.join(os.path.realpath(args.repo_path), ".venv", "bin", "python")
        if os.path.exists(venv_py):
            config.test_python = venv_py
    if args.test_cmd:
        config.test_cmd = args.test_cmd
    if args.model:
        config.model = args.model
    if args.max_steps is not None:
        config.max_steps = args.max_steps
    if args.budget is not None:
        config.cost_budget_usd = args.budget
    if args.timeout is not None:
        config.run_tests_timeout_s = args.timeout
        config.judge_timeout_s = args.timeout
    config.stream = bool(args.stream)  # run 默认非流式（成本准确、预算护栏有效）

    on_text = (lambda t: print(t, end="", flush=True)) if config.stream else None
    print(f"▶ run {args.repo_path}")
    r = run_repo(args.repo_path, config, task=args.task, targets=args.target,
                 allow_dirty=args.allow_dirty, branch=args.branch, on_text=on_text)

    if r.status in ("not_git_repo", "not_repo_root", "dirty_tree", "mid_operation",
                    "no_tests_collected", "baseline_error"):
        print(f"✗ {r.status}：{r.message}")
        return 1

    s = r.baseline_summary
    print(f"\n基线：{s.get('passed', 0)} passed / {s.get('failed', 0)} failed / "
          f"{s.get('error', 0)} error / {s.get('skipped', 0)} skipped（mode={r.mode}）")
    if r.status == "no_failing_tests":
        print(f"→ {r.message}")
        return 0

    short = lambda ts: "、".join(t.split("::")[-1] for t in ts[:8]) + ("…" if len(ts) > 8 else "")
    print(f"目标（{len(r.target_tests)}）：{short(r.target_tests)}")
    if config.stream:
        print()  # 流式输出后补一个换行
    print(f"分支：{r.branch}（基线 {r.base_ref or 'detached'} @ {(r.base_sha or '?')[:8]}）")
    print(f"步数 {r.steps} · tokens {r.input_tokens}/{r.output_tokens} · "
          f"cost ${r.cost_usd:.4f} · {r.wall_s:.1f}s · stop={r.stop_reason}")
    print(("✅ SOLVED" if r.solved else "❌ NOT SOLVED") +
          f"  fixed={len(r.fixed)}/{len(r.target_tests)}  regressions={len(r.regressions)}")
    if r.regressions:
        print(f"  回归：{short(r.regressions)}")
    if r.still_failing:
        print(f"  仍红：{short(r.still_failing)}")
    n_files = sum(1 for ln in r.diff.splitlines() if ln.startswith("+++ "))
    print(f"\n改动文件：{n_files}；未跟踪：{len(r.untracked)}")
    print(f"查看改动：git -C {args.repo_path} diff {(r.base_sha or 'HEAD')[:8]}")
    print(f"丢弃改动：git -C {args.repo_path} checkout . && git -C {args.repo_path} clean -fd（先加 --dry-run）")
    return 0 if r.solved else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 主入口：接线加分发。

    顺序是先 load_dotenv() 把 .env 读进环境，再 Config.from_env() 在默认值上叠非
    密钥旋钮，然后解析参数、按 args.command 分发到对应 cmd_*。密钥类环境变量由
    anthropic SDK 直接读，绝不进 Config、绝不打印。

    argv 缺省时用 sys.argv[1:]，传进来主要是方便测试注入。返回进程退出码。
    """
    load_dotenv()
    config = Config.from_env()
    # 流式在各子命令内按需设置：solve 开（实时显示）、bench/run 关（成本记账准确）。
    args = build_parser().parse_args(argv)
    if getattr(args, "name", None):        # run --name：先记名字，问候才用得上
        profile.set_name(args.name)
    print(profile.greeting(profile.resolve_name()))   # 所有子命令统一问候一次（仅终端，不进产物）
    if args.command == "solve":
        return cmd_solve(args, config)
    if args.command == "bench":
        return cmd_bench(args, config)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "experiment":
        return cmd_experiment(args, config)
    if args.command == "run":
        return cmd_run(args, config)
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

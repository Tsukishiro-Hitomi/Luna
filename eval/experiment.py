"""Resumable, auditable repeated benchmark campaigns."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional

import pytest

from agent.config import Config
from eval.run_bench import (
    Task,
    capture_baseline,
    discover_tasks,
    run_one_task,
    validate_task_dataset,
)


VARIANTS = ("baseline", "haiku", "retrieval")
_CAMPAIGN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _git(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)


def repository_state(root: str) -> dict:
    commit = _git(root, "rev-parse", "--short", "HEAD").stdout.strip() or "unknown"
    lines = _git(root, "status", "--porcelain").stdout.splitlines()
    changes = []
    for line in lines:
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        changes.append(path.strip('"'))
    return {"commit": commit, "dirty": bool(changes), "changes": changes}


def _sanitized_command(command: Optional[List[str]]) -> List[str]:
    home = os.path.expanduser("~")
    values = list(command or sys.argv)
    if not home or home == os.sep:
        return values
    return [value.replace(home, "~") for value in values]


def task_dataset_digest(tasks_dir: str) -> str:
    """Hash all task metadata, patches, and fixture source files."""
    digest = hashlib.sha256()
    root = os.path.realpath(tasks_dir)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in ("__pycache__", ".pytest_cache")
        )
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")) or name == "README.md":
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def config_for_variant(base: Config, variant: str) -> Config:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    config = replace(base, price_per_mtok=dict(base.price_per_mtok))
    config.stream = False
    config.enable_retrieval = variant == "retrieval"
    if variant == "haiku":
        config.model = config.model_haiku
    return config


def _safe_config(config: Config) -> dict:
    """Serialize only non-secret benchmark settings."""
    raw = asdict(config)
    raw.pop("price_per_mtok", None)
    raw.pop("test_python", None)
    raw.pop("test_cmd", None)
    return raw


def build_manifest(
    root: str,
    tasks_dir: str,
    campaign: str,
    variants: List[str],
    attempts: int,
    cost_cap_usd: float,
    base_config: Config,
    command: Optional[List[str]] = None,
) -> dict:
    state = repository_state(root)
    return {
        "schema_version": 1,
        "campaign": campaign,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "repo_commit": state["commit"],
        "dirty_tree": state["dirty"],
        "task_digest_sha256": task_dataset_digest(tasks_dir),
        "n_tasks": len(discover_tasks(tasks_dir, strict=True)),
        "attempts_per_task": attempts,
        "variants": variants,
        "cost_cap_usd": cost_cap_usd,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "pytest": pytest.__version__,
        "config": _safe_config(base_config),
        "command": _sanitized_command(command),
    }


def _write_json(path: str, value: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def load_attempts(path: str) -> List[dict]:
    if not os.path.isfile(path):
        return []
    records = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
    return records


def _append_attempt(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def wilson_interval(solved: int, total: int, z: float = 1.959963984540054) -> List[float]:
    if total <= 0:
        return [0.0, 0.0]
    p = solved / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _metric_summary(records: List[dict], key: str) -> dict:
    values = [float(record.get(key, 0.0) or 0.0) for record in records]
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "median": 0.0}
    return {
        "mean": statistics.fmean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "median": statistics.median(values),
    }


def summarize_group(records: List[dict]) -> dict:
    total = len(records)
    solved = sum(bool(record.get("solved")) for record in records)
    invalid = sum(record.get("status") != "ok" for record in records)
    return {
        "attempts": total,
        "solved": solved,
        "solve_rate": solved / total if total else 0.0,
        "solve_rate_wilson_95": wilson_interval(solved, total),
        "invalid_or_error": invalid,
        "steps": _metric_summary(records, "steps"),
        "tokens": _metric_summary(records, "tokens"),
        "cost_usd": _metric_summary(records, "cost_usd"),
        "wall_s": _metric_summary(records, "wall_s"),
    }


def _group(records: Iterable[dict], key: str) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for record in records:
        grouped.setdefault(str(record.get(key, "unknown")), []).append(record)
    return grouped


def _paired_deltas(records: List[dict]) -> dict:
    lookup = {
        (record["variant"], record["task_id"], record["attempt_index"]): record
        for record in records
    }
    output = {}
    for variant in sorted({record["variant"] for record in records} - {"baseline"}):
        pairs = []
        for (name, task_id, attempt_index), candidate in lookup.items():
            if name != variant:
                continue
            baseline = lookup.get(("baseline", task_id, attempt_index))
            if baseline is not None:
                pairs.append((baseline, candidate))
        output[variant] = {
            "pairs": len(pairs),
            "solve_rate_delta": statistics.fmean(
                float(candidate["solved"]) - float(baseline["solved"])
                for baseline, candidate in pairs
            ) if pairs else 0.0,
        }
        for key in ("steps", "tokens", "cost_usd", "wall_s"):
            deltas = [
                float(candidate.get(key, 0.0)) - float(baseline.get(key, 0.0))
                for baseline, candidate in pairs
            ]
            output[variant][f"{key}_mean_delta"] = statistics.fmean(deltas) if deltas else 0.0
    return output


def aggregate_attempts(records: List[dict], manifest: dict) -> dict:
    variants = _group(records, "variant")
    return {
        "schema_version": 1,
        "campaign": manifest["campaign"],
        "repo_commit": manifest["repo_commit"],
        "task_digest_sha256": manifest["task_digest_sha256"],
        "attempts_per_task": manifest["attempts_per_task"],
        "n_attempt_records": len(records),
        "total_cost_usd": sum(float(record.get("cost_usd", 0.0) or 0.0) for record in records),
        "variants": {
            name: {
                "overall": summarize_group(items),
                "by_fixture": {
                    group: summarize_group(group_records)
                    for group, group_records in sorted(_group(items, "fixture").items())
                },
                "by_difficulty": {
                    group: summarize_group(group_records)
                    for group, group_records in sorted(_group(items, "difficulty").items())
                },
                "by_task": {
                    group: summarize_group(group_records)
                    for group, group_records in sorted(_group(items, "task_id").items())
                },
            }
            for name, items in sorted(variants.items())
        },
        "paired_against_baseline": _paired_deltas(records),
    }


def render_report(summary: dict) -> str:
    lines = [
        f"# Luna experiment: {summary['campaign']}",
        "",
        f"- commit: `{summary['repo_commit']}`",
        f"- task digest: `{summary['task_digest_sha256']}`",
        f"- attempts per task: `{summary['attempts_per_task']}`",
        f"- recorded attempts: `{summary['n_attempt_records']}`",
        f"- total estimated cost: `${summary['total_cost_usd']:.2f}`",
        "",
        "## Variants",
        "",
        "| variant | solved | solve rate | 95% Wilson CI | steps mean±sd | cost mean±sd | invalid |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, data in summary["variants"].items():
        overall = data["overall"]
        low, high = overall["solve_rate_wilson_95"]
        lines.append(
            f"| {name} | {overall['solved']}/{overall['attempts']} | "
            f"{overall['solve_rate']:.1%} | {low:.1%}–{high:.1%} | "
            f"{overall['steps']['mean']:.2f}±{overall['steps']['stdev']:.2f} | "
            f"${overall['cost_usd']['mean']:.4f}±{overall['cost_usd']['stdev']:.4f} | "
            f"{overall['invalid_or_error']} |"
        )

    lines.extend(["", "## Per-fixture solve rate", ""])
    fixtures = sorted({
        fixture for variant in summary["variants"].values()
        for fixture in variant["by_fixture"]
    })
    lines.append("| variant | " + " | ".join(fixtures) + " |")
    lines.append("|---|" + "---:|" * len(fixtures))
    for name, data in summary["variants"].items():
        values = [
            f"{data['by_fixture'][fixture]['solve_rate']:.1%}"
            if fixture in data["by_fixture"] else "-"
            for fixture in fixtures
        ]
        lines.append(f"| {name} | " + " | ".join(values) + " |")

    if summary["paired_against_baseline"]:
        lines.extend([
            "", "## Paired deltas against baseline", "",
            "Positive values mean the variant used more resources than baseline.", "",
            "| variant | pairs | solve-rate Δ | steps Δ | tokens Δ | cost Δ | wall Δ |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ])
        for name, data in summary["paired_against_baseline"].items():
            lines.append(
                f"| {name} | {data['pairs']} | {data['solve_rate_delta']:+.1%} | "
                f"{data['steps_mean_delta']:+.2f} | {data['tokens_mean_delta']:+.0f} | "
                f"${data['cost_usd_mean_delta']:+.4f} | {data['wall_s_mean_delta']:+.2f}s |"
            )

    lines.extend([
        "", "> Repeated-run solve rate is an empirical proportion across attempts. It is not",
        "> presented as a deterministic guarantee. Harness errors remain in the denominator.", "",
    ])
    return "\n".join(lines)


def _attempt_record(task: Task, variant: str, attempt_index: int, result: dict) -> dict:
    allowed = {
        "status", "solved", "steps", "input_tokens", "output_tokens", "tokens",
        "cost_usd", "wall_s", "stop_reason", "target_tests", "regressions",
        "fixture", "difficulty", "tags",
    }
    record = {key: value for key, value in result.items() if key in allowed}
    record.update({
        "attempt_id": f"{variant}/{task.id}/{attempt_index}",
        "variant": variant,
        "task_id": task.id,
        "attempt_index": attempt_index,
        "fixture": task.fixture_id,
        "difficulty": task.difficulty,
        "tags": list(task.tags),
        "recorded_at": _now(),
    })
    return record


def run_experiment(
    tasks_dir: str,
    base_config: Config,
    campaign: str,
    attempts: int,
    variants: List[str],
    cost_cap_usd: float,
    *,
    publish: bool = False,
    output_root: Optional[str] = None,
    run_task: Callable[[Task, Config, dict], dict] = run_one_task,
    validate: bool = True,
    command: Optional[List[str]] = None,
) -> dict:
    """Run or resume a campaign, persisting each terminal attempt immediately."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if not _CAMPAIGN_NAME.fullmatch(campaign):
        raise ValueError("campaign must contain only letters, digits, dot, underscore, and dash")
    if cost_cap_usd <= 0:
        raise ValueError("cost cap must be positive")
    variants = list(dict.fromkeys(variants))
    unknown = sorted(set(variants) - set(VARIANTS))
    if unknown:
        raise ValueError(f"unknown variants: {', '.join(unknown)}")

    root = os.path.dirname(os.path.abspath(tasks_dir.rstrip(os.sep)))
    if output_root is None:
        family = "artifacts" if publish else os.path.join("results", "campaigns")
        output_root = os.path.join(root, "eval", family, campaign)
    state = repository_state(root)
    if publish and state["dirty"]:
        artifact_rel = os.path.relpath(os.path.realpath(output_root), os.path.realpath(root))
        artifact_rel = artifact_rel.rstrip(os.sep) + os.sep
        changes = state.get("changes") or ["<unknown>"]
        disallowed = [path for path in changes if not path.startswith(artifact_rel)]
        if disallowed:
            raise RuntimeError(
                "official publish mode requires a clean Git worktree; unrelated changes: "
                + ", ".join(disallowed)
            )
    if validate:
        validation = validate_task_dataset(tasks_dir, base_config.judge_timeout_s)
        if not validation["valid"]:
            raise RuntimeError("task dataset validation failed: " + "; ".join(validation["errors"]))

    os.makedirs(output_root, exist_ok=True)
    manifest_path = os.path.join(output_root, "manifest.json")
    attempts_path = os.path.join(output_root, "attempts.jsonl")
    summary_path = os.path.join(output_root, "summary.json")
    report_path = os.path.join(output_root, "report.md")

    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        expected = (
            state["commit"], task_dataset_digest(tasks_dir), attempts, variants,
            float(cost_cap_usd),
        )
        actual = (
            manifest["repo_commit"], manifest["task_digest_sha256"],
            manifest["attempts_per_task"], manifest["variants"],
            float(manifest["cost_cap_usd"]),
        )
        if actual != expected:
            raise RuntimeError(
                "cannot resume: commit, task digest, attempts, variants, or cost cap changed"
            )
    else:
        manifest = build_manifest(
            root, tasks_dir, campaign, variants, attempts, cost_cap_usd,
            base_config, command,
        )
        _write_json(manifest_path, manifest)

    tasks = discover_tasks(tasks_dir, strict=True)
    baselines = {}
    for task in tasks:
        if task.fixture_id not in baselines:
            baselines[task.fixture_id] = capture_baseline(task.fixture_dir)

    records = load_attempts(attempts_path)
    seen = {record["attempt_id"] for record in records}
    spent = sum(float(record.get("cost_usd", 0.0) or 0.0) for record in records)

    for variant in variants:
        config = config_for_variant(base_config, variant)
        for task in tasks:
            for attempt_index in range(1, attempts + 1):
                attempt_id = f"{variant}/{task.id}/{attempt_index}"
                if attempt_id in seen:
                    continue
                if spent >= cost_cap_usd:
                    manifest["status"] = "budget_exhausted"
                    manifest["finished_at"] = _now()
                    _write_json(manifest_path, manifest)
                    summary = aggregate_attempts(records, manifest)
                    _write_json(summary_path, summary)
                    with open(report_path, "w", encoding="utf-8") as handle:
                        handle.write(render_report(summary))
                    return summary
                print(f"[experiment] {attempt_id}", file=sys.stderr)
                result = run_task(task, config, baselines[task.fixture_id])
                record = _attempt_record(task, variant, attempt_index, result)
                _append_attempt(attempts_path, record)
                records.append(record)
                seen.add(attempt_id)
                spent += float(record.get("cost_usd", 0.0) or 0.0)

    manifest["status"] = "complete"
    manifest["finished_at"] = _now()
    _write_json(manifest_path, manifest)
    summary = aggregate_attempts(records, manifest)
    _write_json(summary_path, summary)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(render_report(summary))
    return summary

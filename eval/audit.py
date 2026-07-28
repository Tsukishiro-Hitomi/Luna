"""Offline integrity checks for published experiments and real-repository cases."""

from __future__ import annotations

import json
import os
import re
from typing import List

from eval.experiment import aggregate_attempts, load_attempts, render_report


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SENSITIVE_PATTERNS = (
    ("absolute macOS home path", re.compile(r"/Users/[^\s/'\"`]+/")),
    ("absolute Linux home path", re.compile(r"/home/[^\s/'\"`]+/")),
    ("Anthropic-style secret", re.compile(r"sk-ant-[A-Za-z0-9_-]{12,}")),
)
_TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".patch", ".py", ".txt"}


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _scan_tree(root: str) -> List[str]:
    errors: List[str] = []
    if not os.path.isdir(root):
        return errors
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.splitext(name)[1] not in _TEXT_SUFFIXES:
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                content = handle.read()
            for label, pattern in _SENSITIVE_PATTERNS:
                if pattern.search(content):
                    errors.append(f"{os.path.relpath(path, root)} contains {label}")
    return errors


def verify_experiment_artifact(directory: str) -> List[str]:
    """Recompute a committed summary and report from its immutable attempt records."""
    errors: List[str] = []
    required = ("manifest.json", "attempts.jsonl", "summary.json", "report.md")
    missing = [name for name in required if not os.path.isfile(os.path.join(directory, name))]
    if missing:
        return [f"{directory}: missing {', '.join(missing)}"]
    try:
        manifest = _read_json(os.path.join(directory, "manifest.json"))
        records = load_attempts(os.path.join(directory, "attempts.jsonl"))
        committed = _read_json(os.path.join(directory, "summary.json"))
        recomputed = aggregate_attempts(records, manifest)
        if committed != recomputed:
            errors.append(f"{directory}: summary.json does not match attempts.jsonl")
        with open(os.path.join(directory, "report.md"), encoding="utf-8") as handle:
            report = handle.read()
        if report != render_report(recomputed):
            errors.append(f"{directory}: report.md does not match the recomputed summary")
        attempt_ids = [record.get("attempt_id") for record in records]
        if len(attempt_ids) != len(set(attempt_ids)):
            errors.append(f"{directory}: duplicate attempt_id values")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"{directory}: {type(exc).__name__}: {exc}")
    return errors


def verify_real_case_index(real_cases_dir: str) -> List[str]:
    """Validate provenance, local references, and benchmark separation for every case."""
    errors: List[str] = []
    index_path = os.path.join(real_cases_dir, "index.json")
    try:
        index = _read_json(index_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"{index_path}: {type(exc).__name__}: {exc}"]
    if index.get("schema_version") != 1:
        errors.append("real-case index must use schema_version 1")
    cases = index.get("cases")
    if not isinstance(cases, list) or not cases:
        return errors + ["real-case index must contain a non-empty cases list"]
    ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or any(not value for value in ids):
        errors.append("every real case must have a case_id")
    if len(ids) != len(set(ids)):
        errors.append("real-case IDs must be unique")

    required_fields = (
        "case_id", "directory", "status", "upstream_url", "issue_url", "license",
        "base_commit", "reproduction_patch", "preparation_script", "test_command",
        "result_file", "included_in_controlled_pass_at_1",
    )
    for entry in cases:
        if not isinstance(entry, dict):
            errors.append("real-case entries must be JSON objects")
            continue
        case_id = entry.get("case_id", "<unknown>")
        missing = [field for field in required_fields if field not in entry]
        if missing:
            errors.append(f"{case_id}: missing index fields: {', '.join(missing)}")
            continue
        if entry["status"] not in {"planned", "reproduced", "solved"}:
            errors.append(f"{case_id}: invalid status")
        if not entry["license"] or not entry["test_command"]:
            errors.append(f"{case_id}: license and test_command must be non-empty")
        if entry["included_in_controlled_pass_at_1"] is not False:
            errors.append(f"{case_id}: real cases must be excluded from controlled pass@1")
        if not _COMMIT_RE.fullmatch(str(entry["base_commit"])):
            errors.append(f"{case_id}: base_commit must be a pinned 40-character SHA")
        for field in ("upstream_url", "issue_url"):
            if not str(entry[field]).startswith("https://"):
                errors.append(f"{case_id}: {field} must be an HTTPS URL")
        directory = str(entry["directory"])
        if not _safe_relative_path(directory):
            errors.append(f"{case_id}: directory must stay within eval/real_cases")
            continue
        case_dir = os.path.join(real_cases_dir, directory)
        for field in ("reproduction_patch", "preparation_script", "result_file"):
            filename = str(entry[field])
            if not _safe_relative_path(filename):
                errors.append(f"{case_id}: {field} must be a safe relative path")
                continue
            path = os.path.join(case_dir, filename)
            if not os.path.isfile(path):
                errors.append(f"{case_id}: missing {field} file {entry[field]}")
        result_filename = str(entry["result_file"])
        result_path = os.path.join(case_dir, result_filename)
        if _safe_relative_path(result_filename) and os.path.isfile(result_path):
            try:
                result = _read_json(result_path)
                upstream = result["upstream"]
                if result.get("case_id") != case_id:
                    errors.append(f"{case_id}: result case_id does not match index")
                mappings = {
                    "upstream_url": upstream.get("url"),
                    "issue_url": upstream.get("issue_url"),
                    "license": upstream.get("license"),
                    "base_commit": upstream.get("base_commit"),
                }
                for field, value in mappings.items():
                    if entry[field] != value:
                        errors.append(f"{case_id}: {field} differs between index and result")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{case_id}: invalid result file: {exc}")
    return errors


def _safe_relative_path(value: str) -> bool:
    normalized = os.path.normpath(value)
    return (
        bool(value)
        and not os.path.isabs(value)
        and normalized != ".."
        and not normalized.startswith(".." + os.sep)
    )


def audit_repository(root: str) -> dict:
    """Audit all committed evidence without running tests or calling a model."""
    root = os.path.realpath(root)
    errors: List[str] = []
    artifacts_root = os.path.join(root, "eval", "artifacts")
    artifact_dirs: List[str] = []
    if os.path.isdir(artifacts_root):
        artifact_dirs = sorted(
            os.path.join(artifacts_root, name)
            for name in os.listdir(artifacts_root)
            if os.path.isdir(os.path.join(artifacts_root, name))
        )
    if not artifact_dirs:
        errors.append("no published experiment artifacts found")
    for directory in artifact_dirs:
        errors.extend(verify_experiment_artifact(directory))

    real_cases_root = os.path.join(root, "eval", "real_cases")
    errors.extend(verify_real_case_index(real_cases_root))
    for evidence_root in (artifacts_root, real_cases_root):
        errors.extend(
            f"{os.path.relpath(evidence_root, root)}: {error}"
            for error in _scan_tree(evidence_root)
        )
    return {
        "valid": not errors,
        "artifact_campaigns": len(artifact_dirs),
        "real_cases": _real_case_count(real_cases_root),
        "errors": errors,
    }


def _real_case_count(real_cases_dir: str) -> int:
    try:
        cases = _read_json(os.path.join(real_cases_dir, "index.json")).get("cases", [])
        return len(cases) if isinstance(cases, list) else 0
    except (OSError, ValueError, json.JSONDecodeError):
        return 0

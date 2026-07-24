"""eval.run_repo 单测（v2 编排器）：git 安全 / target=失败测试 / judge / 反作弊 / 早退。

全程 monkeypatch 掉 run_agent（不打网关），在临时 git 仓库上验证编排与判定。
"""
import os
import subprocess
import types

import pytest

from agent.config import Config
from eval import run_repo as rr

GOOD_CALC = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
BUG_CALC = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a + b\n"  # sub 写成加法
TEST_CALC = (
    "from calc import add, sub\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n"
    "def test_sub():\n    assert sub(5, 3) == 2\n"
)


def _git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)


def _mk_repo(tmp_path, calc_src):
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "calc.py").write_text(calc_src, encoding="utf-8")
    (repo / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
    _git(str(repo), "init", "-q")
    _git(str(repo), "add", "-A")
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@e", "-c", "user.name=t",
                    "commit", "-qm", "base"], capture_output=True, text=True)
    return str(repo)


def _fake_agent(write_calc=None, write_test=None):
    """返回一个假 run_agent：往仓库写指定文件内容，模拟 agent 的改动。"""
    def _fn(repo, desc, config, on_text=None):
        if write_calc is not None:
            with open(os.path.join(repo, "calc.py"), "w", encoding="utf-8") as f:
                f.write(write_calc)
        if write_test is not None:
            with open(os.path.join(repo, "test_calc.py"), "w", encoding="utf-8") as f:
                f.write(write_test)
        return types.SimpleNamespace(num_steps=3, total_input_tokens=100,
                                     total_output_tokens=20, total_cost_usd=0.001,
                                     stop_reason="model_stop")
    return _fn


def test_solved(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path, BUG_CALC)
    monkeypatch.setattr("eval.run_repo.run_agent", _fake_agent(write_calc=GOOD_CALC))
    r = rr.run_repo(repo, Config())
    assert r.status == "solved" and r.solved
    assert any("test_sub" in t for t in r.fixed)
    assert r.regressions == []
    assert r.branch and r.branch.startswith("fixpoint/fix-")
    assert "calc.py" in r.diff


def test_no_failing_tests_early_exit(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path, GOOD_CALC)  # 全绿
    called = {"n": 0}

    def _should_not_run(*a, **k):
        called["n"] += 1
        return types.SimpleNamespace(num_steps=0, total_input_tokens=0,
                                     total_output_tokens=0, total_cost_usd=0.0, stop_reason="x")

    monkeypatch.setattr("eval.run_repo.run_agent", _should_not_run)
    r = rr.run_repo(repo, Config())
    assert r.status == "no_failing_tests" and not r.solved
    assert called["n"] == 0            # 没跑 agent
    assert r.branch is None            # 没建分支


def test_regression_caught(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path, BUG_CALC)
    # 修好 sub，却把 add 弄坏（return a*b）
    broke_add = "def add(a, b):\n    return a * b\n\n\ndef sub(a, b):\n    return a - b\n"
    monkeypatch.setattr("eval.run_repo.run_agent", _fake_agent(write_calc=broke_add))
    r = rr.run_repo(repo, Config())
    assert not r.solved
    assert any("test_add" in t for t in r.regressions)


def test_anti_cheat_restores_tests(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path, BUG_CALC)
    # 作弊：不改 calc.py，改把 test_sub 断言删掉让它假绿
    cheat_test = ("from calc import add, sub\n\n"
                  "def test_add():\n    assert add(2, 3) == 5\n\n"
                  "def test_sub():\n    pass\n")
    monkeypatch.setattr("eval.run_repo.run_agent", _fake_agent(write_test=cheat_test))
    r = rr.run_repo(repo, Config())
    assert not r.solved                # 原版测试被还原 → test_sub 仍红


def test_not_git_repo(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr("eval.run_repo.run_agent", _fake_agent())
    assert rr.run_repo(str(plain), Config()).status == "not_git_repo"


def test_dirty_tree_rejected(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path, BUG_CALC)
    (tmp_path / "demo" / "extra.txt").write_text("dirty", encoding="utf-8")  # 未提交改动
    monkeypatch.setattr("eval.run_repo.run_agent", _fake_agent())
    assert rr.run_repo(repo, Config()).status == "dirty_tree"


def test_not_repo_root(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path, BUG_CALC)
    sub = os.path.join(repo, "pkg")
    os.makedirs(sub)
    monkeypatch.setattr("eval.run_repo.run_agent", _fake_agent())
    assert rr.run_repo(sub, Config()).status == "not_repo_root"

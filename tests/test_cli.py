"""CLI wiring tests that never invoke a model."""

from agent.config import Config
import cli


def test_parser_exposes_engineering_and_evidence_commands():
    parser = cli.build_parser()
    assert parser.parse_args(["validate"]).command == "validate"
    assert parser.parse_args(["audit"]).command == "audit"
    run = parser.parse_args(["run", "/tmp/repo", "fix it", "--budget", "1.5"])
    assert run.repo_path == "/tmp/repo"
    assert run.task == "fix it"
    assert run.budget == 1.5


def test_audit_exit_code_and_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "audit_repository", lambda root: {
        "valid": True, "artifact_campaigns": 2, "real_cases": 3, "errors": [],
    })
    assert cli.cmd_audit(cli.build_parser().parse_args(["audit"])) == 0
    assert "2 experiment campaign(s), 3 real case(s)" in capsys.readouterr().out


def test_main_dispatches_audit(monkeypatch):
    monkeypatch.setattr(cli.Config, "from_env", lambda: Config())
    monkeypatch.setattr(cli.profile, "resolve_name", lambda: "tester")
    monkeypatch.setattr(cli, "cmd_audit", lambda args: 7)
    assert cli.main(["audit"]) == 7


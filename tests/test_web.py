"""Offline request-boundary and web-backend tests."""

from io import BytesIO

import pytest

import serve
import web_backend


def _request_reader(body: bytes, declared_length=None):
    handler = serve.Handler.__new__(serve.Handler)
    length = len(body) if declared_length is None else declared_length
    handler.headers = {"Content-Length": str(length)}
    handler.rfile = BytesIO(body)
    sent = []
    handler._send = lambda code, ctype, payload: sent.append((code, ctype, payload))
    return handler, sent


def test_read_json_accepts_only_an_object():
    handler, sent = _request_reader(b'{"message": "hi"}')
    assert handler._read_json() == {"message": "hi"}
    assert sent == []

    handler, sent = _request_reader(b"[]")
    assert handler._read_json() is None
    assert sent[0][0] == 400


def test_read_json_rejects_invalid_and_oversized_requests():
    handler, sent = _request_reader(b"not-json")
    assert handler._read_json() is None
    assert sent[0][0] == 400

    handler, sent = _request_reader(b"", serve.MAX_REQUEST_BYTES + 1)
    assert handler._read_json() is None
    assert sent[0][0] == 413
    assert b"request too large" in sent[0][2]


@pytest.mark.parametrize(
    ("message", "expected_repo", "has_task"),
    [
        ("fix /tmp/demo please", "/tmp/demo", True),
        ("/tmp/demo", "/tmp/demo", False),
        ("no path here", "", False),
    ],
)
def test_path_parsing(message, expected_repo, has_task):
    repo, task = web_backend.parse_message(message)
    assert repo == expected_repo
    assert (task is not None) is has_task


def test_run_fix_redacts_internal_exception(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("/Users/alice/private sk-ant-secret-value")

    monkeypatch.setattr(web_backend, "run_repo", fail)
    result = web_backend.run_fix("/tmp/repo", None)
    assert result["status"] == "error"
    assert "/Users/" not in result["message"]
    assert "sk-ant" not in result["message"]
    assert "RuntimeError" not in result["message"]


def test_static_routes_are_whitelisted():
    handler = serve.Handler.__new__(serve.Handler)
    files = []
    replies = []
    handler._send_file = lambda path: files.append(path)
    handler._send = lambda code, ctype, body: replies.append((code, body))

    handler.path = "/"
    handler.do_GET()
    assert files and files[0].endswith("web/index.html")

    handler.path = "/../README.md"
    handler.do_GET()
    assert replies[-1][0] == 404


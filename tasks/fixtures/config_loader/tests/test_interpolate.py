import pytest

from errors import ConfigError
from interpolate import interpolate


def test_expands_environment_variable():
    assert interpolate("postgres://${HOST}/db", {"HOST": "db.local"}) == "postgres://db.local/db"


def test_expands_multiple_variables():
    value = "${SCHEME}://${HOST}:${PORT}"
    assert interpolate(value, {"SCHEME": "http", "HOST": "x", "PORT": 8080}) == "http://x:8080"


def test_missing_variable_raises():
    with pytest.raises(ConfigError, match="MISSING"):
        interpolate("${MISSING}", {})


def test_default_is_used_when_missing():
    assert interpolate("${PORT:-8000}", {}) == "8000"


def test_environment_beats_default():
    assert interpolate("${PORT:-8000}", {"PORT": "9000"}) == "9000"


def test_recurses_through_lists_and_dicts():
    value = {"hosts": ["${PRIMARY}", {"url": "https://${SECONDARY}"}]}
    assert interpolate(value, {"PRIMARY": "a", "SECONDARY": "b"}) == {
        "hosts": ["a", {"url": "https://b"}]
    }


def test_non_string_values_are_preserved():
    assert interpolate({"count": 3, "enabled": True, "value": None}, {}) == {
        "count": 3, "enabled": True, "value": None
    }

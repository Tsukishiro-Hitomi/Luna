import pytest

from errors import ValidationError
from schema import get_path, validate


def test_get_path_reads_nested_value():
    assert get_path({"db": {"port": 5432}}, "db.port") == 5432


def test_missing_required_path_raises():
    with pytest.raises(ValidationError, match="db.host"):
        validate({"db": {}}, required=["db.host"])


def test_type_validation_accepts_expected_type():
    config = {"server": {"port": 8080}}
    assert validate(config, types={"server.port": int}) is config


def test_type_validation_rejects_wrong_type():
    with pytest.raises(ValidationError, match="server.port must be int"):
        validate({"server": {"port": "8080"}}, types={"server.port": int})


def test_multiple_requirements_are_checked():
    config = {"db": {"host": "x", "port": 5432}}
    assert validate(config, required=["db.host", "db.port"]) is config

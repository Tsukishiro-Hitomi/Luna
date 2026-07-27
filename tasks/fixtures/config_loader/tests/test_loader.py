import json

import pytest

from errors import ConfigError, IncludeCycleError
from loader import load_config


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_loads_single_file(tmp_path):
    path = tmp_path / "app.json"
    _write(path, {"port": 8080})
    assert load_config(path) == {"port": 8080}


def test_include_is_resolved_relative_to_parent(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write(config_dir / "base.json", {"host": "localhost"})
    _write(config_dir / "app.json", {"include": "base.json", "port": 8080})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_config(config_dir / "app.json") == {"host": "localhost", "port": 8080}


def test_child_values_override_included_values(tmp_path):
    _write(tmp_path / "base.json", {"db": {"host": "base", "port": 5432}})
    _write(tmp_path / "app.json", {"include": "base.json", "db": {"host": "child"}})
    assert load_config(tmp_path / "app.json")["db"] == {"host": "child", "port": 5432}


def test_later_include_overrides_earlier_include(tmp_path):
    _write(tmp_path / "first.json", {"value": 1, "left": True})
    _write(tmp_path / "second.json", {"value": 2, "right": True})
    _write(tmp_path / "app.json", {"include": ["first.json", "second.json"]})
    assert load_config(tmp_path / "app.json") == {"value": 2, "left": True, "right": True}


def test_nested_includes_work_across_directories(tmp_path):
    shared = tmp_path / "shared"
    env = tmp_path / "env"
    shared.mkdir()
    env.mkdir()
    _write(shared / "base.json", {"db": {"port": 5432}})
    _write(env / "dev.json", {"include": "../shared/base.json", "db": {"host": "dev"}})
    _write(tmp_path / "app.json", {"include": "env/dev.json", "debug": True})
    assert load_config(tmp_path / "app.json") == {
        "db": {"port": 5432, "host": "dev"}, "debug": True
    }


def test_interpolates_values_after_loading(tmp_path):
    _write(tmp_path / "app.json", {"database": {"url": "postgres://${HOST}/app"}})
    assert load_config(tmp_path / "app.json", {"HOST": "db"}) == {
        "database": {"url": "postgres://db/app"}
    }


def test_include_cycle_raises_useful_error(tmp_path):
    _write(tmp_path / "a.json", {"include": "b.json"})
    _write(tmp_path / "b.json", {"include": "a.json"})
    with pytest.raises(IncludeCycleError, match="include cycle"):
        load_config(tmp_path / "a.json")


def test_rejects_non_object_root(tmp_path):
    _write(tmp_path / "bad.json", [1, 2, 3])
    with pytest.raises(ConfigError, match="root must be an object"):
        load_config(tmp_path / "bad.json")


def test_rejects_invalid_include_type(tmp_path):
    _write(tmp_path / "bad.json", {"include": 42})
    with pytest.raises(ConfigError, match="include must be"):
        load_config(tmp_path / "bad.json")

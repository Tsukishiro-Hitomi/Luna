import pytest

from errors import ConfigError
from merge import deep_merge


def test_flat_override_wins():
    assert deep_merge({"port": 80}, {"port": 443}) == {"port": 443}


def test_nested_merge_preserves_sibling():
    base = {"db": {"host": "localhost", "port": 5432}}
    override = {"db": {"host": "db.internal"}}
    assert deep_merge(base, override) == {
        "db": {"host": "db.internal", "port": 5432}
    }


def test_new_nested_key_is_added():
    assert deep_merge({"db": {"host": "x"}}, {"db": {"pool": 5}}) == {
        "db": {"host": "x", "pool": 5}
    }


def test_lists_are_replaced():
    assert deep_merge({"plugins": ["a", "b"]}, {"plugins": ["c"]}) == {
        "plugins": ["c"]
    }


def test_does_not_mutate_inputs():
    base = {"db": {"host": "localhost"}, "plugins": ["a"]}
    override = {"db": {"port": 5432}, "plugins": ["b"]}
    deep_merge(base, override)
    assert base == {"db": {"host": "localhost"}, "plugins": ["a"]}
    assert override == {"db": {"port": 5432}, "plugins": ["b"]}


def test_result_does_not_alias_inputs():
    base = {"nested": {"items": [1]}}
    result = deep_merge(base, {})
    result["nested"]["items"].append(2)
    assert base == {"nested": {"items": [1]}}


def test_rejects_non_dict_inputs():
    with pytest.raises(ConfigError):
        deep_merge([], {})

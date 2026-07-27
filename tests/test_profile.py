"""agent.profile 的单测：名字优先读 profile.json、读不到再回落 git/$USER，profile 损坏也不崩，问候语保持纯文本。"""
from agent import profile


def test_greeting_plain_text():
    g = profile.greeting("Alice")
    assert isinstance(g, str) and "Alice" in g
    assert all(ord(c) < 0x1F000 for c in g)  # 无 emoji


def test_roundtrip_profile_first(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert profile.get_name() is None
    profile.set_name("Zhao")
    assert profile.get_name() == "Zhao"
    assert profile.resolve_name() == "Zhao"  # profile.json 优先于 git/$USER


def test_resolve_falls_back_nonempty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # 空目录、无 profile
    name = profile.resolve_name()
    assert isinstance(name, str) and name  # 回落 git global / $USER / "there"，非空不崩


def test_corrupt_profile_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    p = tmp_path / "luna" / "profile.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ not valid json", encoding="utf-8")
    assert profile.get_name() is None                 # 损坏 → None，不抛
    assert isinstance(profile.resolve_name(), str)

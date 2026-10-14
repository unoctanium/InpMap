"""Profile names and the configuration folder."""

from inpmap import profiles


def test_config_dir_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert profiles.config_dir() == tmp_path / "inpmap"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", "/home/u")
    assert str(profiles.config_dir()) == "/home/u/.config/inpmap"


def test_resolve(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert profiles.resolve(None) == str(tmp_path / "inpmap" / "default.inpmap")
    assert profiles.resolve("dcs") == str(tmp_path / "inpmap" / "dcs.inpmap")
    assert profiles.resolve("my.inpmap") == "my.inpmap"  # a file in the current directory
    assert profiles.resolve("config/local") == "config/local"  # contains '/': a path
    assert profiles.profile_name(None) == "default"
    assert profiles.profile_name("dcs") == "dcs"
    assert profiles.profile_name("/tmp/x.inpmap") is None

import pytest

from inpmap.backends.linux_service import UnitError, quote, render_unit

PY = "/home/u/InpMap/.venv/bin/python3"
DIR = "/home/u/.config/inpmap"


def test_unit_runs_the_profile_of_the_instance():
    text = render_unit(
        PY, DIR, [("dcs", "OK"), ("msfs", "invalid (1 problem(s); see inpmap check)")]
    )
    assert f'ExecStart="{PY}" -m inpmap run --wait-for-devices %i' in text
    assert "Description=InpMap input remapper, profile %i" in text
    assert "Type=exec" in text and "Restart=on-failure" in text
    assert "RestartPreventExitStatus=1 2" in text  # config/usage errors: no restart loop
    assert "WantedBy=default.target" in text
    assert "#   dcs                  OK" in text
    assert "systemctl --user enable --now inpmap@dcs.service" in text
    assert "systemctl --user stop 'inpmap@*' && systemctl --user start inpmap@dcs.service" in text
    assert "disable --now 'inpmap@*'" not in text  # disable does not accept globs
    assert "Conflicts=" not in text  # there is no single-configuration unit any more


def test_unit_without_profiles_suggests_default():
    text = render_unit(PY, DIR, [])
    assert "#   (none yet)" in text
    assert "systemctl --user enable --now inpmap@default.service" in text


def test_unit_sections_in_order():
    lines = render_unit(PY, DIR, []).splitlines()
    assert [line for line in lines if line.startswith("[")] == ["[Unit]", "[Service]", "[Install]"]
    for line in lines:
        assert not line or line.startswith(("#", "[")) or "=" in line


def test_quote_escapes_specifiers_and_quotes():
    assert quote("/a b/50%") == '"/a b/50%%"'
    assert quote('/my "conf".inpmap') == '"/my \\"conf\\".inpmap"'


@pytest.mark.parametrize("path", ["/a$HOME/x", "/a\nb"])
def test_quote_rejects_what_systemd_cannot_express(path):
    with pytest.raises(UnitError, match="cannot express"):
        quote(path)


def test_python_path_must_be_absolute_and_plain():
    with pytest.raises(UnitError, match="absolute"):
        render_unit("python3", DIR, [])
    with pytest.raises(UnitError, match="cannot express"):
        render_unit('/odd "dir"/python3', DIR, [])

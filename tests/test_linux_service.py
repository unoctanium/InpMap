import pytest

from inpmap.backends.linux_service import UnitError, quote, render_unit

PY = "/home/u/InpMap/.venv/bin/python3"
CONF = "/home/u/InpMap/config/local.inpmap"


def test_unit_runs_the_configuration_with_this_python():
    text = render_unit(PY, CONF, "config/local.inpmap")
    assert f'ExecStart="{PY}" -m inpmap run --wait-for-devices "{CONF}"' in text
    assert "Type=exec" in text
    assert "Restart=on-failure" in text
    assert "RestartPreventExitStatus=1 2" in text  # config/usage errors: no restart loop
    assert "WantedBy=default.target" in text
    assert "systemctl --user enable --now inpmap.service" in text
    assert "systemctl --user disable --now inpmap.service" in text


def test_unit_sections_in_order():
    lines = render_unit(PY, CONF, "c.inpmap").splitlines()
    sections = [line for line in lines if line.startswith("[")]
    assert sections == ["[Unit]", "[Service]", "[Install]"]
    # every non-comment line is a section header, a key=value setting or blank
    for line in lines:
        assert not line or line.startswith(("#", "[")) or "=" in line


def test_quote_escapes_specifiers_and_quotes():
    assert quote("/a b/50%") == '"/a b/50%%"'
    assert quote('/my "conf".inpmap') == '"/my \\"conf\\".inpmap"'


@pytest.mark.parametrize("path", ["/a$HOME/x", "/a\nb"])
def test_quote_rejects_what_systemd_cannot_express(path):
    with pytest.raises(UnitError, match="cannot express"):
        quote(path)


def test_command_path_rejects_quotes():
    with pytest.raises(UnitError, match="cannot express"):
        render_unit('/odd "dir"/python3', CONF, "c")


def test_relative_paths_are_rejected():
    with pytest.raises(UnitError, match="absolute"):
        render_unit(PY, "config/local.inpmap", "c")


def test_profiles_unit_runs_the_instance_file():
    from inpmap.backends.linux_service import render_profiles_unit

    text = render_profiles_unit(PY, "/home/u/50% conf/", "conf", [("dcs", "OK"), ("msfs", "OK")])
    assert f'ExecStart="{PY}" -m inpmap run --wait-for-devices "/home/u/50%% conf/%i.inpmap"' in (
        text
    )
    assert "Description=InpMap input remapper, profile %i" in text
    assert "Conflicts=inpmap.service" in text
    assert "After=inpmap.service" in text  # stopped before the profile starts
    assert "#   dcs                  OK" in text
    assert "systemctl --user enable --now inpmap@dcs.service" in text
    assert "systemctl --user stop 'inpmap@*' && systemctl --user start inpmap@dcs.service" in text
    assert "disable --now 'inpmap@*'" not in text  # disable does not accept globs


def test_profiles_unit_needs_an_absolute_directory():
    from inpmap.backends.linux_service import render_profiles_unit

    with pytest.raises(UnitError, match="absolute"):
        render_profiles_unit(PY, "config", "config", [])

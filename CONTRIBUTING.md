# Contributing to InpMap

Thanks for your interest. InpMap is young; reports from real systems help
most right now.

## Reporting a problem

Open an issue with the **Bug report** form. Please include `inpmap
--version`, how you installed InpMap, your distribution and desktop, the
smallest configuration that shows the problem, and the output of `inpmap -v
run PROFILE` (or `journalctl --user -u inpmap@PROFILE -e` for the service).
Remove anything private, such as user names and home paths, first.

Many problems have a known answer in the troubleshooting table of
[docs/usage.md](docs/usage.md#5-troubleshooting).

## Reporting that it works

Open an issue with the **Test report** form, also when everything worked.
InpMap is verified on CachyOS with KDE Plasma (Wayland) only; every other
distribution, desktop, keyboard, gamepad and game is new ground. The checks
are listed in [docs/manual-tests.md](docs/manual-tests.md); a few of them
are enough.

## Ideas and feature requests

Open an issue and describe what you want to achieve, not only the syntax
you have in mind. Planned work and ideas already collected are in
[docs/roadmap.md](docs/roadmap.md).

## Changing the code

[docs/development.md](docs/development.md) explains the setup, the tests
and the architecture. In short:

- Keep a change small and focused; open an issue first for anything large.
- Add or update tests. The unit tests need no devices or root:
  `.venv/bin/python -m pytest`.
- Run the linter and formatter: `.venv/bin/ruff check . && .venv/bin/ruff
  format --check .`
- Update the documentation when behaviour changes, and `CHANGELOG.md` for
  anything a user notices.
- The configuration language is specified in
  [docs/configuration.md](docs/configuration.md). A change to the language
  starts there and is agreed on in an issue before the grammar and the
  compiler follow.
- Safety comes first: no key may ever be left stuck, and no device may be
  grabbed unless the configuration asks for it.

Contributions are accepted under the project's [MIT license](LICENSE).

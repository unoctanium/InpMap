# Developing InpMap

For contributors. Users need only [installation.md](installation.md),
[usage.md](usage.md) and [configuration.md](configuration.md).

Governing documents: [roadmap.md](roadmap.md) (goals, requirements,
milestones), `CLAUDE.md` (engineering rules), `docs/STATUS.md` (current
state and next steps), [manual-tests.md](manual-tests.md) (tests on real
hardware). How to report problems and propose changes:
[CONTRIBUTING.md](../CONTRIBUTING.md); the issue forms are in
`.github/ISSUE_TEMPLATE/`.

[configuration.md](configuration.md) is both the user reference and the
specification of the configuration language: a language change is made
there first and agreed on before the grammar, compiler, editor syntax files
and examples follow.

## Setup

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev]'          # adds pytest and ruff
```

## Tests and linting

```sh
.venv/bin/python -m pytest                 # unit tests; no devices or root needed
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Tests marked `hardware` need access to `/dev/uinput` and `/dev/input` and
are excluded by default; run them with `.venv/bin/python -m pytest -m hardware`.
They use only synthetic devices they create themselves and grab every device
they emit on, so no event reaches the desktop and real hardware is not
touched.

`tests/test_docs.py` checks that every ```` ```inpmap ```` block in
`docs/configuration.md` and the README is valid and formatted (`inpmap
fmt`), and that the packaged example `src/inpmap/data/example.inpmap`
equals the complete example there; `tests/test_example.py` checks that the
example does what its comments say. The example of the JSON era,
`tests/data/json_era_example.inpmap`, is still checked against the
timelines recorded on real hardware in `tests/golden_example_traces.py`.
Use ```` ```text ```` for fragments that are not valid on their own.

## Architecture

```text
.inpmap file ─► dsl/parser ─► dsl/compiler ─► config (validate) ─► models
                                                                     │
physical device ─► backends/linux_input ─► runtime ─► engine ─► output ─► backends/linux ─► uinput
                   (grab, pass-through)     (loop)    (rules,   (devices)
                                              │        macros,
                                              └──────► routing: unmapped input
                                                       to the outputs
```

The core (everything outside `backends/`) does not import evdev; it works on
`InputEvent`/`KeyAction` models, so it can be unit-tested with the fakes in
`tests/fakes.py` and later get a Windows backend.

| Module | Responsibility |
|---|---|
| `dsl/inpmap.lark`, `dsl/parser.py` | grammar (lark, LALR) and parser; syntax errors with positions |
| `dsl/compiler.py` | language → configuration data (device inference, aliases, gestures → nested `if_tap`, non-blocking `hold`/`axis` + more statements → `parallel`); maps every validator message back to `FILE:LINE:COLUMN` |
| `config.py`, `config_macros.py` | validate configuration data, build the models |
| `models.py`, `macros.py`, `codes.py`, `_linux_codes.py` | models, macro step model, code names (generated) |
| `loading.py` | load a file by extension |
| `engine.py`, `modifiers.py`, `state.py`, `axes.py`, `macro_runtime.py` | mapping engine: rule choice incl. modifiers, reference counts, axis holder stacks, macro runs as generator fibers on a timer queue |
| `output.py`, `input.py` | backend interfaces; output manager |
| `routing.py` | where a device's unmapped input goes (`plan_route`, refusals) and the `Router` that sends it to the outputs as shared holders |
| `runtime.py` | startup order, event loop, reconnect, masking of modifiers, keyboard LEDs, guaranteed cleanup |
| `backends/linux.py` | virtual devices through uinput |
| `backends/linux_input.py` | physical devices: selection, grab, pass-through device, LEDs, `SYN_DROPPED` resync |
| `input_config.py` | `inpmap input-config`: grouping, selectors, text insertion, the interactive session |
| `backends/linux_setup.py` | sysfs device scan (no device access needed), udev rule generator |
| `backends/linux_service.py` | systemd user unit generator (`inpmap service-unit`) |
| `profiles.py` | configuration folder (`~/.config/inpmap/`) and profile names |
| `data/`, `data_files.py` | files shipped with the program: the example and the editor syntax files |
| `detect.py` | `inpmap detect`: events written as triggers |
| `dsl/formatter.py` | `inpmap fmt` |
| `trace.py` | `macro-trace` on a fake clock |
| `cli.py` | commands, exit codes |

Changing the configuration language: update `docs/configuration.md` first
and get it approved (CLAUDE.md §7), then the grammar, compiler, editor
syntax files in `src/inpmap/data/syntax/` and the examples.

## Continuous integration and releases

`.github/workflows/ci.yml` runs ruff and the unit tests for Python 3.11 to
3.14 on every push to `main` and on pull requests (the hardware tests need
`/dev/uinput` and only run locally).

A release:

1. Set the version in `src/inpmap/__init__.py` and describe the changes in
   `CHANGELOG.md`; commit.
2. Tag and push, e.g. `git tag v0.3.0 && git push origin main v0.3.0`.
3. `.github/workflows/release.yml` tests, checks that the tag matches the
   version, builds the sdist and wheel and publishes them to PyPI with
   trusted publishing (configured once on pypi.org for this repository,
   workflow `release.yml`, environment `pypi`; no token is stored).

## Packaging

`packaging/aur/` holds the Arch Linux (AUR) package: `PKGBUILD`,
`.SRCINFO` and the packaged user unit; its README describes the test build,
publishing and updates for a new version.

## Working with Claude Code

InpMap is developed with Claude Code. The rules are in `CLAUDE.md`; the
project state and the next steps are in `docs/STATUS.md`, so that any new
session can continue where the last one ended (`CLAUDE.md` §16). Start a
session in the repository root with `claude` and type `/session-start`
(saying "continue" works too). Claude then:

1. reads `docs/STATUS.md`, `docs/roadmap.md` and `CLAUDE.md`;
2. compares the status with `git status` and `git log`; if they disagree
   (uncommitted changes, a step left "in progress"), it treats the last
   session as interrupted, checks those changes, runs the tests and
   corrects the status file;
3. summarises where things stand, what was verified, what is next, and
   whether a decision or a manual test is waiting.

At the end of a session, `/handoff` brings the status file up to date,
runs the tests and commits finished, test-passing work. Claude commits
automatically at each finished step and never pushes on its own.

## Event code table

`src/inpmap/_linux_codes.py` is generated from the kernel header so the core
does not depend on evdev. A test cross-checks it against the installed
`evdev.ecodes`. Regenerate after kernel header updates:

```sh
.venv/bin/python tools/gen_codes.py
```

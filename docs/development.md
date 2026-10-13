# Developing InpMap

For contributors. Users need only [installation.md](installation.md),
[usage.md](usage.md) and [configuration.md](configuration.md).

Governing documents: `project_spec.md` (product specification and roadmap,
German), `CLAUDE.md` (engineering rules), `docs/STATUS.md` (current state
and next steps).

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
`docs/configuration.md` is valid, that `config/example.inpmap` equals the
complete example there, and that the example behaves like the recorded
reference timelines in `tests/golden_example_traces.py`. Use ```` ```text ````
for fragments that are not valid on their own.

## Architecture

```text
.inpmap file ─► dsl/parser ─► dsl/compiler ─► config (validate) ─► models
                                                                     │
physical device ─► backends/linux_input ─► runtime ─► engine ─► output ─► backends/linux ─► uinput
                   (grab, forward)          (loop)    (rules,   (devices,
                                                       macros)   ref counts)
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
| `runtime.py` | startup order, event loop, reconnect, masking of modifiers, guaranteed cleanup |
| `backends/linux.py` | virtual devices through uinput |
| `backends/linux_input.py` | physical devices: selection, grab, forwarding device, LEDs, `SYN_DROPPED` resync |
| `input_config.py` | `inpmap input-config`: grouping, selectors, text insertion, the interactive session |
| `backends/linux_setup.py` | sysfs device scan (no device access needed), udev rule generator |
| `backends/linux_service.py` | systemd user unit generator (`inpmap service-unit`) |
| `trace.py` | `macro-trace` on a fake clock |
| `cli.py` | commands, exit codes |

Changing the configuration language: update `docs/configuration.md` first
and get it approved (CLAUDE.md §7), then the grammar, compiler, editor files
in `editors/` and the examples.

## Event code table

`src/inpmap/_linux_codes.py` is generated from the kernel header so the core
does not depend on evdev. A test cross-checks it against the installed
`evdev.ecodes`. Regenerate after kernel header updates:

```sh
.venv/bin/python tools/gen_codes.py
```

## Design background

`docs/macros-research.md` records how Input Remapper's macros work and why
InpMap's macro design differs. Input Remapper (GPL-3.0) is a functional
reference only; no code is copied.

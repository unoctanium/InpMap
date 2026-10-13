# Writing configurations by hand: options (discussion)

Status: **for discussion**, nothing decided or implemented (2026-10-13).

## Problem

The JSON format is precise, validated and machine-friendly, but verbose to
write in a text editor:

- every output and step is a nested object (`{"tap": {"code": ..., "device": ...}}`);
- full Linux names are required (`KEY_LEFTCTRL`, `BTN_SOUTH`);
- JSON has no comments, and a trailing comma is a syntax error;
- the editor gives no help (no completion, no inline errors);
- you have to know a key's code name before you can write it.

Example today (F9 combo):

```json
{
  "id": "combo",
  "input": { "device": "physical-keyboard", "type": "key", "code": "KEY_F9" },
  "outputs": [
    { "macro": { "steps": [
      { "tap": { "code": "KEY_Q", "device": "keyboard" } },
      { "wait_ms": { "min": 40, "max": 60 } },
      { "tap": { "code": "BTN_EAST", "device": "gamepad" } }
    ] } }
  ]
}
```

## Guiding idea

Keep **one canonical model** (today's validated structure). Any easier
notation is only an alternative *spelling* that the loader expands into the
same model, so validation, the engine and future GUIs stay unchanged. Error
messages must still point to the text the user wrote.

## Options

### O1. Comments and trailing commas (JSONC)

Allow `// ...` comments and trailing commas, like VS Code's settings files.

- Benefit: the single biggest everyday improvement; configs can explain
  themselves (the `description` field is a workaround today).
- Cost: small. The standard library's `json` can't parse it; a small,
  string-aware comment/comma stripper (~50 lines + tests) or a dependency
  (`json5`) is needed.
- **Spec impact:** the spec says JSON is the only format. JSONC is a strict
  superset, but it needs an explicit decision. Proposal: file extension
  `.jsonc` or a top-level opt-in; plain `.json` stays strict JSON.

### O2. JSON Schema for editor support

Publish a JSON Schema generated from our model; configs reference it with
`"$schema": "..."`.

- Benefit: completion of keys, step names and code names; hover
  documentation; red underlines while typing. Works in VS Code, and in
  Kate / KWrite (KDE) and other editors via a JSON language server.
- Cost: medium (generator + test that schema and validator agree). Our own
  validator stays authoritative; the schema only helps while typing.
- Spec impact: none (needs `$schema` allowed as a top-level key).

### O3. Shorthand spellings inside JSON

Accept short forms next to the canonical ones:

| What | Canonical | Shorthand |
|---|---|---|
| key output | `{"device": "keyboard", "type": "key", "code": "KEY_Y"}` | `"keyboard:KEY_Y"` |
| input | `{"device": "kbd", "type": "key", "code": "KEY_F9"}` | `"kbd:KEY_F9"` |
| macro step | `{"tap": {"code": "KEY_Q", "device": "keyboard"}}` | `"tap keyboard:KEY_Q"` |
| chord | `{"tap": ["KEY_LEFTCTRL", "KEY_C"]}` | `"tap KEY_LEFTCTRL+KEY_C"` |
| wait | `{"wait_ms": {"min": 40, "max": 60}}` | `"wait 40..60"` |
| macro output | `{"macro": {"steps": [...]}}` | `"macro": [...]` directly on the mapping |
| mappings | array of objects with `id` | object keyed by id |

The F9 example would become:

```jsonc
"mappings": {
  // F9: q, short pause, gamepad B
  "combo": {
    "input": "kbd:KEY_F9",
    "macro": ["tap keyboard:KEY_Q", "wait 40..60", "tap gamepad:BTN_EAST"]
  }
}
```

- Benefit: roughly a third of the size; reads like a script, but is still
  JSON and still validated.
- Cost: medium. A small, strict grammar for step strings; the canonical form
  stays available for everything (complex steps keep the object form).
- Risk: two spellings for the same thing. Mitigation: a formatter (O6)
  converts in both directions.

### O4. Shorter key names

Allow names without the prefix where unambiguous: `"Q"`, `"LEFTCTRL"`,
`"F9"` for keyboards; for gamepads either `BTN_` names, direction names
(`south`/`east`/`north`/`west`) or optional Xbox-style labels (`A/B/X/Y`,
documented as a convention because PlayStation/Nintendo labels differ).
Common aliases like `ctrl`, `shift`, `alt`, `meta` (left variants).

- Benefit: less typing, fewer prefix mistakes.
- Cost: small; risk of ambiguity, so the alias table must be explicit and
  tested, and `inpmap check` should show the resolved Linux names.

### O5. A small text language for macros

Like Input Remapper: `"macro": "tap(keyboard:Q) wait(40..60) tap(gamepad:BTN_EAST)"`,
or one macro file per text block.

- Benefit: most compact for long scripts.
- Cost: highest (parser, error positions inside strings, escaping); we
  decided against it as the primary format (Q1). Only worth it if O3 turns
  out to be insufficient.

### O6. Tooling around the format

- `inpmap keys` (or `devices --watch`): press a key, see its code name, and
  which device it came from — removes the need to look up names.
- `inpmap fmt CONFIG [--compact | --expand]`: rewrites a config in a
  consistent layout, converting between shorthand and canonical form.
- `inpmap new`: generates a starting config from the connected devices.
- Better errors already exist; `macro-trace` already explains behaviour.

### O7. Splitting large configurations

Named macros defined once and referenced by several mappings (N10 from the
macro discussion), and possibly `include` of other files. Helps once
configurations grow; less important for the first steps.

### O8. Different file format (TOML / YAML)

TOML handles deep nesting poorly (macros are trees); YAML is indentation
sensitive and was explicitly excluded by the spec. Not recommended.

### O9. GUI (V3/V4)

Solves authoring for most users eventually, but is far away; the options
above also make the GUI simpler (it would write the canonical form).

## Proposal

| Priority | Options | Why |
|---|---|---|
| 1 | O1 comments + trailing commas, O6 `inpmap keys` | biggest relief for little effort |
| 2 | O2 JSON Schema | editor completion and inline errors |
| 3 | O3 shorthand + O4 short names + O6 `fmt` | shorter configs, still one model |
| later | O7 named macros / includes | when configs grow |
| not now | O5 text language, O8 TOML/YAML | cost or spec conflict |

## Questions

1. Which editor do you use for configs (Kate/KWrite, VS Code, vim, ...)?
   This decides how much O2 is worth.
2. Comments (O1): allow JSONC (needs a spec decision)?
3. Shorthand (O3): do the examples feel right? Which parts matter most?
4. Short names (O4): which gamepad naming — `BTN_SOUTH`, `south`, or `A`?
5. Anything missing, e.g. a different workflow you have in mind?

## Answers and findings (2026-10-13)

- **Editors:** Kate and nano.
- **Comments:** allowed — user approved the spec change.
- **Shorter is better.**
- **Gamepad names:** positional names (`BTN_SOUTH` …) stay canonical. Verified
  in `linux/input-event-codes.h`: `BTN_A = BTN_SOUTH`, `BTN_B = BTN_EAST`,
  but `BTN_X = BTN_NORTH` (top, labelled **Y** on Xbox) and
  `BTN_Y = BTN_WEST` (left, labelled **X** on Xbox). The kernel's
  `Documentation/input/gamepad.rst` defines buttons by physical position
  only. So `BTN_A`/`BTN_B` match Xbox labels, `BTN_X`/`BTN_Y` do not.
  Proposal: keep accepting the aliases, but `inpmap check` warns about
  `BTN_X`/`BTN_Y`.
- **Text language:** user is now open to it (spec change) and asks about
  **KDL**.

## KDL (proposal under discussion)

Facts checked 2026-10-13:

- KDL ("a small, pleasant document language", kdl.dev): nodes with
  arguments, `key=value` properties and `{ children }`; `//`, `/* */`
  comments and `/-` to comment out a whole node. Current spec **KDL 2.0.0,
  finalized**.
- Kate: KDE's syntax-highlighting framework ships `kdl.xml` (`*.kdl`).
  nano: no built-in KDL highlighting found; we could ship a `nanorc` file.
- Python parsers: `kdl-py` 1.2.0 (Jan 2024, pure Python, MIT) supports
  **KDL 1.0 only**; `ckdl` (C library with Python support, MIT, active,
  last push 2026-03) — KDL 2 support and wheel availability **not yet
  verified**; `cuddle` is v1 only.

Why KDL differs from the "text language" we rejected: the grammar is a
published standard with its own test suite; we would not design a parser
grammar, only map KDL nodes to our existing model. Error positions (line,
column) come for free. Trees (macros) are natural in KDL.

Draft of the example configuration in KDL:

```kdl
version 1
settings key-pause-ms=10
variables { presses 0 }

input physical-keyboard path="/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd"
output keyboard type=keyboard name="InpMap Virtual Keyboard"
output gamepad type=gamepad name="InpMap Virtual Gamepad"

// X types y and holds the gamepad's south button (A)
mapping x-to-y input=physical-keyboard:KEY_X {
    key keyboard:KEY_Y
    key gamepad:BTN_SOUTH
}

// F9: q, short pause, gamepad east button (B)
mapping combo input=physical-keyboard:KEY_F9 {
    macro {
        tap keyboard:KEY_Q
        wait 40 60
        tap gamepad:BTN_EAST
        add presses 1
    }
}

// F10: tap 1, double tap 2, long press 3
mapping tap-double-long input=physical-keyboard:KEY_F10 {
    macro device=keyboard {
        if-tap {
            then { if-tap { then { tap KEY_2 }; else { tap KEY_1 } } }
            else { tap KEY_3 }
        }
    }
}

mapping autofire input=physical-keyboard:KEY_F11 {
    macro device=gamepad on-release=cancel {
        while-held { tap BTN_SOUTH pause-ms=30 }
    }
}

mapping stick-up input=physical-keyboard:KEY_F12 {
    axis gamepad:ABS_Y -1.0 attack-ms=150 release-ms=50
}

// Caps Lock alone: Escape; with another key: Ctrl
mapping caps input=physical-keyboard:KEY_CAPSLOCK {
    macro device=keyboard {
        if-single {
            then { tap KEY_ESC }
            else { hold-keys KEY_LEFTCTRL }
        }
    }
}
```

Open decisions:

1. KDL as the hand-written format **instead of** JSON, or **next to** JSON
   (JSON for tools, a future GUI, interchange; `inpmap convert` both ways)?
2. Parser: verify `ckdl` (KDL 2, packaging on Arch/Debian/Fedora, wheels);
   otherwise write our own KDL 2 parser (no dependency, checked against the
   official KDL test suite), or use KDL 1 via `kdl-py`.
3. If JSON stays a user format: JSONC comments as well?
4. Naming style in KDL: kebab-case (`key-pause-ms`, KDL convention) vs.
   today's snake_case.

## Parser check (2026-10-13, second round)

- **kdl-py (github.com/tabatkins/kdlpy, = PyPI `kdl-py`)**: main branch is
  KDL 2.0.0 compliant since 2025-01-18 (commit "The upgrade to kdl v2 is
  done."), last commit 2025-02-19. **Not released**: `semver.txt` on main
  still says 1.2.0, the only tag is v1.2.0 ("Final planned KDL1 release …
  with major version 2, we'll be on KDL2"), highest PyPI version is 1.2.0
  (KDL 1). Pure Python, MIT. Syntax errors carry a location (via the
  input stream); nodes carry **no** source positions.
  Using it for KDL 2 means installing from a pinned git commit or vendoring
  it (MIT allows copying with the license notice).
- **ckdl 1.0** (PyPI, released 2024-12, wheels rebuilt 2025-11): KDL 2 and
  1, C backend, wheels for CPython 3.6–3.14 (Linux x86_64/aarch64/i686 incl.
  musl, Windows, macOS), sdist; API `ckdl.parse(text, version=...)` —
  default `version=1`, must pass 2. Documented `Node` attributes have **no**
  source positions; whether `ParseError` includes line/column is not
  documented (to test).
- Neither library gives node positions, so semantic errors are reported by
  path (`mapping 'combo' > macro > step 2 (tap)`), like JSON paths today.

## Replacing JSON completely by KDL (analysis)

Advantages:
- one format: one loader, one set of docs and examples, no conversion, no
  question "which format?", no naming bridge;
- comments everywhere, compact syntax; Kate highlights `*.kdl`;
- the validator keeps working unchanged: KDL is translated to the same
  internal data shape, and unit tests that build configs as Python dicts
  stay as they are.

Disadvantages:
- loading a configuration requires a third-party parser (today: stdlib
  `json` only) — installation gets a dependency (ckdl: compiled wheels;
  kdl-py: unreleased code, pinned or vendored);
- tooling is smaller than JSON's (no `jq`, JSON Schema editors, every
  language's stdlib); scripts or a future GUI must read/write KDL through a
  library; comments in hand-written files are lost when a tool rewrites
  them (same as JSON, which has no comments at all);
- less widely known than JSON;
- spec and CLAUDE.md say "JSON is the required format" → both must be
  updated (user has approved changing the spec);
- the existing JSON example/local configs need converting (small).

Cost of keeping JSON as a secondary format: very low, because the
internal data shape *is* JSON-shaped; only the file loader and a
`convert` command would remain.

## Round 3: custom DSL and Lua (2026-10-13)

User sketch of a custom DSL (excerpt): `settings { key_pause_ms = 10 }`,
`let presses = 0`, `map KEY_X { hold keyboard.KEY_Y; hold gamepad.BTN_SOUTH }`,
`wait random(40ms, 60ms)`, `presses += 1`,
`on tap { … } on double_tap { … } on long_press { … }`,
`while held { … } on release { cancel immediately }`,
`axis gamepad.ABS_Y { target = -1.0  attack = 150ms  release = 50ms }`.

Facts checked:
- LuaMacros (github.com/YAL-Tools/LuaMacros): Windows-only (Visual Studio
  C++/WinAPI) hotkey tool scripted in Lua; **archived 2024-03-26**;
  inspiration only.
- `lupa` 2.8 (MIT-style; changelog 2026-04-15): Python wrapper around Lua;
  binary wheels bundle Lua 5.1–5.5 and LuaJIT; cp314 wheels not verified.
- `lark` 1.3.1 (2025-10-27, MIT, pure Python, Python ≥3.8): parser library
  with grammar files and automatic line/column tracking.

Observations:
- Two separate decisions: **vocabulary/semantics** (gesture handlers
  on tap/double_tap/long_press, non-blocking `hold` in a mapping body,
  units like `40ms`, `+=` on variables, `random(a, b)`, default input
  device) vs. **syntax carrier** (JSON, KDL, own DSL, Lua). The semantic
  ideas improve any carrier.
- Custom DSL: most readable; with `lark` the parser cost is moderate and
  errors get line/column (better than both KDL libraries); needs its own
  Kate syntax file and nanorc, a formatter/printer for tools and a GUI,
  and a written grammar spec. Risk: growing into a programming language.
- Lua: maximum power, but config becomes code — conflicts with CLAUDE.md
  ("never execute arbitrary code from a configuration file"), static
  validation before grabbing devices, guaranteed release of owned
  outputs, and the planned GUI editors. Possible later as an optional,
  sandboxed `script` step that only calls our safe API (coroutines map
  onto the existing fiber executor).

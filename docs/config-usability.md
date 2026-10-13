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

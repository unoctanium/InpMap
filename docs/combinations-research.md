# Input Remapper: combination triggers (research summary)

Source: Input Remapper main @ 1f770e5c (GPL-3.0; behaviour only, no code
copied), read 2026-10-13: `injection/mapping_handlers/combination_handler.py`,
`hierarchy_handler.py`, `mapping_parser.py`, `key_handler.py`,
`macro_handler.py`, `event_reader.py`, `configs/input_config.py`,
`configs/mapping.py`, `readme/usage.md`, `readme/examples.md`, tests in
`tests/unit/test_event_pipeline/` and `test_mapping_handlers.py`.

- **Definition**: tuple of inputs matched by (type, code, origin device);
  order of pressing irrelevant (`_is_activated`: all keys pressed). Order
  only matters for duplicate detection and ranking. >6 keys: warning. One
  analog input max. Combinations across separate devices not supported
  (docs suggest variables in macros instead).
- **Before firing**: keys pressed before the combination is complete are
  forwarded unmodified (docs: "all the input keys you press before the
  combination is complete will be injected unmodified").
- **On firing**: with `release_combination_keys` (default **on**, GUI
  "Release Input"), releases of the already-forwarded keys are written to
  the forwarding device **before** the output (test
  `test_releases_then_triggers`: `(KEY_A,1),(KEY_A,0),(KEY_1,1)`). Their
  later physical releases are swallowed. Option off: output is modified by
  the held modifiers (docs: `Shift+1 -> a` gives `A`).
- **Release**: deactivates when any key of the combination is released;
  remaining held keys' releases are swallowed if already released
  synthetically. Modifiers are never re-pressed. Re-pressing the last key
  while others are held fires again.
- **Overlaps**: hierarchy handler per shared key; longer combinations
  ranked first; equal length: undefined ("¯\_(ツ)_/¯"). Lower-ranked
  mappings are suppressed only when the higher one fires on the same
  event; depending on press order a shorter and a longer combination can
  both be active (test `test_combination`).
- **Bookkeeping**: forwarded-key state is per handler; comments admit
  duplicate release events ("ignored by evdev anyway").
- **Autorepeat** (value 2) is dropped before any handler.
- **No left/right aliases**; GUI warns about combinations with
  Ctrl/Shift/Alt ("may not combine properly").

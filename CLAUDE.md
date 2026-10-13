# CLAUDE.md — Project Engineering Instructions

## 1. Authority and project context

This repository implements a configuration-driven, cross-platform input remapper.

Before making implementation changes, read `project_spec.md` in the repository root. It is the authoritative source for product goals, functional requirements, milestones, scope, and acceptance criteria.

If this file and `project_spec.md` appear to conflict:
1. Follow `project_spec.md` for product behavior and roadmap.
2. Follow this `CLAUDE.md` for engineering practices.
3. Point out any material conflict and ask only if it cannot be resolved safely from context.

Do not duplicate the full product specification here. Keep this file focused on how to work in the repository.

### Product direction

- V1: Linux, Python, configuration in the InpMap configuration language (`.inpmap`, originally JSON), physical keyboard and digital gamepad buttons, virtual keyboard/gamepad output, no GUI.
- V1.1: extend mapping and macro capabilities based on a careful study of Input Remapper's documentation and source.
- V2: Windows backend, no GUI.
- V3: Windows GUI.
- V4: Linux GUI.
- Later Linux operation as a background service/daemon managed by systemd.

Input Remapper by Sezanteb is a functional reference, not a mandate to copy its architecture or code wholesale:
https://github.com/sezanzeb/input-remapper

Review its actual documentation, source, tests, and license before relying on a particular behavior. Do not claim that a behavior or API exists unless verified. Respect its license if code is copied or adapted.

## 2. Start every task by inspecting the repository

At the beginning of a task:
0. At the start of every session, read `docs/STATUS.md` first and follow section 17.
1. Read `project_spec.md` and this `CLAUDE.md` if not already read in the current context.
2. Inspect the existing directory structure, relevant source files, tests, dependency declarations, and Git status.
3. Identify the smallest coherent change that satisfies the task.
4. Preserve existing working behavior unless the specification requires changing it.
5. If the repository already contains an implementation, extend it rather than replacing it wholesale without a compelling reason.

Do not assume a file, module, command, dependency, or API exists. Verify it.

Prefer using the repository's existing tooling and conventions when they are sound. Do not introduce a new framework or dependency just to avoid a small amount of straightforward code.

## 3. Engineering principles

Write code that is:

- Readable and unsurprising.
- Modular, with clear responsibilities and narrow interfaces.
- Explicit about state, side effects, device access, and errors.
- Easy to unit-test without physical hardware or root privileges.
- Documented where the reasoning is not obvious.
- Maintainable by another Python developer.
- Portable where practical, with operating-system-specific behavior isolated behind backend interfaces.
- Conservative about dependencies, privileges, and system changes.

Prefer straightforward code over clever abstractions. Avoid premature generalization, unnecessary design patterns, excessive indirection, and speculative features.

Do not build future GUI or Windows functionality prematurely. However, do not unnecessarily couple the core mapping engine to Linux-specific objects or APIs.

## 4. Python standards

- Target the Python version documented by the project. If not yet specified, inspect the available environment and choose a reasonable supported baseline before using newer syntax.
- Follow PEP 8 and standard Python naming conventions.
- Use type hints for public functions, core models, and nontrivial interfaces.
- Add docstrings to public modules, classes, and functions where they clarify contracts or behavior.
- Keep functions focused and reasonably short.
- Prefer explicit data models and validation over loosely structured dictionaries once data enters the core.
- Use standard-library modules when they are sufficient.
- Handle expected errors explicitly; do not silently swallow exceptions.
- Do not use broad `except Exception` unless there is a specific boundary where it is necessary to log, clean up, and re-raise or shut down safely.
- Do not use mutable default arguments.
- Avoid global mutable state. Pass dependencies and state explicitly.
- Avoid shelling out to external commands when a well-supported Python API is suitable; if a command is necessary, document and test the assumption.
- Do not add comments that merely repeat the code. Explain non-obvious reasoning, invariants, and safety constraints.

Use a consistent formatter/linter and test runner once chosen. Prefer a small toolchain; do not add multiple overlapping formatters or linters.

## 5. Architecture and module boundaries

Keep the core mapping logic independent of the operating-system backend.

A reasonable initial separation is:

- Configuration: parse, compile and validate `.inpmap` files.
- Models: typed internal representations of devices, inputs, rules, and actions.
- Input layer: normalize physical input events.
- Mapping engine: match normalized inputs to rules.
- State manager: track active inputs and outputs, overlapping mappings, and press/release lifetimes.
- Output manager: route normalized actions to named virtual devices.
- Linux backend: `evdev`, `uinput`, device discovery, grabbing, and Linux-specific cleanup.
- CLI/runtime: startup, shutdown, logging, configuration selection, and diagnostics.

Adapt the layout to the actual repository and keep it as small as possible. Do not create empty or ceremonial modules just to match a diagram.

The core engine should consume and produce internal event/action models, not require `evdev` event objects throughout the code. Backend interfaces should be small and explicit.

Keep runtime logic separate from CLI argument parsing so the same runtime can later be used in foreground mode, a systemd service, and eventually a GUI or other control interface.

## 6. Dependencies and portability

A major project goal is reliable installation on other PCs. Minimize dependencies and document every non-obvious one.

Before adding a dependency:
1. Check whether the Python standard library or an existing dependency can solve the problem cleanly.
2. Confirm that the dependency is maintained, compatible with the supported Python versions, and installable on the target platform.
3. Explain why it is needed and what functionality it provides.
4. Add it to the correct dependency group and document any platform restrictions.
5. Consider whether it complicates installation, native compilation, packaging, or future Windows support.

Use separate dependency groups when appropriate, for example:
- runtime dependencies;
- Linux-only runtime dependencies;
- development/test dependencies.

Do not make Linux-only packages mandatory dependencies for a future Windows installation unless the packaging system can correctly mark them as platform-specific.

Pin dependencies only when justified. For reproducible development or release builds, use an appropriate lock/constraints strategy if the project adopts one. Do not confuse a development lock file with the complete installation specification.

Avoid unnecessary dependencies on large frameworks. Do not add a GUI toolkit in V1.

### Installation requirements

The eventual installation process should be scriptable and documented for a clean machine. Design toward:
- a documented Python baseline;
- a virtual environment or an appropriate package installation mechanism;
- explicit system-level prerequisites;
- clear permission/device setup instructions;
- a repeatable installation and test procedure;
- clear uninstall/removal instructions when system files or service definitions are installed.

Do not assume every target machine is CachyOS. Keep distribution-specific instructions separate and identify which parts apply to Arch-based systems versus other Linux distributions.

Do not run destructive commands, modify system configuration, install packages globally, or change device permissions without explaining the effect and obtaining user confirmation when the action is consequential.

## 7. Configuration language

The InpMap configuration language (`.inpmap` files, specified in `docs/configuration.md`) is the only user-facing configuration format. It replaced JSON on 2026-10-13 by decision of the user. Do not introduce another format (JSON, YAML, TOML, Lua, …) unless the product specification is explicitly changed.

- Change the language only by first updating `docs/configuration.md` and getting the user's approval; keep the grammar (`src/inpmap/dsl/inpmap.lark`), the compiler, the editor syntax files (`editors/`) and the examples consistent with it.
- Validate the configuration at startup before creating or grabbing input devices.
- Reject unknown device references, unsupported event types, invalid codes, duplicate identifiers, and malformed rules with useful error messages.
- Report every problem as `FILE:LINE:COLUMN: message`, all problems of a file together, and name the mapping where it helps.
- Keep configuration parsing separate from execution: parser → compiler → validated data → internal models, once; avoid repeated ad hoc parsing throughout the runtime.
- Include a language version and a clear policy for future incompatible changes.
- Provide an example configuration (`config/example.inpmap`) that is valid against the current implementation and tested.
- Test both valid and invalid configurations.
- Never execute arbitrary code from a configuration file; the language stays declarative.

The parser uses `lark`. Justify any further parsing or validation dependency.

## 8. Input remapping correctness and safety

Input handling has important state and system-level consequences. Correctness is more important than adding features quickly.

### Press/release lifecycle

- Treat press and release as distinct events.
- Never leave a virtual key or button stuck after release, error, device removal, or shutdown.
- Track active outputs and release them during orderly cleanup.
- Handle key-repeat events explicitly; do not interpret repeat as a fresh press unless the defined semantics require it.
- Consider duplicate, missing, and out-of-order events.
- Handle overlapping mappings with reference counts or another clearly tested ownership model. One input releasing a shared output must not release it while another input still holds it.
- Avoid blocking the input event loop with long waits or macro execution. When macros are introduced, use a suitable scheduler/state machine or task model with deterministic cancellation and cleanup.

### Input grabbing and passthrough

`evdev` reading alone does not suppress an event from other applications. Verify the Linux mechanism used for input grabbing, including the implications of `EVIOCGRAB`.

- Do not grab devices until configuration validation and output-device initialization have succeeded where feasible.
- Be explicit about which physical devices are grabbed and why.
- Handle grab failures without leaving the application in a misleading partial state.
- Ensure grabs are released on normal exit and failure.
- Do not assume exclusive grabbing is harmless to KDE, desktop shortcuts, accessibility tools, other remappers, or applications.
- Define and test passthrough behavior. A grabbed device cannot simply be assumed to pass all unmapped events through.
- Never claim the original input is suppressed until an integration test verifies it.

### Virtual output devices

- Declare only capabilities the virtual device actually needs.
- Give virtual devices stable, descriptive names.
- Verify that Linux recognizes each virtual device and that the intended event codes are accepted.
- Keep keyboard and gamepad outputs separate when that makes the target application's device detection more reliable.
- Treat controller button labels such as A/B/X/Y as convention-dependent. Use Linux event codes such as `BTN_SOUTH` internally when appropriate and document the mapping.
- Release active events and destroy/close virtual devices cleanly.

### Privileges

- Avoid running the whole program as root by default.
- Document the actual access requirements for `/dev/input/event*` and `/dev/uinput`.
- Prefer narrowly scoped, understandable permission setup.
- Do not recommend blanket world-writable permissions for input devices.
- Separate privileged setup from normal runtime where practical.
- Explain security and usability trade-offs before changing permissions or system services.

## 9. Testing policy

Tests are part of each implementation task, not an optional follow-up.

Use `pytest` unless the repository already has a justified alternative.

### Unit tests

The core mapping and state logic should be testable without:
- physical devices;
- `/dev/uinput`;
- root privileges;
- a running desktop session.

Use small fakes or test doubles for input and output backends. Avoid elaborate mocking frameworks unless necessary.

Cover at least:
- configuration parsing and validation (including error positions);
- mapping match/no-match behavior;
- one input producing multiple outputs;
- press and release;
- repeated events;
- multiple inputs sharing one output;
- invalid device references and event codes;
- cleanup and cancellation paths;
- errors from output backends.

### Integration tests

Clearly distinguish unit tests from tests that require real Linux device access.

For hardware/device integration, test:
- virtual keyboard creation;
- virtual gamepad creation;
- event visibility through tools such as `evtest`;
- physical `X` producing virtual `KEY_Y` and the configured gamepad face button;
- release behavior;
- suppression of the original `X`;
- cleanup after normal shutdown and controlled failure.

Do not silently skip a required integration test and then report the feature as verified. State exactly what ran, what passed, what failed, and what still requires a manual test.

After each meaningful change:
1. Run the narrow relevant tests.
2. Run the full test suite when practical.
3. Report the actual commands and outcomes.
4. Fix regressions before moving on.

Do not modify tests merely to make incorrect implementation pass. If a requirement or test is wrong, explain why and update it deliberately.

## 10. Logging, errors, and diagnostics

- Use Python's `logging` module rather than scattered `print()` calls for runtime diagnostics.
- Use CLI output for concise user-facing results and errors.
- Include enough context to diagnose device discovery, configuration, grabbing, output initialization, and cleanup failures.
- Avoid logging sensitive or unnecessary raw input details by default.
- Use appropriate log levels.
- Return meaningful exit codes for command-line failures.
- Keep error messages actionable and understandable.
- Do not silently continue after a partial initialization failure that makes the remapper unsafe or misleading.

## 11. CLI and future daemon operation

V1 should first work reliably in the foreground. Foreground operation makes debugging and hardware testing easier.

Design for a future Linux daemon managed by `systemd`, but do not implement a full service before the basic end-to-end mapping is proven.

The eventual daemon should:
- run without an interactive terminal or GUI;
- use the same runtime and mapping engine as foreground mode;
- load a defined configuration file path;
- log to journald or a documented logging destination;
- handle termination signals and clean up active outputs, virtual devices, and input grabs;
- handle device hotplug and configuration errors predictably;
- use documented, minimal privileges;
- support service start/stop/restart and clear diagnostics;
- have a documented installation and removal path.

Do not daemonize by forking manually if systemd can manage the foreground process. Prefer a service unit that runs the application in the foreground and lets systemd supervise it.

Do not build a complex IPC protocol or live configuration reload before it is needed. Keep the runtime API clean enough that these can be added later.

## 12. Documentation and installation scripts

Keep the repository usable by a new developer and by someone installing it on another PC.

Maintain:
- `README.md`: project overview, motivation, supported scope, quick start, and links to the user documentation.
- User documentation for newcomers: `docs/installation.md` (setup, permissions, uninstall), `docs/usage.md` (workflow, every command and option, troubleshooting), `docs/configuration.md` (complete language reference); `docs/development.md` for contributors.
- `project_spec.md`: product specification and milestones.
- `CLAUDE.md`: these development instructions.
- example configuration(s) (`config/example.inpmap`) that are tested against the current implementation.
- installation scripts only when their behavior is clear, safe, and justified.

Any installation script must:
- be idempotent where practical;
- detect unsupported environments and fail with an actionable message;
- explain or clearly display system-level changes;
- avoid destructive actions;
- check command failures and stop when a required step fails;
- not assume paths or usernames;
- distinguish user-level setup from system-level setup;
- provide a corresponding uninstall or rollback procedure when it changes system state.

Document external system dependencies separately from Python dependencies. Do not imply that `pip install` alone is sufficient if device permissions, kernel interfaces, packages, or service setup are also required.

## 13. Code changes and Git hygiene

- Make small, focused changes.
- Avoid unrelated refactors during a feature task.
- Do not overwrite user changes.
- Check `git status` before potentially disruptive operations.
- Never discard changes, reset branches, rewrite history, or delete files without explicit authorization.
- Commit automatically at each completed, test-passing step (see section 17). Otherwise do not commit unless asked. Never push, amend published commits, or rewrite history without explicit authorization.
- Keep generated artifacts, caches, virtual environments, and local machine configuration out of version control using appropriate `.gitignore` entries.
- Update tests and documentation when behavior changes.
- Do not add generated files or large lockfiles without understanding the repository's chosen workflow.

## 14. Working with Input Remapper as a reference

When implementing macro or mapping features:
1. Locate the relevant documentation, implementation, and tests in the upstream repository.
2. Read the actual code paths and tests rather than relying on names or summaries.
3. Record the behavior we intend to reproduce in our own terms.
4. Identify differences required by our multi-output design.
5. Decide whether to implement the behavior independently or adapt code with license compliance.
6. Add tests for the chosen semantics before broadening the implementation.

Do not assume our configuration syntax must match Input Remapper's syntax. Our format should be coherent, versioned, documented, and suitable for multiple output devices and future backends.

## 15. Definition of done for a coding task

Unless the task explicitly asks only for analysis, a code change is complete only when:
- the requested behavior is implemented;
- relevant tests have been added or updated;
- the tests that can be run in the current environment have been run;
- any unrun integration/manual tests are clearly identified;
- dependencies and platform assumptions are documented;
- user-facing configuration and documentation remain consistent;
- cleanup and failure behavior have been considered;
- `docs/STATUS.md` reflects the new state (section 17).

Do not claim success beyond the evidence available.

## 16. First action in this repository

(Historical: the repository has been initialized. New sessions follow section 17.)

When beginning work on this project:
1. Read `project_spec.md`.
2. Inspect the repository and `git status`.
3. Inspect the Python version and relevant Linux device access without making system changes.
4. Report any environment constraints that materially affect implementation.
5. Start implementing the smallest useful slice: project metadata, JSON configuration model/validation, and unit tests.
6. Then implement and test virtual-device creation, followed by physical input handling and the end-to-end test defined in `project_spec.md`.

Do not respond with another high-level project plan only. Start with concrete repository inspection and implementation.

## 17. Session continuity and handoff (mandatory)

Any session may crash or be terminated at any time. A new session must be able to continue seamlessly from the repository alone, without the previous conversation. `docs/STATUS.md` is the handoff document and the single source of truth for project state.

### Starting a session

The user starts a session with `claude` in the repository root and runs `/session-start` (or simply asks to continue). Claude then, before doing anything else:
1. Reads `docs/STATUS.md`, then `project_spec.md` and this file if not already in context.
2. Runs `git status` and `git log --oneline -10` and compares them with `docs/STATUS.md`. Any difference (uncommitted changes, commits not mentioned, a step marked in progress) means the previous session ended unexpectedly. Inspect those changes, run the test suite, and fix `docs/STATUS.md` before continuing.
3. Reports to the user in a few lines: current position, what was last done, verification status, the next step, and any pending user decisions or manual tests. Then continues with the next step unless the user redirects.

### Keeping the handoff current

Update `docs/STATUS.md` on disk:
- when a step or sub-step is completed;
- when a design decision is made (record the reason);
- before asking the user to run a manual or hardware test (record exactly what was asked and what result is awaited);
- when receiving test results from the user (record the actual outcome);
- before any long or risky operation;
- at the end of a session (`/handoff`).

Keep it factual and concise: current position, next steps, decisions with reasons, environment facts, verification status (what ran, what passed, what was not run), uncommitted work, open questions, and a dated session log. Never record results that were not actually observed. Rewrite stale sections instead of only appending.

### Commits

Commit automatically (authorized by the user) whenever a step or meaningful sub-step is completed and the test suite and linter pass:
- update `docs/STATUS.md` in the same commit;
- use a descriptive message; commit only files belonging to the work, never secrets, caches, or local machine configuration;
- do not commit failing or half-finished work; list it under "Uncommitted work" in `docs/STATUS.md` instead;
- never push, amend, or rewrite history without explicit authorization.

### Memory

Do not rely on Claude's local auto-memory or on conversation history for project state. Anything a future session needs belongs in `docs/STATUS.md` or other repository docs.

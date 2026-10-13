"""Command-line interface.

Only argument parsing and user-facing output live here; loading, validation
and the runtime are separate so a systemd service can reuse them.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Sequence

from . import __version__, codes
from .config import ConfigError
from .input import InputError
from .loading import load
from .macros import AXIS_KINDS, AXIS_NAMES, AxisKind, Led
from .models import Config, OutputMode
from .output import OutputError, OutputManager
from .runtime import CleanupError, Runtime
from .trace import format_trace, trace

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_USAGE = 2  # also used by argparse itself
EXIT_DEVICE_ERROR = 3
EXIT_INTERRUPTED = 130

AXIS_NAMES_BY_NAME = {name: code for code, name in AXIS_NAMES.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inpmap", description="Configuration-driven input remapper."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate a configuration file")
    check.add_argument("config", help="path to the .inpmap configuration file")
    check.set_defaults(handler=_cmd_check)

    devices = commands.add_parser(
        "devices", help="list physical input devices (for choosing config selectors)"
    )
    devices.add_argument(
        "--all", action="store_true", help="also list devices without keys or buttons"
    )
    devices.set_defaults(handler=_cmd_devices)

    codes_cmd = commands.add_parser(
        "codes",
        help="list key, button and axis names (optionally only those containing FILTER)",
        description=(
            "List the names usable in configuration files: KEY_* and BTN_* codes (all "
            "usable as triggers) and the gamepad axes, with the output type that can "
            "send each one. FILTER selects names containing it (any case), e.g. 'kp' "
            "for the numpad."
        ),
    )
    codes_cmd.add_argument("filter", nargs="?", default="", help="part of a name, e.g. kp")
    codes_cmd.set_defaults(handler=_cmd_codes)

    input_config = commands.add_parser(
        "input-config",
        help="choose input devices interactively and add them to a configuration file",
        description=(
            "List the input devices grouped by physical device, let you pick them by "
            "number or by pressing a key on them, and add 'input' blocks to CONFIG "
            "(created if it does not exist). Nothing else in the file is changed."
        ),
    )
    input_config.add_argument("config", help="path to a new or existing .inpmap file")
    input_config.set_defaults(handler=_cmd_input_config)

    udev_rules = commands.add_parser(
        "udev-rules",
        help="print udev rules granting session access to /dev/uinput and the configured inputs",
        description=(
            "Print udev rules (systemd-logind 'uaccess') for /dev/uinput and the input "
            "devices of CONFIG, which must be connected. Nothing is installed; the output "
            "contains the install and removal commands."
        ),
    )
    udev_rules.add_argument("config", help="path to the .inpmap configuration file")
    udev_rules.set_defaults(handler=_cmd_udev_rules)

    trace_cmd = commands.add_parser(
        "macro-trace",
        help="simulate a mapping and print its output timeline (no devices)",
        description=(
            "Run one mapping (macros, taps, axis outputs) on a simulated clock and print "
            "every output event with its time. No devices are opened or created."
        ),
    )
    trace_cmd.add_argument("config", help="path to the .inpmap configuration file")
    trace_cmd.add_argument(
        "mapping",
        help="mapping name: its 'as' name or the trigger as written, e.g. KEY_F9",
    )
    trace_cmd.add_argument(
        "--hold-ms", type=float, default=100.0, help="how long each press lasts (default 100)"
    )
    trace_cmd.add_argument(
        "--press-at",
        type=float,
        action="append",
        metavar="MS",
        help="press the input at this time (repeatable; default 0)",
    )
    trace_cmd.add_argument(
        "--other-key-at",
        type=float,
        action="append",
        metavar="MS",
        help="press another key at this time (repeatable), e.g. for 'if single'",
    )
    trace_cmd.add_argument("--until-ms", type=float, help="simulate up to this time")
    trace_cmd.add_argument("--seed", type=int, default=0, help="seed for random durations")
    trace_cmd.add_argument(
        "--modifiers",
        metavar="NAMES",
        help="comma-separated modifiers held during the simulation, e.g. ctrl,right_shift, "
        "or 'none' (default: what the mapping requires)",
    )
    trace_cmd.add_argument(
        "--led",
        action="append",
        choices=[led.value for led in Led],
        help="treat this LED as lit on the input device (repeatable)",
    )
    trace_cmd.set_defaults(handler=_cmd_macro_trace)

    run = commands.add_parser(
        "run",
        help="run the remapper in the foreground",
        description=(
            "Create the virtual outputs, grab the configured input devices (after all "
            "their keys are released) and remap until Ctrl+C/SIGTERM or --timeout."
        ),
    )
    run.add_argument("config", help="path to the .inpmap configuration file")
    run.add_argument(
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="stop automatically after this many seconds (recommended for first tests)",
    )
    run.add_argument(
        "--wait-for-devices",
        action="store_true",
        help="if an input device cannot be opened at startup, wait for it instead of "
        "failing (used by the service)",
    )
    run.set_defaults(handler=_cmd_run)

    service_unit = commands.add_parser(
        "service-unit",
        help="print a systemd user unit that runs CONFIG at login",
        description=(
            "Print a systemd user unit (systemctl --user) that runs 'inpmap run' for "
            "CONFIG with this installation's Python. Nothing is installed; the output "
            "contains the install and removal commands."
        ),
    )
    service_unit.add_argument("config", help="path to the .inpmap configuration file")
    service_unit.set_defaults(handler=_cmd_service_unit)

    test_outputs = commands.add_parser(
        "test-outputs",
        help="create the virtual output devices and emit each mapped output once",
        description=(
            "Create the configured virtual devices, wait, then press and release every "
            "mapped output code. Physical devices are not touched. Keyboard output goes "
            "to the focused window like real typing; KEY_Y is a key position, so on a "
            "German layout it types 'z'."
        ),
    )
    test_outputs.add_argument("config", help="path to the .inpmap configuration file")
    test_outputs.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="seconds to wait after creating the devices (default: 3)",
    )
    test_outputs.add_argument(
        "--hold", type=float, default=0.2, help="seconds each output is held (default: 0.2)"
    )
    test_outputs.add_argument(
        "--only",
        action="append",
        metavar="DEVICE",
        help="emit only on this output device id (repeatable)",
    )
    test_outputs.add_argument(
        "--no-emit",
        action="store_true",
        help="only create the devices for --delay seconds; emit nothing",
    )
    test_outputs.set_defaults(handler=_cmd_test_outputs)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.handler(args)


def _cmd_devices(args: argparse.Namespace) -> int:
    try:
        from .backends.linux_input import list_input_devices
    except ImportError as exc:
        print(f"Linux backend unavailable: {exc}", file=sys.stderr)
        return EXIT_DEVICE_ERROR
    devices, unreadable = list_input_devices()
    shown = 0
    for info in devices:
        if not args.all and info.key_count == 0 and info.gamepad_buttons == 0:
            continue
        shown += 1
        own = "  [InpMap virtual device]" if info.own else ""
        print(f"{info.path}: '{info.name}'{own}")
        print(f"    keys: {info.key_count}, gamepad buttons: {info.gamepad_buttons}")
        for link in info.links:
            print(f"    {link}")
    if shown == 0:
        print("no matching readable input devices")
    if unreadable:
        print(
            f"\n{len(unreadable)} event node(s) not readable by this user "
            f"({', '.join(unreadable)}); see docs/installation.md, 'Device permissions'."
        )
    return EXIT_OK


def _cmd_macro_trace(args: argparse.Namespace) -> int:
    try:
        config = _load(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    try:
        lines = trace(
            config,
            args.mapping,
            hold_ms=args.hold_ms,
            press_at=args.press_at,
            other_key_at=args.other_key_at,
            until_ms=args.until_ms,
            seed=args.seed,
            leds=frozenset(Led(name) for name in args.led or []),
            modifiers=_modifier_list(args.modifiers),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(format_trace(lines))
    return EXIT_OK


def _modifier_list(text: str | None) -> list[str] | None:
    if text is None:
        return None
    if text == "none":
        return []
    return [name.strip() for name in text.split(",") if name.strip()]


def _cmd_codes(args: argparse.Namespace) -> int:
    wanted = args.filter.upper()
    rows = []
    for entry in codes.catalog():
        if not any(wanted in name for name in (entry.name, *entry.aliases)):
            continue
        sent_by = entry.sent_by or "- (only as input)"
        also = f"  (also {', '.join(entry.aliases)})" if entry.aliases else ""
        rows.append(f"{entry.name:<28} {entry.code:>4}  {sent_by}{also}")
    for name, code in AXIS_NAMES_BY_NAME.items():
        if wanted in name:
            kind = "stick" if AXIS_KINDS[code] is AxisKind.STICK else "trigger"
            rows.append(f"{name:<28} {code:>4}  gamepad axis ({kind})")
    if not rows:
        print(f"no name contains '{args.filter}'")
        return EXIT_OK
    print(f"{'NAME':<28} {'CODE':>4}  SENT BY")
    print("\n".join(rows))
    return EXIT_OK


IDENTIFY_TIMEOUT = 15.0


def _cmd_input_config(args: argparse.Namespace) -> int:
    from .backends.linux_setup import devices_for_input_config
    from .dsl.compiler import compile_text
    from .dsl.parser import DslSyntaxError
    from .input_config import ConfigFile, Device, Session, run_session

    if not args.config.endswith(".inpmap"):
        print("error: configuration files must end in .inpmap", file=sys.stderr)
        return EXIT_USAGE
    try:
        file = ConfigFile.load(args.config)
    except (DslSyntaxError, ValueError) as exc:
        print(
            f"{exc}\nFix the file first; input-config only adds to valid syntax.", file=sys.stderr
        )
        return EXIT_CONFIG_ERROR
    devices = devices_for_input_config()

    def identify(candidates: list[Device]) -> Device | None:
        try:
            from .backends.linux_input import wait_for_key_press
        except ImportError as exc:
            print(f"Linux backend unavailable: {exc}")
            return None
        try:
            path, failed = wait_for_key_press([d.path for d in candidates], IDENTIFY_TIMEOUT)
        except KeyboardInterrupt:
            path, failed = None, []
        finally:
            _discard_typed_input()
        if failed:
            print(
                f"({len(failed)} device(s) could not be read; see docs/installation.md, "
                "'Device permissions')"
            )
        return next((d for d in candidates if d.path == path), None)

    def check(text: str) -> list[str]:
        try:
            compile_text(text, args.config)
        except ConfigError as exc:
            return list(exc.problems)
        return []

    session = Session(file, devices, say=print, identify=identify, check=check)
    try:
        run_session(session, input)
    except KeyboardInterrupt:
        print("\nNo changes written.")
        return EXIT_INTERRUPTED
    return EXIT_OK


def _discard_typed_input() -> None:
    """Drop what the identifying key press typed into the terminal."""
    if not sys.stdin.isatty():
        return
    import termios

    termios.tcflush(sys.stdin, termios.TCIFLUSH)


def _cmd_udev_rules(args: argparse.Namespace) -> int:
    from .backends.linux_setup import read_sysfs_inputs, render_rules

    try:
        config = _load(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    try:
        print(render_rules(config, read_sysfs_inputs(), args.config), end="")
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_DEVICE_ERROR
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        config = _load(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if args.timeout is not None and args.timeout <= 0:
        print("--timeout must be positive", file=sys.stderr)
        return EXIT_USAGE
    try:
        from .backends.linux import LinuxOutputBackend
        from .backends.linux_input import LinuxInputBackend
    except ImportError as exc:
        print(f"Linux backend unavailable: {exc}", file=sys.stderr)
        return EXIT_DEVICE_ERROR

    stop = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        stop.set()

    # SIGHUP: closing the terminal window must also lead to an orderly stop.
    stop_signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = {sig: signal.signal(sig, request_stop) for sig in stop_signals}
    try:
        runtime = Runtime(
            config,
            LinuxInputBackend(),
            LinuxOutputBackend(),
            wait_for_inputs=args.wait_for_devices,
        )
        if args.timeout is not None:
            print(f"will stop automatically after {args.timeout:g}s", flush=True)
        reason = runtime.run(stop, timeout=args.timeout)
        print(f"stopped ({reason.value}); all devices released", flush=True)
        return EXIT_OK
    except (InputError, OutputError, CleanupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_DEVICE_ERROR
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _cmd_service_unit(args: argparse.Namespace) -> int:
    from .backends.linux_service import UnitError, render_unit

    try:
        _load(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    # Not resolved: a virtual environment's python is a symlink that must stay one.
    python = os.path.abspath(sys.executable)
    try:
        print(render_unit(python, os.path.abspath(args.config), args.config), end="")
    except UnitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        config = _load(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print(f"{args.config}: OK (version {config.version})")
    print(describe_config(config))
    return EXIT_OK


def _cmd_test_outputs(args: argparse.Namespace) -> int:
    try:
        config = _load(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    selected = args.only or list(config.outputs)
    unknown = [device_id for device_id in selected if device_id not in config.outputs]
    if unknown:
        known = ", ".join(config.outputs)
        print(f"unknown output device(s): {', '.join(unknown)} (known: {known})", file=sys.stderr)
        return EXIT_USAGE
    if args.delay < 0 or args.hold < 0:
        print("--delay and --hold must not be negative", file=sys.stderr)
        return EXIT_USAGE

    try:
        from .backends.linux import LinuxOutputBackend
    except ImportError as exc:
        print(f"Linux backend unavailable: {exc}", file=sys.stderr)
        return EXIT_DEVICE_ERROR

    # Turn SIGTERM into the same orderly shutdown path as Ctrl+C.
    previous = signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    try:
        with OutputManager(LinuxOutputBackend(), config) as outputs:
            for device_id, device in outputs.devices.items():
                node = getattr(device, "node", None) or "unknown node"
                print(f"created {device_id}: '{config.outputs[device_id].name}' at {node}")
            if args.no_emit:
                print(f"keeping devices for {args.delay:g}s (no events)", flush=True)
                time.sleep(args.delay)
            else:
                print(f"emitting in {args.delay:g}s", flush=True)
                time.sleep(args.delay)
                _pulse_outputs(outputs, config, selected, args.hold)
        print("devices removed")
        return EXIT_OK
    except OutputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_DEVICE_ERROR
    except KeyboardInterrupt:
        print("interrupted; outputs released and devices removed", file=sys.stderr)
        return EXIT_INTERRUPTED
    finally:
        signal.signal(signal.SIGTERM, previous)


def _pulse_outputs(
    outputs: OutputManager, config: Config, device_ids: Sequence[str], hold: float
) -> None:
    for device_id in device_ids:
        for code in sorted(config.output_codes(device_id)):
            name = codes.code_name(code)
            outputs.press(device_id, code)
            print(f"  {device_id}: {name} pressed", flush=True)
            time.sleep(hold)
            outputs.release(device_id, code)
            print(f"  {device_id}: {name} released", flush=True)
            time.sleep(hold)


def _raise_keyboard_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def _load(path: str) -> Config:
    """Load a configuration and print its warnings (to stderr)."""
    result = load(path)
    for warning in result.warnings:
        print(warning, file=sys.stderr)
    return result.config


def describe_config(config: Config) -> str:
    """Human-readable summary of a validated configuration."""
    lines = ["inputs:"]
    for spec in config.inputs.values():
        selector = f"name '{spec.name}'" if spec.name is not None else f"path {spec.path}"
        lines.append(f"  {spec.id}: {selector}")
    lines.append("outputs:")
    for out in config.outputs.values():
        lines.append(f"  {out.id}: {out.kind.value} '{out.name}'")
    lines.append("mappings:")
    for rule in config.mappings:
        targets = [
            f"{action.device} {codes.code_name(action.code)}"
            + (f" ({action.mode.value})" if action.mode is not OutputMode.HOLD else "")
            for action in rule.outputs
        ]
        targets += [f"{axis.device} {AXIS_NAMES[axis.code]} {axis.value:+g}" for axis in rule.axes]
        targets += [
            f"macro ({len(macro.steps)} step{'s' if len(macro.steps) != 1 else ''})"
            for macro in rule.macros
        ]
        if rule.disabled:
            targets = ["disabled"]
        device = rule.trigger.device or "every input"
        trigger = f"{device} {codes.code_name(rule.trigger.code)}"
        if rule.trigger.any_modifiers:
            trigger += " (any modifiers)"
        elif rule.trigger.modifiers:
            trigger += " with " + "+".join(sorted(r.name for r in rule.trigger.modifiers))
        lines.append(f"  {rule.id}: {trigger} -> {', '.join(targets)}")
    if config.variables:
        lines.append("variables:")
        lines += [f"  {name} = {value!r}" for name, value in config.variables.items()]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())

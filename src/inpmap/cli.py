"""Command-line interface.

Only argument parsing and user-facing output live here; loading, validation
and (later) the runtime are separate so a systemd service can reuse them.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__, codes
from .config import ConfigError, load_config
from .models import Config

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
# argparse itself exits with 2 on usage errors.


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inpmap", description="Configuration-driven input remapper."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate a configuration file")
    check.add_argument("config", help="path to the JSON configuration")
    check.set_defaults(handler=_cmd_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.handler(args)


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print(f"{args.config}: OK (version {config.version})")
    print(describe_config(config))
    return EXIT_OK


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
        targets = ", ".join(
            f"{action.device} {codes.code_name(action.code)}" for action in rule.outputs
        )
        trigger = f"{rule.trigger.device} {codes.code_name(rule.trigger.code)}"
        lines.append(f"  {rule.id}: {trigger} -> {targets}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())

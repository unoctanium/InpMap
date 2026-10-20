"""Test tool: an emulated DualSense Edge that presses its buttons in turn.

Creates the same device as an output with ``emulate = "dualsense-edge"``
(docs/configuration.md §3.5, ``inpmap.backends.linux_uhid``) without any
input device, and presses cross, the back paddles and the Fn buttons one
after another. For checking what a game or Steam receives, e.g. in WoW
(``PADPADDLE1``…``4``), without a physical controller.

Usage (needs write access to /dev/uhid; `inpmap udev-rules` grants it for a
profile that emulates a controller, otherwise use sudo):
    python3 tools/dualsense_edge_uhid.py              # press sequence, until Ctrl+C
    python3 tools/dualsense_edge_uhid.py --idle       # only create the device
    python3 tools/dualsense_edge_uhid.py --buttons rpaddle lpaddle --hold 2

The device is destroyed on exit.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

# Run from the source tree without installing (also under sudo).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inpmap.backends.linux_uhid import open_uhid  # noqa: E402
from inpmap.codes import CODES  # noqa: E402
from inpmap.models import EMULATE_DUALSENSE_EDGE, OutputDeviceSpec, OutputKind  # noqa: E402
from inpmap.output import OutputError  # noqa: E402

log = logging.getLogger("dualsense-edge-uhid")

# name -> (code, description); SDL paddle numbers as WoW shows them.
BUTTONS = {
    "cross": ("BTN_SOUTH", "cross (SDL A, WoW PAD1)"),
    "rpaddle": ("BTN_GRIPR", "right back paddle (SDL PADDLE1, WoW PADPADDLE1)"),
    "lpaddle": ("BTN_GRIPL", "left back paddle (SDL PADDLE2, WoW PADPADDLE2)"),
    "rfn": ("BTN_GRIPR2", "right Fn button (SDL PADDLE3, WoW PADPADDLE3)"),
    "lfn": ("BTN_GRIPL2", "left Fn button (SDL PADDLE4, WoW PADPADDLE4)"),
}
DEFAULT_SEQUENCE = ("cross", "rpaddle", "lpaddle", "rfn", "lfn")
SPEC = OutputDeviceSpec(
    id="uhid-test",
    kind=OutputKind.GAMEPAD,
    name="InpMap test DualSense Edge",
    emulate=EMULATE_DUALSENSE_EDGE,
)


def run(args: argparse.Namespace) -> None:
    device = open_uhid(SPEC)
    log.info("created '%s' (054c:0df2, uniq %s)", SPEC.name, device.uniq)
    pressed: str | None = None
    try:
        time.sleep(args.start_delay)
        if args.idle:
            log.info("idle, Ctrl+C to stop")
            while True:
                time.sleep(3600)
        rounds = 0
        while args.rounds == 0 or rounds < args.rounds:
            rounds += 1
            for name in args.buttons:
                code_name, description = BUTTONS[name]
                log.info("PRESS   %-8s %s", name, description)
                device.set_key(CODES[code_name], True)
                pressed = code_name
                time.sleep(args.hold)
                log.info("release %s", name)
                device.set_key(CODES[code_name], False)
                pressed = None
                time.sleep(args.gap)
    finally:
        if pressed is not None:
            device.set_key(CODES[pressed], False)  # never leave a button held
        device.close()
        log.info("device destroyed")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--idle", action="store_true", help="only create the device, press nothing")
    parser.add_argument(
        "--buttons",
        nargs="+",
        choices=BUTTONS,
        default=DEFAULT_SEQUENCE,
        help="buttons to press in turn (default: %(default)s)",
    )
    parser.add_argument(
        "--hold", type=float, default=1.0, help="seconds each button is held (default: %(default)s)"
    )
    parser.add_argument(
        "--gap", type=float, default=1.0, help="seconds between presses (default: %(default)s)"
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=5.0,
        help="seconds before the first press (default: %(default)s)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="number of rounds, 0 = until Ctrl+C (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    # SIGTERM takes the same cleanup path as Ctrl+C.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        run(args)
    except KeyboardInterrupt:
        pass
    except OutputError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Linux backend: a gamepad output that emulates a Sony DualSense Edge via /dev/uhid.

The one deliberate exception to "our virtual devices never impersonate real
hardware" (docs/configuration.md §3.5), opt-in with ``emulate =
"dualsense-edge"``. Why: Proton hands a uinput gamepad to Windows games
through Wine's SDL backend as an XInput controller, which has no paddles.
A uhid device gets a real ``/dev/hidraw*`` node; Proton passes Sony pads
through as raw HID by default, so the game's own PlayStation driver (SDL's
HIDAPI PS5 driver in many games) reads our reports directly.

Protocol facts this module relies on (checked 2026-10-20 against Linux
``drivers/hid/hid-playstation.c``, SDL2 ``src/joystick/hidapi/SDL_hidapi_ps5.c``
and ``SDL_gamecontroller.c``):

* Input report 0x01 over USB is 64 bytes including the ID; hid-playstation
  accepts it only on ``BUS_USB`` with exactly that size. No CRC on USB.
* The Edge's extra buttons are bits 4-7 of byte 10 (left Fn, right Fn, left
  paddle, right paddle); SDL exposes them as paddles only for PID 0x0DF2.
* On probe, hid-playstation reads feature reports 0x09 (20 bytes), 0x20 (64)
  and 0x05 (41) and fails unless each has exactly that length and starts with
  its ID. The MAC in 0x09 becomes ``uniq`` and must be unique among the
  connected DualSenses.
* SDL decides "USB, full reports" only if a 64-byte report arrives within
  16 ms of opening the device, so reports are streamed continuously (every
  4 ms, like the real controller), not only on changes.

The report descriptor and the feature replies are written here from those
facts (not copied from a device dump). The descriptor declares the same
report IDs and sizes as a DualSense, which is what hid-core and Windows'
HID stack check.

Threading: a uhid device must answer the kernel's GET_REPORT requests while
it is being probed and keep sending reports, independent of the input loop.
Each device therefore has one small thread that reads ``/dev/uhid`` and
sends a report every 4 ms; the event loop only changes the state under a
lock and sends an extra report right away so that presses are not delayed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import select
import struct
import threading
import time
from collections.abc import Callable, Sequence

from .. import codes
from ..macros import GAMEPAD_AXES, OUTPUT_AXIS_KINDS, AxisKind, Led
from ..models import OutputDeviceSpec, TouchPoint
from ..output import OutputError

log = logging.getLogger(__name__)

EMULATION = "dualsense-edge"

# -- uhid ABI (include/uapi/linux/uhid.h) -------------------------------------

UHID_DESTROY = 1
UHID_START = 2
UHID_STOP = 3
UHID_OPEN = 4
UHID_CLOSE = 5
UHID_OUTPUT = 6
UHID_GET_REPORT = 9
UHID_GET_REPORT_REPLY = 10
UHID_CREATE2 = 11
UHID_INPUT2 = 12
UHID_SET_REPORT = 13
UHID_SET_REPORT_REPLY = 14

UHID_FEATURE_REPORT = 0
UHID_INPUT_REPORT = 2

# sizeof(struct uhid_event): u32 type + the largest member (uhid_create2_req).
UHID_EVENT_SIZE = 4 + 128 + 64 + 64 + 2 + 2 + 4 * 4 + 4096
BUS_USB = 0x03
EIO = 5

# -- Identity ------------------------------------------------------------------

VENDOR = 0x054C  # Sony Interactive Entertainment
PRODUCT = 0x0DF2  # DualSense Edge Wireless Controller
VERSION = 0x0100
# No "/inputN" in phys: Wine would turn it into an "&MI_NN" interface suffix.
PHYS = "inpmap-uhid"
# Locally administered MAC prefix (bit 1 of the first byte set): never a
# real controller's. It also marks the evdev nodes hid-playstation creates
# for our device, whose phys is empty (see linux_input.is_own_device).
MAC_PREFIX = (0x02, 0x49, 0x4D)  # 02:"I":"M"
OWN_UNIQ_PREFIX = ":".join(f"{b:02x}" for b in MAC_PREFIX) + ":"


def mac_address(output_id: str) -> tuple[int, ...]:
    """A stable MAC for an output: the prefix plus 3 bytes of a hash of its id.

    Stable across restarts (Steam keeps settings per controller) and
    different for two emulated outputs (hid-playstation rejects duplicates).
    """
    digest = hashlib.sha256(output_id.encode("utf-8")).digest()
    return (*MAC_PREFIX, *digest[:3])


def uniq(mac: tuple[int, ...]) -> str:
    """The MAC as the kernel shows it in ``uniq`` (lowercase, colons)."""
    return ":".join(f"{b:02x}" for b in mac)


# -- Report descriptor -----------------------------------------------------------
#
# HID 1.11 short items. Report 0x01: six 8-bit axes (left X/Y, right X/Y,
# L2/R2), a vendor byte (counter), a 4-bit hat, 15 buttons, 13 vendor bits
# (PS, touchpad, mute, Edge Fn and paddles live here), 52 vendor bytes:
# 63 data bytes. Output 0x02: 47 bytes. Features 0x05, 0x09, 0x20.

REPORT_DESCRIPTOR = bytes(
    [
        0x05, 0x01,        # Usage Page (Generic Desktop)
        0x09, 0x05,        # Usage (Game Pad)
        0xA1, 0x01,        # Collection (Application)
        0x85, 0x01,        #   Report ID (1)
        0x09, 0x30,        #   Usage (X)        left stick X
        0x09, 0x31,        #   Usage (Y)        left stick Y
        0x09, 0x32,        #   Usage (Z)        right stick X
        0x09, 0x35,        #   Usage (Rz)       right stick Y
        0x09, 0x33,        #   Usage (Rx)       L2
        0x09, 0x34,        #   Usage (Ry)       R2
        0x15, 0x00,        #   Logical Minimum (0)
        0x26, 0xFF, 0x00,  #   Logical Maximum (255)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x06,        #   Report Count (6)
        0x81, 0x02,        #   Input (Data, Variable, Absolute)
        0x06, 0x00, 0xFF,  #   Usage Page (Vendor Defined 0xFF00)
        0x09, 0x20,        #   Usage (0x20)     counter
        0x95, 0x01,        #   Report Count (1)
        0x81, 0x02,        #   Input (Data, Variable, Absolute)
        0x05, 0x01,        #   Usage Page (Generic Desktop)
        0x09, 0x39,        #   Usage (Hat Switch)
        0x15, 0x00,        #   Logical Minimum (0)
        0x25, 0x07,        #   Logical Maximum (7)
        0x35, 0x00,        #   Physical Minimum (0)
        0x46, 0x3B, 0x01,  #   Physical Maximum (315)
        0x65, 0x14,        #   Unit (Degrees)
        0x75, 0x04,        #   Report Size (4)
        0x95, 0x01,        #   Report Count (1)
        0x81, 0x42,        #   Input (Data, Variable, Absolute, Null State)
        0x65, 0x00,        #   Unit (None)
        0x05, 0x09,        #   Usage Page (Button)
        0x19, 0x01,        #   Usage Minimum (1)
        0x29, 0x0F,        #   Usage Maximum (15)
        0x15, 0x00,        #   Logical Minimum (0)
        0x25, 0x01,        #   Logical Maximum (1)
        0x75, 0x01,        #   Report Size (1)
        0x95, 0x0F,        #   Report Count (15)
        0x81, 0x02,        #   Input (Data, Variable, Absolute)
        0x06, 0x00, 0xFF,  #   Usage Page (Vendor Defined 0xFF00)
        0x09, 0x21,        #   Usage (0x21)     PS, touchpad, mute, Edge buttons
        0x95, 0x0D,        #   Report Count (13)
        0x81, 0x02,        #   Input (Data, Variable, Absolute)
        0x09, 0x22,        #   Usage (0x22)     sensors, touch, status
        0x26, 0xFF, 0x00,  #   Logical Maximum (255)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x34,        #   Report Count (52)
        0x81, 0x02,        #   Input (Data, Variable, Absolute)
        0x85, 0x02,        #   Report ID (2)    effects (rumble, lights)
        0x09, 0x23,        #   Usage (0x23)
        0x95, 0x2F,        #   Report Count (47)
        0x91, 0x02,        #   Output (Data, Variable, Absolute)
        0x85, 0x05,        #   Report ID (5)    IMU calibration
        0x09, 0x24,        #   Usage (0x24)
        0x95, 0x28,        #   Report Count (40)
        0xB1, 0x02,        #   Feature (Data, Variable, Absolute)
        0x85, 0x09,        #   Report ID (9)    pairing info (MAC)
        0x09, 0x25,        #   Usage (0x25)
        0x95, 0x13,        #   Report Count (19)
        0xB1, 0x02,        #   Feature (Data, Variable, Absolute)
        0x85, 0x20,        #   Report ID (0x20) firmware info
        0x09, 0x26,        #   Usage (0x26)
        0x95, 0x3F,        #   Report Count (63)
        0xB1, 0x02,        #   Feature (Data, Variable, Absolute)
        0xC0,              # End Collection
    ]
)  # fmt: skip

# -- Feature reports ---------------------------------------------------------------


def calibration_report() -> bytes:
    """Feature 0x05 (41 bytes): symmetric IMU calibration, no bias.

    hid-playstation divides by (plus - minus) ranges; any non-zero ranges are
    valid. The motion sensors stay at rest, so the values only need to be sane.
    """
    gyro = (0, 0, 0) + (8800, -8800) * 3  # pitch/yaw/roll bias, then plus/minus each
    speed = (540, 540)
    accel = (8192, -8192) * 3  # x, y, z: +1 g, -1 g
    data = struct.pack("<17h", *gyro, *speed, *accel)
    return bytes([0x05]) + data + bytes(41 - 1 - len(data))


def pairing_report(mac: tuple[int, ...]) -> bytes:
    """Feature 0x09 (20 bytes): the MAC, least significant byte first."""
    return bytes([0x09, *reversed(mac)]) + bytes(13)


def firmware_report() -> bytes:
    """Feature 0x20 (64 bytes): build date, hardware/firmware versions.

    hid-playstation reads the hardware version (le32 at 24), firmware version
    (le32 at 28) and update version (le16 at 44); SDL reads the update version
    only to choose a rumble mode. The values are InpMap's own.
    """
    report = bytearray(64)
    report[0] = 0x20
    report[1:20] = b"InpMap emulation   "  # date and time fields (19 bytes)
    struct.pack_into("<I", report, 24, 0x00000001)  # hardware version
    struct.pack_into("<I", report, 28, 0x00010000)  # firmware version
    struct.pack_into("<H", report, 44, 0x0300)  # update version
    return bytes(report)


# -- Input report ------------------------------------------------------------------

INPUT_REPORT_SIZE = 64
REPORT_INTERVAL = 0.004
START_TIMEOUT = 5.0
HAT_NEUTRAL = 8

# EV_KEY code -> (byte, bit) in report 0x01 (hid-playstation DS_BUTTONS*).
BUTTON_BITS: dict[int, tuple[int, int]] = {
    # 0x133 is the left button for Xbox pads, SDL and Steam (BTN_FACE_LEFT), although
    # the kernel also calls it BTN_FACE_LEFT (configuration.md §3.3).
    codes.CODES["BTN_FACE_LEFT"]: (8, 0x10),  # Square
    codes.CODES["BTN_FACE_DOWN"]: (8, 0x20),  # Cross
    codes.CODES["BTN_FACE_RIGHT"]: (8, 0x40),  # Circle
    codes.CODES["BTN_FACE_UP"]: (8, 0x80),  # Triangle
    codes.CODES["BTN_TL"]: (9, 0x01),  # L1
    codes.CODES["BTN_TR"]: (9, 0x02),  # R1
    codes.CODES["BTN_SELECT"]: (9, 0x10),  # Create
    codes.CODES["BTN_START"]: (9, 0x20),  # Options
    codes.CODES["BTN_THUMBL"]: (9, 0x40),  # L3
    codes.CODES["BTN_THUMBR"]: (9, 0x80),  # R3
    codes.CODES["BTN_MODE"]: (10, 0x01),  # PS
    # The paddle codes follow the positions Steam shows for the Edge
    # (configuration.md §3.5): upper row = Fn buttons, lower row = back
    # paddles. SDL numbers them from the back, right first.
    codes.CODES["BTN_GRIPL"]: (10, 0x10),  # left Fn = SDL paddle 4
    codes.CODES["BTN_GRIPR"]: (10, 0x20),  # right Fn = SDL paddle 3
    codes.CODES["BTN_GRIPL2"]: (10, 0x40),  # left paddle = SDL paddle 2
    codes.CODES["BTN_GRIPR2"]: (10, 0x80),  # right paddle = SDL paddle 1
}
_TOUCHPAD_CLICK_BIT = (10, 0x02)
_TL2 = codes.CODES["BTN_TL2"]
_TR2 = codes.CODES["BTN_TR2"]
_L2_BIT = (9, 0x04)
_R2_BIT = (9, 0x08)
_UP = codes.CODES["BTN_DPAD_UP"]
_DOWN = codes.CODES["BTN_DPAD_DOWN"]
_LEFT = codes.CODES["BTN_DPAD_LEFT"]
_RIGHT = codes.CODES["BTN_DPAD_RIGHT"]
DPAD_BUTTONS = frozenset({_UP, _DOWN, _LEFT, _RIGHT})

# What the output carries (configuration.md §3.5); the touchpad click only
# comes from a routed touchpad.
BUTTONS: frozenset[int] = frozenset(BUTTON_BITS) | {_TL2, _TR2} | DPAD_BUTTONS

# Touch points: 4 bytes each at 33 and 37 (hid-playstation struct
# dualsense_touch_point): bit 7 of the first byte set = no finger, bits 0-6
# the contact number; then 12-bit x and 12-bit y, little-endian, packed.
TOUCH_POINTS = 2
TOUCH_OFFSETS = (33, 37)
TOUCH_INACTIVE = 0x80
TOUCHPAD_WIDTH = 1920
TOUCHPAD_HEIGHT = 1080

# Axis code -> byte in report 0x01.
AXIS_BYTES = {
    GAMEPAD_AXES[name][0]: offset
    for name, offset in (
        ("ABS_X", 1),
        ("ABS_Y", 2),
        ("ABS_RX", 3),
        ("ABS_RY", 4),
        ("ABS_Z", 5),
        ("ABS_RZ", 6),
    )
}

# (vertical, horizontal) with -1 = up/left -> DualSense hat value.
_HAT = {
    (-1, 0): 0,
    (-1, 1): 1,
    (0, 1): 2,
    (1, 1): 3,
    (1, 0): 4,
    (1, -1): 5,
    (0, -1): 6,
    (-1, -1): 7,
    (0, 0): HAT_NEUTRAL,
}


def hat_value(held: set[int] | frozenset[int]) -> int:
    """The hat value for the held D-pad buttons; opposite directions cancel."""
    vertical = (_DOWN in held) - (_UP in held)
    horizontal = (_RIGHT in held) - (_LEFT in held)
    return _HAT[(vertical, horizontal)]


def touch_bytes(point: TouchPoint | None) -> bytes:
    """The 4 report bytes of one touch point (x, y fractions -> 1920 x 1080)."""
    if point is None:
        return bytes([TOUCH_INACTIVE, 0, 0, 0])
    x = max(0, min(TOUCHPAD_WIDTH - 1, int(point.x * (TOUCHPAD_WIDTH - 1) + 0.5)))
    y = max(0, min(TOUCHPAD_HEIGHT - 1, int(point.y * (TOUCHPAD_HEIGHT - 1) + 0.5)))
    return bytes([point.id & 0x7F, x & 0xFF, (x >> 8) | ((y & 0x0F) << 4), y >> 4])


def stick_byte(value: float) -> int:
    """-1.0 … 1.0 -> 0 … 255 with rest (0.0) at 128."""
    return max(0, min(255, int((value + 1.0) * 127.5 + 0.5)))


def trigger_byte(value: float) -> int:
    """0.0 … 1.0 -> 0 … 255."""
    return max(0, min(255, int(value * 255 + 0.5)))


class PadState:
    """Buttons and axes of the emulated controller; builds input reports."""

    def __init__(self) -> None:
        self.held: set[int] = set()
        self.axes: dict[int, float] = {}
        self.touch: tuple[TouchPoint | None, ...] = ()
        self._counter = 0
        self._timestamp = 0

    def report(self) -> bytes:
        """The next input report 0x01; advances the counter and timestamp."""
        report = bytearray(INPUT_REPORT_SIZE)
        report[0] = 0x01
        for code, offset in AXIS_BYTES.items():
            value = self.axes.get(code, 0.0)
            kind = OUTPUT_AXIS_KINDS[code]
            report[offset] = trigger_byte(value) if kind is AxisKind.TRIGGER else stick_byte(value)
        # A trigger button presses its trigger fully (§3.5 rule 2).
        for button, offset in ((_TL2, 5), (_TR2, 6)):
            if button in self.held:
                report[offset] = 255
        report[7] = self._counter & 0xFF
        report[8] = hat_value(self.held)
        for code in self.held:
            if code in BUTTON_BITS:
                byte, bit = BUTTON_BITS[code]
                report[byte] |= bit
        if codes.TOUCHPAD_CLICK in self.held:
            report[_TOUCHPAD_CLICK_BIT[0]] |= _TOUCHPAD_CLICK_BIT[1]
        if report[5]:
            report[_L2_BIT[0]] |= _L2_BIT[1]
        if report[6]:
            report[_R2_BIT[0]] |= _R2_BIT[1]
        struct.pack_into("<I", report, 28, self._timestamp & 0xFFFFFFFF)
        for index, offset in enumerate(TOUCH_OFFSETS):
            point = self.touch[index] if index < len(self.touch) else None
            report[offset : offset + 4] = touch_bytes(point)
        report[53] = 0x0A  # battery full, discharging
        self._counter += 1
        self._timestamp += 12000  # 4 ms in the controller's ~0.33 µs units
        return bytes(report)


# -- uhid events -------------------------------------------------------------------


def create2_event(name: str, mac: tuple[int, ...]) -> bytes:
    header = struct.pack(
        "<I128s64s64sHHIIII",
        UHID_CREATE2,
        name.encode("utf-8"),
        PHYS.encode(),
        uniq(mac).encode(),
        len(REPORT_DESCRIPTOR),
        BUS_USB,
        VENDOR,
        PRODUCT,
        VERSION,
        0,
    )
    return header + REPORT_DESCRIPTOR


def input2_event(report: bytes) -> bytes:
    return struct.pack("<IH", UHID_INPUT2, len(report)) + report


def get_report_reply(request_id: int, err: int, data: bytes) -> bytes:
    return struct.pack("<IIHH", UHID_GET_REPORT_REPLY, request_id, err, len(data)) + data


def set_report_reply(request_id: int, err: int) -> bytes:
    return struct.pack("<IIH", UHID_SET_REPORT_REPLY, request_id, err)


DESTROY_EVENT = struct.pack("<I", UHID_DESTROY)


# -- The device --------------------------------------------------------------------


class UhidDualSenseEdge:
    """An emulated DualSense Edge. Implements :class:`inpmap.output.OutputDevice`.

    ``fd`` is an open ``/dev/uhid`` descriptor (tests pass one end of a
    socket pair); the device takes ownership and closes it.
    """

    def __init__(
        self,
        spec: OutputDeviceSpec,
        fd: int,
        start_timeout: float = START_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.spec = spec
        self._fd = fd
        self._clock = clock
        self._mac = mac_address(spec.id)
        self._features = {
            0x05: calibration_report(),
            0x09: pairing_report(self._mac),
            0x20: firmware_report(),
        }
        self._state = PadState()
        self._lock = threading.Lock()  # state and writes to fd
        self._started = threading.Event()
        self._stop = threading.Event()
        self._running = False  # between UHID_START and UHID_STOP
        self._failure: OSError | None = None
        try:
            os.write(fd, create2_event(spec.name, self._mac))
        except OSError as exc:
            os.close(fd)
            raise OutputError(f"cannot create emulated controller '{spec.name}': {exc}") from exc
        self._thread = threading.Thread(target=self._serve, name=f"uhid {spec.id}", daemon=True)
        self._thread.start()
        if not self._started.wait(start_timeout):
            self._shutdown()
            raise OutputError(
                f"cannot create emulated controller '{spec.name}': "
                f"the kernel did not start it within {start_timeout:g} s"
            )
        log.debug("uhid device '%s' started (uniq %s)", spec.name, uniq(self._mac))

    @property
    def uniq(self) -> str:
        return uniq(self._mac)

    # OutputDevice

    def set_key(self, code: int, pressed: bool) -> None:
        if code not in BUTTONS and code != codes.TOUCHPAD_CLICK:
            raise OutputError(f"'{self.spec.name}' has no button {codes.code_name(code)}")
        with self._lock:
            if pressed:
                self._state.held.add(code)
            else:
                self._state.held.discard(code)
            self._send_locked()

    def set_axis(self, code: int, value: float) -> None:
        if code not in AXIS_BYTES:
            raise OutputError(f"'{self.spec.name}' has no axis {code:#x}")
        with self._lock:
            self._state.axes[code] = value
            self._send_locked()

    def set_touch(self, points: Sequence[TouchPoint | None]) -> None:
        if len(points) > TOUCH_POINTS:
            raise OutputError(f"'{self.spec.name}' reports at most {TOUCH_POINTS} fingers")
        with self._lock:
            self._state.touch = tuple(points)
            self._send_locked()

    def fileno(self) -> int | None:
        return None

    def poll_leds(self) -> frozenset[Led] | None:
        return None

    def close(self) -> None:
        errors = self._shutdown()
        if errors:
            raise OutputError(f"closing '{self.spec.name}' failed: {'; '.join(errors)}")

    # internals

    def _send_locked(self) -> None:
        """Send the current state now (caller holds the lock)."""
        if self._failure is not None:
            raise OutputError(f"writing to '{self.spec.name}' failed: {self._failure}")
        if not self._running:
            return  # the kernel rejects input before UHID_START
        try:
            os.write(self._fd, input2_event(self._state.report()))
        except OSError as exc:
            self._failure = exc
            raise OutputError(f"writing to '{self.spec.name}' failed: {exc}") from exc

    def _serve(self) -> None:
        """Thread: answer the kernel and stream reports until stopped."""
        next_report = self._clock()
        try:
            while not self._stop.is_set():
                timeout = max(0.0, next_report - self._clock())
                readable, _, _ = select.select([self._fd], [], [], timeout)
                if readable:
                    self._handle(os.read(self._fd, UHID_EVENT_SIZE))
                if self._clock() >= next_report:
                    with self._lock:
                        if self._running and self._failure is None:
                            os.write(self._fd, input2_event(self._state.report()))
                    next_report += REPORT_INTERVAL
                    if next_report < self._clock():  # fell behind (suspend, load)
                        next_report = self._clock() + REPORT_INTERVAL
        except OSError as exc:
            if not self._stop.is_set():
                log.error("emulated controller '%s' failed: %s", self.spec.name, exc)
                with self._lock:
                    self._failure = exc

    def _handle(self, event: bytes) -> None:
        if len(event) < 4:
            return
        (event_type,) = struct.unpack_from("<I", event)
        if event_type == UHID_START:
            with self._lock:
                self._running = True
            self._started.set()
        elif event_type == UHID_STOP:
            with self._lock:
                self._running = False
            log.debug("uhid device '%s' stopped by the kernel", self.spec.name)
        elif event_type == UHID_GET_REPORT:
            request_id, rnum, rtype = struct.unpack_from("<IBB", event, 4)
            if rtype == UHID_FEATURE_REPORT and rnum in self._features:
                reply = get_report_reply(request_id, 0, self._features[rnum])
            else:
                log.debug("refusing report %#04x (type %d)", rnum, rtype)
                reply = get_report_reply(request_id, EIO, b"")
            with self._lock:
                os.write(self._fd, reply)
        elif event_type == UHID_SET_REPORT:
            (request_id,) = struct.unpack_from("<I", event, 4)
            with self._lock:
                os.write(self._fd, set_report_reply(request_id, 0))
        # UHID_OUTPUT (rumble, light bar, player LEDs, trigger effects),
        # UHID_OPEN and UHID_CLOSE: accepted and ignored (§3.5 rule 4).

    def _shutdown(self) -> list[str]:
        """Stop the thread, destroy the device, close the descriptor."""
        errors: list[str] = []
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        try:
            os.write(self._fd, DESTROY_EVENT)
        except OSError as exc:
            errors.append(str(exc))
        try:
            os.close(self._fd)
        except OSError as exc:
            errors.append(str(exc))
        return errors


def open_uhid(spec: OutputDeviceSpec, devnode: str = "/dev/uhid") -> UhidDualSenseEdge:
    """Create the emulated controller for ``spec`` through ``devnode``."""
    try:
        fd = os.open(devnode, os.O_RDWR | os.O_CLOEXEC)
    except OSError as exc:
        raise OutputError(
            f"cannot create emulated controller '{spec.name}': {exc}. "
            f"Check that {devnode} exists and is writable by this user "
            "(see docs/installation.md, 'Device permissions')."
        ) from exc
    return UhidDualSenseEdge(spec, fd)

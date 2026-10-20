"""The emulated DualSense Edge (backends/linux_uhid.py, configuration.md §3.5).

The device runs against one end of a socket pair that plays the kernel's
part of /dev/uhid, so no device access is needed.
"""

from __future__ import annotations

import socket
import struct
import time

import pytest

from inpmap import codes
from inpmap.backends import linux_uhid as u
from inpmap.backends.linux_setup import is_own_node
from inpmap.models import OutputDeviceSpec, OutputKind
from inpmap.output import OutputError

SPEC = OutputDeviceSpec("gamepad", OutputKind.GAMEPAD, "InpMap gamepad", emulate="dualsense-edge")


def c(name):
    return codes.CODES[name]


# -- descriptor ------------------------------------------------------------------


def report_sizes(descriptor: bytes) -> dict[tuple[str, int], int]:
    """Bits per (main item kind, report ID), from the HID short items."""
    sizes: dict[tuple[str, int], int] = {}
    report_id, report_size, report_count = 0, 0, 0
    kinds = {0x80: "input", 0x90: "output", 0xB0: "feature"}
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        length = (0, 1, 2, 4)[prefix & 0x03]
        value = int.from_bytes(descriptor[i + 1 : i + 1 + length], "little")
        tag = prefix & 0xFC
        if tag == 0x84:
            report_id = value
        elif tag == 0x74:
            report_size = value
        elif tag == 0x94:
            report_count = value
        elif tag in kinds:
            key = (kinds[tag], report_id)
            sizes[key] = sizes.get(key, 0) + report_size * report_count
        i += 1 + length
    return sizes


def test_descriptor_declares_the_dualsense_report_sizes():
    # hid-playstation and SDL need 64-byte input reports (ID + 63 bytes);
    # the feature lengths are those hid-playstation requests.
    assert report_sizes(u.REPORT_DESCRIPTOR) == {
        ("input", 0x01): 63 * 8,
        ("output", 0x02): 47 * 8,
        ("feature", 0x05): 40 * 8,
        ("feature", 0x09): 19 * 8,
        ("feature", 0x20): 63 * 8,
    }
    assert u.REPORT_DESCRIPTOR[:4] == bytes([0x05, 0x01, 0x09, 0x05])  # a gamepad
    assert u.REPORT_DESCRIPTOR[-1] == 0xC0


def test_feature_reports():
    mac = u.mac_address("gamepad")
    for report, report_id, size in (
        (u.calibration_report(), 0x05, 41),
        (u.pairing_report(mac), 0x09, 20),
        (u.firmware_report(), 0x20, 64),
    ):
        assert (report[0], len(report)) == (report_id, size)
    assert u.pairing_report(mac)[1:7] == bytes(reversed(mac))
    # hid-playstation divides by the plus/minus ranges; none may be zero.
    values = struct.unpack_from("<17h", u.calibration_report(), 1)
    gyro, speed, accel = values[3:9], values[9:11], values[11:17]
    for plus_minus in (gyro, accel):
        assert all(plus_minus[i] != plus_minus[i + 1] for i in range(0, 6, 2))
    assert sum(speed) != 0


def test_mac_is_stable_local_and_differs_per_output():
    a, b = u.mac_address("gamepad"), u.mac_address("gamepad2")
    assert a == u.mac_address("gamepad") and a != b
    assert a[0] & 0x02 and not a[0] & 0x01  # locally administered, unicast
    assert u.uniq(a).startswith(u.OWN_UNIQ_PREFIX)


def test_kernel_nodes_of_the_emulated_controller_are_own():
    assert is_own_node("", u.uniq(u.mac_address("gamepad")).upper())
    assert is_own_node("inpmap", "")
    assert not is_own_node("usb-0000:00:14.0-1/input0", "e8:47:3a:01:02:03")


# -- input report ----------------------------------------------------------------


def test_button_set_matches_the_validator():
    assert u.BUTTONS == codes.DUALSENSE_EDGE_BUTTONS


def test_neutral_report():
    report = u.PadState().report()
    assert len(report) == 64 and report[0] == 0x01
    assert report[1:7] == bytes([128, 128, 128, 128, 0, 0])
    assert report[8] == u.HAT_NEUTRAL and report[9] == report[10] == 0
    assert report[33] & 0x80 and report[37] & 0x80


@pytest.mark.parametrize(
    ("name", "byte", "bit"),
    [
        ("BTN_WEST", 8, 0x10),
        ("BTN_SOUTH", 8, 0x20),
        ("BTN_EAST", 8, 0x40),
        ("BTN_NORTH", 8, 0x80),
        ("BTN_TL", 9, 0x01),
        ("BTN_TR", 9, 0x02),
        ("BTN_SELECT", 9, 0x10),
        ("BTN_START", 9, 0x20),
        ("BTN_THUMBL", 9, 0x40),
        ("BTN_THUMBR", 9, 0x80),
        ("BTN_MODE", 10, 0x01),
        ("BTN_GRIPL", 10, 0x80),  # right paddle: SDL paddle 1
        ("BTN_GRIPR", 10, 0x40),  # left paddle: SDL paddle 2
        ("BTN_GRIPL2", 10, 0x20),  # right Fn: SDL paddle 3
        ("BTN_GRIPR2", 10, 0x10),  # left Fn: SDL paddle 4
    ],
)
def test_button_bits(name, byte, bit):
    neutral = u.PadState().report()
    state = u.PadState()
    state.held.add(c(name))
    report = state.report()
    assert report[byte] == neutral[byte] | bit
    assert [i for i in range(64) if report[i] != neutral[i]] == [byte]


@pytest.mark.parametrize(
    ("held", "hat"),
    [
        ((), 8),
        (("BTN_DPAD_UP",), 0),
        (("BTN_DPAD_UP", "BTN_DPAD_RIGHT"), 1),
        (("BTN_DPAD_RIGHT",), 2),
        (("BTN_DPAD_DOWN", "BTN_DPAD_RIGHT"), 3),
        (("BTN_DPAD_DOWN",), 4),
        (("BTN_DPAD_DOWN", "BTN_DPAD_LEFT"), 5),
        (("BTN_DPAD_LEFT",), 6),
        (("BTN_DPAD_UP", "BTN_DPAD_LEFT"), 7),
        (("BTN_DPAD_UP", "BTN_DPAD_DOWN"), 8),
        (("BTN_DPAD_UP", "BTN_DPAD_DOWN", "BTN_DPAD_LEFT"), 6),
    ],
)
def test_dpad_becomes_the_hat(held, hat):
    assert u.hat_value({c(name) for name in held}) == hat


def test_axes_and_triggers():
    state = u.PadState()
    state.axes[0x00] = -1.0  # ABS_X
    state.axes[0x01] = 1.0  # ABS_Y
    state.axes[0x03] = 0.5  # ABS_RX
    state.axes[0x02] = 0.5  # ABS_Z: L2 half
    report = state.report()
    assert report[1:5] == bytes([0, 255, 191, 128])
    assert report[5] == 128 and report[9] & 0x04  # L2 analog and its button bit
    assert report[6] == 0 and not report[9] & 0x08


def test_trigger_button_presses_the_trigger_fully():
    state = u.PadState()
    state.axes[0x05] = 0.25  # ABS_RZ
    state.held.add(c("BTN_TR2"))
    report = state.report()
    assert report[6] == 255 and report[9] & 0x08


def test_counter_and_timestamp_advance():
    state = u.PadState()
    first, second = state.report(), state.report()
    assert (first[7], second[7]) == (0, 1)
    assert struct.unpack_from("<I", second, 28)[0] > struct.unpack_from("<I", first, 28)[0]


# -- the device against a fake kernel ----------------------------------------------


class FakeKernel:
    """The kernel's end of /dev/uhid."""

    def __init__(self) -> None:
        self.sock, device_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.device_fd = device_end.detach()
        self.sock.settimeout(2.0)

    def receive(self) -> tuple[int, bytes]:
        data = self.sock.recv(u.UHID_EVENT_SIZE)
        return struct.unpack_from("<I", data)[0], data

    def receive_until(self, event_type: int) -> bytes:
        while True:
            kind, data = self.receive()
            if kind == event_type:
                return data

    def send(self, data: bytes) -> None:
        self.sock.send(data)

    def start(self) -> None:
        self.send(struct.pack("<IQ", u.UHID_START, 0))


def open_device(kernel: FakeKernel, **kwargs) -> u.UhidDualSenseEdge:
    kernel.start()  # queued; the device answers once its thread runs
    return u.UhidDualSenseEdge(SPEC, kernel.device_fd, **kwargs)


def test_create_announces_the_identity():
    kernel = FakeKernel()
    device = open_device(kernel)
    try:
        kind, event = kernel.receive()
        assert kind == u.UHID_CREATE2
        name, phys, uniq = struct.unpack_from("<128s64s64s", event, 4)
        assert name.rstrip(b"\0") == b"InpMap gamepad"
        assert phys.rstrip(b"\0") == b"inpmap-uhid"
        assert uniq.rstrip(b"\0").decode() == device.uniq
        rd_size, bus, vendor, product = struct.unpack_from("<HHII", event, 4 + 256)
        assert (rd_size, bus, vendor, product) == (len(u.REPORT_DESCRIPTOR), 3, 0x054C, 0x0DF2)
        assert event[4 + 256 + 20 :] == u.REPORT_DESCRIPTOR
    finally:
        device.close()


def test_feature_requests_are_answered_and_others_refused():
    kernel = FakeKernel()
    device = open_device(kernel)
    try:
        for request_id, rnum, size, err in ((7, 0x09, 20, 0), (8, 0x20, 64, 0), (9, 0x05, 41, 0)):
            kernel.send(struct.pack("<IIBB", u.UHID_GET_REPORT, request_id, rnum, 0))
            reply = kernel.receive_until(u.UHID_GET_REPORT_REPLY)
            assert struct.unpack_from("<IHH", reply, 4) == (request_id, err, size)
            assert reply[12] == rnum
        kernel.send(struct.pack("<IIBB", u.UHID_GET_REPORT, 10, 0x22, 0))
        reply = kernel.receive_until(u.UHID_GET_REPORT_REPLY)
        assert struct.unpack_from("<IHH", reply, 4) == (10, u.EIO, 0)
        kernel.send(struct.pack("<IIBBH", u.UHID_SET_REPORT, 11, 0x80, 0, 1) + b"\0")
        reply = kernel.receive_until(u.UHID_SET_REPORT_REPLY)
        assert struct.unpack_from("<IH", reply, 4) == (11, 0)
    finally:
        device.close()


def test_reports_stream_and_presses_are_sent_at_once():
    kernel = FakeKernel()
    device = open_device(kernel)
    try:
        first = kernel.receive_until(u.UHID_INPUT2)
        assert struct.unpack_from("<H", first, 4)[0] == 64
        device.set_key(c("BTN_GRIPL"), True)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            report = kernel.receive_until(u.UHID_INPUT2)[6:]
            if report[10] & 0x80:
                break
        else:
            pytest.fail("the press never arrived")
        device.set_key(c("BTN_GRIPL"), False)
        device.set_axis(0x00, 1.0)
        while True:
            report = kernel.receive_until(u.UHID_INPUT2)[6:]
            if report[1] == 255:
                assert not report[10] & 0x80
                break
    finally:
        device.close()
    kernel.receive_until(u.UHID_DESTROY)


def test_output_reports_are_ignored():
    kernel = FakeKernel()
    device = open_device(kernel)
    try:
        kernel.send(struct.pack("<I", u.UHID_OUTPUT) + b"\x02" + bytes(4095) + b"\x30\x00\x01")
        kernel.receive_until(u.UHID_INPUT2)  # still streaming
    finally:
        device.close()


def test_unknown_codes_are_refused():
    kernel = FakeKernel()
    device = open_device(kernel)
    try:
        with pytest.raises(OutputError):
            device.set_key(c("BTN_TRIGGER_HAPPY1"), True)
        with pytest.raises(OutputError):
            device.set_axis(0x10, 1.0)  # ABS_HAT0X
        assert device.fileno() is None and device.poll_leds() is None
    finally:
        device.close()


def test_no_start_from_the_kernel_is_an_error():
    kernel = FakeKernel()
    with pytest.raises(OutputError, match="did not start"):
        u.UhidDualSenseEdge(SPEC, kernel.device_fd, start_timeout=0.05)
    kinds = [kernel.receive()[0], kernel.receive()[0]]
    assert kinds == [u.UHID_CREATE2, u.UHID_DESTROY]


def test_lost_device_is_reported_on_the_next_write():
    kernel = FakeKernel()
    device = open_device(kernel)
    try:
        kernel.receive_until(u.UHID_INPUT2)
        kernel.sock.close()
        with pytest.raises(OutputError):
            for _ in range(100):
                device.set_key(c("BTN_SOUTH"), True)
                device.set_key(c("BTN_SOUTH"), False)
                time.sleep(0.01)
    finally:
        with pytest.raises(OutputError):
            device.close()


def test_missing_devnode_is_an_actionable_error(tmp_path):
    with pytest.raises(OutputError, match="installation.md"):
        u.open_uhid(SPEC, str(tmp_path / "uhid"))

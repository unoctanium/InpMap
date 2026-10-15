"""In-memory test doubles for backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from inpmap import codes
from inpmap.axis_triggers import AxisEvent, normalize
from inpmap.input import InputDeviceLost, InputError
from inpmap.models import InputDeviceSpec, InputEvent, KeyAction, OutputDeviceSpec
from inpmap.output import OutputError
from inpmap.routing import DeviceCapabilities, RoutePlan

# Raw fake events: ("key", code, value), ("abs", code, value), ("syn",), ("msc", code, value).
SYN = ("syn",)


def key_raw(code: int, value: int) -> tuple:
    return ("key", code, value)


def abs_raw(code: int, value: int) -> tuple:
    return ("abs", code, value)


@dataclass
class FakeInputSource:
    spec: InputDeviceSpec
    held: set[int] = field(default_factory=set)
    queue: list[tuple] = field(default_factory=list)
    forwarded: list[tuple] = field(default_factory=list)
    journal: list[str] = field(default_factory=list)
    grabbed: bool = False
    closed: bool = False
    lost: bool = False
    grab_error: InputError | None = None
    close_error: InputError | None = None
    discarded: list[tuple] = field(default_factory=list)
    lit: set = field(default_factory=set)  # Led values
    masked: set = field(default_factory=set)
    physically_down: set = field(default_factory=set)
    keys: frozenset | None = None  # reported key codes; None: every code
    axes: dict = field(default_factory=dict)  # ABS code -> (min, max)
    relative: frozenset = frozenset()  # REL codes
    plan: RoutePlan | None = None  # set by start_passthrough
    dropped: list[tuple] = field(default_factory=list)  # not carried by the pass-through device

    def capabilities(self) -> DeviceCapabilities:
        # Without explicit keys the fake is a keyboard (every KEY_* code).
        keys = codes.KEYBOARD_OUTPUT_KEYS if self.keys is None else self.keys
        return DeviceCapabilities(keys, dict(self.axes), self.relative)

    def start_passthrough(self, plan: RoutePlan) -> None:
        self.plan = plan

    def _carried(self, raw: tuple) -> bool:
        plan = self.plan
        if plan is None or plan.own:
            return True
        if raw[0] == "key":
            return raw[1] in plan.passthrough_keys
        if raw[0] == "abs":
            return raw[1] in plan.passthrough_axes
        if raw[0] == "rel":
            return raw[1] in plan.passthrough_relative
        return False

    def axis_ranges(self) -> dict:
        return dict(self.axes)

    def key_codes(self) -> frozenset[int]:
        return frozenset(range(0x300)) if self.keys is None else self.keys

    @property
    def description(self) -> str:
        return f"fake {self.spec.id}"

    def leds(self) -> frozenset:
        return frozenset(self.lit)

    def set_leds(self, leds: frozenset) -> None:
        self.lit = set(leds)
        self.journal.append(f"leds {self.spec.id} {sorted(led.value for led in leds)}")

    def held_codes(self) -> frozenset[int]:
        if self.lost:
            raise InputDeviceLost(f"{self.description} lost")
        return frozenset(self.held)

    def grab(self) -> None:
        self.journal.append(f"grab {self.spec.id}")
        if self.lost:
            raise InputDeviceLost(f"{self.description} lost")
        if self.grab_error is not None:
            raise self.grab_error
        self.grabbed = True

    def read(self) -> list[tuple[InputEvent | None, object]]:
        if self.lost:
            raise InputDeviceLost(f"{self.description} lost")
        raws, self.queue = self.queue, []
        for raw in raws:
            if raw[0] == "key" and raw[2] == 1:
                self.physically_down.add(raw[1])
            elif raw[0] == "key" and raw[2] == 0:
                self.physically_down.discard(raw[1])
        if not self.grabbed:
            self.discarded += raws
        result = []
        for raw in raws:
            if raw[0] == "key":
                event = InputEvent(self.spec.id, raw[1], KeyAction(raw[2]))
                result.append((event, raw))
            elif raw[0] == "abs" and raw[1] in self.axes:
                value = normalize(raw[2], *self.axes[raw[1]])
                result.append((AxisEvent(self.spec.id, raw[1], value), raw))
            else:
                result.append((None, raw))
        return result

    def forward(self, raw: object) -> None:
        if not self._carried(raw):
            self.dropped.append(raw)
            return
        if raw[0] == "key" and raw[1] in self.masked:
            return
        if raw[0] == "key" and raw[2] != 1 and not self._forwarded_down(raw[1]):
            return  # like the real source: no release/repeat of keys not down
        self.forwarded.append(raw)

    def mask(self, code: int) -> None:
        if code in self.masked:
            return
        self.masked.add(code)
        if self._forwarded_down(code):
            self.forwarded.append(("key", code, 0))

    def unmask(self, code: int) -> None:
        if code not in self.masked:
            return
        self.masked.discard(code)
        if code in self.physically_down and not self._forwarded_down(code):
            self.forwarded.append(("key", code, 1))

    def _forwarded_down(self, code: int) -> bool:
        state = False
        for raw in self.forwarded:
            if raw[0] == "key" and raw[1] == code and raw[2] in (0, 1):
                state = raw[2] == 1
        return state

    def close(self) -> None:
        self.journal.append(f"close {self.spec.id}")
        self.grabbed = False
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


@dataclass
class FakeInputBackend:
    """Opens pre-built sources; each wait() call runs the next script step.

    ``sources[id]`` is returned by open(); ``replacements[id]`` holds sources
    returned by later open() calls (reconnects), in order. When the script is
    exhausted, ``stop`` (if given) is set.
    """

    sources: dict[str, FakeInputSource]
    script: list[Callable[[], None]] = field(default_factory=list)
    stop: object | None = None
    open_error: dict[str, InputError] = field(default_factory=dict)
    opened_codes: dict[str, frozenset[int]] = field(default_factory=dict)
    replacements: dict[str, list[FakeInputSource]] = field(default_factory=dict)
    open_count: dict[str, int] = field(default_factory=dict)  # successful opens
    open_attempts: dict[str, int] = field(default_factory=dict)

    def open(self, spec: InputDeviceSpec, mapped_codes: frozenset[int]) -> FakeInputSource:
        self.open_attempts[spec.id] = self.open_attempts.get(spec.id, 0) + 1
        if spec.id in self.open_error:
            raise self.open_error[spec.id]
        self.opened_codes[spec.id] = mapped_codes
        count = self.open_count.get(spec.id, 0)
        self.open_count[spec.id] = count + 1
        if count == 0:
            return self.sources[spec.id]
        return self.replacements[spec.id].pop(0)

    def wait(self, sources, timeout: float, feedback=()) -> list[FakeInputSource]:
        if self.script:
            self.script.pop(0)()
        elif self.stop is not None:
            self.stop.set()
        return [s for s in sources if s.queue or s.lost]


@dataclass
class FakeOutputDevice:
    spec: OutputDeviceSpec
    key_codes: frozenset[int]
    events: list[tuple[int, bool]] = field(default_factory=list)
    axis_events: list[tuple[int, float]] = field(default_factory=list)
    closed: bool = False
    fail_writes: bool = False
    fail_close: bool = False

    def set_key(self, code: int, pressed: bool) -> None:
        if self.closed:
            raise AssertionError("write to closed device")
        if code not in self.key_codes:
            raise AssertionError(f"code {code:#x} not declared")
        if self.fail_writes:
            raise OutputError("simulated write failure")
        self.events.append((code, pressed))

    def set_axis(self, code: int, value: float) -> None:
        if self.closed:
            raise AssertionError("write to closed device")
        if self.fail_writes:
            raise OutputError("simulated write failure")
        self.axis_events.append((code, value))

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise OutputError("simulated close failure")

    def fileno(self) -> int | None:
        return None

    def poll_leds(self):
        """LED states set by a test (``set_leds``), each reported once."""
        leds, self.pending_leds = self.pending_leds, None
        return leds

    pending_leds: frozenset | None = None


@dataclass
class FakeOutputBackend:
    created: dict[str, FakeOutputDevice] = field(default_factory=dict)
    fail_on: str | None = None
    journal: list[str] = field(default_factory=list)

    def create(self, spec: OutputDeviceSpec, key_codes: frozenset[int]) -> FakeOutputDevice:
        self.journal.append(f"create {spec.id}")
        if spec.id == self.fail_on:
            raise OutputError(f"simulated create failure for {spec.id}")
        device = FakeOutputDevice(spec, key_codes)
        self.created[spec.id] = device
        return device

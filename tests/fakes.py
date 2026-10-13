"""In-memory test doubles for backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from inpmap.input import InputDeviceLost, InputError
from inpmap.models import InputDeviceSpec, InputEvent, KeyAction, OutputDeviceSpec
from inpmap.output import OutputError

# Raw fake events: ("key", code, value) or ("syn",) or ("msc", code, value).
SYN = ("syn",)


def key_raw(code: int, value: int) -> tuple:
    return ("key", code, value)


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

    @property
    def description(self) -> str:
        return f"fake {self.spec.id}"

    def held_codes(self) -> frozenset[int]:
        return frozenset(self.held)

    def grab(self) -> None:
        self.journal.append(f"grab {self.spec.id}")
        if self.grab_error is not None:
            raise self.grab_error
        self.grabbed = True

    def read(self) -> list[tuple[InputEvent | None, object]]:
        if self.lost:
            raise InputDeviceLost(f"{self.description} lost")
        raws, self.queue = self.queue, []
        if not self.grabbed:
            self.discarded += raws
        result = []
        for raw in raws:
            if raw[0] == "key":
                event = InputEvent(self.spec.id, raw[1], KeyAction(raw[2]))
                result.append((event, raw))
            else:
                result.append((None, raw))
        return result

    def forward(self, raw: object) -> None:
        self.forwarded.append(raw)

    def close(self) -> None:
        self.journal.append(f"close {self.spec.id}")
        self.grabbed = False
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


@dataclass
class FakeInputBackend:
    """Opens pre-built sources; each wait() call runs the next script step.

    When the script is exhausted, ``stop`` (if given) is set.
    """

    sources: dict[str, FakeInputSource]
    script: list[Callable[[], None]] = field(default_factory=list)
    stop: object | None = None
    open_error: dict[str, InputError] = field(default_factory=dict)
    opened_codes: dict[str, frozenset[int]] = field(default_factory=dict)

    def open(self, spec: InputDeviceSpec, mapped_codes: frozenset[int]) -> FakeInputSource:
        if spec.id in self.open_error:
            raise self.open_error[spec.id]
        self.opened_codes[spec.id] = mapped_codes
        return self.sources[spec.id]

    def wait(self, sources, timeout: float) -> list[FakeInputSource]:
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

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise OutputError("simulated close failure")


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

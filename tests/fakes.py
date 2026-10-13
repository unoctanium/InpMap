"""In-memory test doubles for backends."""

from __future__ import annotations

from dataclasses import dataclass, field

from inpmap.models import OutputDeviceSpec
from inpmap.output import OutputError


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

    def create(self, spec: OutputDeviceSpec, key_codes: frozenset[int]) -> FakeOutputDevice:
        if spec.id == self.fail_on:
            raise OutputError(f"simulated create failure for {spec.id}")
        device = FakeOutputDevice(spec, key_codes)
        self.created[spec.id] = device
        return device

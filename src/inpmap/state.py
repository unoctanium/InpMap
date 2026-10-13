"""Reference-counted ownership of output keys.

Several held inputs may share one output (two buttons both mapped to KEY_Y).
The output must stay pressed while at least one of them is held, so each
(output device, code) has a count of holders: it is pressed on 0 -> 1 and
released on 1 -> 0.
"""

from __future__ import annotations

from collections import Counter

OutputKey = tuple[str, int]  # (output device id, code)


class OutputRefCounts:
    """Counts how many active inputs hold each output key."""

    def __init__(self) -> None:
        self._counts: Counter[OutputKey] = Counter()

    def acquire(self, key: OutputKey) -> bool:
        """Add a holder. Returns True if the key just became held (0 -> 1)."""
        self._counts[key] += 1
        return self._counts[key] == 1

    def release(self, key: OutputKey) -> bool:
        """Remove a holder. Returns True if the key just became free (1 -> 0).

        Raises ValueError if the key has no holders: callers must only
        release what they acquired, so this indicates a bug.
        """
        if self._counts[key] <= 0:
            del self._counts[key]
            raise ValueError(f"release of unheld output {key}")
        self._counts[key] -= 1
        if self._counts[key] == 0:
            del self._counts[key]
            return True
        return False

    def count(self, key: OutputKey) -> int:
        return self._counts.get(key, 0)

    def held(self) -> frozenset[OutputKey]:
        return frozenset(self._counts)

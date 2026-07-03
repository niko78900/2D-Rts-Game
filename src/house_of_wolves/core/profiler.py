"""Minimal profiler hooks for future hot-path work."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter


@dataclass(slots=True)
class Profiler:
    """Small named-span profiler for development builds."""

    totals_ms: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter() - start) * 1000
            self.totals_ms[name] += elapsed_ms
            self.counts[name] += 1

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {
            name: {
                "total_ms": total,
                "count": float(self.counts[name]),
                "avg_ms": total / max(1, self.counts[name]),
            }
            for name, total in self.totals_ms.items()
        }

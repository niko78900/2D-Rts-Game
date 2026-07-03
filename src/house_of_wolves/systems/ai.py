"""Enemy and neutral AI system shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AISystem:
    def update(self, world: object, dt_ms: int) -> None:
        return None

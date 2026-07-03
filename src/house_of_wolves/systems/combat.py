"""Combat system shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CombatSystem:
    def update(self, world: object, dt_ms: int) -> None:
        return None

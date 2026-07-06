"""Upgrade system shell."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class UpgradeState:
    researched: set[str] = field(default_factory=set)


@dataclass(slots=True)
class UpgradeSystem:
    state: UpgradeState = field(default_factory=UpgradeState)

    def update(self, world: object, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
        return None

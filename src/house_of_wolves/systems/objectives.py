"""Scenario objective system shell."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ObjectiveState:
    active: set[str] = field(default_factory=set)
    completed: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ObjectiveSystem:
    state: ObjectiveState = field(default_factory=ObjectiveState)

    def update(self, world: object, dt_ms: int) -> None:
        return None

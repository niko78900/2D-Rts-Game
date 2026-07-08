"""Lightweight transient visuals produced by combat events."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, WorldPosition


@dataclass(slots=True)
class CombatEffect:
    """One short-lived visual that does not participate in gameplay."""

    kind: str
    position: WorldPosition
    duration_ms: int
    remaining_ms: int
    owner: str = "neutral"
    target_entity_id: EntityId | None = None
    value: int | None = None
    direction_x: float = 1.0
    direction_y: float = 0.0

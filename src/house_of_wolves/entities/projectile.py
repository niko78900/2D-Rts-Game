"""Projectile state."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class Projectile(Entity):
    """Lightweight ranged attack that tracks only its intended target."""

    target_entity_id: EntityId | None = None
    target_pos: WorldPosition | None = None
    source_entity_id: EntityId | None = None
    damage: int = 0
    speed: float = 0
    remaining_lifetime_ms: int = 0
    hit_radius: float = 10.0
    splash_radius: float = 0.0

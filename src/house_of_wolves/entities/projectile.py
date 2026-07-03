"""Projectile state."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class Projectile(Entity):
    target_entity_id: EntityId | None = None
    target_pos: WorldPosition | None = None
    damage: int = 0
    speed: float = 0

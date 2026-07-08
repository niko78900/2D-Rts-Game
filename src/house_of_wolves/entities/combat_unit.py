"""Combat unit state."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId
from house_of_wolves.entities.unit import Unit


@dataclass(slots=True)
class CombatUnit(Unit):
    damage: int = 0
    attack_cooldown_ms: int = 1000
    cooldown_remaining_ms: int = 0
    attack_windup_remaining_ms: int = 0
    pending_attack_target_id: EntityId | None = None
    facing_x: float = 1.0
    facing_y: float = 0.0

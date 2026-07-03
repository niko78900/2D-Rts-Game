"""Mobile unit entity."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class Unit(Entity):
    speed: float = 0
    state: str = "idle"
    attack_range: float = 0

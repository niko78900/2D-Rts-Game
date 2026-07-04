"""Harvestable resource node."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import Footprint
from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class ResourceNode(Entity):
    resource_type: str = "wood"
    amount_remaining: int = 0
    max_amount_remaining: int | None = None
    gather_time_ms: int = 1000
    harvest_slots: int = 1
    depleted_replacement: str | None = None
    blocking_footprint: Footprint | None = None

    @property
    def blocking_bounds(self) -> tuple[float, float, float, float]:
        footprint = self.blocking_footprint or self.footprint
        return footprint.bounds_at(self.position)

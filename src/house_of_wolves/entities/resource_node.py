"""Harvestable resource node."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import Footprint
from house_of_wolves.entities.base import Entity

WOOD_RESOURCE_HP = 150
MINERAL_RESOURCE_HP = 500
RESOURCE_NODE_HP_BY_TYPE = {
    "wood": WOOD_RESOURCE_HP,
    "stone": MINERAL_RESOURCE_HP,
    "iron": MINERAL_RESOURCE_HP,
    "gold": MINERAL_RESOURCE_HP,
}


@dataclass(slots=True)
class ResourceNode(Entity):
    resource_type: str = "wood"
    amount_remaining: int = 0
    max_amount_remaining: int | None = None
    gather_time_ms: int = 1000
    harvest_slots: int = 1
    depleted_replacement: str | None = None
    blocking_footprint: Footprint | None = None
    state: str = "active"
    destruction_remaining_ms: int = 0
    respawn_enabled: bool = True

    @property
    def blocking_bounds(self) -> tuple[float, float, float, float]:
        footprint = self.blocking_footprint or self.footprint
        return footprint.bounds_at(self.position)


def resource_hp_for_type(resource_type: str) -> int:
    return RESOURCE_NODE_HP_BY_TYPE.get(resource_type, MINERAL_RESOURCE_HP)

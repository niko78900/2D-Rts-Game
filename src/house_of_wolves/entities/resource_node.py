"""Harvestable resource node."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, Footprint
from house_of_wolves.core.game_specs import resource_spec_from_type
from house_of_wolves.entities.base import Entity

WOOD_RESOURCE_HP = resource_spec_from_type("wood").amount
STONE_RESOURCE_HP = resource_spec_from_type("stone").amount
ORE_RESOURCE_HP = resource_spec_from_type("iron").amount
GOLD_RESOURCE_HP = resource_spec_from_type("gold").amount
RESOURCE_NODE_HP_BY_TYPE = {
    "wood": WOOD_RESOURCE_HP,
    "stone": STONE_RESOURCE_HP,
    "iron": ORE_RESOURCE_HP,
    "gold": GOLD_RESOURCE_HP,
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
    source_entity_id: EntityId | None = None

    @property
    def blocking_bounds(self) -> tuple[float, float, float, float]:
        """Return the resource footprint used for movement blocking."""
        footprint = self.blocking_footprint or self.footprint
        return footprint.bounds_at(self.position)


def resource_hp_for_type(resource_type: str) -> int:
    """Return the starting HP for a resource type."""
    return RESOURCE_NODE_HP_BY_TYPE.get(resource_type, STONE_RESOURCE_HP)

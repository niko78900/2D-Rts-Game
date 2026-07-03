"""Harvestable resource node."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class ResourceNode(Entity):
    resource_type: str = "wood"
    amount_remaining: int = 0
    gather_time_ms: int = 1000
    harvest_slots: int = 1
    depleted_replacement: str | None = None

"""Building entity state."""

from __future__ import annotations

from dataclasses import dataclass, field

from house_of_wolves.core.contracts import ProductionQueueItem
from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class Building(Entity):
    build_progress_ms: int = 0
    build_time_ms: int = 0
    complete: bool = False
    production_queue: list[ProductionQueueItem] = field(default_factory=list)
    functions: dict[str, object] = field(default_factory=dict)

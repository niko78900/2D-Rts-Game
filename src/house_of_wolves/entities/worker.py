"""Worker unit state."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId
from house_of_wolves.entities.unit import Unit


@dataclass(slots=True)
class Worker(Unit):
    build_target: EntityId | None = None

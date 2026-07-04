"""Building entity state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from house_of_wolves.core.contracts import ProductionQueueItem, WorldPosition
from house_of_wolves.entities.base import Entity


@dataclass(frozen=True, slots=True)
class ProductionBuildingConfig:
    """Reusable production-building behavior shared by huts and later producers."""

    dropoff: bool = False
    population_cap_bonus: int = 0
    trainable_units: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ProductionBuildingConfig:
        return cls(
            dropoff=bool(value.get("dropoff", False)),
            population_cap_bonus=int(value.get("population_cap_bonus", 0)),
            trainable_units=tuple(str(unit_id) for unit_id in value.get("trainable_units", ())),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "dropoff": self.dropoff,
            "population_cap_bonus": self.population_cap_bonus,
            "trainable_units": list(self.trainable_units),
        }


@dataclass(slots=True)
class Building(Entity):
    build_progress_ms: int = 0
    build_time_ms: int = 0
    complete: bool = False
    production_queue: list[ProductionQueueItem] = field(default_factory=list)
    functions: dict[str, object] = field(default_factory=dict)
    dropoff_point: WorldPosition | None = None

    @property
    def production_config(self) -> ProductionBuildingConfig:
        return ProductionBuildingConfig.from_mapping(self.functions)

    @classmethod
    def production_functions(
        cls,
        *,
        dropoff: bool = False,
        population_cap_bonus: int = 0,
        trainable_units: tuple[str, ...] = (),
    ) -> dict[str, object]:
        return ProductionBuildingConfig(
            dropoff=dropoff,
            population_cap_bonus=population_cap_bonus,
            trainable_units=trainable_units,
        ).to_mapping()

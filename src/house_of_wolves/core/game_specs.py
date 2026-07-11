"""Typed accessors for validated gameplay JSON definitions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from house_of_wolves.core.contracts import Footprint
from house_of_wolves.core.data import DataBundle, DefinitionLoadError, load_data_bundle

RESOURCE_KEYS = ("wood", "food", "stone", "iron", "gold")
DEFAULT_UNIT_FOOTPRINT = Footprint(38, 58)


@dataclass(frozen=True, slots=True)
class UnitDataSpec:
    """Runtime unit stats loaded from data/units.json."""

    unit_id: str
    display_name: str
    footprint: Footprint
    hp: int
    damage: int
    speed: float
    attack_range: float
    attack_cooldown_ms: int
    cost: dict[str, int]
    population_cost: int


@dataclass(frozen=True, slots=True)
class BuildingDataSpec:
    """Runtime building stats loaded from data/buildings.json."""

    building_id: str
    display_name: str
    footprint: Footprint
    hp: int
    build_time_ms: int
    cost: dict[str, int]
    functions: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ResourceDataSpec:
    """Runtime resource-node stats loaded from data/resources.json."""

    resource_id: str
    display_name: str
    resource_type: str
    amount: int
    gather_time_ms: int
    harvest_slots: int
    depleted_replacement: str
    footprint: Footprint
    blocking_footprint: Footprint
    tags: tuple[str, ...]


@lru_cache(maxsize=1)
def game_data_bundle() -> DataBundle:
    """Load validated gameplay data once for runtime spec construction."""
    return load_data_bundle()


def unit_spec_from_data(
    unit_id: str,
    *,
    footprint: Footprint = DEFAULT_UNIT_FOOTPRINT,
) -> UnitDataSpec:
    """Return the canonical unit stats for a unit id."""
    raw = _definition(game_data_bundle().units.items, unit_id, "unit")
    stats = raw["stats"]
    return UnitDataSpec(
        unit_id=unit_id,
        display_name=str(raw["display_name"]),
        footprint=footprint,
        hp=int(stats["hp"]),
        damage=int(stats["damage"]),
        speed=float(stats["speed"]),
        attack_range=float(stats["attack_range"]),
        attack_cooldown_ms=int(stats["attack_cooldown_ms"]),
        cost=runtime_cost(raw["cost"]),
        population_cost=int(raw["population"]),
    )


def building_spec_from_data(building_id: str) -> BuildingDataSpec:
    """Return the canonical building stats for a building id."""
    raw = _definition(game_data_bundle().buildings.items, building_id, "building")
    stats = raw["stats"]
    width, height = _pair(stats["footprint_px"], f"{building_id}.stats.footprint_px")
    return BuildingDataSpec(
        building_id=building_id,
        display_name=str(raw["display_name"]),
        footprint=Footprint(width, height),
        hp=int(stats["hp"]),
        build_time_ms=int(stats["build_time_ms"]),
        cost=runtime_cost(raw["cost"]),
        functions=dict(raw.get("functions", {})),
    )


def resource_spec_from_type(resource_type: str) -> ResourceDataSpec:
    """Return the canonical resource-node stats for a resource type."""
    for resource_id, raw in game_data_bundle().resources.items.items():
        if raw.get("resource_type") == resource_type:
            return resource_spec_from_id(resource_id)
    raise DefinitionLoadError(f"Unknown resource type: {resource_type}")


def resource_spec_from_id(resource_id: str) -> ResourceDataSpec:
    """Return the canonical resource-node stats for a resource definition id."""
    raw = _definition(game_data_bundle().resources.items, resource_id, "resource")
    width, height = _pair(raw["footprint_px"], f"{resource_id}.footprint_px")
    blocking_width, blocking_height = _pair(
        raw["blocking_footprint_px"],
        f"{resource_id}.blocking_footprint_px",
    )
    return ResourceDataSpec(
        resource_id=resource_id,
        display_name=str(raw["display_name"]),
        resource_type=str(raw["resource_type"]),
        amount=int(raw["amount"]),
        gather_time_ms=int(raw["gather_time_ms"]),
        harvest_slots=int(raw["harvest_slots"]),
        depleted_replacement=str(raw["depleted_replacement"]),
        footprint=Footprint(width, height),
        blocking_footprint=Footprint(blocking_width, blocking_height),
        tags=tuple(str(tag) for tag in raw["tags"]),
    )


def _definition(
    definitions: dict[str, dict[str, Any]],
    item_id: str,
    item_type: str,
) -> dict[str, Any]:
    try:
        return definitions[item_id]
    except KeyError as exc:
        raise DefinitionLoadError(f"Unknown {item_type} definition: {item_id}") from exc


def runtime_cost(raw_cost: dict[str, Any]) -> dict[str, int]:
    """Return a compact runtime cost dict with zero-cost resources omitted."""
    return {
        resource: amount
        for resource in RESOURCE_KEYS
        if (amount := max(0, int(raw_cost.get(resource, 0)))) > 0
    }


def _pair(raw_pair: object, source: str) -> tuple[int, int]:
    if not isinstance(raw_pair, list | tuple) or len(raw_pair) != 2:
        raise DefinitionLoadError(f"{source} must be a two-value list")
    return (int(raw_pair[0]), int(raw_pair[1]))

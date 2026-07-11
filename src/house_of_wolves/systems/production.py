"""Unit production helpers and system shell."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.core.game_specs import (
    building_spec_from_data,
    runtime_cost,
    unit_spec_from_data,
)
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.combat_unit import CombatUnit
from house_of_wolves.entities.unit import Unit
from house_of_wolves.systems.commands import make_command
from house_of_wolves.world.collision import nearest_free_position
from house_of_wolves.world.terrain import DEFAULT_TERRAIN_HEIGHT, terrain_layout_for_height
from house_of_wolves.world.world import WorldState

BARRACKS_BUILDING_ID = "barracks"
ARCHERY_BUILDING_ID = "archery"
ARCHERY_RANGE_BUILDING_ID = "archery_range"


@dataclass(frozen=True, slots=True)
class ProductionBuildingSpec:
    """Configures a first-pass military production building."""

    building_id: str
    display_name: str
    footprint: Footprint
    hp: int
    build_time_ms: int
    cost: dict[str, int]
    trainable_units: tuple[str, ...]



def _production_building_spec(building_id: str) -> ProductionBuildingSpec:
    """Build a production-building spec from the validated building data."""
    spec = building_spec_from_data(building_id)
    return ProductionBuildingSpec(
        building_id=building_id,
        display_name=spec.display_name,
        footprint=spec.footprint,
        hp=spec.hp,
        build_time_ms=spec.build_time_ms,
        cost=spec.cost,
        trainable_units=tuple(str(unit_id) for unit_id in spec.functions["trainable_units"]),
    )


BARRACKS_SPEC = _production_building_spec(BARRACKS_BUILDING_ID)
ARCHERY_SPEC = _production_building_spec(ARCHERY_BUILDING_ID)
PRODUCTION_BUILDING_SPECS = {
    BARRACKS_BUILDING_ID: BARRACKS_SPEC,
    ARCHERY_BUILDING_ID: ARCHERY_SPEC,
    ARCHERY_RANGE_BUILDING_ID: ARCHERY_SPEC,
}


def _unit_template(unit_id: str) -> dict[str, object]:
    """Build the legacy unit template shape from validated unit data."""
    spec = unit_spec_from_data(unit_id)
    return {
        "hp": spec.hp,
        "speed": spec.speed,
        "footprint": (spec.footprint.width, spec.footprint.height),
        "damage": spec.damage,
        "attack_range": spec.attack_range,
        "attack_cooldown_ms": spec.attack_cooldown_ms,
        "cost": spec.cost,
        "population_cost": spec.population_cost,
    }


UNIT_TEMPLATES = {
    unit_id: _unit_template(unit_id)
    for unit_id in ("settler", "spearman", "archer", "enemy_swordsman", "enemy_archer")
}


def _building_unit_costs() -> dict[str, dict[str, dict[str, int]]]:
    """Load building-specific production price overrides from building data."""
    costs: dict[str, dict[str, dict[str, int]]] = {}
    for building_id in (BARRACKS_BUILDING_ID, ARCHERY_BUILDING_ID):
        functions = building_spec_from_data(building_id).functions
        overrides = functions.get("unit_cost_overrides", {})
        costs[building_id] = {
            str(unit_id): runtime_cost(raw_cost)
            for unit_id, raw_cost in dict(overrides).items()
        }
    costs[ARCHERY_RANGE_BUILDING_ID] = dict(costs[ARCHERY_BUILDING_ID])
    return costs


BUILDING_UNIT_COSTS = _building_unit_costs()


class ProductionError(ValueError):
    """Raised when a production request cannot be fulfilled."""


@dataclass(slots=True)
class ProductionSystem:
    def update(self, world: object, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
        return None


def produce_unit(world: WorldState, producer_id: EntityId, unit_id: str) -> Unit:
    """Create a unit from a building and command it to its rally point."""

    producer = world.entities.get(producer_id)
    if not isinstance(producer, Building):
        raise ProductionError("producer must be a building")
    if not producer.alive:
        raise ProductionError("producer building is destroyed")
    if not producer.complete:
        raise ProductionError("producer building is not complete")
    production_config = producer.production_config
    if unit_id not in production_config.trainable_units:
        raise ProductionError(f"{unit_id} is not trainable by this building")
    if unit_id not in UNIT_TEMPLATES:
        raise ProductionError(f"{unit_id} has no production template")
    population_cost = unit_population_cost(unit_id, world)
    if world.current_population + population_cost > world.max_population:
        raise ProductionError("Population cap reached.")

    missing_resource = _first_missing_resource(world, unit_cost(unit_id, producer))
    if missing_resource is not None:
        raise ProductionError(f"Not enough {missing_resource}.")

    _spend_resources(world, unit_cost(unit_id, producer))
    unit = _create_unit(world, producer, unit_id)
    world.add_entity(unit)

    if producer.dropoff_point is not None:
        command = make_command("move", [unit.id], target_pos=producer.dropoff_point)
        world.enqueue_command(unit.id, command)

    return unit


def unit_population_cost(unit_id: str, world: WorldState | None = None) -> int:
    """Return the population cost for a unit type."""
    template = UNIT_TEMPLATES.get(unit_id, {})
    default_cost = world.settings.default_unit_pop_cost if world is not None else 1
    return max(0, int(template.get("population_cost", default_cost)))


def unit_cost(unit_id: str, producer: Building | None = None) -> dict[str, int]:
    """Return the resource cost for a unit type."""
    if producer is not None:
        for building_id, costs_by_unit in BUILDING_UNIT_COSTS.items():
            if building_id in producer.tags and unit_id in costs_by_unit:
                return dict(costs_by_unit[unit_id])
    template = UNIT_TEMPLATES.get(unit_id, {})
    raw_cost = template.get("cost", {})
    return {str(resource): max(0, int(amount)) for resource, amount in raw_cost.items()}


def _create_unit(world: WorldState, producer: Building, unit_id: str) -> Unit:
    """Create unit."""
    template = UNIT_TEMPLATES[unit_id]
    width, height = template["footprint"]
    spawn_pos = available_spawn_position_for(world, producer)
    return CombatUnit(
        id=world.allocate_entity_id(),
        owner=producer.owner,
        position=spawn_pos,
        footprint=Footprint(width, height),
        hp=int(template["hp"]),
        max_hp=int(template["hp"]),
        tags=_unit_tags_for(unit_id, producer.owner),
        speed=float(template["speed"]),
        attack_range=float(template["attack_range"]),
        damage=int(template["damage"]),
        attack_cooldown_ms=int(template["attack_cooldown_ms"]),
        population_cost=unit_population_cost(unit_id, world),
    )


def create_combat_unit(
    world: WorldState,
    unit_id: str,
    owner: str,
    position: WorldPosition,
) -> CombatUnit:
    """Create a combat unit from a configured template without charging resources."""
    # Enemy waves and scripted spawns need the same stats as trained units without
    # touching player resources or population reservations.
    if unit_id not in UNIT_TEMPLATES:
        raise ProductionError(f"{unit_id} has no production template")
    template = UNIT_TEMPLATES[unit_id]
    width, height = template["footprint"]
    hp = int(template["hp"])
    return CombatUnit(
        id=world.allocate_entity_id(),
        owner=owner,
        position=position,
        footprint=Footprint(width, height),
        hp=hp,
        max_hp=hp,
        tags=_unit_tags_for(unit_id, owner),
        speed=float(template["speed"]),
        attack_range=float(template["attack_range"]),
        damage=int(template["damage"]),
        attack_cooldown_ms=int(template["attack_cooldown_ms"]),
        population_cost=0 if owner != "frontier" else unit_population_cost(unit_id, world),
    )


def _unit_tags_for(unit_id: str, owner: str) -> tuple[str, ...]:
    """Return tags used to render, select, and command a unit template."""
    if owner == "frontier":
        return ("unit", unit_id, "selectable", "movable")
    if unit_id == "enemy_swordsman":
        return ("unit", "enemy_swordsman", "raider_swordsman", "enemy", "selectable", "movable")
    return ("unit", unit_id, "enemy", "selectable", "movable")


def spawn_position_for(
    producer: Building,
    world_height: int | float = DEFAULT_TERRAIN_HEIGHT,
) -> WorldPosition:
    """Return a default spawn position for a production building."""
    left, _top, width, _height = producer.bounds
    return WorldPosition(
        left + width + 42,
        terrain_layout_for_height(world_height).unit_walkable_top_y,
    )


def available_spawn_position_for(world: WorldState, producer: Building) -> WorldPosition:
    """Find a nearby unblocked spawn position."""
    return nearest_free_position(
        world,
        spawn_position_for(producer, world.settings.world_height),
    )


def _first_missing_resource(world: WorldState, cost: dict[str, int]) -> str | None:
    """Return the first resource missing from a cost."""
    for resource, amount in cost.items():
        if amount > world.resources.get(resource, 0):
            return resource
    return None


def _spend_resources(world: WorldState, cost: dict[str, int]) -> None:
    """Spend resources."""
    for resource, amount in cost.items():
        if amount <= 0:
            continue
        world.resources[resource] = world.resources.get(resource, 0) - amount

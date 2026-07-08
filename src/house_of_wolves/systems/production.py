"""Unit production helpers and system shell."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
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


# Keep first-pass military building stats in one place so placement, construction,
# production, and tests do not drift while the JSON data remains a validation source.
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


BARRACKS_SPEC = ProductionBuildingSpec(
    building_id=BARRACKS_BUILDING_ID,
    display_name="Barracks",
    footprint=Footprint(190, 135),
    hp=700,
    build_time_ms=14_000,
    cost={"wood": 100, "stone": 25},
    trainable_units=("spearman",),
)
ARCHERY_SPEC = ProductionBuildingSpec(
    building_id=ARCHERY_BUILDING_ID,
    display_name="Archery",
    footprint=Footprint(180, 125),
    hp=560,
    build_time_ms=12_000,
    cost={"wood": 90, "stone": 15},
    trainable_units=("archer",),
)
PRODUCTION_BUILDING_SPECS = {
    BARRACKS_BUILDING_ID: BARRACKS_SPEC,
    ARCHERY_BUILDING_ID: ARCHERY_SPEC,
    ARCHERY_RANGE_BUILDING_ID: ARCHERY_SPEC,
}

UNIT_TEMPLATES = {
    "settler": {
        "hp": 40,
        "speed": 92,
        "footprint": (38, 58),
        "damage": 6,
        "attack_range": 115,
        "attack_cooldown_ms": 900,
        "cost": {"wood": 20, "food": 10},
        "population_cost": 1,
    },
    "spearman": {
        "hp": 50,
        "speed": 72,
        "footprint": (38, 58),
        "damage": 10,
        "attack_range": 42,
        "attack_cooldown_ms": 1000,
        "cost": {"wood": 25, "food": 20, "iron": 5},
        "population_cost": 1,
    },
    "archer": {
        "hp": 25,
        "speed": 68,
        "footprint": (38, 58),
        "damage": 4,
        "attack_range": 210,
        "attack_cooldown_ms": 1000,
        "cost": {"wood": 45, "food": 15},
        "population_cost": 1,
    },
    "enemy_swordsman": {
        "hp": 90,
        "speed": 68,
        "footprint": (38, 58),
        "damage": 14,
        "attack_range": 42,
        "attack_cooldown_ms": 1100,
        "cost": {},
        "population_cost": 0,
    },
    "enemy_archer": {
        "hp": 35,
        "speed": 65,
        "footprint": (38, 58),
        "damage": 5,
        "attack_range": 210,
        "attack_cooldown_ms": 1200,
        "cost": {},
        "population_cost": 0,
    },
}

BUILDING_UNIT_COSTS = {
    # Huts keep their emergency/default unit prices; dedicated military buildings
    # can override the same unit template with more efficient production costs.
    BARRACKS_BUILDING_ID: {
        "spearman": {"wood": 30, "food": 15},
    },
    ARCHERY_BUILDING_ID: {
        "archer": {"wood": 45, "food": 15},
    },
    ARCHERY_RANGE_BUILDING_ID: {
        "archer": {"wood": 45, "food": 15},
    },
}


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

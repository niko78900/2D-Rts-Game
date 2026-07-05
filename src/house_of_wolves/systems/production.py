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
        "hp": 70,
        "speed": 78,
        "footprint": (38, 58),
        "damage": 12,
        "attack_range": 42,
        "attack_cooldown_ms": 950,
        "cost": {"wood": 25, "food": 20, "iron": 5},
        "population_cost": 1,
    },
}


class ProductionError(ValueError):
    """Raised when a production request cannot be fulfilled."""


@dataclass(slots=True)
class ProductionSystem:
    def update(self, world: object, dt_ms: int) -> None:
        return None


def produce_unit(world: WorldState, producer_id: EntityId, unit_id: str) -> Unit:
    """Create a unit from a building and command it to its rally point."""

    producer = world.entities.get(producer_id)
    if not isinstance(producer, Building):
        raise ProductionError("producer must be a building")
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

    missing_resource = _first_missing_resource(world, unit_cost(unit_id))
    if missing_resource is not None:
        raise ProductionError(f"Not enough {missing_resource}.")

    _spend_resources(world, unit_cost(unit_id))
    unit = _create_unit(world, producer, unit_id)
    world.add_entity(unit)

    if producer.dropoff_point is not None:
        command = make_command("move", [unit.id], target_pos=producer.dropoff_point)
        world.enqueue_command(unit.id, command)

    return unit


def unit_population_cost(unit_id: str, world: WorldState | None = None) -> int:
    template = UNIT_TEMPLATES.get(unit_id, {})
    default_cost = world.settings.default_unit_pop_cost if world is not None else 1
    return max(0, int(template.get("population_cost", default_cost)))


def unit_cost(unit_id: str) -> dict[str, int]:
    template = UNIT_TEMPLATES.get(unit_id, {})
    raw_cost = template.get("cost", {})
    return {str(resource): max(0, int(amount)) for resource, amount in raw_cost.items()}


def _create_unit(world: WorldState, producer: Building, unit_id: str) -> Unit:
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
        tags=("unit", unit_id, "selectable", "movable"),
        speed=float(template["speed"]),
        attack_range=float(template["attack_range"]),
        damage=int(template["damage"]),
        attack_cooldown_ms=int(template["attack_cooldown_ms"]),
        population_cost=unit_population_cost(unit_id, world),
    )


def spawn_position_for(
    producer: Building,
    world_height: int | float = DEFAULT_TERRAIN_HEIGHT,
) -> WorldPosition:
    left, _top, width, _height = producer.bounds
    return WorldPosition(
        left + width + 42,
        terrain_layout_for_height(world_height).unit_walkable_top_y,
    )


def available_spawn_position_for(world: WorldState, producer: Building) -> WorldPosition:
    return nearest_free_position(
        world,
        spawn_position_for(producer, world.settings.world_height),
    )


def _first_missing_resource(world: WorldState, cost: dict[str, int]) -> str | None:
    for resource, amount in cost.items():
        if amount > world.resources.get(resource, 0):
            return resource
    return None


def _spend_resources(world: WorldState, cost: dict[str, int]) -> None:
    for resource, amount in cost.items():
        if amount <= 0:
            continue
        world.resources[resource] = world.resources.get(resource, 0) - amount

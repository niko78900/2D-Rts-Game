"""Unit production helpers and system shell."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.unit import Unit
from house_of_wolves.systems.commands import make_command
from house_of_wolves.world.collision import nearest_free_position
from house_of_wolves.world.world import WorldState

UNIT_TEMPLATES = {
    "settler": {"hp": 40, "speed": 92, "footprint": (38, 58)},
    "spearman": {"hp": 70, "speed": 78, "footprint": (38, 58)},
}


class ProductionError(ValueError):
    """Raised when a production request cannot be fulfilled."""


@dataclass(slots=True)
class ProductionSystem:
    def update(self, world: object, dt_ms: int) -> None:
        return None


def produce_unit(world: WorldState, producer_id: EntityId, unit_id: str) -> Unit:
    """Create a unit from a building and command it to the building drop-off point."""

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

    unit = _create_unit(world, producer, unit_id)
    world.add_entity(unit)

    if producer.dropoff_point is not None:
        command = make_command("move", [unit.id], target_pos=producer.dropoff_point)
        world.enqueue_command(unit.id, command)

    return unit


def _create_unit(world: WorldState, producer: Building, unit_id: str) -> Unit:
    template = UNIT_TEMPLATES[unit_id]
    width, height = template["footprint"]
    spawn_pos = available_spawn_position_for(world, producer)
    return Unit(
        id=world.allocate_entity_id(),
        owner=producer.owner,
        position=spawn_pos,
        footprint=Footprint(width, height),
        hp=int(template["hp"]),
        tags=("unit", unit_id, "selectable", "movable"),
        speed=float(template["speed"]),
    )


def spawn_position_for(producer: Building) -> WorldPosition:
    left, _top, width, _height = producer.bounds
    return WorldPosition(left + width + 42, producer.position.y)


def available_spawn_position_for(world: WorldState, producer: Building) -> WorldPosition:
    return nearest_free_position(world, spawn_position_for(producer))

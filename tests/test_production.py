from __future__ import annotations

import pytest

from house_of_wolves.entities.unit import Unit
from house_of_wolves.systems.production import (
    ProductionError,
    available_spawn_position_for,
    produce_unit,
    spawn_position_for,
)
from house_of_wolves.world.collision import UNIT_COLLISION_RADIUS, nearest_unit_distance
from house_of_wolves.world.demo import create_demo_world


def test_produce_unit_adds_unit_and_sends_it_to_building_dropoff_point() -> None:
    """Verify that produce unit adds unit and sends it to building dropoff point."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    original_unit_count = sum("unit" in entity.tags for entity in world.entities.values())
    expected_spawn = available_spawn_position_for(world, hut)
    starting_wood = world.resources["wood"]
    starting_population = world.current_population

    unit = produce_unit(world, hut.id, "settler")
    command = world.command_queues[unit.id].peek()

    assert isinstance(unit, Unit)
    assert "settler" in unit.tags
    assert unit.position == expected_spawn
    assert nearest_unit_distance(world, unit.position, ignore_id=unit.id) >= UNIT_COLLISION_RADIUS
    assert (
        sum("unit" in entity.tags for entity in world.entities.values())
        == original_unit_count + 1
    )
    assert world.resources["wood"] == starting_wood - 20
    assert world.current_population == starting_population + unit.population_cost
    assert command is not None
    assert command.type == "move"
    assert command.target_pos == hut.dropoff_point


def test_produce_unit_rejects_units_not_trained_by_building() -> None:
    """Verify that produce unit rejects units not trained by building."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)

    with pytest.raises(ProductionError):
        produce_unit(world, hut.id, "archer")


def test_produce_unit_rejects_when_population_cap_is_full() -> None:
    """Verify that produce unit rejects when population cap is full."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    world.resources["wood"] = 1000
    while world.current_population < world.max_population:
        produce_unit(world, hut.id, "settler")
    unit_count = sum("unit" in entity.tags for entity in world.entities.values())

    with pytest.raises(ProductionError, match="Population cap reached"):
        produce_unit(world, hut.id, "settler")

    assert world.current_population == world.max_population
    assert sum("unit" in entity.tags for entity in world.entities.values()) == unit_count


def test_produce_unit_rejects_when_resources_are_missing() -> None:
    """Verify that produce unit rejects when resources are missing."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    world.resources["wood"] = 0

    with pytest.raises(ProductionError, match="Not enough wood"):
        produce_unit(world, hut.id, "settler")


def test_available_spawn_position_moves_away_from_occupied_exit() -> None:
    """Verify that available spawn position moves away from occupied exit."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    blocker = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    world.update_entity_position(blocker.id, spawn_position_for(hut))

    assert available_spawn_position_for(world, hut) != spawn_position_for(hut)

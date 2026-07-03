from __future__ import annotations

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.world.demo import create_demo_world


def test_movement_consumes_move_command_and_updates_spatial_hash() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    original_bounds = unit.bounds
    target = WorldPosition(unit.position.x + 400, unit.position.y)
    command = make_command("move", [unit.id], target_pos=target)

    world.enqueue_command(unit.id, command)
    MovementSystem().update(world, 500)

    assert unit.position.x > target.x - 400
    assert unit.id in world.spatial_hash.query(unit.bounds)
    assert world.command_queues[unit.id].peek() == command

    MovementSystem().update(world, 5000)

    assert unit.position == target
    assert world.command_queues[unit.id].peek() is None
    assert unit.state == "idle"
    assert unit.id not in world.spatial_hash.query(original_bounds)

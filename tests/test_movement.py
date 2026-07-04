from __future__ import annotations

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.entities.unit import Unit
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.systems.pathing import DETOUR_MARGIN
from house_of_wolves.world.collision import (
    RESOURCE_OBSTACLE_CLEARANCE,
    UNIT_CLIP_FRACTION,
    UNIT_COLLISION_RADIUS,
    UNIT_HITBOX_RADIUS,
    first_hard_obstacle_on_segment,
    position_blocked_by_hard_obstacle,
    resolve_unit_position,
    unit_distance,
)
from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.terrain import UNIT_WALKABLE_TOP_Y, terrain_layout_for_height


def test_unit_collision_allows_one_third_hitbox_clipping() -> None:
    assert UNIT_CLIP_FRACTION == 1 / 3
    assert UNIT_COLLISION_RADIUS == UNIT_HITBOX_RADIUS * (1 - UNIT_CLIP_FRACTION)


def test_movement_consumes_move_command_and_updates_spatial_hash() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    original_bounds = unit.bounds
    target = WorldPosition(unit.position.x + 260, unit.position.y)
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


def test_units_resolve_around_same_destination_instead_of_overlapping() -> None:
    world = create_demo_world()
    units = [entity for entity in world.entities.values() if "unit" in entity.tags][:2]
    target = WorldPosition(900, 500)
    movement = MovementSystem()

    for unit in units:
        world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=target))

    for _ in range(100):
        movement.update(world, 100)

    assert unit_distance(units[0], units[1]) >= UNIT_COLLISION_RADIUS - 0.001
    assert all(
        unit_distance_from_position(unit, target) <= movement.shared_destination_radius
        for unit in units
    )


def test_move_targets_inside_building_lane_stop_at_unit_lane_edge() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    movement = MovementSystem()
    target = WorldPosition(unit.position.x + 120, UNIT_WALKABLE_TOP_Y - 80)

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=target))
    for _ in range(50):
        movement.update(world, 100)

    assert unit.position.y >= UNIT_WALKABLE_TOP_Y
    assert world.command_queues[unit.id].peek() is None


def test_move_targets_below_ui_stop_at_map_bottom() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    movement = MovementSystem()
    map_bottom = terrain_layout_for_height(world.settings.world_height).unit_walkable_bottom_y
    target = WorldPosition(unit.position.x + 80, world.settings.world_height + 200)

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=target))
    for _ in range(80):
        movement.update(world, 100)

    assert unit.position.y <= map_bottom
    assert world.command_queues[unit.id].peek() is None


def test_resource_nodes_block_direct_unit_movement() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    movement = MovementSystem(unreachable_timeout_ms=10_000)
    world.update_entity_position(
        unit.id,
        WorldPosition(mine.bounds[0] - 90, mine.position.y),
    )

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=mine.position))
    for _ in range(100):
        movement.update(world, 100)
        if world.command_queues[unit.id].peek() is None:
            break

    assert not position_blocked_by_hard_obstacle(world, unit.position, ignore_id=unit.id)
    assert world.command_queues[unit.id].peek() is None


def test_units_steer_around_resource_nodes_when_target_is_behind_them() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    movement = MovementSystem(unreachable_timeout_ms=10_000)
    world.update_entity_position(
        unit.id,
        WorldPosition(mine.bounds[0] - 120, mine.position.y),
    )
    target = WorldPosition(mine.bounds[0] + mine.bounds[2] + 140, mine.position.y)

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=target))
    for _ in range(30):
        movement.update(world, 100)

    assert not position_blocked_by_hard_obstacle(world, unit.position, ignore_id=unit.id)
    assert unit.position.y != mine.position.y


def test_move_command_inserts_detour_waypoints_around_resource_blocker() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    left, _top, width, _height = mine.blocking_bounds
    start = WorldPosition(left - 150, mine.position.y)
    target = WorldPosition(left + width + 150, mine.position.y)
    movement = MovementSystem(unreachable_timeout_ms=10_000)
    world.update_entity_position(unit.id, start)

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=target))
    movement.update(world, 16)

    commands = world.command_queues[unit.id].commands
    assert len(commands) >= 2
    assert commands[0].payload["path_detour"] is True
    assert commands[0].target_pos is not None
    assert commands[0].target_pos.y != target.y
    _left, top, _width, height = mine.blocking_bounds
    bottom = top + height
    detour_margin = DETOUR_MARGIN + RESOURCE_OBSTACLE_CLEARANCE + 0.001
    assert (
        abs(commands[0].target_pos.y - top) <= detour_margin
        or abs(commands[0].target_pos.y - bottom) <= detour_margin
    )
    assert commands[-1].target_pos == target
    assert (
        first_hard_obstacle_on_segment(
            world,
            unit.position,
            commands[0].target_pos,
            ignore_id=unit.id,
        )
        is None
    )


def test_move_target_inside_resource_blocker_is_projected_outside() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    world.update_entity_position(
        unit.id,
        WorldPosition(mine.blocking_bounds[0] - 150, mine.position.y),
    )

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=mine.position))
    MovementSystem(unreachable_timeout_ms=10_000).update(world, 16)

    final_target = world.command_queues[unit.id].commands[-1].target_pos
    assert final_target is not None
    assert final_target != mine.position
    assert not position_blocked_by_hard_obstacle(world, final_target, ignore_id=unit.id)


def test_unit_reaches_target_behind_resource_using_detour_waypoints() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    left, _top, width, _height = mine.blocking_bounds
    start = WorldPosition(left - 180, mine.position.y)
    target = WorldPosition(left + width + 180, mine.position.y)
    movement = MovementSystem(unreachable_timeout_ms=10_000)
    unit.speed = 180
    world.update_entity_position(unit.id, start)

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=target))
    for _ in range(100):
        movement.update(world, 100)
        if world.command_queues[unit.id].peek() is None:
            break

    assert world.command_queues[unit.id].peek() is None
    assert unit_distance_from_position(unit, target) <= movement.arrival_radius + 1
    assert not position_blocked_by_hard_obstacle(world, unit.position, ignore_id=unit.id)


def test_group_move_finishes_near_slot_without_exact_pixel_snap() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    original_position = unit.position
    target = WorldPosition(unit.position.x + 10, unit.position.y)
    movement = MovementSystem()

    world.enqueue_command(
        unit.id,
        make_command("move", [unit.id], target_pos=target, group_move=True, formation_index=0),
    )
    movement.update(world, 16)

    assert unit.position == original_position
    assert world.command_queues[unit.id].peek() is None
    assert unit.state == "idle"


def test_unreachable_move_command_times_out_at_closest_reached_position() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    target = WorldPosition(unit.position.x + 220, unit.position.y)
    movement = MovementSystem(unreachable_timeout_ms=100)

    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=target))
    movement.update(world, 500)

    closest_reached = unit.position
    unit.speed = 0
    movement.update(world, 50)

    assert world.command_queues[unit.id].peek() is not None

    movement.update(world, 60)

    assert unit.position == closest_reached
    assert unit.state == "idle"
    assert world.command_queues[unit.id].peek() is None


def test_moving_unit_shoves_blocking_unit_forward() -> None:
    world = create_demo_world()
    mover, blocker, bystander = [
        entity for entity in world.entities.values() if "unit" in entity.tags
    ][:3]
    movement = MovementSystem()

    world.update_entity_position(mover.id, WorldPosition(360, 500))
    world.update_entity_position(blocker.id, WorldPosition(392, 500))
    world.update_entity_position(bystander.id, WorldPosition(1000, 500))
    original_blocker_position = blocker.position

    world.enqueue_command(
        mover.id,
        make_command("move", [mover.id], target_pos=WorldPosition(540, 500)),
    )
    movement.update(world, 500)

    shove_distance = unit_distance_from_position(blocker, original_blocker_position)
    assert blocker.position.x > original_blocker_position.x
    assert 0 < shove_distance <= movement.max_shove_px + 3
    assert world.command_queues[blocker.id].peek() is None


def test_repeated_friendly_collisions_enable_temporary_ghosting_without_canceling_move() -> None:
    world = create_demo_world()
    mover, blocker, second_blocker = [
        entity for entity in world.entities.values() if "unit" in entity.tags
    ][:3]
    movement = MovementSystem(
        max_shove_px=0,
        unreachable_timeout_ms=100_000,
        friendly_ghost_collision_limit=3,
        friendly_ghost_area_px=80,
        friendly_ghost_duration_ms=600,
    )

    world.update_entity_position(mover.id, WorldPosition(360, 500))
    world.update_entity_position(blocker.id, WorldPosition(366, 500))
    world.update_entity_position(second_blocker.id, WorldPosition(366, 506))
    world.enqueue_command(
        mover.id,
        make_command("move", [mover.id], target_pos=WorldPosition(620, 500)),
    )

    for _ in range(8):
        movement.update(world, 16)
        progress = movement._progress_by_entity.get(mover.id)
        if progress is not None and progress.friendly_ghost_until_ms > world.elapsed_ms:
            break

    progress = movement._progress_by_entity[mover.id]
    assert progress.friendly_ghost_until_ms > world.elapsed_ms
    assert world.command_queues[mover.id].peek() is not None


def test_friendly_ghosting_passes_same_team_units_but_not_enemy_units() -> None:
    world = create_demo_world()
    mover, friendly_blocker = [
        entity for entity in world.entities.values() if "unit" in entity.tags
    ][:2]
    enemy = Unit(
        id=world.allocate_entity_id(),
        owner="wolves",
        position=WorldPosition(430, 500),
        footprint=Footprint(38, 58),
        hp=60,
        tags=("unit", "enemy", "movable"),
        speed=70,
    )
    world.update_entity_position(mover.id, WorldPosition(360, 500))
    world.update_entity_position(friendly_blocker.id, WorldPosition(390, 500))
    world.add_entity(enemy)

    ghosted = {mover.id}
    friendly_result = resolve_unit_position(
        world,
        mover.id,
        friendly_blocker.position,
        current=mover.position,
        friendly_ghost_ids=ghosted,
    )
    enemy_result = resolve_unit_position(
        world,
        mover.id,
        enemy.position,
        current=mover.position,
        friendly_ghost_ids=ghosted,
    )

    assert friendly_result == friendly_blocker.position
    assert enemy_result != enemy.position


def test_overlapping_idle_units_are_pushed_apart_on_update() -> None:
    world = create_demo_world()
    units = [entity for entity in world.entities.values() if "unit" in entity.tags][:2]

    world.update_entity_position(units[1].id, units[0].position)
    assert unit_distance(units[0], units[1]) == 0

    MovementSystem().update(world, 16)

    first_separation = unit_distance(units[0], units[1])
    assert 0 < first_separation < UNIT_COLLISION_RADIUS

    for _ in range(8):
        MovementSystem().update(world, 16)

    assert unit_distance(units[0], units[1]) >= UNIT_COLLISION_RADIUS - 0.001


def unit_distance_from_position(unit: object, position: WorldPosition) -> float:
    return ((unit.position.x - position.x) ** 2 + (unit.position.y - position.y) ** 2) ** 0.5

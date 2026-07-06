"""Lightweight unit collision and placement helpers."""

from __future__ import annotations

from math import cos, hypot, pi, sin
from typing import Any

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.core.performance import add_collision_checks
from house_of_wolves.world.terrain import clamp_unit_position_to_walkable_lane_for_height
from house_of_wolves.world.world import WorldState

UNIT_HITBOX_RADIUS = 22.0
UNIT_CLIP_FRACTION = 1 / 3
UNIT_COLLISION_RADIUS = UNIT_HITBOX_RADIUS * (1 - UNIT_CLIP_FRACTION)
MAX_COLLISION_ADJUSTMENT = 5.0
MAX_SEPARATION_PUSH = 2.0
SHOVE_INFLUENCE_RADIUS = UNIT_COLLISION_RADIUS * 1.35
MAX_SHOVE_PUSH = 4.0
HARD_OBSTACLE_CLEARANCE = UNIT_HITBOX_RADIUS
RESOURCE_OBSTACLE_CLEARANCE = 4.0
MAX_LOCAL_SEPARATION_NEIGHBORS = 12
MAX_LOCAL_SHOVE_NEIGHBORS = 16
_EPSILON = 0.0001


def is_unit(entity: object) -> bool:
    return "unit" in getattr(entity, "tags", ())


def is_hard_obstacle(entity: object) -> bool:
    tags = set(getattr(entity, "tags", ()))
    return getattr(entity, "alive", False) and bool(tags & {"building", "resource"})


def blocking_bounds_for_entity(entity: object) -> tuple[float, float, float, float]:
    """Return the movement-blocking bounds for an entity."""

    blocking_bounds = getattr(entity, "blocking_bounds", None)
    if blocking_bounds is not None:
        return blocking_bounds
    return entity.bounds


def unit_distance(first: Any, second: Any) -> float:
    first_pos = first.position
    second_pos = second.position
    return hypot(first_pos.x - second_pos.x, first_pos.y - second_pos.y)


def occupied_by_unit(
    world: WorldState,
    position: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
    source_id: EntityId | None = None,
    friendly_ghost_ids: set[EntityId] | None = None,
    min_distance: float = UNIT_COLLISION_RADIUS,
) -> bool:
    nearest = nearest_unit_distance(
        world,
        position,
        ignore_id=ignore_id,
        source_id=source_id,
        friendly_ghost_ids=friendly_ghost_ids,
        query_radius=max(min_distance + UNIT_HITBOX_RADIUS, min_distance * 2.0),
    )
    return nearest is not None and nearest < min_distance


def nearest_unit_distance(
    world: WorldState,
    position: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
    source_id: EntityId | None = None,
    friendly_ghost_ids: set[EntityId] | None = None,
    query_radius: float | None = None,
) -> float | None:
    nearest: float | None = None
    source_id = source_id or ignore_id
    candidates = (
        _unit_entities_near_position(world, position, query_radius)
        if query_radius is not None
        else (entity for entity in world.entities.values() if is_unit(entity))
    )
    checked = 0
    for entity in candidates:
        checked += 1
        if _skip_unit_collision(
            world,
            source_id,
            entity,
            ignore_id=ignore_id,
            friendly_ghost_ids=friendly_ghost_ids,
        ):
            continue
        distance = hypot(entity.position.x - position.x, entity.position.y - position.y)
        if nearest is None or distance < nearest:
            nearest = distance
    add_collision_checks(world, checked)
    return nearest


def resolve_unit_position(
    world: WorldState,
    entity_id: EntityId,
    desired: WorldPosition,
    *,
    current: WorldPosition | None = None,
    min_distance: float = UNIT_COLLISION_RADIUS,
    max_adjustment: float = MAX_COLLISION_ADJUSTMENT,
    friendly_ghost_ids: set[EntityId] | None = None,
) -> WorldPosition:
    """Softly slide a moving unit away from occupied pixels without teleporting."""

    desired = _clamp_for_world(world, desired)
    entity = world.entities.get(entity_id)
    origin = _clamp_for_world(
        world,
        current or (entity.position if entity is not None else desired),
    )
    desired = _resolve_hard_obstacles(
        world,
        entity_id,
        origin,
        desired,
        max_adjustment=max_adjustment,
    )
    blocker, distance = _closest_overlapping_unit(
        world,
        entity_id,
        desired,
        friendly_ghost_ids=friendly_ghost_ids,
        min_distance=min_distance,
    )
    if blocker is None:
        return desired

    adjusted = desired
    for attempt in range(2):
        if attempt > 0:
            blocker, distance = _closest_overlapping_unit(
                world,
                entity_id,
                adjusted,
                friendly_ghost_ids=friendly_ghost_ids,
                min_distance=min_distance,
            )
        if blocker is None:
            return adjusted

        normal_x, normal_y = _collision_normal(
            adjusted,
            blocker.position,
            entity_id,
            blocker.id,
            origin,
        )
        move_x = adjusted.x - origin.x
        move_y = adjusted.y - origin.y
        move_length = hypot(move_x, move_y)
        inward_amount = move_x * normal_x + move_y * normal_y
        if move_length > _EPSILON and inward_amount < 0:
            slide_x = move_x - normal_x * inward_amount
            slide_y = move_y - normal_y * inward_amount
            slide_length = hypot(slide_x, slide_y)
            if slide_length <= _EPSILON:
                tangent_x, tangent_y = _slide_tangent(
                    normal_x,
                    normal_y,
                    entity_id,
                    blocker.id,
                )
                slide_length = min(move_length, max_adjustment)
                slide_x = tangent_x * slide_length
                slide_y = tangent_y * slide_length
            elif slide_length > move_length:
                scale = move_length / slide_length
                slide_x *= scale
                slide_y *= scale
            adjusted = WorldPosition(origin.x + slide_x, origin.y + slide_y)
        else:
            overlap = min_distance - distance if distance > _EPSILON else min_distance
            push = min(max_adjustment, overlap)
            adjusted = WorldPosition(
                adjusted.x + normal_x * push,
                adjusted.y + normal_y * push,
            )
            adjusted = _clamp_for_world(world, adjusted)
        adjusted = _resolve_hard_obstacles(
            world,
            entity_id,
            origin,
            adjusted,
            max_adjustment=max_adjustment,
        )

    return _clamp_for_world(world, adjusted)


def separate_overlapping_units(
    world: WorldState,
    *,
    min_distance: float = UNIT_COLLISION_RADIUS,
    max_push: float = MAX_SEPARATION_PUSH,
    iterations: int = 1,
    friendly_ghost_ids: set[EntityId] | None = None,
) -> None:
    """Push overlapping units apart so crowds slide instead of locking together."""

    friendly_ghost_ids = friendly_ghost_ids or set()
    for _ in range(iterations):
        units = sorted(
            (entity for entity in world.entities.values() if is_unit(entity)),
            key=lambda entity: int(entity.id),
        )
        offsets: dict[EntityId, list[float]] = {entity.id: [0.0, 0.0] for entity in units}
        processed_pairs: set[tuple[EntityId, EntityId]] = set()
        for first in units:
            nearby = _nearby_units(
                world,
                first.position,
                min_distance + UNIT_HITBOX_RADIUS,
                ignore_id=first.id,
                max_count=MAX_LOCAL_SEPARATION_NEIGHBORS,
            )
            for second in nearby:
                pair = (
                    min(first.id, second.id, key=int),
                    max(first.id, second.id, key=int),
                )
                if pair in processed_pairs:
                    continue
                processed_pairs.add(pair)
                _add_pair_separation(
                    offsets,
                    first,
                    second,
                    min_distance,
                    max_push,
                    friendly_ghost_ids,
                )

        moved = False
        for unit in units:
            dx, dy = offsets[unit.id]
            length = hypot(dx, dy)
            if length <= _EPSILON:
                continue
            if length > max_push:
                scale = max_push / length
                dx *= scale
                dy *= scale
            target = _clamp_for_world(
                world,
                WorldPosition(unit.position.x + dx, unit.position.y + dy),
            )
            world.update_entity_position(
                unit.id,
                resolve_unit_position(
                    world,
                    unit.id,
                    target,
                    current=unit.position,
                    max_adjustment=max_push,
                    friendly_ghost_ids=friendly_ghost_ids,
                ),
            )
            moved = True
        if not moved:
            return


def shove_units_from_movement(
    world: WorldState,
    mover_id: EntityId,
    origin: WorldPosition,
    desired: WorldPosition,
    *,
    influence_radius: float = SHOVE_INFLUENCE_RADIUS,
    max_push: float = MAX_SHOVE_PUSH,
    friendly_ghost_ids: set[EntityId] | None = None,
) -> None:
    """Nudge units in front of a mover so crowds give way under pressure."""

    move_x = desired.x - origin.x
    move_y = desired.y - origin.y
    move_length = hypot(move_x, move_y)
    if move_length <= _EPSILON:
        return

    direction_x = move_x / move_length
    direction_y = move_y / move_length
    mover = world.entities.get(mover_id)
    friendly_ghost_ids = friendly_ghost_ids or set()
    shove_candidates: list[tuple[float, Any, float, float]] = []
    for entity in _units_for_bounds(
        world,
        _segment_query_bounds(origin, desired, influence_radius),
    ):
        if entity.id == mover_id:
            continue
        if (
            mover is not None
            and _same_owner(mover, entity)
            and (mover_id in friendly_ghost_ids or entity.id in friendly_ghost_ids)
        ):
            continue
        projection, side_distance = _movement_segment_distance(
            origin,
            direction_x,
            direction_y,
            move_length,
            entity.position,
        )
        if projection < -influence_radius or projection > move_length + influence_radius:
            continue
        if side_distance >= influence_radius:
            continue

        pressure = 1.0 - (side_distance / influence_radius)
        side_x, side_y = _shove_side_direction(
            origin,
            direction_x,
            direction_y,
            projection,
            move_length,
            entity,
            mover_id,
        )
        push_distance = min(max_push, move_length * 0.55) * pressure
        push_x = direction_x * 0.78 + side_x * 0.22
        push_y = direction_y * 0.78 + side_y * 0.22
        push_length = hypot(push_x, push_y)
        if push_length <= _EPSILON:
            continue
        shove_candidates.append(
            (
                projection,
                entity,
                (push_x / push_length) * push_distance,
                (push_y / push_length) * push_distance,
            )
        )
        if len(shove_candidates) >= MAX_LOCAL_SHOVE_NEIGHBORS:
            break

    for _projection, entity, push_x, push_y in sorted(
        shove_candidates,
        key=lambda item: item[0],
    ):
        target = _clamp_for_world(
            world,
            WorldPosition(entity.position.x + push_x, entity.position.y + push_y)
        )
        world.update_entity_position(
            entity.id,
            resolve_unit_position(
                world,
                entity.id,
                target,
                current=entity.position,
                max_adjustment=max_push,
                friendly_ghost_ids=friendly_ghost_ids,
            ),
        )


def _add_pair_separation(
    offsets: dict[EntityId, list[float]],
    first: Any,
    second: Any,
    min_distance: float,
    max_push: float,
    friendly_ghost_ids: set[EntityId],
) -> None:
    if _same_owner(first, second) and (
        first.id in friendly_ghost_ids or second.id in friendly_ghost_ids
    ):
        return

    dx = second.position.x - first.position.x
    dy = second.position.y - first.position.y
    distance = hypot(dx, dy)
    if distance >= min_distance:
        return

    if distance == 0:
        direction_x, direction_y = _deterministic_pair_direction(first.id, second.id)
    else:
        direction_x = dx / distance
        direction_y = dy / distance

    push = min((min_distance - distance) / 2, max_push)
    offsets[first.id][0] -= direction_x * push
    offsets[first.id][1] -= direction_y * push
    offsets[second.id][0] += direction_x * push
    offsets[second.id][1] += direction_y * push


def _movement_segment_distance(
    origin: WorldPosition,
    direction_x: float,
    direction_y: float,
    move_length: float,
    position: WorldPosition,
) -> tuple[float, float]:
    rel_x = position.x - origin.x
    rel_y = position.y - origin.y
    projection = rel_x * direction_x + rel_y * direction_y
    clamped_projection = min(max(projection, 0.0), move_length)
    closest_x = origin.x + direction_x * clamped_projection
    closest_y = origin.y + direction_y * clamped_projection
    return projection, hypot(position.x - closest_x, position.y - closest_y)


def _shove_side_direction(
    origin: WorldPosition,
    direction_x: float,
    direction_y: float,
    projection: float,
    move_length: float,
    entity: Any,
    mover_id: EntityId,
) -> tuple[float, float]:
    clamped_projection = min(max(projection, 0.0), move_length)
    closest_x = origin.x + direction_x * clamped_projection
    closest_y = origin.y + direction_y * clamped_projection
    side_x = entity.position.x - closest_x
    side_y = entity.position.y - closest_y
    side_length = hypot(side_x, side_y)
    if side_length > _EPSILON:
        return side_x / side_length, side_y / side_length
    return _slide_tangent(direction_x, direction_y, mover_id, entity.id)


def _closest_overlapping_unit(
    world: WorldState,
    entity_id: EntityId,
    position: WorldPosition,
    *,
    friendly_ghost_ids: set[EntityId] | None,
    min_distance: float,
) -> tuple[Any | None, float]:
    closest: Any | None = None
    closest_distance = min_distance
    checked = 0
    for entity in _unit_entities_near_position(
        world,
        position,
        min_distance + UNIT_HITBOX_RADIUS,
    ):
        checked += 1
        if _skip_unit_collision(
            world,
            entity_id,
            entity,
            ignore_id=entity_id,
            friendly_ghost_ids=friendly_ghost_ids,
        ):
            continue
        distance = hypot(entity.position.x - position.x, entity.position.y - position.y)
        if distance < closest_distance:
            closest = entity
            closest_distance = distance
    add_collision_checks(world, checked)
    return closest, closest_distance


def _collision_normal(
    position: WorldPosition,
    blocker_position: WorldPosition,
    entity_id: EntityId,
    blocker_id: EntityId,
    origin: WorldPosition,
) -> tuple[float, float]:
    dx = position.x - blocker_position.x
    dy = position.y - blocker_position.y
    distance = hypot(dx, dy)
    if distance > _EPSILON:
        return dx / distance, dy / distance

    origin_dx = origin.x - blocker_position.x
    origin_dy = origin.y - blocker_position.y
    origin_distance = hypot(origin_dx, origin_dy)
    if origin_distance > _EPSILON:
        return origin_dx / origin_distance, origin_dy / origin_distance

    return _deterministic_pair_direction(entity_id, blocker_id)


def _slide_tangent(
    normal_x: float,
    normal_y: float,
    entity_id: EntityId,
    blocker_id: EntityId,
) -> tuple[float, float]:
    side = 1.0 if int(entity_id) < int(blocker_id) else -1.0
    return -normal_y * side, normal_x * side


def _deterministic_pair_direction(
    first_id: EntityId,
    second_id: EntityId,
) -> tuple[float, float]:
    first_value = int(first_id)
    second_value = int(second_id)
    low = min(first_value, second_value)
    high = max(first_value, second_value)
    angle = (((low * 73856093) ^ (high * 19349663)) % 360) * pi / 180
    direction = (cos(angle), sin(angle))
    if first_value <= second_value:
        return direction
    return -direction[0], -direction[1]


def nearest_free_position(
    world: WorldState,
    desired: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
    min_distance: float = UNIT_COLLISION_RADIUS,
) -> WorldPosition:
    """Find a deterministic nearby unoccupied position around a desired point."""

    desired = _clamp_for_world(world, desired)
    if (
        not occupied_by_unit(world, desired, ignore_id=ignore_id, min_distance=min_distance)
        and not position_blocked_by_hard_obstacle(world, desired, ignore_id=ignore_id)
    ):
        return desired

    for radius in range(round(min_distance), 280, round(min_distance)):
        for dx, dy in _ring_offsets(radius):
            candidate = _clamp_for_world(
                world,
                WorldPosition(desired.x + dx, desired.y + dy)
            )
            if not occupied_by_unit(
                world,
                candidate,
                ignore_id=ignore_id,
                min_distance=min_distance,
            ) and not position_blocked_by_hard_obstacle(
                world,
                candidate,
                ignore_id=ignore_id,
            ):
                return candidate
    return desired


def position_blocked_by_hard_obstacle(
    world: WorldState,
    position: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
    clearance: float = HARD_OBSTACLE_CLEARANCE,
) -> bool:
    return _hard_obstacle_at_position(
        world,
        position,
        ignore_id=ignore_id,
        clearance=clearance,
    ) is not None


def project_position_out_of_hard_obstacles(
    world: WorldState,
    position: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
    clearance: float = HARD_OBSTACLE_CLEARANCE,
) -> WorldPosition:
    """Move a target to the nearest valid point outside hard obstacle blockers."""

    adjusted = _clamp_for_world(world, position)
    for _ in range(6):
        obstacle = _hard_obstacle_at_position(
            world,
            adjusted,
            ignore_id=ignore_id,
            clearance=clearance,
        )
        if obstacle is None:
            return adjusted
        adjusted = _clamp_for_world(
            world,
            _nearest_point_outside_rect(
                adjusted,
                _inflated_obstacle_rect(obstacle, clearance=clearance),
            ),
        )

    return nearest_free_position(
        world,
        adjusted,
        ignore_id=ignore_id,
        min_distance=max(1.0, clearance),
    )


def first_hard_obstacle_on_segment(
    world: WorldState,
    origin: WorldPosition,
    desired: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
    clearance: float = HARD_OBSTACLE_CLEARANCE,
) -> tuple[Any, tuple[float, float, float, float]] | None:
    """Return the first hard blocker crossed by a unit-sized movement segment."""

    collision = _first_hard_obstacle_collision(
        world,
        ignore_id,
        origin,
        desired,
        clearance=clearance,
    )
    if collision is None:
        return None
    obstacle, inflated_rect, _normal_x, _normal_y, _entry_t = collision
    return obstacle, inflated_rect


def _ring_offsets(radius: int) -> tuple[tuple[float, float], ...]:
    return (
        (radius, 0),
        (-radius, 0),
        (0, radius),
        (0, -radius),
        (radius, radius),
        (radius, -radius),
        (-radius, radius),
        (-radius, -radius),
    )


def _clamp_for_world(world: WorldState, position: WorldPosition) -> WorldPosition:
    return clamp_unit_position_to_walkable_lane_for_height(
        position,
        world.settings.world_height,
    )


def _resolve_hard_obstacles(
    world: WorldState,
    entity_id: EntityId,
    origin: WorldPosition,
    desired: WorldPosition,
    *,
    max_adjustment: float,
) -> WorldPosition:
    adjusted = desired
    for _ in range(3):
        collision = _first_hard_obstacle_collision(world, entity_id, origin, adjusted)
        if collision is None:
            return adjusted
        _blocker, inflated_rect, normal_x, normal_y, entry_t = collision
        if _point_in_rect(origin, inflated_rect):
            adjusted = _clamp_for_world(world, _nearest_point_outside_rect(origin, inflated_rect))
            continue
        move_x = adjusted.x - origin.x
        move_y = adjusted.y - origin.y
        move_length = hypot(move_x, move_y)
        if move_length <= _EPSILON:
            adjusted = _nearest_point_outside_rect(adjusted, inflated_rect)
            continue

        boundary_t = max(0.0, entry_t - 0.02)
        base = WorldPosition(origin.x + move_x * boundary_t, origin.y + move_y * boundary_t)
        inward_amount = move_x * normal_x + move_y * normal_y
        slide_x = move_x - normal_x * inward_amount
        slide_y = move_y - normal_y * inward_amount
        slide_length = hypot(slide_x, slide_y)
        if slide_length <= _EPSILON:
            candidates = _perpendicular_slide_candidates(
                world,
                entity_id,
                base,
                normal_x,
                normal_y,
                adjusted,
                max_adjustment,
            )
            if candidates:
                adjusted = candidates[0]
                continue
            adjusted = _nearest_point_outside_rect(base, inflated_rect)
            continue

        remaining = move_length * max(0.0, 1.0 - boundary_t)
        slide_distance = min(max_adjustment, remaining)
        candidate = _clamp_for_world(
            world,
            WorldPosition(
                base.x + (slide_x / slide_length) * slide_distance,
                base.y + (slide_y / slide_length) * slide_distance,
            ),
        )
        if not position_blocked_by_hard_obstacle(world, candidate, ignore_id=entity_id):
            adjusted = candidate
            continue
        adjusted = _nearest_point_outside_rect(base, inflated_rect)
    return _clamp_for_world(world, adjusted)


def _first_hard_obstacle_collision(
    world: WorldState,
    ignore_id: EntityId | None,
    origin: WorldPosition,
    desired: WorldPosition,
    *,
    clearance: float = HARD_OBSTACLE_CLEARANCE,
) -> tuple[Any, tuple[float, float, float, float], float, float, float] | None:
    first_collision: (
        tuple[Any, tuple[float, float, float, float], float, float, float] | None
    ) = None
    first_t = 2.0
    checked = 0
    for obstacle in _hard_obstacles_for_bounds(
        world,
        _segment_query_bounds(origin, desired, clearance + UNIT_HITBOX_RADIUS),
        ignore_id=ignore_id,
    ):
        checked += 1
        inflated_rect = _inflated_obstacle_rect(obstacle, clearance=clearance)
        if _point_in_rect(desired, inflated_rect):
            collision = _segment_rect_entry(origin, desired, inflated_rect)
            if collision is None:
                normal_x, normal_y = _nearest_rect_normal(desired, inflated_rect)
                entry_t = 0.0
            else:
                entry_t, normal_x, normal_y = collision
            if entry_t < first_t:
                first_t = entry_t
                first_collision = (obstacle, inflated_rect, normal_x, normal_y, entry_t)
            continue
        collision = _segment_rect_entry(origin, desired, inflated_rect)
        if collision is None:
            continue
        entry_t, normal_x, normal_y = collision
        if 0.0 <= entry_t <= 1.0 and entry_t < first_t:
            first_t = entry_t
            first_collision = (obstacle, inflated_rect, normal_x, normal_y, entry_t)
    add_collision_checks(world, checked)
    return first_collision


def _hard_obstacle_at_position(
    world: WorldState,
    position: WorldPosition,
    *,
    ignore_id: EntityId | None,
    clearance: float,
) -> Any | None:
    checked = 0
    for obstacle in _hard_obstacles_for_bounds(
        world,
        _bounds_around_position(position, clearance + UNIT_HITBOX_RADIUS),
        ignore_id=ignore_id,
    ):
        checked += 1
        if _point_in_rect(position, _inflated_obstacle_rect(obstacle, clearance=clearance)):
            add_collision_checks(world, checked)
            return obstacle
    add_collision_checks(world, checked)
    return None


def _bounds_around_position(
    position: WorldPosition,
    radius: float,
) -> tuple[float, float, float, float]:
    radius = max(0.0, float(radius))
    return (position.x - radius, position.y - radius, radius * 2.0, radius * 2.0)


def _segment_query_bounds(
    origin: WorldPosition,
    desired: WorldPosition,
    padding: float,
) -> tuple[float, float, float, float]:
    padding = max(0.0, float(padding))
    left = min(origin.x, desired.x) - padding
    top = min(origin.y, desired.y) - padding
    right = max(origin.x, desired.x) + padding
    bottom = max(origin.y, desired.y) + padding
    return (left, top, max(1.0, right - left), max(1.0, bottom - top))


def _entities_for_bounds(
    world: WorldState,
    bounds: tuple[float, float, float, float],
) -> list[Any]:
    return [
        entity
        for entity_id in world.spatial_hash.query(bounds)
        if (entity := world.entities.get(entity_id)) is not None
    ]


def _entities_near_position(
    world: WorldState,
    position: WorldPosition,
    radius: float,
) -> list[Any]:
    return _entities_for_bounds(world, _bounds_around_position(position, radius))


def _units_for_bounds(
    world: WorldState,
    bounds: tuple[float, float, float, float],
) -> list[Any]:
    query_ids = world.spatial_hash.query(bounds)
    indexed_unit_ids = getattr(world, "unit_ids", set())
    if indexed_unit_ids:
        query_ids = query_ids & indexed_unit_ids
    return [
        entity
        for entity_id in query_ids
        if (entity := world.entities.get(entity_id)) is not None and is_unit(entity)
    ]


def _unit_entities_near_position(
    world: WorldState,
    position: WorldPosition,
    radius: float,
) -> list[Any]:
    radius_sq = max(0.0, radius) * max(0.0, radius)
    query_ids = world.spatial_hash.query(_bounds_around_position(position, radius))
    indexed_unit_ids = getattr(world, "unit_ids", set())
    if indexed_unit_ids:
        query_ids = query_ids & indexed_unit_ids
    units: list[Any] = []
    for entity_id in query_ids:
        entity = world.entities.get(entity_id)
        if entity is None or not is_unit(entity):
            continue
        dx = entity.position.x - position.x
        dy = entity.position.y - position.y
        if (dx * dx) + (dy * dy) <= radius_sq:
            units.append(entity)
    return units


def _nearby_units(
    world: WorldState,
    position: WorldPosition,
    radius: float,
    *,
    ignore_id: EntityId | None = None,
    max_count: int | None = None,
) -> list[Any]:
    candidates: list[tuple[float, Any]] = []
    for entity in _unit_entities_near_position(world, position, radius):
        if entity.id == ignore_id:
            continue
        dx = entity.position.x - position.x
        dy = entity.position.y - position.y
        distance_sq = (dx * dx) + (dy * dy)
        candidates.append((distance_sq, entity))
        if max_count is not None and len(candidates) >= max_count * 3:
            break
    candidates.sort(key=lambda item: item[0])
    if max_count is not None:
        candidates = candidates[:max_count]
    return [entity for _distance_sq, entity in candidates]


def _hard_obstacles_for_bounds(
    world: WorldState,
    bounds: tuple[float, float, float, float],
    *,
    ignore_id: EntityId | None,
) -> list[Any]:
    query_ids = world.spatial_hash.query(bounds)
    indexed_obstacle_ids = getattr(world, "hard_obstacle_ids", set())
    if indexed_obstacle_ids:
        query_ids = query_ids & indexed_obstacle_ids
    obstacles: list[Any] = []
    for entity_id in query_ids:
        if entity_id == ignore_id:
            continue
        entity = world.entities.get(entity_id)
        if entity is not None and is_hard_obstacle(entity):
            obstacles.append(entity)
    return obstacles


def _hard_obstacles(world: WorldState, *, ignore_id: EntityId | None) -> list[Any]:
    return [
        entity
        for entity in world.entities.values()
        if entity.id != ignore_id and is_hard_obstacle(entity)
    ]


def _inflated_obstacle_rect(
    obstacle: Any,
    *,
    clearance: float = HARD_OBSTACLE_CLEARANCE,
) -> tuple[float, float, float, float]:
    clearance = _clearance_for_obstacle(obstacle, clearance)
    left, top, width, height = blocking_bounds_for_entity(obstacle)
    return (
        left - clearance,
        top - clearance,
        left + width + clearance,
        top + height + clearance,
    )


def _clearance_for_obstacle(obstacle: Any, requested_clearance: float) -> float:
    if "resource" in getattr(obstacle, "tags", ()):
        return min(requested_clearance, RESOURCE_OBSTACLE_CLEARANCE)
    return requested_clearance


def _point_in_rect(position: WorldPosition, rect: tuple[float, float, float, float]) -> bool:
    left, top, right, bottom = rect
    return left <= position.x <= right and top <= position.y <= bottom


def _segment_rect_entry(
    origin: WorldPosition,
    desired: WorldPosition,
    rect: tuple[float, float, float, float],
) -> tuple[float, float, float] | None:
    left, top, right, bottom = rect
    dx = desired.x - origin.x
    dy = desired.y - origin.y
    t_min = 0.0
    t_max = 1.0
    normal = (0.0, 0.0)
    for axis_origin, axis_delta, min_side, max_side, min_normal, max_normal in (
        (origin.x, dx, left, right, (-1.0, 0.0), (1.0, 0.0)),
        (origin.y, dy, top, bottom, (0.0, -1.0), (0.0, 1.0)),
    ):
        if abs(axis_delta) <= _EPSILON:
            if axis_origin < min_side or axis_origin > max_side:
                return None
            continue
        inv_delta = 1.0 / axis_delta
        t1 = (min_side - axis_origin) * inv_delta
        t2 = (max_side - axis_origin) * inv_delta
        enter_normal = min_normal
        if t1 > t2:
            t1, t2 = t2, t1
            enter_normal = max_normal
        if t1 > t_min:
            t_min = t1
            normal = enter_normal
        t_max = min(t_max, t2)
        if t_min > t_max:
            return None
    if t_max < 0.0 or t_min > 1.0:
        return None
    if _point_in_rect(origin, rect):
        normal = _nearest_rect_normal(origin, rect)
        t_min = 0.0
    return (max(0.0, t_min), normal[0], normal[1])


def _nearest_rect_normal(
    position: WorldPosition,
    rect: tuple[float, float, float, float],
) -> tuple[float, float]:
    left, top, right, bottom = rect
    distances = (
        (abs(position.x - left), -1.0, 0.0),
        (abs(right - position.x), 1.0, 0.0),
        (abs(position.y - top), 0.0, -1.0),
        (abs(bottom - position.y), 0.0, 1.0),
    )
    _distance_to_side, normal_x, normal_y = min(distances, key=lambda item: item[0])
    return normal_x, normal_y


def _nearest_point_outside_rect(
    position: WorldPosition,
    rect: tuple[float, float, float, float],
) -> WorldPosition:
    left, top, right, bottom = rect
    normal_x, normal_y = _nearest_rect_normal(position, rect)
    if normal_x < 0:
        return WorldPosition(left - _EPSILON, position.y)
    if normal_x > 0:
        return WorldPosition(right + _EPSILON, position.y)
    if normal_y < 0:
        return WorldPosition(position.x, top - _EPSILON)
    return WorldPosition(position.x, bottom + _EPSILON)


def _perpendicular_slide_candidates(
    world: WorldState,
    entity_id: EntityId,
    base: WorldPosition,
    normal_x: float,
    normal_y: float,
    desired: WorldPosition,
    max_adjustment: float,
) -> list[WorldPosition]:
    tangent_x, tangent_y = -normal_y, normal_x
    candidates = [
        _clamp_for_world(
            world,
            WorldPosition(base.x + tangent_x * max_adjustment, base.y + tangent_y * max_adjustment),
        ),
        _clamp_for_world(
            world,
            WorldPosition(base.x - tangent_x * max_adjustment, base.y - tangent_y * max_adjustment),
        ),
    ]
    open_candidates = [
        candidate
        for candidate in candidates
        if not position_blocked_by_hard_obstacle(world, candidate, ignore_id=entity_id)
    ]
    return sorted(
        open_candidates,
        key=lambda candidate: hypot(candidate.x - desired.x, candidate.y - desired.y),
    )


def _skip_unit_collision(
    world: WorldState,
    source_id: EntityId | None,
    entity: Any,
    *,
    ignore_id: EntityId | None,
    friendly_ghost_ids: set[EntityId] | None,
) -> bool:
    if not is_unit(entity) or entity.id == ignore_id:
        return True
    if source_id is None or not friendly_ghost_ids:
        return False
    source = world.entities.get(source_id)
    return (
        source is not None
        and _same_owner(source, entity)
        and (source_id in friendly_ghost_ids or entity.id in friendly_ghost_ids)
    )


def _same_owner(first: Any, second: Any) -> bool:
    return getattr(first, "owner", None) == getattr(second, "owner", None)

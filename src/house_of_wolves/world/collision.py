"""Lightweight unit collision and placement helpers."""

from __future__ import annotations

from math import cos, hypot, pi, sin
from typing import Any

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.world.world import WorldState

UNIT_COLLISION_RADIUS = 22.0
MAX_COLLISION_ADJUSTMENT = 5.0
MAX_SEPARATION_PUSH = 2.0
SHOVE_INFLUENCE_RADIUS = UNIT_COLLISION_RADIUS * 1.35
MAX_SHOVE_PUSH = 4.0
_EPSILON = 0.0001


def is_unit(entity: object) -> bool:
    return "unit" in getattr(entity, "tags", ())


def unit_distance(first: Any, second: Any) -> float:
    first_pos = first.position
    second_pos = second.position
    return hypot(first_pos.x - second_pos.x, first_pos.y - second_pos.y)


def occupied_by_unit(
    world: WorldState,
    position: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
    min_distance: float = UNIT_COLLISION_RADIUS,
) -> bool:
    nearest = nearest_unit_distance(world, position, ignore_id=ignore_id)
    return nearest is not None and nearest < min_distance


def nearest_unit_distance(
    world: WorldState,
    position: WorldPosition,
    *,
    ignore_id: EntityId | None = None,
) -> float | None:
    nearest: float | None = None
    for entity in world.entities.values():
        if not is_unit(entity) or entity.id == ignore_id:
            continue
        distance = hypot(entity.position.x - position.x, entity.position.y - position.y)
        if nearest is None or distance < nearest:
            nearest = distance
    return nearest


def resolve_unit_position(
    world: WorldState,
    entity_id: EntityId,
    desired: WorldPosition,
    *,
    current: WorldPosition | None = None,
    min_distance: float = UNIT_COLLISION_RADIUS,
    max_adjustment: float = MAX_COLLISION_ADJUSTMENT,
) -> WorldPosition:
    """Softly slide a moving unit away from occupied pixels without teleporting."""

    if not occupied_by_unit(world, desired, ignore_id=entity_id, min_distance=min_distance):
        return desired

    entity = world.entities.get(entity_id)
    origin = current or (entity.position if entity is not None else desired)
    adjusted = desired
    for _ in range(2):
        blocker, distance = _closest_overlapping_unit(
            world,
            entity_id,
            adjusted,
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

    return adjusted


def separate_overlapping_units(
    world: WorldState,
    *,
    min_distance: float = UNIT_COLLISION_RADIUS,
    max_push: float = MAX_SEPARATION_PUSH,
    iterations: int = 1,
) -> None:
    """Push overlapping units apart so crowds slide instead of locking together."""

    for _ in range(iterations):
        units = sorted(
            (entity for entity in world.entities.values() if is_unit(entity)),
            key=lambda entity: int(entity.id),
        )
        offsets: dict[EntityId, list[float]] = {entity.id: [0.0, 0.0] for entity in units}
        for index, first in enumerate(units):
            for second in units[index + 1 :]:
                _add_pair_separation(offsets, first, second, min_distance, max_push)

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
            world.update_entity_position(
                unit.id,
                WorldPosition(unit.position.x + dx, unit.position.y + dy),
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
) -> None:
    """Nudge units in front of a mover so crowds give way under pressure."""

    move_x = desired.x - origin.x
    move_y = desired.y - origin.y
    move_length = hypot(move_x, move_y)
    if move_length <= _EPSILON:
        return

    direction_x = move_x / move_length
    direction_y = move_y / move_length
    shove_candidates: list[tuple[float, Any, float, float]] = []
    for entity in world.entities.values():
        if not is_unit(entity) or entity.id == mover_id:
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

    for _projection, entity, push_x, push_y in sorted(
        shove_candidates,
        key=lambda item: item[0],
    ):
        target = WorldPosition(entity.position.x + push_x, entity.position.y + push_y)
        world.update_entity_position(
            entity.id,
            resolve_unit_position(
                world,
                entity.id,
                target,
                current=entity.position,
                max_adjustment=max_push,
            ),
        )


def _add_pair_separation(
    offsets: dict[EntityId, list[float]],
    first: Any,
    second: Any,
    min_distance: float,
    max_push: float,
) -> None:
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
    min_distance: float,
) -> tuple[Any | None, float]:
    closest: Any | None = None
    closest_distance = min_distance
    for entity in world.entities.values():
        if not is_unit(entity) or entity.id == entity_id:
            continue
        distance = hypot(entity.position.x - position.x, entity.position.y - position.y)
        if distance < closest_distance:
            closest = entity
            closest_distance = distance
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

    if not occupied_by_unit(world, desired, ignore_id=ignore_id, min_distance=min_distance):
        return desired

    for radius in range(round(min_distance), 280, round(min_distance)):
        for dx, dy in _ring_offsets(radius):
            candidate = WorldPosition(desired.x + dx, desired.y + dy)
            if not occupied_by_unit(
                world,
                candidate,
                ignore_id=ignore_id,
                min_distance=min_distance,
            ):
                return candidate
    return desired


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

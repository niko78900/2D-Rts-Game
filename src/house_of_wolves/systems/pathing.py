"""Simple obstacle waypoint planning for move commands."""

from __future__ import annotations

from math import hypot

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.world.collision import (
    HARD_OBSTACLE_CLEARANCE,
    first_hard_obstacle_on_segment,
    position_blocked_by_hard_obstacle,
    project_position_out_of_hard_obstacles,
)
from house_of_wolves.world.terrain import clamp_unit_position_to_walkable_lane_for_height
from house_of_wolves.world.world import WorldState

DETOUR_MARGIN = 6.0
MAX_DETOUR_OBSTACLES = 3
MIN_WAYPOINT_DISTANCE = 3.0


def move_waypoints_around_blockers(
    world: WorldState,
    entity_id: EntityId,
    origin: WorldPosition,
    target: WorldPosition,
) -> list[WorldPosition]:
    """Return internal move waypoints that steer around hard blockers."""

    final_target = project_position_out_of_hard_obstacles(
        world,
        target,
        ignore_id=entity_id,
    )
    waypoints: list[WorldPosition] = []
    current = origin
    handled_rects: set[tuple[int, int, int, int]] = set()

    for _ in range(MAX_DETOUR_OBSTACLES):
        collision = first_hard_obstacle_on_segment(
            world,
            current,
            final_target,
            ignore_id=entity_id,
        )
        if collision is None:
            break

        _obstacle, inflated_rect = collision
        rect_key = tuple(round(value) for value in inflated_rect)
        if rect_key in handled_rects:
            break
        handled_rects.add(rect_key)

        detour = _best_detour_points(world, entity_id, current, final_target, inflated_rect)
        if not detour:
            break
        for point in detour:
            if _far_enough(current, point) and (
                not waypoints or _far_enough(waypoints[-1], point)
            ):
                waypoints.append(point)
                current = point

    if not waypoints or _far_enough(waypoints[-1], final_target):
        waypoints.append(final_target)
    return waypoints


def _best_detour_points(
    world: WorldState,
    entity_id: EntityId,
    origin: WorldPosition,
    target: WorldPosition,
    inflated_rect: tuple[float, float, float, float],
) -> list[WorldPosition]:
    left, top, right, bottom = inflated_rect
    moving_right = target.x >= origin.x
    before_x = (left - DETOUR_MARGIN) if moving_right else (right + DETOUR_MARGIN)
    after_x = (right + DETOUR_MARGIN) if moving_right else (left - DETOUR_MARGIN)
    candidate_routes = [
        [
            _valid_waypoint(world, entity_id, WorldPosition(before_x, top - DETOUR_MARGIN)),
            _valid_waypoint(world, entity_id, WorldPosition(after_x, top - DETOUR_MARGIN)),
        ],
        [
            _valid_waypoint(world, entity_id, WorldPosition(before_x, bottom + DETOUR_MARGIN)),
            _valid_waypoint(world, entity_id, WorldPosition(after_x, bottom + DETOUR_MARGIN)),
        ],
    ]

    routes: list[tuple[int, float, list[WorldPosition]]] = []
    for route in candidate_routes:
        if any(point is None for point in route):
            continue
        points = [point for point in route if point is not None]
        clear = _route_clear(world, entity_id, [origin, *points, target])
        routes.append((0 if clear else 1, _route_length([origin, *points, target]), points))

    if not routes:
        return []
    _penalty, _length, points = min(routes, key=lambda route: (route[0], route[1]))
    return points


def _valid_waypoint(
    world: WorldState,
    entity_id: EntityId,
    position: WorldPosition,
) -> WorldPosition | None:
    candidate = _clamp_to_world(world, position)
    candidate = project_position_out_of_hard_obstacles(
        world,
        candidate,
        ignore_id=entity_id,
        clearance=HARD_OBSTACLE_CLEARANCE,
    )
    if position_blocked_by_hard_obstacle(world, candidate, ignore_id=entity_id):
        return None
    return candidate


def _route_clear(
    world: WorldState,
    entity_id: EntityId,
    points: list[WorldPosition],
) -> bool:
    for start, end in zip(points, points[1:], strict=False):
        if (
            first_hard_obstacle_on_segment(world, start, end, ignore_id=entity_id)
            is not None
        ):
            return False
    return True


def _route_length(points: list[WorldPosition]) -> float:
    return sum(_distance(start, end) for start, end in zip(points, points[1:], strict=False))


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def _far_enough(first: WorldPosition, second: WorldPosition) -> bool:
    return _distance(first, second) >= MIN_WAYPOINT_DISTANCE


def _clamp_to_world(world: WorldState, position: WorldPosition) -> WorldPosition:
    clamped = clamp_unit_position_to_walkable_lane_for_height(
        position,
        world.settings.world_height,
    )
    return WorldPosition(
        max(0.0, min(float(world.settings.world_width), clamped.x)),
        clamped.y,
    )

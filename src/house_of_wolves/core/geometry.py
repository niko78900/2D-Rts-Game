"""Shared geometry helpers for world-space RTS calculations."""

from __future__ import annotations

from math import hypot
from typing import Protocol

from house_of_wolves.core.contracts import WorldPosition

Bounds = tuple[float, float, float, float]


class HasBounds(Protocol):
    @property
    def bounds(self) -> Bounds:
        """Return a world-space rectangle."""


def distance(first: WorldPosition, second: WorldPosition) -> float:
    """Return straight-line distance between two world positions."""
    return hypot(first.x - second.x, first.y - second.y)


def direction_to(
    origin: WorldPosition,
    target: WorldPosition,
    *,
    fallback: tuple[float, float] = (1.0, 0.0),
) -> tuple[float, float]:
    """Return a normalized direction vector with a deterministic fallback."""
    dx = target.x - origin.x
    dy = target.y - origin.y
    length = hypot(dx, dy)
    if length <= 0.0001:
        return fallback
    return (dx / length, dy / length)


def visual_center(entity: HasBounds) -> WorldPosition:
    """Return the center point of an entity's anchored bounds."""
    left, top, width, height = entity.bounds
    return WorldPosition(left + width / 2, top + height / 2)


def bounds_intersect(first: Bounds, second: Bounds) -> bool:
    """Return whether two rectangles intersect."""
    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    return not (
        first_left + first_width < second_left
        or second_left + second_width < first_left
        or first_top + first_height < second_top
        or second_top + second_height < first_top
    )


def point_in_bounds(point: WorldPosition, bounds: Bounds) -> bool:
    """Return whether a point is inside a rectangle."""
    left, top, width, height = bounds
    return left <= point.x <= left + width and top <= point.y <= top + height


def inflate_bounds(bounds: Bounds, amount: float) -> Bounds:
    """Return a rectangle inflated by an equal margin on every side."""
    left, top, width, height = bounds
    return (
        left - amount,
        top - amount,
        width + amount * 2,
        height + amount * 2,
    )


def circle_overlaps_bounds(center: WorldPosition, radius: float, bounds: Bounds) -> bool:
    """Return whether a circle overlaps a rectangle."""
    left, top, width, height = bounds
    right = left + width
    bottom = top + height
    closest_x = min(max(center.x, left), right)
    closest_y = min(max(center.y, top), bottom)
    return hypot(center.x - closest_x, center.y - closest_y) <= radius


def circle_overlaps_entity_bounds(
    center: WorldPosition,
    radius: float,
    entity: HasBounds,
) -> bool:
    """Return whether a circle overlaps an entity's bounds."""
    return circle_overlaps_bounds(center, radius, entity.bounds)

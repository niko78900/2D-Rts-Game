"""Loose group movement slot assignment."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt
from typing import Protocol

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.systems.commands import make_command
from house_of_wolves.world.collision import UNIT_HITBOX_RADIUS
from house_of_wolves.world.terrain import (
    DEFAULT_TERRAIN_HEIGHT,
    clamp_unit_position_to_walkable_lane_for_height,
)
from house_of_wolves.world.world import WorldState

FORMATION_SLOT_SPACING_X = UNIT_HITBOX_RADIUS * 1.85
FORMATION_SLOT_SPACING_Y = UNIT_HITBOX_RADIUS * 1.35


class PositionedUnit(Protocol):
    id: EntityId
    position: WorldPosition


@dataclass(frozen=True, slots=True)
class AssignedMoveSlot:
    entity_id: EntityId
    position: WorldPosition
    formation_index: int


def generate_loose_formation_slots(
    center: WorldPosition,
    units: list[PositionedUnit],
    *,
    world_height: int | float = DEFAULT_TERRAIN_HEIGHT,
) -> list[WorldPosition]:
    """Generate loose destination slots around a clicked target."""

    if not units:
        return []
    if len(units) == 1:
        return [_clamp(center, world_height)]

    sorted_units = sort_units_spatially(units)
    rows = _cluster_rows(sorted_units)
    group_center = _center_of_units(sorted_units)
    raw_slots: list[WorldPosition] = []
    for row in rows:
        row_center_x = sum(unit.position.x for unit in row) / len(row)
        for unit in row:
            offset_x = _spread_offset(unit.position.x - group_center.x)
            offset_y = _spread_offset(
                unit.position.y - group_center.y,
                axis_spacing=FORMATION_SLOT_SPACING_Y,
            )
            if len(row) > 1:
                offset_x += _spread_offset(unit.position.x - row_center_x) * 0.35
            raw_slots.append(
                _clamp(WorldPosition(center.x + offset_x, center.y + offset_y), world_height)
            )

    if _slots_too_tight(raw_slots):
        raw_slots = _grid_slots(center, len(units), _group_aspect(sorted_units), world_height)
    return sort_slots_spatially(_relax_slots(raw_slots, world_height))


def assign_units_to_slots(
    units: list[PositionedUnit],
    slots: list[WorldPosition],
) -> list[AssignedMoveSlot]:
    """Assign sorted units to sorted slots by matching spatial order."""

    sorted_units = sort_units_spatially(units)
    sorted_slots = sort_slots_spatially(slots)
    return [
        AssignedMoveSlot(unit.id, slot, index)
        for index, (unit, slot) in enumerate(zip(sorted_units, sorted_slots, strict=False))
    ]


def issue_group_move_command(
    world: WorldState,
    unit_ids: list[EntityId],
    clicked_pos: WorldPosition,
    *,
    queued: bool = False,
) -> list[AssignedMoveSlot]:
    """Issue one move command per unit, using stable loose formation slots."""

    units = _movable_units_for_ids(world, unit_ids)
    if not units:
        return []

    ordered_units = _formation_order_for_command(world, units, queued=queued)
    slots = generate_loose_formation_slots(
        _clamp(clicked_pos, world.settings.world_height),
        ordered_units,
        world_height=world.settings.world_height,
    )
    assignments = [
        AssignedMoveSlot(unit.id, slot, index)
        for index, (unit, slot) in enumerate(zip(ordered_units, slots, strict=False))
    ]
    for assignment in assignments:
        command = make_command(
            "move",
            [assignment.entity_id],
            target_pos=assignment.position,
            queued=queued,
            group_move=len(assignments) > 1,
            formation_index=assignment.formation_index,
            formation_size=len(assignments),
            clicked_pos=clicked_pos.to_json(),
        )
        world.enqueue_command(assignment.entity_id, command)
    return assignments


def sort_units_spatially(units: list[PositionedUnit]) -> list[PositionedUnit]:
    return sorted(units, key=lambda unit: (unit.position.y, unit.position.x, int(unit.id)))


def sort_slots_spatially(slots: list[WorldPosition]) -> list[WorldPosition]:
    return sorted(slots, key=lambda slot: (slot.y, slot.x))


def _movable_units_for_ids(world: WorldState, unit_ids: list[EntityId]) -> list[PositionedUnit]:
    units: list[PositionedUnit] = []
    for entity_id in unit_ids:
        entity = world.entities.get(entity_id)
        if (
            entity is not None
            and "unit" in entity.tags
            and "movable" in entity.tags
            and entity.owner == "frontier"
        ):
            units.append(entity)
    return units


def _formation_order_for_command(
    world: WorldState,
    units: list[PositionedUnit],
    *,
    queued: bool,
) -> list[PositionedUnit]:
    if not queued:
        return sort_units_spatially(units)

    indexed_units: list[tuple[int, PositionedUnit]] = []
    for unit in units:
        index = _queued_formation_index(world, unit.id)
        if index is None:
            return sort_units_spatially(units)
        indexed_units.append((index, unit))
    return [unit for _index, unit in sorted(indexed_units, key=lambda item: item[0])]


def _queued_formation_index(world: WorldState, entity_id: EntityId) -> int | None:
    queue = world.command_queues.get(entity_id)
    if queue is None:
        return None
    for command in reversed(queue.commands):
        index = command.payload.get("formation_index")
        if command.type == "move" and isinstance(index, int):
            return index
    return None


def _center_of_units(units: list[PositionedUnit]) -> WorldPosition:
    return WorldPosition(
        sum(unit.position.x for unit in units) / len(units),
        sum(unit.position.y for unit in units) / len(units),
    )


def _cluster_rows(units: list[PositionedUnit]) -> list[list[PositionedUnit]]:
    sorted_units = sort_units_spatially(units)
    rows: list[list[PositionedUnit]] = []
    row_threshold = FORMATION_SLOT_SPACING_Y * 0.85
    for unit in sorted_units:
        if not rows:
            rows.append([unit])
            continue
        row_center_y = sum(item.position.y for item in rows[-1]) / len(rows[-1])
        if abs(unit.position.y - row_center_y) <= row_threshold:
            rows[-1].append(unit)
        else:
            rows.append([unit])
    for row in rows:
        row.sort(key=lambda unit: (unit.position.x, int(unit.id)))
    return rows


def _spread_offset(offset: float, *, axis_spacing: float = FORMATION_SLOT_SPACING_X) -> float:
    if abs(offset) < axis_spacing:
        return 0.0
    return offset


def _slots_too_tight(slots: list[WorldPosition]) -> bool:
    for index, first in enumerate(slots):
        for second in slots[index + 1 :]:
            if _distance(first, second) < FORMATION_SLOT_SPACING_Y:
                return True
    return False


def _grid_slots(
    center: WorldPosition,
    count: int,
    aspect: float,
    world_height: int | float,
) -> list[WorldPosition]:
    columns = max(1, min(count, ceil(sqrt(count * aspect))))
    rows = ceil(count / columns)
    slots: list[WorldPosition] = []
    for index in range(count):
        row = index // columns
        column = index % columns
        row_count = columns if row < rows - 1 else count - (row * columns)
        x_offset = (column - ((row_count - 1) / 2)) * FORMATION_SLOT_SPACING_X
        y_offset = (row - ((rows - 1) / 2)) * FORMATION_SLOT_SPACING_Y
        slots.append(_clamp(WorldPosition(center.x + x_offset, center.y + y_offset), world_height))
    return slots


def _group_aspect(units: list[PositionedUnit]) -> float:
    if len(units) <= 1:
        return 1.0
    xs = [unit.position.x for unit in units]
    ys = [unit.position.y for unit in units]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if height <= FORMATION_SLOT_SPACING_Y * 0.5:
        return max(1.8, width / FORMATION_SLOT_SPACING_X)
    return max(0.45, min(2.8, width / height))


def _relax_slots(
    slots: list[WorldPosition],
    world_height: int | float,
) -> list[WorldPosition]:
    relaxed = list(slots)
    for _ in range(3):
        offsets = [[0.0, 0.0] for _slot in relaxed]
        for first_index, first in enumerate(relaxed):
            for second_index in range(first_index + 1, len(relaxed)):
                second = relaxed[second_index]
                dx = second.x - first.x
                dy = second.y - first.y
                distance = _distance(first, second)
                if distance >= FORMATION_SLOT_SPACING_Y or distance == 0:
                    continue
                push = (FORMATION_SLOT_SPACING_Y - distance) / 2
                direction_x = dx / distance
                direction_y = dy / distance
                offsets[first_index][0] -= direction_x * push
                offsets[first_index][1] -= direction_y * push
                offsets[second_index][0] += direction_x * push
                offsets[second_index][1] += direction_y * push
        relaxed = [
            _clamp(WorldPosition(slot.x + offset[0], slot.y + offset[1]), world_height)
            for slot, offset in zip(relaxed, offsets, strict=False)
        ]
    return relaxed


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return ((first.x - second.x) ** 2 + (first.y - second.y) ** 2) ** 0.5


def _clamp(position: WorldPosition, world_height: int | float) -> WorldPosition:
    return clamp_unit_position_to_walkable_lane_for_height(position, world_height)

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.systems.group_movement import (
    FORMATION_SLOT_SPACING_X,
    assign_units_to_slots,
    generate_loose_formation_slots,
    issue_group_move_command,
)
from house_of_wolves.world.demo import create_demo_world


@dataclass(slots=True)
class FakeUnit:
    id: EntityId
    position: WorldPosition


def test_generate_loose_formation_slots_preserves_spatial_layout() -> None:
    """Verify that generate loose formation slots preserves spatial layout."""
    units = [
        FakeUnit(EntityId(1), WorldPosition(0, 0)),
        FakeUnit(EntityId(2), WorldPosition(90, 0)),
        FakeUnit(EntityId(3), WorldPosition(0, 70)),
        FakeUnit(EntityId(4), WorldPosition(90, 70)),
    ]
    center = WorldPosition(1000, 520)

    assignments = assign_units_to_slots(units, generate_loose_formation_slots(center, units))
    by_id = {assignment.entity_id: assignment.position for assignment in assignments}

    assert by_id[EntityId(1)].x < center.x
    assert by_id[EntityId(2)].x > center.x
    assert by_id[EntityId(3)].x < center.x
    assert by_id[EntityId(4)].x > center.x
    assert by_id[EntityId(1)].y < by_id[EntityId(3)].y
    assert by_id[EntityId(2)].y < by_id[EntityId(4)].y
    assert len({slot.position for slot in assignments}) == len(units)


def test_assignment_uses_row_tolerant_order_for_nearly_aligned_units() -> None:
    """Verify that assignment uses row tolerant order for nearly aligned units."""
    units = [
        FakeUnit(EntityId(1), WorldPosition(100, 504)),
        FakeUnit(EntityId(2), WorldPosition(500, 496)),
    ]
    slots = [WorldPosition(900, 520), WorldPosition(960, 520)]

    assignments = assign_units_to_slots(units, slots)
    by_id = {assignment.entity_id: assignment.position for assignment in assignments}

    assert by_id[EntityId(1)] == slots[0]
    assert by_id[EntityId(2)] == slots[1]


def test_generate_loose_formation_slots_caps_oversized_selection_spread() -> None:
    """Verify that generate loose formation slots caps oversized selection spread."""
    units = [
        FakeUnit(EntityId(1), WorldPosition(100, 520)),
        FakeUnit(EntityId(2), WorldPosition(1100, 516)),
    ]
    center = WorldPosition(700, 520)

    slots = generate_loose_formation_slots(center, units)
    xs = [slot.x for slot in slots]

    assert max(xs) - min(xs) <= FORMATION_SLOT_SPACING_X * 1.5
    assert all(abs(slot.x - center.x) <= FORMATION_SLOT_SPACING_X for slot in slots)


def test_issue_group_move_command_assigns_unique_targets() -> None:
    """Verify that issue group move command assigns unique targets."""
    world = create_demo_world()
    units = [
        entity for entity in world.entities.values()
        if "unit" in entity.tags and entity.owner == "frontier"
    ]

    assignments = issue_group_move_command(
        world,
        [unit.id for unit in units],
        WorldPosition(900, 520),
    )

    assert len(assignments) == len(units)
    assert len({assignment.position for assignment in assignments}) == len(units)
    for assignment in assignments:
        command = world.command_queues[assignment.entity_id].peek()
        assert command is not None
        assert command.queued is False
        assert command.issuer_ids == (assignment.entity_id,)
        assert command.target_pos == assignment.position
        assert command.payload["group_move"] is True
        assert command.payload["formation_index"] == assignment.formation_index


def test_normal_group_move_replaces_existing_queue() -> None:
    """Verify that normal group move replaces existing queue."""
    world = create_demo_world()
    units = [
        entity for entity in world.entities.values()
        if "unit" in entity.tags and entity.owner == "frontier"
    ]

    issue_group_move_command(world, [unit.id for unit in units], WorldPosition(900, 520))
    issue_group_move_command(
        world,
        [unit.id for unit in units],
        WorldPosition(1200, 520),
        queued=True,
    )
    issue_group_move_command(world, [unit.id for unit in units], WorldPosition(1400, 520))

    assert all(len(world.command_queues[unit.id].commands) == 1 for unit in units)


def test_shift_queued_group_move_preserves_formation_indices() -> None:
    """Verify that shift queued group move preserves formation indices."""
    world = create_demo_world()
    units = [
        entity for entity in world.entities.values()
        if "unit" in entity.tags and entity.owner == "frontier"
    ]
    unit_ids = [unit.id for unit in units]

    issue_group_move_command(world, unit_ids, WorldPosition(900, 520))
    issue_group_move_command(world, list(reversed(unit_ids)), WorldPosition(1200, 520), queued=True)

    for unit_id in unit_ids:
        commands = world.command_queues[unit_id].commands
        assert len(commands) == 2
        assert commands[0].payload["formation_index"] == commands[1].payload["formation_index"]
        assert commands[1].queued is True

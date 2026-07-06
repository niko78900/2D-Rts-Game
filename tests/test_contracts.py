from __future__ import annotations

from house_of_wolves.core.contracts import (
    Command,
    CommandQueue,
    EntityId,
    Footprint,
    ProductionQueueItem,
    ResourceAmount,
    WorldPosition,
)
from house_of_wolves.world.world import WorldState


def test_contracts_round_trip_json_values() -> None:
    """Verify that contracts round trip json values."""
    command = Command(
        type="attack",
        issuer_ids=(EntityId(1),),
        target_entity_id=EntityId(9),
        payload={"stance": "hold"},
    )
    queue = CommandQueue(EntityId(1), [command])

    restored = CommandQueue.from_json(queue.to_json())

    assert restored.owner_id == EntityId(1)
    assert restored.peek() == command


def test_core_value_objects_validate_and_serialize() -> None:
    """Verify that core value objects validate and serialize."""
    position = WorldPosition(100.5, 420)
    footprint = Footprint(20, 40)
    resource = ResourceAmount("wood", 25)
    item = ProductionQueueItem("settler", 500)

    assert footprint.bounds_at(position) == (90.5, 380, 20, 40)
    assert ResourceAmount.from_json(resource.to_json()) == resource
    assert ProductionQueueItem.from_json(item.to_json()).item_id == "settler"


def test_world_state_serializes_command_queues_without_losing_ids() -> None:
    """Verify that world state serializes command queues without losing ids."""
    world = WorldState()
    entity_id = world.allocate_entity_id()
    command = Command(type="move", issuer_ids=(entity_id,), target_pos=WorldPosition(10, 20))

    world.enqueue_command(entity_id, command)
    restored = WorldState.from_json(world.to_json())

    assert restored.command_queues[entity_id].peek() == command

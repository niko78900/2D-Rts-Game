from __future__ import annotations

from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.economy import EconomySystem
from house_of_wolves.world.demo import create_demo_world


def test_settler_gather_command_adds_matching_resource_and_drains_node() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    world.update_entity_position(settler.id, tree.position)
    starting_wood = world.resources["wood"]
    starting_remaining = tree.amount_remaining
    world.enqueue_command(
        settler.id,
        make_command(
            "gather",
            [settler.id],
            target_entity_id=tree.id,
            target_pos=tree.position,
            resource_type="wood",
        ),
    )

    EconomySystem().update(world, tree.gather_time_ms)

    assert world.resources["wood"] == starting_wood + 10
    assert tree.amount_remaining == starting_remaining - 10
    assert settler.state == "gathering"


def test_gather_command_rejects_wrong_resource_type() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    world.update_entity_position(settler.id, tree.position)
    world.enqueue_command(
        settler.id,
        make_command(
            "gather",
            [settler.id],
            target_entity_id=tree.id,
            target_pos=tree.position,
            resource_type="gold",
        ),
    )

    EconomySystem().update(world, tree.gather_time_ms)

    assert world.command_queues[settler.id].peek() is None
    assert tree.amount_remaining == tree.max_amount_remaining

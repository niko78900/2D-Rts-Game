from __future__ import annotations

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.entities.resource_node import ResourceNode, resource_hp_for_type
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.economy import (
    GATHER_CARRY_AMOUNT,
    GATHER_SWING_MS,
    GATHER_SWINGS_PER_LOAD,
    EconomySystem,
    assign_auto_gather_targets,
    hut_deposit_position,
    resource_interaction_position,
)
from house_of_wolves.world.demo import create_demo_world


def test_settler_gather_command_swings_carries_deposits_and_returns() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    interaction_point = resource_interaction_position(world, tree, settler.id)
    world.update_entity_position(settler.id, interaction_point)
    starting_wood = world.resources["wood"]
    starting_remaining = tree.amount_remaining
    world.enqueue_command(
        settler.id,
        make_command(
            "gather",
            [settler.id],
            target_entity_id=tree.id,
            target_pos=interaction_point,
            resource_type="wood",
            current_resource_id=tree.id.to_json(),
        ),
    )

    EconomySystem().update(world, GATHER_SWING_MS * GATHER_SWINGS_PER_LOAD)

    commands = world.command_queues[settler.id].commands
    assert world.resources["wood"] == starting_wood
    assert tree.amount_remaining == starting_remaining - GATHER_SWINGS_PER_LOAD
    assert settler.carry_type == "wood"
    assert settler.carry_amount == GATHER_CARRY_AMOUNT
    assert [command.type for command in commands[:2]] == ["move", "gather"]

    world.command_queues[settler.id].pop_next()
    world.update_entity_position(settler.id, hut_deposit_position(world, hut, settler.id))
    EconomySystem().update(world, 16)

    commands = world.command_queues[settler.id].commands
    assert world.resources["wood"] == starting_wood + GATHER_CARRY_AMOUNT
    assert settler.carry_type is None
    assert settler.carry_amount == 0
    assert [command.type for command in commands[:2]] == ["move", "gather"]
    assert commands[1].target_entity_id == tree.id


def test_gather_command_rejects_wrong_resource_type() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    interaction_point = resource_interaction_position(world, tree, settler.id)
    world.update_entity_position(settler.id, interaction_point)
    world.enqueue_command(
        settler.id,
        make_command(
            "gather",
            [settler.id],
            target_entity_id=tree.id,
            target_pos=interaction_point,
            resource_type="gold",
            current_resource_id=tree.id.to_json(),
        ),
    )

    EconomySystem().update(world, GATHER_SWING_MS * GATHER_SWINGS_PER_LOAD)

    assert world.command_queues[settler.id].peek() is None
    assert tree.amount_remaining == tree.max_amount_remaining
    assert settler.state == "idle"


def test_gather_command_requires_completed_deposit_hut() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    world.remove_entity(hut.id)
    interaction_point = resource_interaction_position(world, tree, settler.id)
    world.update_entity_position(settler.id, interaction_point)
    world.enqueue_command(
        settler.id,
        make_command(
            "gather",
            [settler.id],
            target_entity_id=tree.id,
            target_pos=interaction_point,
            resource_type="wood",
        ),
    )

    EconomySystem().update(world, 16)

    assert world.command_queues[settler.id].peek() is None
    assert [notification.message for notification in world.notifications] == [
        "Needs hut to deposit."
    ]


def test_auto_gather_avoids_unsafe_resource_nodes() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)

    assignments, message = assign_auto_gather_targets(
        world,
        [settler.id],
        "iron",
        owner="frontier",
    )

    assert assignments == {}
    assert message == "No safe ore source found."


def test_auto_gather_redistributes_settlers_across_safe_nodes() -> None:
    world = create_demo_world()
    settlers = [entity for entity in world.entities.values() if "settler" in entity.tags]
    first = settlers[0]
    second = _add_settler_like(world, WorldPosition(first.position.x + 34, first.position.y))
    _add_extra_resource_node(world, "wood", WorldPosition(930, first.position.y + 40))

    assignments, message = assign_auto_gather_targets(
        world,
        [first.id, second.id],
        "wood",
        owner="frontier",
    )

    assert message is None
    assert len(assignments) == 2
    assert len({resource.id for resource in assignments.values()}) == 2


def test_destroyed_resource_node_is_removed_and_respawned_later() -> None:
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    tree.hp = 0
    tree.amount_remaining = 0
    tree.state = "destroying"
    tree.destruction_remaining_ms = 1
    system = EconomySystem(respawn_min_ms=0, respawn_max_ms=0)

    system.update(world, 1)

    assert tree.id not in world.entities
    assert any(
        isinstance(entity, ResourceNode) and entity.resource_type == "wood"
        for entity in world.entities.values()
    )


def _add_settler_like(world, position: WorldPosition):
    template = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    entity = type(template)(
        id=world.allocate_entity_id(),
        owner=template.owner,
        position=position,
        footprint=template.footprint,
        hp=template.hp,
        max_hp=template.max_hp,
        tags=template.tags,
        speed=template.speed,
        attack_range=template.attack_range,
        damage=template.damage,
        attack_cooldown_ms=template.attack_cooldown_ms,
    )
    world.add_entity(entity)
    return entity


def _add_extra_resource_node(
    world,
    resource_type: str,
    position: WorldPosition,
) -> ResourceNode:
    hp = resource_hp_for_type(resource_type)
    node = ResourceNode(
        id=world.allocate_entity_id(),
        owner="neutral",
        position=position,
        footprint=Footprint(82, 126),
        hp=hp,
        max_hp=hp,
        tags=("resource", "wood_tree", "selectable"),
        resource_type=resource_type,
        amount_remaining=hp,
        max_amount_remaining=hp,
        gather_time_ms=900,
        blocking_footprint=Footprint(42, 92),
    )
    world.add_entity(node)
    return node

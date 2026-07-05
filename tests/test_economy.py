from __future__ import annotations

from math import hypot

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import (
    GOLD_RESOURCE_HP,
    WOOD_RESOURCE_HP,
    ResourceNode,
    resource_hp_for_type,
)
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.economy import (
    GATHER_CARRY_AMOUNT,
    GATHER_SWING_MS,
    GATHER_SWINGS_PER_LOAD,
    GOLD_RESPAWN_DELAY_MS,
    MAX_ACTIVE_GOLD_NODES,
    MAX_ACTIVE_TREES,
    RESPAWN_AVOID_RADIUS,
    RESPAWN_RETRY_MS,
    TREE_RESPAWN_DELAY_MS,
    EconomySystem,
    ResourceRespawn,
    active_resource_nodes,
    assign_auto_gather_targets,
    completed_deposit_huts,
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


def test_completed_player_huts_are_the_only_deposit_hubs() -> None:
    world = create_demo_world()
    completed_hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    incomplete_hut = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(completed_hut.position.x + 260, completed_hut.position.y),
        footprint=completed_hut.footprint,
        hp=65,
        max_hp=650,
        tags=("building", "hut", "selectable"),
        complete=False,
        functions=Building.production_functions(dropoff=True),
        dropoff_point=completed_hut.dropoff_point,
    )
    enemy_hut = Building(
        id=world.allocate_entity_id(),
        owner="wolves",
        position=WorldPosition(completed_hut.position.x + 520, completed_hut.position.y),
        footprint=completed_hut.footprint,
        hp=650,
        max_hp=650,
        tags=("building", "hut", "selectable"),
        complete=True,
        functions=Building.production_functions(dropoff=True),
        dropoff_point=completed_hut.dropoff_point,
    )
    world.add_entity(incomplete_hut)
    world.add_entity(enemy_hut)

    assert completed_deposit_huts(world, "frontier") == [completed_hut]
    assert completed_deposit_huts(world, "wolves") == [enemy_hut]


def test_auto_gather_avoids_unsafe_resource_nodes() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if entity.owner == "wolves")
    _remove_resource_nodes(world, "iron")
    _add_extra_resource_node(world, "iron", enemy.position)

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

    assignments, message = assign_auto_gather_targets(
        world,
        [first.id, second.id],
        "wood",
        owner="frontier",
    )

    assert message is None
    assert len(assignments) == 2
    assert len({resource.id for resource in assignments.values()}) == 2


def test_destroyed_tree_respawns_after_exact_delay() -> None:
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    starting_ids = {node.id for node in active_resource_nodes(world, "wood")}
    destroyed_position = tree.position
    tree.hp = 0
    tree.amount_remaining = 0
    tree.state = "destroying"
    tree.destruction_remaining_ms = 1
    system = EconomySystem()

    system.update(world, 1)

    assert tree.id not in world.entities
    assert len(active_resource_nodes(world, "wood")) == MAX_ACTIVE_TREES - 1
    assert len(system.respawns) == 1
    assert system.respawns[0].resource_type == "wood"
    assert system.respawns[0].due_ms == TREE_RESPAWN_DELAY_MS

    world.elapsed_ms = TREE_RESPAWN_DELAY_MS
    system.update(world, 16)

    spawned = active_resource_nodes(world, "wood")
    new_trees = [node for node in spawned if node.id not in starting_ids]
    assert len(spawned) == MAX_ACTIVE_TREES
    assert len(new_trees) == 1
    assert new_trees[0].hp == WOOD_RESOURCE_HP
    assert new_trees[0].amount_remaining == WOOD_RESOURCE_HP
    assert _distance(new_trees[0].position, destroyed_position) > RESPAWN_AVOID_RADIUS
    assert system.respawns == []


def test_tree_respawn_retries_when_active_tree_cap_is_full() -> None:
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    system = EconomySystem()
    system.respawns.append(ResourceRespawn("wood", world.elapsed_ms, tree.position))

    system.update(world, 16)

    assert len(active_resource_nodes(world, "wood")) == MAX_ACTIVE_TREES
    assert len(system.respawns) == 1
    assert system.respawns[0].due_ms == world.elapsed_ms + RESPAWN_RETRY_MS


def test_wood_gatherer_waits_for_new_tree_when_none_are_active() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    _remove_resource_nodes(world, "wood", keep_ids={tree.id})
    interaction_point = resource_interaction_position(world, tree, settler.id)
    world.update_entity_position(settler.id, interaction_point)
    tree.hp = 0
    tree.amount_remaining = 0
    tree.state = "destroying"
    tree.destruction_remaining_ms = 1
    system = EconomySystem()
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

    system.update(world, 1)

    command = world.command_queues[settler.id].peek()
    assert command is not None
    assert command.type == "gather"
    assert settler.state == "idle"

    world.elapsed_ms = TREE_RESPAWN_DELAY_MS
    system.update(world, 16)

    commands = world.command_queues[settler.id].commands
    assert [command.type for command in commands[:2]] == ["move", "gather"]
    assert commands[1].payload["current_resource_id"] != tree.id.to_json()


def test_destroyed_mine_resource_respawns_after_exact_delay() -> None:
    world = create_demo_world()
    gold = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    starting_ids = {node.id for node in active_resource_nodes(world, "gold")}
    destroyed_position = gold.position
    gold.hp = 0
    gold.amount_remaining = 0
    gold.state = "destroying"
    gold.destruction_remaining_ms = 1
    system = EconomySystem()

    system.update(world, 1)

    assert gold.id not in world.entities
    assert len(active_resource_nodes(world, "gold")) == MAX_ACTIVE_GOLD_NODES - 1
    assert len(system.respawns) == 1
    assert system.respawns[0].resource_type == "gold"
    assert system.respawns[0].due_ms == GOLD_RESPAWN_DELAY_MS

    world.elapsed_ms = GOLD_RESPAWN_DELAY_MS - 1
    system.update(world, 16)
    assert len(active_resource_nodes(world, "gold")) == MAX_ACTIVE_GOLD_NODES - 1

    world.elapsed_ms = GOLD_RESPAWN_DELAY_MS
    system.update(world, 16)

    spawned = active_resource_nodes(world, "gold")
    new_gold = [node for node in spawned if node.id not in starting_ids]
    assert len(spawned) == MAX_ACTIVE_GOLD_NODES
    assert len(new_gold) == 1
    assert new_gold[0].hp == GOLD_RESOURCE_HP
    assert new_gold[0].amount_remaining == GOLD_RESOURCE_HP
    assert _distance(new_gold[0].position, destroyed_position) > RESPAWN_AVOID_RADIUS
    assert system.respawns == []


def test_mine_respawn_skips_when_resource_type_is_at_cap() -> None:
    world = create_demo_world()
    gold = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    system = EconomySystem()
    system.respawns.append(ResourceRespawn("gold", world.elapsed_ms, gold.position))

    system.update(world, 16)

    assert len(active_resource_nodes(world, "gold")) == 5
    assert system.respawns == []


def test_mine_respawn_retries_when_no_valid_spawn_location_exists() -> None:
    world = create_demo_world()
    gold = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    world.remove_entity(gold.id)
    world.add_entity(
        Building(
            id=world.allocate_entity_id(),
            owner="frontier",
            position=WorldPosition(world.settings.world_width / 2, world.settings.world_height),
            footprint=Footprint(world.settings.world_width * 2, world.settings.world_height * 2),
            hp=1,
            max_hp=1,
            tags=("building", "blocker"),
        )
    )
    system = EconomySystem()
    system.respawns.append(ResourceRespawn("gold", world.elapsed_ms, gold.position))

    system.update(world, 16)

    assert len(active_resource_nodes(world, "gold")) == MAX_ACTIVE_GOLD_NODES - 1
    assert len(system.respawns) == 1
    assert system.respawns[0].due_ms == world.elapsed_ms + RESPAWN_RETRY_MS


def _remove_resource_nodes(
    world: object,
    resource_type: str,
    *,
    keep_ids: set[object] | None = None,
) -> None:
    kept = keep_ids or set()
    for resource in list(active_resource_nodes(world, resource_type)):
        if resource.id in kept:
            continue
        world.remove_entity(resource.id)


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
    tags_by_type = {
        "wood": ("resource", "wood_tree", "selectable"),
        "stone": ("resource", "stone_outcrop", "selectable"),
        "iron": ("resource", "iron_deposit", "selectable"),
        "gold": ("resource", "gold_mine", "selectable"),
    }
    hp = resource_hp_for_type(resource_type)
    node = ResourceNode(
        id=world.allocate_entity_id(),
        owner="neutral",
        position=position,
        footprint=Footprint(82, 126),
        hp=hp,
        max_hp=hp,
        tags=tags_by_type[resource_type],
        resource_type=resource_type,
        amount_remaining=hp,
        max_amount_remaining=hp,
        gather_time_ms=900,
        blocking_footprint=Footprint(42, 92),
    )
    world.add_entity(node)
    return node


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)

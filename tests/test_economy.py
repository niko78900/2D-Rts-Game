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
    MAX_RESOURCE_CANDIDATES_TO_PATHCHECK,
    MINE_HARVEST_MAX_SLOTS,
    MINE_HARVEST_MIN_SLOTS,
    RESPAWN_AVOID_RADIUS,
    RESPAWN_RETRY_MS,
    TREE_HARVEST_MAX_SLOTS,
    TREE_HARVEST_MIN_SLOTS,
    TREE_RESPAWN_DELAY_MS,
    EconomySystem,
    ResourceRespawn,
    active_resource_nodes,
    assign_auto_gather_targets,
    cached_active_resource_nodes,
    completed_deposit_huts,
    hut_deposit_position,
    is_unit_in_gather_range,
    mine_harvest_area_bounds,
    mine_harvest_slot_candidates,
    resource_edge_distance,
    resource_interaction_position,
    tree_harvest_area_bounds,
    tree_harvest_slot_candidates,
)
from house_of_wolves.world.collision import position_blocked_by_hard_obstacle
from house_of_wolves.world.demo import create_demo_world


def test_settler_gather_command_swings_carries_deposits_and_returns() -> None:
    """Verify that settler gather command swings carries deposits and returns."""
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
    """Verify that gather command rejects wrong resource type."""
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


def test_gather_starts_when_failed_move_left_settler_at_resource_edge() -> None:
    """Verify that gather starts when failed move left settler at resource edge."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    left, top, width, height = mine.blocking_bounds
    valid_edge_position = WorldPosition(left + width + 30, top + (height / 2))
    stale_wrong_side_target = WorldPosition(left - 30, top + (height / 2))
    world.update_entity_position(settler.id, valid_edge_position)
    command = make_command(
        "gather",
        [settler.id],
        target_entity_id=mine.id,
        target_pos=stale_wrong_side_target,
        resource_type="gold",
        current_resource_id=mine.id.to_json(),
        resource_interaction_resource_id=mine.id.to_json(),
        resource_interaction_x=stale_wrong_side_target.x,
        resource_interaction_y=stale_wrong_side_target.y,
        pending_move_key=f"resource:{int(mine.id)}",
    )
    world.enqueue_command(settler.id, command)

    EconomySystem().update(world, 16)

    assert is_unit_in_gather_range(settler, mine)
    assert world.command_queues[settler.id].peek() == command
    assert settler.state == "gathering"
    assert world.notifications == []


def test_resource_interaction_position_stays_outside_resource_blocker() -> None:
    """Verify that resource interaction position stays outside resource blocker."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)

    interaction = resource_interaction_position(world, mine, settler.id)

    assert not position_blocked_by_hard_obstacle(world, interaction, ignore_id=settler.id)
    assert resource_edge_distance(interaction, mine) <= EconomySystem().gather_interaction_range


def test_tree_harvest_slots_are_distinct_inside_front_area() -> None:
    """Verify that tree harvest slots are stable, distinct, and outside the blocker."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)

    slots = tree_harvest_slot_candidates(world, tree, settler.id)
    first_four = slots[:TREE_HARVEST_MIN_SLOTS]

    assert TREE_HARVEST_MIN_SLOTS <= len(slots) <= TREE_HARVEST_MAX_SLOTS
    assert len({(round(slot.x), round(slot.y)) for slot in first_four}) == 4
    assert all(_point_in_bounds(slot, tree_harvest_area_bounds(tree)) for slot in first_four)
    assert all(
        not position_blocked_by_hard_obstacle(world, slot, ignore_id=settler.id)
        for slot in first_four
    )


def test_tree_gather_range_uses_large_front_area() -> None:
    """Verify that tree gathering starts anywhere inside the harvest area."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    slot = tree_harvest_slot_candidates(world, tree, settler.id)[0]
    world.update_entity_position(settler.id, slot)

    assert is_unit_in_gather_range(settler, tree)


def test_tree_interaction_position_falls_back_when_first_slot_is_blocked() -> None:
    """Verify that blocked tree slots fall back to another slot in the harvest area."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    blocked_slot = tree_harvest_slot_candidates(world, tree, settler.id)[0]
    _add_settler_like(world, blocked_slot)

    interaction = resource_interaction_position(world, tree, settler.id, candidate_index=0)

    assert _distance(interaction, blocked_slot) > 0
    assert _point_in_bounds(interaction, tree_harvest_area_bounds(tree))
    assert not position_blocked_by_hard_obstacle(world, interaction, ignore_id=settler.id)


def test_mine_harvest_slots_are_distinct_inside_mining_area() -> None:
    """Verify that mine slots are stable, distinct, and outside the blocker."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)

    slots = mine_harvest_slot_candidates(world, mine, settler.id)
    first_four = slots[:MINE_HARVEST_MIN_SLOTS]

    assert MINE_HARVEST_MIN_SLOTS <= len(slots) <= MINE_HARVEST_MAX_SLOTS
    assert len({(round(slot.x), round(slot.y)) for slot in first_four}) == 4
    assert all(_point_in_bounds(slot, mine_harvest_area_bounds(mine)) for slot in first_four)
    assert all(
        not position_blocked_by_hard_obstacle(world, slot, ignore_id=settler.id)
        for slot in first_four
    )


def test_mine_gather_range_uses_large_mining_area() -> None:
    """Verify that mine gathering starts anywhere inside the mining area."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    slot = mine_harvest_slot_candidates(world, mine, settler.id)[0]
    world.update_entity_position(settler.id, slot)

    assert is_unit_in_gather_range(settler, mine)


def test_mine_interaction_position_falls_back_when_first_slot_is_blocked() -> None:
    """Verify that blocked mine slots fall back to another slot in the mining area."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    blocked_slot = mine_harvest_slot_candidates(world, mine, settler.id)[0]
    _add_settler_like(world, blocked_slot)

    interaction = resource_interaction_position(world, mine, settler.id, candidate_index=0)

    assert _distance(interaction, blocked_slot) > 0
    assert _point_in_bounds(interaction, mine_harvest_area_bounds(mine))
    assert not position_blocked_by_hard_obstacle(world, interaction, ignore_id=settler.id)


def test_generic_resource_interaction_keeps_edge_distance_behavior() -> None:
    """Verify that non-tree and non-mine resources keep simple edge interaction."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    resource = ResourceNode(
        id=world.allocate_entity_id(),
        owner="neutral",
        position=WorldPosition(940, 510),
        footprint=Footprint(50, 34),
        hp=25,
        max_hp=25,
        tags=("resource", "food_carcass", "selectable"),
        resource_type="food",
        amount_remaining=25,
        max_amount_remaining=25,
        gather_time_ms=600,
        blocking_footprint=Footprint(32, 24),
    )
    world.add_entity(resource)

    interaction = resource_interaction_position(world, resource, settler.id)

    assert resource_edge_distance(interaction, resource) <= EconomySystem().gather_interaction_range
    assert not position_blocked_by_hard_obstacle(world, interaction, ignore_id=settler.id)


def test_gather_command_requires_completed_deposit_hut() -> None:
    """Verify that gather command requires completed deposit hut."""
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


def test_loaded_gatherer_retries_hut_deposit_route_before_failing() -> None:
    """Verify that a stale hut move failure retries before notifying failure."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    settler.carry_type = "wood"
    settler.carry_amount = GATHER_CARRY_AMOUNT
    command = make_command(
        "gather",
        [settler.id],
        target_entity_id=tree.id,
        target_pos=tree.position,
        resource_type="wood",
        current_resource_id=tree.id.to_json(),
        pending_move_key=f"hut:{int(hut.id)}",
    )
    world.enqueue_command(settler.id, command)

    EconomySystem().update(world, 16)

    commands = world.command_queues[settler.id].commands
    assert [queued.type for queued in commands[:2]] == ["move", "gather"]
    assert commands[1] == command
    assert command.payload["hut_deposit_retry_count"] == 1
    assert world.notifications == []


def test_loaded_gatherer_chooses_nearest_hut_over_cached_hut() -> None:
    """Verify that each loaded resource trip refreshes the nearest deposit hut."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    old_hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    new_hut = _add_completed_hut(world, WorldPosition(1000, old_hut.position.y))
    old_position = hut_deposit_position(world, old_hut, settler.id)
    world.update_entity_position(settler.id, WorldPosition(800, old_position.y))
    settler.carry_type = "wood"
    settler.carry_amount = GATHER_CARRY_AMOUNT
    command = make_command(
        "gather",
        [settler.id],
        target_entity_id=tree.id,
        target_pos=tree.position,
        resource_type="wood",
        current_resource_id=tree.id.to_json(),
        deposit_hut_id=old_hut.id.to_json(),
        deposit_hut_x=old_position.x,
        deposit_hut_y=old_position.y,
    )
    world.enqueue_command(settler.id, command)

    EconomySystem().update(world, 16)

    commands = world.command_queues[settler.id].commands
    assert [queued.type for queued in commands[:2]] == ["move", "gather"]
    assert commands[0].target_pos == hut_deposit_position(world, new_hut, settler.id)
    assert command.payload["deposit_hut_id"] == new_hut.id.to_json()


def test_active_deposit_move_periodically_retargets_to_closest_hut() -> None:
    """Verify that walking deposit trips can switch to a closer completed hut."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    old_hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    new_hut = _add_completed_hut(world, WorldPosition(1000, old_hut.position.y))
    old_position = hut_deposit_position(world, old_hut, settler.id)
    world.update_entity_position(settler.id, WorldPosition(800, old_position.y))
    settler.carry_type = "wood"
    settler.carry_amount = GATHER_CARRY_AMOUNT
    gather_command = make_command(
        "gather",
        [settler.id],
        target_entity_id=tree.id,
        target_pos=tree.position,
        resource_type="wood",
        current_resource_id=tree.id.to_json(),
        pending_move_key=f"hut:{int(old_hut.id)}",
        deposit_hut_id=old_hut.id.to_json(),
        deposit_hut_x=old_position.x,
        deposit_hut_y=old_position.y,
        deposit_target_checked_ms=0,
    )
    move_command = make_command(
        "move",
        [settler.id],
        target_pos=old_position,
        gather_move=True,
    )
    queue = world.command_queues[settler.id]
    queue.commands = [move_command, gather_command]
    world.elapsed_ms = 2000

    EconomySystem(deposit_target_refresh_ms=1000).update(world, 16)

    commands = world.command_queues[settler.id].commands
    assert commands[0].type == "move"
    assert commands[0].target_pos == hut_deposit_position(world, new_hut, settler.id)
    assert gather_command.payload["pending_move_key"] == f"hut:{int(new_hut.id)}"
    assert gather_command.payload["deposit_hut_id"] == new_hut.id.to_json()


def test_completed_player_huts_are_the_only_deposit_hubs() -> None:
    """Verify that completed player huts are the only deposit hubs."""
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
    """Verify that auto gather avoids unsafe resource nodes."""
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
    assert message == "No safe iron source found."


def test_auto_gather_redistributes_settlers_across_safe_nodes() -> None:
    """Verify that auto gather redistributes settlers across safe nodes."""
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


def test_resource_node_cache_updates_when_nodes_are_added_and_removed() -> None:
    """Verify that resource node cache updates when nodes are added and removed."""
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)

    world.remove_entity(tree.id)

    assert tree.id not in world.resource_nodes_by_type["wood"]
    assert len(cached_active_resource_nodes(world, "wood")) == MAX_ACTIVE_TREES - 1

    replacement = _add_extra_resource_node(world, "wood", tree.position)

    assert replacement.id in world.resource_nodes_by_type["wood"]
    assert len(cached_active_resource_nodes(world, "wood")) == MAX_ACTIVE_TREES


def test_auto_gather_assignment_jobs_are_budgeted_across_frames() -> None:
    """Verify that auto gather assignment jobs are budgeted across frames."""
    world = create_demo_world()
    settlers = [entity for entity in world.entities.values() if "settler" in entity.tags]
    first = settlers[0]
    second = _add_settler_like(world, WorldPosition(first.position.x + 34, first.position.y))
    third = _add_settler_like(world, WorldPosition(first.position.x + 68, first.position.y))
    gatherer_ids = [first.id, second.id, third.id]
    system = EconomySystem(max_path_jobs_per_frame=2)

    message = system.queue_auto_gather(world, gatherer_ids, "wood")

    assert message is None
    assert all(not world.command_queues[gatherer_id].commands for gatherer_id in gatherer_ids)

    system.update(world, 16)

    assigned_after_first_frame = [
        gatherer_id
        for gatherer_id in gatherer_ids
        if world.command_queues[gatherer_id].commands
    ]
    assert len(assigned_after_first_frame) == 2
    assert system.last_frame_stats.path_jobs_processed == 2
    assert system.last_frame_stats.full_path_calculations <= (
        2 * MAX_RESOURCE_CANDIDATES_TO_PATHCHECK
    )

    system.update(world, 16)

    assert all(world.command_queues[gatherer_id].commands for gatherer_id in gatherer_ids)
    assert system.last_frame_stats.path_jobs_processed == 1


def test_destroyed_tree_respawns_after_exact_delay() -> None:
    """Verify that destroyed tree respawns after exact delay."""
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
    """Verify that tree respawn retries when active tree cap is full."""
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    system = EconomySystem()
    system.respawns.append(ResourceRespawn("wood", world.elapsed_ms, tree.position))

    system.update(world, 16)

    assert len(active_resource_nodes(world, "wood")) == MAX_ACTIVE_TREES
    assert len(system.respawns) == 1
    assert system.respawns[0].due_ms == world.elapsed_ms + RESPAWN_RETRY_MS


def test_wood_gatherer_waits_for_new_tree_when_none_are_active() -> None:
    """Verify that wood gatherer waits for new tree when none are active."""
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
    system.update(world, 16)

    commands = world.command_queues[settler.id].commands
    assert [command.type for command in commands[:2]] == ["move", "gather"]
    assert commands[1].payload["current_resource_id"] != tree.id.to_json()


def test_destroyed_mine_resource_respawns_after_exact_delay() -> None:
    """Verify that destroyed mine resource respawns after exact delay."""
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
    """Verify that mine respawn skips when resource type is at cap."""
    world = create_demo_world()
    gold = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
    system = EconomySystem()
    system.respawns.append(ResourceRespawn("gold", world.elapsed_ms, gold.position))

    system.update(world, 16)

    assert len(active_resource_nodes(world, "gold")) == 5
    assert system.respawns == []


def test_mine_respawn_retries_when_no_valid_spawn_location_exists() -> None:
    """Verify that mine respawn retries when no valid spawn location exists."""
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
    """Remove resource nodes test fixture data."""
    kept = keep_ids or set()
    for resource in list(active_resource_nodes(world, resource_type)):
        if resource.id in kept:
            continue
        world.remove_entity(resource.id)


def _add_settler_like(world, position: WorldPosition):
    """Add settler like test fixture data."""
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


def _add_completed_hut(world, position: WorldPosition) -> Building:
    """Add a completed drop-off hut test fixture."""
    template = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    hut = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=position,
        footprint=template.footprint,
        hp=template.max_hp,
        max_hp=template.max_hp,
        tags=template.tags,
        complete=True,
        functions=Building.production_functions(dropoff=True, population_cap_bonus=10),
        dropoff_point=template.dropoff_point,
    )
    world.add_entity(hut)
    return hut


def _add_extra_resource_node(
    world,
    resource_type: str,
    position: WorldPosition,
) -> ResourceNode:
    """Add extra resource node test fixture data."""
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
    """Return distance between two test positions."""
    return hypot(first.x - second.x, first.y - second.y)


def _point_in_bounds(position: WorldPosition, bounds: tuple[float, float, float, float]) -> bool:
    """Return whether a test position is inside bounds."""
    left, top, width, height = bounds
    return left <= position.x <= left + width and top <= position.y <= top + height

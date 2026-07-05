from __future__ import annotations

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.systems.combat import ATTACK_MOVE_CHASE_TIMEOUT_MS, CombatSystem
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.group_movement import issue_group_move_command
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.world.demo import create_demo_world


def test_attack_move_holds_position_and_fires_while_enemy_is_in_range() -> None:
    world = create_demo_world()
    attacker = next(entity for entity in world.entities.values() if "archer" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(attacker.position.x + 120, attacker.position.y),
    )
    starting_hp = enemy.hp
    starting_position = attacker.position

    issue_group_move_command(
        world,
        [attacker.id],
        WorldPosition(attacker.position.x + 500, attacker.position.y),
        attack_move=True,
    )
    combat = CombatSystem()
    movement = MovementSystem()
    combat.update(world, 16)
    movement.update(world, 16)

    command = world.command_queues[attacker.id].peek()
    assert enemy.hp == starting_hp - attacker.damage
    assert attacker.position == starting_position
    assert attacker.state == "attacking"
    assert command is not None
    assert command.payload["attack_move"] is True
    assert command.payload["pause_movement_until_ms"] > world.elapsed_ms


def test_direct_attack_command_fires_at_target_and_finishes_when_killed() -> None:
    world = create_demo_world()
    attacker = next(entity for entity in world.entities.values() if "archer" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(attacker.position.x + 120, attacker.position.y),
    )
    enemy.hp = 1

    world.enqueue_command(
        attacker.id,
        make_command("attack", [attacker.id], target_entity_id=enemy.id),
    )
    CombatSystem().update(world, 16)

    assert enemy.id not in world.entities
    assert world.command_queues[attacker.id].peek() is None
    assert attacker.state == "attacking"


def test_attack_move_chases_locked_target_when_enemy_is_out_of_range() -> None:
    world = create_demo_world()
    attacker = next(entity for entity in world.entities.values() if "spearman" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(attacker.position.x + 130, attacker.position.y),
    )
    start_x = attacker.position.x

    issue_group_move_command(
        world,
        [attacker.id],
        WorldPosition(attacker.position.x - 500, attacker.position.y),
        attack_move=True,
    )
    CombatSystem().update(world, 16)
    MovementSystem().update(world, 300)

    command = world.command_queues[attacker.id].peek()
    assert command is not None
    assert command.payload["attack_move_chase_target_id"] == enemy.id.to_json()
    assert attacker.position.x > start_x


def test_attack_move_gives_up_chase_after_no_contact_timeout() -> None:
    world = create_demo_world()
    attacker = next(entity for entity in world.entities.values() if "spearman" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    marker = WorldPosition(attacker.position.x - 500, attacker.position.y)
    world.update_entity_position(
        enemy.id,
        WorldPosition(attacker.position.x + 130, attacker.position.y),
    )

    issue_group_move_command(world, [attacker.id], marker, attack_move=True)
    combat = CombatSystem(chase_timeout_ms=ATTACK_MOVE_CHASE_TIMEOUT_MS)
    combat.update(world, 16)
    world.elapsed_ms += ATTACK_MOVE_CHASE_TIMEOUT_MS
    combat.update(world, 16)
    start_x = attacker.position.x
    MovementSystem().update(world, 300)

    command = world.command_queues[attacker.id].peek()
    assert command is not None
    assert "attack_move_chase_target_id" not in command.payload
    assert command.payload["attack_move_ignored_target_id"] == enemy.id.to_json()
    assert attacker.position.x < start_x


def test_attack_move_resumes_after_killing_enemy() -> None:
    world = create_demo_world()
    attacker = next(entity for entity in world.entities.values() if "spearman" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(attacker.position.x + 30, attacker.position.y),
    )
    enemy.hp = 1
    start_x = attacker.position.x

    issue_group_move_command(
        world,
        [attacker.id],
        WorldPosition(attacker.position.x + 500, attacker.position.y),
        attack_move=True,
    )
    CombatSystem().update(world, 16)
    MovementSystem().update(world, 300)

    assert enemy.id not in world.entities
    assert world.command_queues[attacker.id].peek() is not None
    assert attacker.position.x > start_x


def test_enemy_raider_chases_player_unit_inside_guard_sphere() -> None:
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    world.update_entity_position(
        settler.id,
        WorldPosition(raider.position.x - 130, raider.position.y),
    )
    start_x = raider.position.x

    CombatSystem().update(world, 500)

    assert raider.position.x < start_x
    assert raider.state == "moving"


def test_idle_friendly_ranged_unit_attacks_enemy_inside_guard_sphere() -> None:
    world = create_demo_world()
    archer = next(entity for entity in world.entities.values() if "archer" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(archer.position.x + 120, archer.position.y),
    )
    starting_hp = enemy.hp

    CombatSystem().update(world, 16)

    assert enemy.hp == starting_hp - archer.damage
    assert archer.state == "attacking"


def test_idle_friendly_melee_unit_chases_enemy_inside_guard_sphere() -> None:
    world = create_demo_world()
    spearman = next(entity for entity in world.entities.values() if "spearman" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(spearman.position.x + 130, spearman.position.y),
    )
    start_x = spearman.position.x

    CombatSystem().update(world, 500)

    assert spearman.position.x > start_x
    assert spearman.state == "moving"


def test_regular_move_command_does_not_trigger_idle_guard_attack() -> None:
    world = create_demo_world()
    archer = next(entity for entity in world.entities.values() if "archer" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(archer.position.x + 120, archer.position.y),
    )
    starting_hp = enemy.hp
    world.enqueue_command(
        archer.id,
        make_command(
            "move",
            [archer.id],
            target_pos=WorldPosition(archer.position.x - 200, archer.position.y),
        ),
    )

    CombatSystem().update(world, 16)

    command = world.command_queues[archer.id].peek()
    assert enemy.hp == starting_hp
    assert command is not None
    assert command.payload.get("attack_move") is not True


def test_gather_move_is_abandoned_when_enemy_can_attack_worker() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    for entity in world.entities.values():
        if "unit" in entity.tags and entity.owner == "frontier" and entity.id != settler.id:
            world.update_entity_position(
                entity.id,
                WorldPosition(settler.position.x - 320, settler.position.y),
            )
    world.update_entity_position(
        enemy.id,
        WorldPosition(settler.position.x + enemy.attack_range, settler.position.y),
    )
    starting_hp = enemy.hp
    world.enqueue_command(
        settler.id,
        make_command(
            "move",
            [settler.id],
            target_pos=WorldPosition(settler.position.x + 200, settler.position.y),
            gather_move=True,
        ),
    )

    CombatSystem().update(world, 16)

    assert world.command_queues[settler.id].peek() is None
    assert enemy.hp == starting_hp - settler.damage
    assert settler.state == "attacking"


def test_enemy_raider_deals_melee_damage_when_player_unit_is_in_range() -> None:
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    world.update_entity_position(
        settler.id,
        WorldPosition(raider.position.x - 30, raider.position.y),
    )
    starting_hp = settler.hp

    CombatSystem().update(world, 16)

    assert settler.hp == starting_hp - raider.damage
    assert raider.state == "attacking"

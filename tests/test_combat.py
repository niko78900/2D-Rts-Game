from __future__ import annotations

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.systems.buildings import (
    BUILDING_DESTRUCTION_MS,
    BuildingLifecycleSystem,
    start_building_destruction,
)
from house_of_wolves.systems.combat import (
    ATTACK_MOVE_CHASE_TIMEOUT_MS,
    MELEE_ATTACK_WINDUP_MS,
    RANGED_ATTACK_WINDUP_MS,
    UNIT_FALL_EFFECT_MS,
    CombatSystem,
)
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.group_movement import issue_group_move_command
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.systems.production import create_combat_unit
from house_of_wolves.world.demo import create_demo_world


def test_attack_move_holds_position_and_fires_while_enemy_is_in_range() -> None:
    """Verify that attack move holds position and fires while enemy is in range."""
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
    assert enemy.hp == starting_hp
    assert attacker.position == starting_position
    assert attacker.state == "attack_windup"
    assert command is not None
    assert command.payload["attack_move"] is True
    assert command.payload["pause_movement_until_ms"] > world.elapsed_ms

    combat.update(world, RANGED_ATTACK_WINDUP_MS)
    assert enemy.hp == starting_hp
    assert len(world.projectiles) == 1

    combat.update(world, 250)
    assert enemy.hp == starting_hp - attacker.damage
    assert not world.projectiles


def test_direct_attack_command_fires_at_target_and_finishes_when_killed() -> None:
    """Verify that direct attack command fires at target and finishes when killed."""
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
    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, RANGED_ATTACK_WINDUP_MS)

    assert enemy.id in world.entities
    assert enemy.hp == 1
    assert len(world.projectiles) == 1

    combat.update(world, 250)

    assert enemy.id not in world.entities
    assert world.command_queues[attacker.id].peek() is None
    fall = next(effect for effect in world.combat_effects if effect.kind == "unit_fall")
    assert fall.direction_x > 0
    assert "enemy" in fall.visual_tags
    assert not any(effect.kind == "death_burst" for effect in world.combat_effects)


def test_attack_move_chases_locked_target_when_enemy_is_out_of_range() -> None:
    """Verify that attack move chases locked target when enemy is out of range."""
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
    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, MELEE_ATTACK_WINDUP_MS)
    MovementSystem().update(world, 300)

    command = world.command_queues[attacker.id].peek()
    assert command is not None
    assert command.payload["attack_move_chase_target_id"] == enemy.id.to_json()
    assert attacker.position.x > start_x


def test_attack_move_gives_up_chase_after_no_contact_timeout() -> None:
    """Verify that attack move gives up chase after no contact timeout."""
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
    """Verify that attack move resumes after killing enemy."""
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
    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, MELEE_ATTACK_WINDUP_MS)
    MovementSystem().update(world, 300)

    assert enemy.id not in world.entities
    assert world.command_queues[attacker.id].peek() is not None
    assert attacker.position.x > start_x


def test_enemy_raider_chases_player_unit_inside_guard_sphere() -> None:
    """Verify that enemy raider chases player unit inside guard sphere."""
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


def test_idle_enemy_base_pressure_uses_blocker_aware_move_command() -> None:
    """Verify that idle enemy pressure routes through movement path planning."""
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)

    CombatSystem().update(world, 16)

    command = world.command_queues[raider.id].peek()
    assert command is not None
    assert command.type == "move"
    assert command.target_pos == hut.position
    assert command.payload["attack_move"] is True
    assert command.payload["wave_attack"] is True
    assert raider.state == "moving"


def test_idle_friendly_ranged_unit_attacks_enemy_inside_guard_sphere() -> None:
    """Verify that idle friendly ranged unit attacks enemy inside guard sphere."""
    world = create_demo_world()
    archer = next(entity for entity in world.entities.values() if "archer" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(archer.position.x + 120, archer.position.y),
    )
    starting_hp = enemy.hp

    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, RANGED_ATTACK_WINDUP_MS)

    assert enemy.hp == starting_hp
    assert len(world.projectiles) == 1

    combat.update(world, 250)

    assert enemy.hp == starting_hp - archer.damage
    assert archer.state == "attack_cooldown"


def test_idle_friendly_melee_unit_chases_enemy_inside_guard_sphere() -> None:
    """Verify that idle friendly melee unit chases enemy inside guard sphere."""
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
    """Verify that regular move command does not trigger idle guard attack."""
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
    """Verify that gather move is abandoned when enemy can attack worker."""
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

    combat = CombatSystem()
    combat.update(world, 16)

    assert world.command_queues[settler.id].peek() is None
    assert enemy.hp == starting_hp

    combat.update(world, RANGED_ATTACK_WINDUP_MS)

    assert enemy.hp == starting_hp
    assert any(projectile.source_entity_id == settler.id for projectile in world.projectiles)

    combat.update(world, 250)

    assert enemy.hp == starting_hp - settler.damage
    assert settler.state == "attack_cooldown"


def test_enemy_raider_deals_melee_damage_when_player_unit_is_in_range() -> None:
    """Verify that enemy raider deals melee damage when player unit is in range."""
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    world.update_entity_position(
        settler.id,
        WorldPosition(raider.position.x - 30, raider.position.y),
    )
    starting_hp = settler.hp

    combat = CombatSystem()
    combat.update(world, 16)
    assert settler.hp == starting_hp

    combat.update(world, MELEE_ATTACK_WINDUP_MS)

    assert settler.hp == starting_hp - raider.damage
    assert raider.state == "attacking"


def test_enemy_unit_can_damage_player_building() -> None:
    """Verify that enemy combat units start building destruction."""
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    building = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(raider.position.x + 30, raider.position.y),
        footprint=Footprint(80, 80),
        hp=1,
        max_hp=100,
        tags=("building", "test_target", "selectable"),
        complete=True,
    )
    world.add_entity(building)

    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, MELEE_ATTACK_WINDUP_MS)

    assert building.id in world.entities
    assert building.alive is False
    assert building.complete is False
    assert building.destruction_remaining_ms == BUILDING_DESTRUCTION_MS
    assert building.id not in world.hard_obstacle_ids
    assert not any(effect.kind == "unit_fall" for effect in world.combat_effects)


def test_destroying_building_is_removed_after_visual_timer() -> None:
    """Verify that building rubble is removed after its destruction timer."""
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    building = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(raider.position.x + 30, raider.position.y),
        footprint=Footprint(80, 80),
        hp=1,
        max_hp=100,
        tags=("building", "test_target", "selectable"),
        complete=True,
    )
    world.add_entity(building)

    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, MELEE_ATTACK_WINDUP_MS)
    BuildingLifecycleSystem().update(world, BUILDING_DESTRUCTION_MS)

    assert building.id not in world.entities


def test_destroyed_hut_stops_granting_deposit_and_population() -> None:
    """Verify that a visually destroying hut is already non-functional."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    assert world.max_population > 0
    assert hut.id in world.completed_deposit_huts_by_owner["frontier"]

    start_building_destruction(world, hut)

    assert hut.alive is False
    assert world.max_population == 0
    assert world.completed_deposit_huts_by_owner.get("frontier", []) == []


def test_attack_move_enemy_damages_building_from_footprint_edge() -> None:
    """Verify that wave-style attack move can hit a building wall edge."""
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    building = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(raider.position.x - 92, raider.position.y),
        footprint=Footprint(150, 116),
        hp=1,
        max_hp=650,
        tags=("building", "hut", "selectable"),
        complete=True,
    )
    world.add_entity(building)
    world.enqueue_command(
        raider.id,
        make_command(
            "move",
            [raider.id],
            target_pos=WorldPosition(raider.position.x - 220, raider.position.y),
            attack_move=True,
            wave_attack=True,
        ),
    )

    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, MELEE_ATTACK_WINDUP_MS)

    assert building.id in world.entities
    assert building.alive is False
    assert building.destruction_remaining_ms == BUILDING_DESTRUCTION_MS
    assert raider.state == "attacking"


def test_enemy_archer_uses_projectile_damage_on_impact() -> None:
    """Verify enemy ranged damage waits for an arrow to reach its target."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    enemy_archer = create_combat_unit(
        world,
        "enemy_archer",
        "wolves",
        WorldPosition(settler.position.x + 120, settler.position.y),
    )
    world.add_entity(enemy_archer)
    world.enqueue_command(
        enemy_archer.id,
        make_command("attack", [enemy_archer.id], target_entity_id=settler.id),
    )
    starting_hp = settler.hp
    combat = CombatSystem()

    combat.update(world, 16)
    combat.update(world, RANGED_ATTACK_WINDUP_MS)

    assert settler.hp == starting_hp
    enemy_arrows = [
        projectile for projectile in world.projectiles if projectile.owner == "wolves"
    ]
    assert len(enemy_arrows) == 1

    combat.update(world, 250)

    assert settler.hp == starting_hp - enemy_archer.damage
    assert not world.projectiles


def test_enemy_arrow_from_right_makes_player_unit_fall_left() -> None:
    """Verify projectile travel direction controls the victim's fall side."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    for entity in world.entities.values():
        if (
            "unit" in entity.tags
            and entity.owner == "frontier"
            and entity.id != settler.id
        ):
            world.update_entity_position(
                entity.id,
                WorldPosition(settler.position.x - 400, settler.position.y),
            )
    enemy_archer = create_combat_unit(
        world,
        "enemy_archer",
        "wolves",
        WorldPosition(settler.position.x + 120, settler.position.y),
    )
    world.add_entity(enemy_archer)
    settler.hp = 1
    world.enqueue_command(
        enemy_archer.id,
        make_command("attack", [enemy_archer.id], target_entity_id=settler.id),
    )
    combat = CombatSystem()

    combat.update(world, 16)
    combat.update(world, RANGED_ATTACK_WINDUP_MS)
    combat.update(world, 250)

    assert settler.id not in world.entities
    fall = next(effect for effect in world.combat_effects if effect.kind == "unit_fall")
    assert fall.direction_x < 0


def test_arrow_flies_to_last_known_position_when_target_disappears() -> None:
    """Verify a stale projectile expires safely without retargeting or damage."""
    world = create_demo_world()
    archer = next(entity for entity in world.entities.values() if "archer" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(archer.position.x + 180, archer.position.y),
    )
    world.enqueue_command(
        archer.id,
        make_command("attack", [archer.id], target_entity_id=enemy.id),
    )
    combat = CombatSystem()
    combat.update(world, 16)
    combat.update(world, RANGED_ATTACK_WINDUP_MS)
    assert len(world.projectiles) == 1

    world.remove_entity(enemy.id)
    combat.update(world, 1000)

    assert not world.projectiles
    assert world.performance_stats.counters.projectile_hits == 0


def test_settler_arrow_expires_safely_when_target_disappears() -> None:
    """Verify settler combat uses the same stale-target projectile behavior."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(settler.position.x + 100, settler.position.y),
    )
    world.enqueue_command(
        settler.id,
        make_command("attack", [settler.id], target_entity_id=enemy.id),
    )
    combat = CombatSystem()

    combat.update(world, 16)
    combat.update(world, RANGED_ATTACK_WINDUP_MS)

    settler_arrows = [
        projectile
        for projectile in world.projectiles
        if projectile.source_entity_id == settler.id
    ]
    assert len(settler_arrows) == 1

    world.remove_entity(enemy.id)
    combat.update(world, 1000)

    assert not any(
        projectile.source_entity_id == settler.id
        for projectile in world.projectiles
    )


def test_archer_windup_spawns_only_one_arrow_per_attack_cycle() -> None:
    """Verify repeated combat updates cannot duplicate a pending ranged shot."""
    world = create_demo_world()
    archer = next(entity for entity in world.entities.values() if "archer" in entity.tags)
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
    world.update_entity_position(
        enemy.id,
        WorldPosition(archer.position.x + 120, archer.position.y),
    )
    world.enqueue_command(
        archer.id,
        make_command("attack", [archer.id], target_entity_id=enemy.id),
    )
    combat = CombatSystem()

    combat.update(world, 16)
    combat.update(world, RANGED_ATTACK_WINDUP_MS - 1)
    assert not world.projectiles

    combat.update(world, 1)
    assert len(world.projectiles) == 1

    combat.update(world, 16)
    assert len(world.projectiles) == 1


def test_player_unit_death_cleans_population_indexes_and_adds_effect() -> None:
    """Verify dead units leave gameplay immediately while their visual remains."""
    world = create_demo_world()
    raider = next(entity for entity in world.entities.values() if "raider_swordsman" in entity.tags)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    for entity in world.entities.values():
        if (
            "unit" in entity.tags
            and entity.owner == "frontier"
            and entity.id != settler.id
        ):
            world.update_entity_position(
                entity.id,
                WorldPosition(settler.position.x - 400, settler.position.y),
            )
    world.update_entity_position(
        settler.id,
        WorldPosition(raider.position.x - 30, raider.position.y),
    )
    settler.hp = 1
    starting_population = world.current_population
    combat = CombatSystem()

    combat.update(world, 16)
    combat.update(world, MELEE_ATTACK_WINDUP_MS)

    assert settler.id not in world.entities
    assert settler.id not in world.unit_ids
    assert settler.id not in world.command_queues
    assert world.current_population == starting_population - settler.population_cost
    fall = next(effect for effect in world.combat_effects if effect.kind == "unit_fall")
    assert fall.direction_x < 0
    assert "settler" in fall.visual_tags

    combat.update(world, UNIT_FALL_EFFECT_MS)

    assert not any(effect.kind == "unit_fall" for effect in world.combat_effects)

from __future__ import annotations

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.core.runtime import BUILD_MENU_ABILITIES, GameRuntime
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.building import Building
from house_of_wolves.systems.combat import CombatSystem
from house_of_wolves.systems.construction import starting_construction_hp
from house_of_wolves.systems.production import create_combat_unit
from house_of_wolves.systems.towers import (
    STONE_ARCHER_TOWER_ID,
    TOWER_SPECS,
    WIZARD_TOWER_ID,
    WOODEN_ARCHER_TOWER_ID,
    TowerCombatSystem,
    tower_functions_for,
)
from house_of_wolves.ui.selected_panel import selected_panel_for
from house_of_wolves.world.demo import create_demo_world


def test_settler_build_menu_exposes_towers() -> None:
    """Verify defensive towers are available from the settler build menu."""
    assert "Wooden Archer Tower" in BUILD_MENU_ABILITIES
    assert "Stone Archer Tower" in BUILD_MENU_ABILITIES
    assert "Wizard Tower" in BUILD_MENU_ABILITIES


def test_runtime_creates_tower_construction_site() -> None:
    """Verify tower placement creates an incomplete hard-blocking building."""
    runtime = GameRuntime(AppSettings())
    site = runtime._create_building_construction_site(  # noqa: SLF001 - integration seam
        WOODEN_ARCHER_TOWER_ID,
        WorldPosition(1200, 300),
    )
    spec = TOWER_SPECS[WOODEN_ARCHER_TOWER_ID]

    assert site.complete is False
    assert site.hp == starting_construction_hp(spec.hp)
    assert site.max_hp == spec.hp
    assert {"building", "tower", WOODEN_ARCHER_TOWER_ID}.issubset(site.tags)
    assert site.id in runtime.world.hard_obstacle_ids
    assert site.functions["tower"] is True


def test_incomplete_tower_does_not_attack() -> None:
    """Verify construction sites cannot fire before completion."""
    world = create_demo_world()
    tower = _add_tower(world, WOODEN_ARCHER_TOWER_ID, complete=False)
    _add_enemy(world, tower.position.x + 40, tower.position.y)

    TowerCombatSystem().update(world, 500)

    assert not world.projectiles


def test_completed_wooden_archer_tower_fires_one_arrow() -> None:
    """Verify wooden archer tower launches one arrow at an enemy in range."""
    world = create_demo_world()
    tower = _add_tower(world, WOODEN_ARCHER_TOWER_ID)
    enemy = _add_enemy(world, tower.position.x + 60, tower.position.y)
    system = TowerCombatSystem()

    system.update(world, 16)
    system.update(world, TOWER_SPECS[WOODEN_ARCHER_TOWER_ID].windup_ms)

    assert len(world.projectiles) == 1
    assert world.projectiles[0].target_entity_id == enemy.id
    assert "arrow" in world.projectiles[0].tags


def test_completed_stone_archer_tower_fires_two_arrows() -> None:
    """Verify stone archer tower uses its double-shot behavior."""
    world = create_demo_world()
    tower = _add_tower(world, STONE_ARCHER_TOWER_ID)
    _add_enemy(world, tower.position.x + 60, tower.position.y)
    system = TowerCombatSystem()

    system.update(world, 16)
    system.update(world, TOWER_SPECS[STONE_ARCHER_TOWER_ID].windup_ms)

    assert len(world.projectiles) == 2
    assert all("arrow" in projectile.tags for projectile in world.projectiles)


def test_completed_wizard_tower_fires_magic_projectile() -> None:
    """Verify wizard tower launches a magic projectile and cast effect."""
    world = create_demo_world()
    tower = _add_tower(world, WIZARD_TOWER_ID)
    _add_enemy(world, tower.position.x + 80, tower.position.y)
    system = TowerCombatSystem()

    system.update(world, 16)
    system.update(world, TOWER_SPECS[WIZARD_TOWER_ID].windup_ms)

    assert len(world.projectiles) == 1
    assert "magic" in world.projectiles[0].tags
    assert any(effect.kind == "magic_cast" for effect in world.combat_effects)


def test_tower_projectile_damage_applies_on_impact() -> None:
    """Verify tower projectile damage uses the shared projectile resolver."""
    world = create_demo_world()
    tower = _add_tower(world, WOODEN_ARCHER_TOWER_ID)
    enemy = _add_enemy(world, tower.position.x + 35, tower.position.y)
    starting_hp = enemy.hp
    tower_system = TowerCombatSystem()

    tower_system.update(world, 16)
    tower_system.update(world, TOWER_SPECS[WOODEN_ARCHER_TOWER_ID].windup_ms)
    CombatSystem().update(world, 500)

    assert enemy.hp == starting_hp - TOWER_SPECS[WOODEN_ARCHER_TOWER_ID].damage


def test_towers_ignore_friendly_units() -> None:
    """Verify towers do not target player-owned units."""
    world = create_demo_world()
    tower = _add_tower(world, WOODEN_ARCHER_TOWER_ID)
    friendly = create_combat_unit(
        world,
        "spearman",
        "frontier",
        WorldPosition(tower.position.x + 50, tower.position.y),
    )
    world.add_entity(friendly)

    TowerCombatSystem().update(world, 500)

    assert not world.projectiles
    assert tower.functions.get("tower_target_id") is None


def test_selected_panel_shows_completed_tower_stats() -> None:
    """Verify selected tower details expose combat state and stats."""
    world = create_demo_world()
    tower = _add_tower(world, WIZARD_TOWER_ID)

    panel = selected_panel_for(world, [tower.id])

    assert panel.title == "Wizard Tower"
    assert "State: Idle" in panel.details
    assert "Damage: 18 x 1" in panel.details
    assert "Range: 320" in panel.details
    assert panel.abilities == ()


def _add_tower(
    world: object,
    tower_id: str,
    *,
    complete: bool = True,
) -> Building:
    """Add a configured tower test fixture."""
    spec = TOWER_SPECS[tower_id]
    tower = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(1000, 360),
        footprint=spec.footprint,
        hp=spec.hp if complete else starting_construction_hp(spec.hp),
        max_hp=spec.hp,
        tags=("building", tower_id, "tower", "selectable"),
        build_time_ms=spec.build_time_ms,
        build_progress_ms=spec.build_time_ms if complete else 0,
        complete=complete,
        functions=tower_functions_for(spec),
    )
    world.add_entity(tower)
    return tower


def _add_enemy(world: object, x: float, y: float) -> object:
    """Add an enemy swordsman test fixture near a tower."""
    enemy = create_combat_unit(
        world,
        "enemy_swordsman",
        "wolves",
        WorldPosition(x, y),
    )
    enemy.footprint = Footprint(38, 58)
    world.add_entity(enemy)
    return enemy

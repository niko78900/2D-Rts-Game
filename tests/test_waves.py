from __future__ import annotations

from house_of_wolves.core.renderer import wave_timer_text
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.systems.waves import WaveSystem, wave_composition_for
from house_of_wolves.world.demo import create_demo_world


def test_wave_system_starts_timer_and_spawns_first_wave() -> None:
    """Verify that timer-based waves spawn the first enemy composition."""
    world = create_demo_world(
        AppSettings(initial_wave_delay_seconds=1, wave_timer_seconds=120)
    )
    starting_ids = set(world.entities)
    starting_enemy_count = sum(
        entity.owner == "wolves" for entity in world.entities.values()
    )

    wave_system = WaveSystem()
    wave_system.update(world, 0)
    world.elapsed_ms = 1000
    wave_system.update(world, 0)

    enemies = [entity for entity in world.entities.values() if entity.owner == "wolves"]
    spawned_enemies = [entity for entity in enemies if entity.id not in starting_ids]
    spawned = len(enemies) - starting_enemy_count
    assert spawned == 2
    assert world.wave_number == 1
    assert world.next_wave_due_ms == world.elapsed_ms + 120_000
    assert world.notifications[-1].message == "Enemy wave incoming!"
    assert all(world.command_queues[enemy.id].peek() is not None for enemy in spawned_enemies)


def test_wave_system_respects_disabled_waves() -> None:
    """Verify that disabling waves prevents automatic spawns."""
    world = create_demo_world(AppSettings(waves_enabled=False, initial_wave_delay_seconds=1))
    starting_enemy_count = sum(
        entity.owner == "wolves" for entity in world.entities.values()
    )

    WaveSystem().update(world, 1000)

    assert sum(entity.owner == "wolves" for entity in world.entities.values()) == (
        starting_enemy_count
    )
    assert world.wave_number == 0


def test_start_wave_now_spawns_archers_on_later_waves() -> None:
    """Verify that manual wave spawning uses scaling compositions."""
    world = create_demo_world()
    wave_system = WaveSystem()

    wave_system.start_wave_now(world)
    wave_system.start_wave_now(world)
    spawned_ids = wave_system.start_wave_now(world)

    spawned = [world.entities[entity_id] for entity_id in spawned_ids]
    assert wave_composition_for(3).archers == 1
    assert any("enemy_archer" in entity.tags for entity in spawned)
    assert any(effect.kind == "spawn_marker" for effect in world.combat_effects)


def test_wave_system_spawns_enemies_from_right_side_only() -> None:
    """Verify that wave units enter from the eastern side of the world."""
    world = create_demo_world()
    spawned_ids = WaveSystem().start_wave_now(world)

    spawned = [world.entities[entity_id] for entity_id in spawned_ids]
    right_side_threshold = world.settings.world_width - 500
    assert all(entity.position.x >= right_side_threshold for entity in spawned)


def test_wave_timer_text_reports_disabled_and_countdown_states() -> None:
    """Verify that the HUD wave timer text reflects wave state."""
    disabled = create_demo_world(AppSettings(waves_enabled=False))
    enabled = create_demo_world(AppSettings(initial_wave_delay_seconds=120))

    assert wave_timer_text(disabled) == "Waves Off"
    assert wave_timer_text(enabled) == "Next wave: 02:00"

from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from house_of_wolves.core.app import main
from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.core.keybindings import (
    KEYBIND_BUILD,
    KEYBIND_COMMAND_SLOT_1,
    KEYBIND_COMMAND_SLOT_5,
    KEYBIND_COMMAND_SLOT_7,
    KEYBIND_GATHER_GOLD,
)
from house_of_wolves.core.runtime import GameRuntime, _desktop_size_for_display
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.combat_unit import CombatUnit
from house_of_wolves.systems.commands import make_command
from house_of_wolves.ui.selected_panel import selected_panel_for
from house_of_wolves.world.terrain import (
    clamp_unit_position_to_walkable_lane_for_height,
    terrain_layout_for_height,
)

BUILD_MENU_EXPECTED = (
    "Hut",
    "Barracks",
    "Archery",
    "Chicken Farm",
    "Pig Farm",
    "Wooden Archer Tower",
    "Stone Archer Tower",
    "Wizard Tower",
)


def ability_center(runtime: GameRuntime, label: str) -> tuple[int, int]:
    """Provide test helper logic for ability center."""
    assert runtime.screen is not None
    assert runtime.renderer is not None
    panel = selected_panel_for(runtime.world, runtime.selection_system.state.selected_ids)
    button = next(
        button for button in runtime.renderer.ability_buttons_for_panel(runtime.screen, panel)
        if button.label == label
    )
    return button.rect.center


def override_ability_center(
    runtime: GameRuntime,
    label: str,
    abilities: tuple[str, ...],
) -> tuple[int, int]:
    """Provide test helper logic for override ability center."""
    assert runtime.screen is not None
    assert runtime.renderer is not None
    panel = selected_panel_for(runtime.world, runtime.selection_system.state.selected_ids)
    button = next(
        button for button in runtime.renderer.ability_buttons_for_panel(
            runtime.screen,
            panel,
            abilities,
        )
        if button.label == label
    )
    return button.rect.center


def selected_settler(runtime: GameRuntime) -> object:
    """Provide test helper logic for selected settler."""
    return next(entity for entity in runtime.world.entities.values() if "settler" in entity.tags)


def add_settler(runtime: GameRuntime, x: float, y: float) -> CombatUnit:
    """Provide test helper logic for add settler."""
    settler = CombatUnit(
        id=runtime.world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(x, y),
        footprint=Footprint(38, 58),
        hp=40,
        max_hp=40,
        tags=("unit", "settler", "selectable", "movable"),
        speed=92,
        attack_range=115,
        damage=6,
        attack_cooldown_ms=900,
    )
    runtime.world.add_entity(settler)
    return settler


def test_validate_cli_mode_keeps_data_validation_behavior(capsys) -> None:
    """Verify that validate cli mode keeps data validation behavior."""
    assert main(["--validate"]) == 0

    output = capsys.readouterr().out
    assert "House of Wolves scaffold validated" in output
    assert "units=11" in output


def test_runtime_initializes_updates_renders_and_shuts_down_windowless() -> None:
    """Verify that runtime initializes updates renders and shuts down windowless."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        runtime.update(16)
        runtime.render()

        assert runtime.screen is not None
        assert isinstance(runtime.screen, pygame.Surface)
    finally:
        runtime.shutdown()


def test_runtime_default_mode_is_borderless_on_primary_display() -> None:
    """Verify that runtime default mode is borderless on primary display."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.settings.fullscreen is False
        assert runtime.settings.display_index == 0
        assert runtime.screen.get_size() == runtime.settings.virtual_size
        assert runtime.display_flags & pygame.NOFRAME
        assert runtime.world.settings.world_height == runtime.screen.get_height()
    finally:
        runtime.shutdown()


def test_default_command_slots_do_not_use_camera_pan_keys() -> None:
    """Verify that default command slots do not use camera pan keys."""
    keybindings = AppSettings().keybindings

    assert keybindings[KEYBIND_COMMAND_SLOT_5] == "z"
    assert keybindings[KEYBIND_COMMAND_SLOT_7] == "x"
    assert "a" not in keybindings.values()
    assert "d" not in keybindings.values()


def test_runtime_control_group_assign_and_recall() -> None:
    """Verify that runtime control group assign and recall."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [
            entity
            for entity in runtime.world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ][:2]
        runtime.selection_system.state.replace([unit.id for unit in units])

        runtime.handle_event(
            pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_1, "mod": pygame.KMOD_CTRL})
        )
        runtime.selection_system.state.clear()
        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_1, "mod": 0}))

        assert runtime.selection_system.state.selected_ids == [unit.id for unit in units]
    finally:
        runtime.shutdown()


def test_runtime_double_click_selects_visible_same_type_units() -> None:
    """Verify that runtime double click selects visible same type units."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        first = selected_settler(runtime)
        second = add_settler(runtime, first.position.x + 72, first.position.y)
        screen_pos = runtime.world.camera.world_to_screen(first.position)

        for _ in range(2):
            runtime.handle_event(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": screen_pos})
            )
            runtime.handle_event(
                pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1, "pos": screen_pos})
            )

        assert runtime.selection_system.state.selected_ids == [first.id, second.id]
    finally:
        runtime.shutdown()


def test_runtime_borderless_uses_monitor_desktop_size() -> None:
    """Verify that runtime borderless uses monitor desktop size."""
    runtime = GameRuntime(AppSettings(fullscreen=False, virtual_width=960, virtual_height=540))

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.screen.get_size() == _desktop_size_for_display(
            runtime.settings.display_index,
            (960, 540),
        )
        assert runtime.screen.get_size() == runtime.settings.virtual_size
        assert runtime.world.camera.viewport_width == runtime.screen.get_width()
        assert runtime.world.camera.viewport_height == runtime.screen.get_height()
    finally:
        runtime.shutdown()


def test_runtime_fullscreen_mode_uses_display_size_for_world_height() -> None:
    """Verify that runtime fullscreen mode uses display size for world height."""
    runtime = GameRuntime(AppSettings(fullscreen=True))

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.settings.fullscreen is True
        assert runtime.settings.virtual_size == runtime.screen.get_size()
        assert runtime.world.settings.world_height == runtime.screen.get_height()
        assert runtime.world.camera.viewport_height == runtime.screen.get_height()
    finally:
        runtime.shutdown()

def test_runtime_settings_menu_toggles_fullscreen_from_borderless_mode() -> None:
    """Verify that runtime settings menu toggles fullscreen from borderless mode."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        assert runtime.settings_menu_open is True
        borderless_size = runtime.screen.get_size()

        toggle_center = runtime.renderer.settings_display_toggle_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": toggle_center})
        )

        assert runtime.settings.fullscreen is True
        assert runtime.screen.get_size() == borderless_size
        assert runtime.settings.virtual_size == borderless_size
        assert runtime.settings_menu_open is False
        assert runtime.display_flags & pygame.FULLSCREEN
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_toggles_resource_hitbox_debug_rendering() -> None:
    """Verify that runtime settings menu toggles resource hitbox debug rendering."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        assert runtime.settings.show_resource_hitboxes is False

        toggle_center = runtime.renderer.settings_resource_hitboxes_toggle_rect(
            runtime.screen
        ).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": toggle_center})
        )

        assert runtime.settings.show_resource_hitboxes is True
        assert runtime.world.settings.show_resource_hitboxes is True
        assert runtime.renderer.settings.show_resource_hitboxes is True
        assert runtime.settings_menu_open is True
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_toggles_unit_and_building_hitbox_debug_rendering() -> None:
    """Verify that runtime settings menu toggles unit and building hitbox debug rendering."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        assert runtime.settings.show_unit_hitboxes is False
        assert runtime.settings.show_building_hitboxes is False

        unit_toggle_center = runtime.renderer.settings_unit_hitboxes_toggle_rect(
            runtime.screen
        ).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": unit_toggle_center})
        )

        building_toggle_center = runtime.renderer.settings_building_hitboxes_toggle_rect(
            runtime.screen
        ).center
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": building_toggle_center},
            )
        )

        assert runtime.settings.show_unit_hitboxes is True
        assert runtime.world.settings.show_unit_hitboxes is True
        assert runtime.renderer.settings.show_unit_hitboxes is True
        assert runtime.settings.show_building_hitboxes is True
        assert runtime.world.settings.show_building_hitboxes is True
        assert runtime.renderer.settings.show_building_hitboxes is True
        assert runtime.settings_menu_open is True
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_toggles_and_starts_enemy_waves() -> None:
    """Verify that runtime settings controls toggle and manually start waves."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        toggle_center = runtime.renderer.settings_waves_toggle_rect(runtime.screen).center
        timer_center = runtime.renderer.settings_wave_timer_toggle_rect(runtime.screen).center
        start_center = runtime.renderer.settings_start_wave_rect(runtime.screen).center

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": toggle_center})
        )

        assert runtime.settings.waves_enabled is False
        assert runtime.world.settings.waves_enabled is False

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": timer_center})
        )

        assert runtime.settings.wave_timer_enabled is False
        assert runtime.world.settings.wave_timer_enabled is False

        starting_enemy_ids = {
            entity.id for entity in runtime.world.entities.values() if entity.owner == "wolves"
        }
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": start_center})
        )

        spawned_enemy_ids = {
            entity.id for entity in runtime.world.entities.values() if entity.owner == "wolves"
        } - starting_enemy_ids
        assert len(spawned_enemy_ids) == 2
        assert runtime.world.wave_number == 1
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_grants_debug_resources() -> None:
    """Verify that settings resource buttons add debug resources."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        starting = {
            resource_key: runtime.world.resources.get(resource_key, 0)
            for resource_key in ("wood", "food", "stone", "iron", "gold")
        }

        for resource_key in starting:
            button_center = runtime.renderer.settings_resource_grant_rect(
                runtime.screen,
                resource_key,
            ).center
            runtime.handle_event(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": button_center})
            )

        assert runtime.world.resources["wood"] == starting["wood"] + 10
        assert runtime.world.resources["food"] == starting["food"] + 10
        assert runtime.world.resources["stone"] == starting["stone"] + 10
        assert runtime.world.resources["iron"] == starting["iron"] + 10
        assert runtime.world.resources["gold"] == starting["gold"] + 10
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_toggles_debug_waypoint_rendering() -> None:
    """Verify that runtime settings menu toggles debug waypoint rendering."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        assert runtime.settings.show_debug_waypoints is False

        toggle_center = runtime.renderer.settings_debug_waypoints_toggle_rect(
            runtime.screen
        ).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": toggle_center})
        )

        assert runtime.settings.show_debug_waypoints is True
        assert runtime.world.settings.show_debug_waypoints is True
        assert runtime.renderer.settings.show_debug_waypoints is True
        assert runtime.settings_menu_open is True
    finally:
        runtime.shutdown()


def test_runtime_toggles_performance_overlay_from_hotkey_and_settings_menu() -> None:
    """Verify that runtime toggles performance overlay from hotkey and settings menu."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        assert runtime.settings.show_performance_overlay is False

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_F3}))

        assert runtime.settings.show_performance_overlay is True
        assert runtime.world.settings.show_performance_overlay is True
        assert runtime.renderer.settings.show_performance_overlay is True

        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        toggle_center = runtime.renderer.settings_performance_overlay_toggle_rect(
            runtime.screen
        ).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": toggle_center})
        )

        assert runtime.settings.show_performance_overlay is False
        assert runtime.world.settings.show_performance_overlay is False
        assert runtime.renderer.settings.show_performance_overlay is False
        assert runtime.settings_menu_open is True
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_toggles_debug_hit_flashes() -> None:
    """Verify hit flashes remain default-off and propagate through runtime settings."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        assert runtime.settings.show_debug_hit_flashes is False

        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": settings_center},
            )
        )
        toggle_center = runtime.renderer.settings_hit_flashes_toggle_rect(
            runtime.screen
        ).center
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": toggle_center},
            )
        )

        assert runtime.settings.show_debug_hit_flashes is True
        assert runtime.world.settings.show_debug_hit_flashes is True
        assert runtime.renderer.settings.show_debug_hit_flashes is True
        assert runtime.settings_menu_open is True
    finally:
        runtime.shutdown()


def test_runtime_clicking_hut_produce_button_spawns_unit() -> None:
    """Verify that runtime clicking hut produce button spawns unit."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])
        unit_count = sum("unit" in entity.tags for entity in runtime.world.entities.values())

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Train Settler")},
            )
        )

        assert (
            sum("unit" in entity.tags for entity in runtime.world.entities.values())
            == unit_count + 1
        )
        assert runtime.drag_start_screen is None
    finally:
        runtime.shutdown()


def test_runtime_hut_command_slot_hotkeys_train_units() -> None:
    """Verify that runtime hut command slot hotkeys train units."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])
        unit_count = sum("unit" in entity.tags for entity in runtime.world.entities.values())

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_q}))
        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_w}))

        units = [entity for entity in runtime.world.entities.values() if "unit" in entity.tags]
        assert len(units) == unit_count + 2
        assert any("settler" in unit.tags for unit in units if int(unit.id) > int(hut.id))
        assert any("spearman" in unit.tags for unit in units if int(unit.id) > int(hut.id))
    finally:
        runtime.shutdown()


def test_runtime_production_refuses_at_population_cap_with_message() -> None:
    """Verify that runtime production refuses at population cap with message."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])
        runtime.world.resources["wood"] = 1000

        while runtime.world.current_population < runtime.world.max_population:
            runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_q}))
        unit_count = sum("unit" in entity.tags for entity in runtime.world.entities.values())
        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_q}))

        assert runtime.world.current_population == runtime.world.max_population
        assert (
            sum("unit" in entity.tags for entity in runtime.world.entities.values())
            == unit_count
        )
        assert runtime.world.notifications[-1].message == "Population cap reached."
    finally:
        runtime.shutdown()


def test_runtime_group_right_click_assigns_unique_move_targets() -> None:
    """Verify that runtime group right click assigns unique move targets."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [
            entity for entity in runtime.world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ]
        runtime.selection_system.state.replace([unit.id for unit in units])

        runtime._issue_move((900, 520), queued=False)

        targets = [
            runtime.world.command_queues[unit.id].peek().target_pos
            for unit in units
            if runtime.world.command_queues[unit.id].peek() is not None
        ]
        assert len(targets) == len(units)
        assert len(set(targets)) == len(units)
    finally:
        runtime.shutdown()


def test_runtime_move_button_issues_regular_move_on_next_map_click() -> None:
    """Verify that runtime move button issues regular move on next map click."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [
            entity for entity in runtime.world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ]
        runtime.selection_system.state.replace([unit.id for unit in units])

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Move")},
            )
        )
        assert runtime.active_command_ability == "Move"

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (900, 520)})
        )

        commands = [runtime.world.command_queues[unit.id].peek() for unit in units]
        assert all(command is not None for command in commands)
        assert all(command.payload.get("attack_move") is False for command in commands)
        assert runtime.active_command_ability is None
        assert runtime.drag_start_screen is None
    finally:
        runtime.shutdown()


def test_runtime_attack_move_button_issues_red_attack_move_commands() -> None:
    """Verify that runtime attack move button issues red attack move commands."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [
            entity for entity in runtime.world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ]
        runtime.selection_system.state.replace([unit.id for unit in units])

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Attack Move")},
            )
        )
        assert runtime.active_command_ability == "Attack Move"

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (1100, 520)})
        )

        commands = [runtime.world.command_queues[unit.id].peek() for unit in units]
        assert all(command is not None for command in commands)
        assert all(command.payload["attack_move"] is True for command in commands)
        assert runtime.active_command_ability is None
    finally:
        runtime.shutdown()


def test_runtime_stop_button_clears_selected_unit_orders() -> None:
    """Verify that runtime stop button clears selected unit orders."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [
            entity for entity in runtime.world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ]
        runtime.selection_system.state.replace([unit.id for unit in units])
        runtime._issue_move((900, 520), queued=False)

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Stop")},
            )
        )

        assert all(not runtime.world.command_queues[unit.id].commands for unit in units)
        assert all(unit.state == "idle" for unit in units)
    finally:
        runtime.shutdown()


def test_runtime_stop_hotkey_clears_selected_unit_orders() -> None:
    """Verify that runtime stop hotkey clears selected unit orders."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [
            entity
            for entity in runtime.world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ]
        runtime.selection_system.state.replace([unit.id for unit in units])
        runtime._issue_move((900, 520), queued=False)

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_s}))

        assert all(not runtime.world.command_queues[unit.id].commands for unit in units)
        assert all(unit.state == "idle" for unit in units)
    finally:
        runtime.shutdown()


def test_runtime_build_button_replaces_unit_actions_with_build_choices() -> None:
    """Verify that runtime build button replaces unit actions with build choices."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Build")},
            )
        )

        assert runtime.build_menu_open is True
        assert runtime.active_building_placement is None
        assert runtime._ability_override() == BUILD_MENU_EXPECTED
    finally:
        runtime.shutdown()


def test_runtime_build_hotkey_opens_build_menu() -> None:
    """Verify that runtime build hotkey opens build menu."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_b}))

        assert runtime.build_menu_open is True
        assert runtime._ability_override() == BUILD_MENU_EXPECTED
    finally:
        runtime.shutdown()


def test_runtime_build_hotkeys_do_not_bypass_mixed_selection_abilities() -> None:
    """Verify that runtime build hotkeys do not bypass mixed selection abilities."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        spearman = next(
            entity for entity in runtime.world.entities.values() if "spearman" in entity.tags
        )
        archer = next(
            entity for entity in runtime.world.entities.values() if "archer" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id, spearman.id, archer.id])

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_b}))
        assert runtime.build_menu_open is False

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_z}))
        assert runtime.build_menu_open is False
    finally:
        runtime.shutdown()


def test_runtime_command_slot_build_hotkey_works_for_settler_only_selection() -> None:
    """Verify that runtime command slot build hotkey works for settler only selection."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_z}))

        assert runtime.build_menu_open is True
        assert runtime._ability_override() == BUILD_MENU_EXPECTED
    finally:
        runtime.shutdown()


def test_runtime_hut_build_choice_enters_placement_mode() -> None:
    """Verify that runtime hut build choice enters placement mode."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Build")},
            )
        )

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": override_ability_center(runtime, "Hut", BUILD_MENU_EXPECTED)},
            )
        )

        assert runtime.build_menu_open is False
        assert runtime.active_building_placement == "hut"
        assert runtime._ability_override() == ("Cancel",)
    finally:
        runtime.shutdown()


def test_runtime_chicken_farm_build_choice_enters_placement_mode() -> None:
    """Verify that runtime chicken farm build choice enters placement mode."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.build_menu_open = True

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {
                    "button": 1,
                    "pos": override_ability_center(
                        runtime,
                        "Chicken Farm",
                        BUILD_MENU_EXPECTED,
                    ),
                },
            )
        )

        assert runtime.build_menu_open is False
        assert runtime.active_building_placement == "chicken_farm"
        assert runtime._ability_override() == ("Cancel",)
    finally:
        runtime.shutdown()


def test_runtime_wizard_tower_build_choice_enters_placement_mode() -> None:
    """Verify that runtime tower build choices enter placement mode."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.build_menu_open = True

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {
                    "button": 1,
                    "pos": override_ability_center(
                        runtime,
                        "Wizard Tower",
                        BUILD_MENU_EXPECTED,
                    ),
                },
            )
        )

        assert runtime.build_menu_open is False
        assert runtime.active_building_placement == "wizard_tower"
        assert runtime._ability_override() == ("Cancel",)
    finally:
        runtime.shutdown()


def test_runtime_build_hut_hotkey_enters_placement_mode_from_build_menu() -> None:
    """Verify that runtime build hut hotkey enters placement mode from build menu."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.build_menu_open = True

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_h}))

        assert runtime.build_menu_open is False
        assert runtime.active_building_placement == "hut"
        assert runtime._ability_override() == ("Cancel",)
    finally:
        runtime.shutdown()


def test_runtime_cancel_build_hotkey_cancels_placement_mode() -> None:
    """Verify that runtime cancel build hotkey cancels placement mode."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        runtime.active_building_placement = "hut"

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_c}))

        assert runtime.active_building_placement is None
        assert runtime._ability_override() is None
    finally:
        runtime.shutdown()


def test_runtime_attack_move_hotkey_activates_attack_move_command() -> None:
    """Verify that runtime attack move hotkey activates attack move command."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [
            entity for entity in runtime.world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ]
        runtime.selection_system.state.replace([unit.id for unit in units])

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_e}))

        assert runtime.active_command_ability == "Attack Move"
    finally:
        runtime.shutdown()


def test_runtime_attack_hotkey_then_enemy_click_issues_attack_command() -> None:
    """Verify that runtime attack hotkey then enemy click issues attack command."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        archer = next(
            entity for entity in runtime.world.entities.values() if "archer" in entity.tags
        )
        enemy = next(entity for entity in runtime.world.entities.values() if "enemy" in entity.tags)
        runtime.selection_system.state.replace([archer.id])
        left, top, width, height = enemy.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_t}))
        assert runtime.active_command_ability == "Attack"

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": screen_pos})
        )

        command = runtime.world.command_queues[archer.id].peek()
        assert command is not None
        assert command.type == "attack"
        assert command.target_entity_id == enemy.id
        assert runtime.active_command_ability is None
    finally:
        runtime.shutdown()


def test_runtime_right_click_enemy_issues_attack_command() -> None:
    """Verify that runtime right click enemy issues attack command."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        archer = next(
            entity
            for entity in runtime.world.entities.values()
            if "archer" in entity.tags and entity.owner == "frontier"
        )
        enemy = next(
            entity for entity in runtime.world.entities.values() if entity.owner == "wolves"
        )
        runtime.selection_system.state.replace([archer.id])
        left, top, width, height = enemy.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 3, "pos": screen_pos},
            )
        )

        command = runtime.world.command_queues[archer.id].peek()
        assert command is not None
        assert command.type == "attack"
        assert command.target_entity_id == enemy.id
    finally:
        runtime.shutdown()


def test_runtime_shift_right_click_enemy_queues_attack_after_move() -> None:
    """Verify that runtime shift right click enemy queues attack after move."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        archer = next(
            entity
            for entity in runtime.world.entities.values()
            if "archer" in entity.tags and entity.owner == "frontier"
        )
        enemy = next(
            entity for entity in runtime.world.entities.values() if entity.owner == "wolves"
        )
        runtime.selection_system.state.replace([archer.id])
        runtime._issue_move((900, 520), queued=False)
        left, top, width, height = enemy.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        pygame.key.set_mods(pygame.KMOD_SHIFT)
        try:
            runtime.handle_event(
                pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN,
                    {"button": 3, "pos": screen_pos},
                )
            )
        finally:
            pygame.key.set_mods(0)

        queue = runtime.world.command_queues[archer.id]
        assert [command.type for command in queue.commands] == ["move", "attack"]
        assert queue.commands[-1].target_entity_id == enemy.id
    finally:
        runtime.shutdown()


def test_runtime_gather_button_auto_queues_move_and_gather() -> None:
    """Verify that runtime gather button auto queues move and gather."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        tree = next(
            entity for entity in runtime.world.entities.values() if "wood_tree" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id])

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Gather Wood")},
            )
        )
        runtime.update(16)

        commands = runtime.world.command_queues[settler.id].commands
        assert [command.type for command in commands[:2]] == ["move", "gather"]
        assert commands[1].target_entity_id == tree.id
        assert commands[1].payload["resource_type"] == "wood"
        assert commands[1].payload["manual"] is False
        assert runtime.active_command_ability is None
    finally:
        runtime.shutdown()


def test_runtime_gather_hotkey_auto_queues_gather_gold_command() -> None:
    """Verify that runtime gather hotkey auto queues gather gold command."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        mine = next(
            entity for entity in runtime.world.entities.values() if "gold_mine" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id])

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_g}))
        runtime.update(16)

        commands = runtime.world.command_queues[settler.id].commands
        assert [command.type for command in commands[:2]] == ["move", "gather"]
        assert commands[1].target_entity_id == mine.id
        assert commands[1].payload["resource_type"] == "gold"
        assert runtime.active_command_ability is None
    finally:
        runtime.shutdown()


def test_runtime_right_click_resource_orders_selected_settlers_to_gather() -> None:
    """Verify that runtime right click resource orders selected settlers to gather."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        mine = next(
            entity for entity in runtime.world.entities.values() if "gold_mine" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id])
        left, top, width, height = mine.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )

        commands = runtime.world.command_queues[settler.id].commands
        assert [command.type for command in commands[:2]] == ["move", "gather"]
        assert commands[1].target_entity_id == mine.id
        assert commands[1].payload["resource_type"] == "gold"
        assert commands[1].payload["manual"] is True
    finally:
        runtime.shutdown()


def test_runtime_right_click_tree_assigns_harvest_slots_to_large_group() -> None:
    """Verify that manual tree gather spreads first eight settlers across slots."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        first = selected_settler(runtime)
        settlers = [first]
        for index in range(9):
            settlers.append(
                add_settler(
                    runtime,
                    first.position.x + 12 + index * 6,
                    first.position.y + (index % 3) * 8,
                )
            )
        tree = next(
            entity for entity in runtime.world.entities.values() if "wood_tree" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id for settler in settlers])
        left, top, width, height = tree.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )

        gather_commands = [
            runtime.world.command_queues[settler.id].commands[1] for settler in settlers
        ]
        move_targets = [
            runtime.world.command_queues[settler.id].commands[0].target_pos
            for settler in settlers
        ]
        first_eight_targets = {
            (round(target.x), round(target.y)) for target in move_targets[:8]
        }
        slot_indexes = [
            command.payload["resource_interaction_candidate_index"]
            for command in gather_commands
        ]
        assert len(first_eight_targets) == 8
        assert slot_indexes[:8] == list(range(8))
        assert slot_indexes[8:] == [0, 1]
        assert all(command.target_entity_id == tree.id for command in gather_commands)
        assert all(command.payload["manual"] is True for command in gather_commands)
    finally:
        runtime.shutdown()


@pytest.mark.parametrize(
    "resource_tag",
    ["gold_mine", "iron_deposit", "stone_outcrop"],
)
def test_runtime_right_click_mine_assigns_harvest_slots_to_large_group(
    resource_tag: str,
) -> None:
    """Verify that manual mine gather spreads first eight settlers across slots."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        first = selected_settler(runtime)
        settlers = [first]
        for index in range(9):
            settlers.append(
                add_settler(
                    runtime,
                    first.position.x + 12 + index * 6,
                    first.position.y + (index % 3) * 8,
                )
            )
        mine = next(
            entity for entity in runtime.world.entities.values() if resource_tag in entity.tags
        )
        runtime.selection_system.state.replace([settler.id for settler in settlers])
        left, top, width, height = mine.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )

        gather_commands = [
            runtime.world.command_queues[settler.id].commands[1] for settler in settlers
        ]
        move_targets = [
            runtime.world.command_queues[settler.id].commands[0].target_pos
            for settler in settlers
        ]
        first_eight_targets = {
            (round(target.x), round(target.y)) for target in move_targets[:8]
        }
        slot_indexes = [
            command.payload["resource_interaction_candidate_index"]
            for command in gather_commands
        ]
        assert len(first_eight_targets) == 8
        assert slot_indexes[:8] == list(range(8))
        assert slot_indexes[8:] == [0, 1]
        assert all(command.target_entity_id == mine.id for command in gather_commands)
        assert all(command.payload["manual"] is True for command in gather_commands)
    finally:
        runtime.shutdown()


def test_runtime_shift_right_click_resource_appends_gather_after_existing_move() -> None:
    """Verify that runtime shift right click resource appends gather after existing move."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        mine = next(
            entity for entity in runtime.world.entities.values() if "gold_mine" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id])
        runtime.world.enqueue_command(
            settler.id,
            make_command(
                "move",
                [settler.id],
                target_pos=WorldPosition(settler.position.x + 120, settler.position.y),
            ),
        )
        left, top, width, height = mine.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        pygame.key.set_mods(pygame.KMOD_SHIFT)
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )
        pygame.key.set_mods(0)

        commands = runtime.world.command_queues[settler.id].commands
        assert [command.type for command in commands[:3]] == ["move", "move", "gather"]
        assert commands[2].target_entity_id == mine.id
        assert commands[2].payload["manual"] is True
    finally:
        pygame.key.set_mods(0)
        runtime.shutdown()


def test_runtime_shift_right_click_mine_preserves_harvest_slot_target() -> None:
    """Verify that queued mine gather stores the assigned slot target."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        mine = next(
            entity for entity in runtime.world.entities.values() if "gold_mine" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id])
        runtime.world.enqueue_command(
            settler.id,
            make_command(
                "move",
                [settler.id],
                target_pos=WorldPosition(settler.position.x + 120, settler.position.y),
            ),
        )
        left, top, width, height = mine.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        pygame.key.set_mods(pygame.KMOD_SHIFT)
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )
        pygame.key.set_mods(0)

        commands = runtime.world.command_queues[settler.id].commands
        gather = commands[2]
        slot_target = commands[1].target_pos
        assert [command.type for command in commands[:3]] == ["move", "move", "gather"]
        assert gather.target_entity_id == mine.id
        assert gather.payload["resource_interaction_candidate_index"] == 0
        assert gather.payload["resource_interaction_x"] == slot_target.x
        assert gather.payload["resource_interaction_y"] == slot_target.y
    finally:
        pygame.key.set_mods(0)
        runtime.shutdown()


def test_runtime_shift_right_click_tree_preserves_harvest_slot_target() -> None:
    """Verify that queued tree gather stores the assigned slot target."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        tree = next(
            entity for entity in runtime.world.entities.values() if "wood_tree" in entity.tags
        )
        runtime.selection_system.state.replace([settler.id])
        runtime.world.enqueue_command(
            settler.id,
            make_command(
                "move",
                [settler.id],
                target_pos=WorldPosition(settler.position.x + 120, settler.position.y),
            ),
        )
        left, top, width, height = tree.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        pygame.key.set_mods(pygame.KMOD_SHIFT)
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )
        pygame.key.set_mods(0)

        commands = runtime.world.command_queues[settler.id].commands
        gather = commands[2]
        slot_target = commands[1].target_pos
        assert [command.type for command in commands[:3]] == ["move", "move", "gather"]
        assert gather.target_entity_id == tree.id
        assert gather.payload["resource_interaction_candidate_index"] == 0
        assert gather.payload["resource_interaction_x"] == slot_target.x
        assert gather.payload["resource_interaction_y"] == slot_target.y
    finally:
        pygame.key.set_mods(0)
        runtime.shutdown()


def test_runtime_right_click_damaged_building_orders_settler_to_repair() -> None:
    """Verify that runtime right click damaged building orders settler to repair."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        hut.hp = 300
        runtime.selection_system.state.replace([settler.id])
        left, top, width, height = hut.bounds
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(left + (width / 2), top + (height / 2))
        )

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )

        commands = runtime.world.command_queues[settler.id].commands
        assert [command.type for command in commands[:2]] == ["move", "repair"]
        assert commands[1].target_entity_id == hut.id
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_rebinds_build_hotkey() -> None:
    """Verify that runtime settings menu rebinds build hotkey."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        row_center = runtime.renderer.settings_keybind_rect(
            runtime.screen,
            KEYBIND_BUILD,
        ).center

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": row_center})
        )
        assert runtime.rebinding_action == KEYBIND_BUILD

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_n}))

        assert runtime.rebinding_action is None
        assert runtime.settings.keybindings[KEYBIND_BUILD] == "n"
        assert runtime.renderer.settings.keybindings[KEYBIND_BUILD] == "n"
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_rebinds_command_slot_hotkey() -> None:
    """Verify that runtime settings menu rebinds command slot hotkey."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        row_center = runtime.renderer.settings_keybind_rect(
            runtime.screen,
            KEYBIND_COMMAND_SLOT_1,
        ).center

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": row_center})
        )
        assert runtime.rebinding_action == KEYBIND_COMMAND_SLOT_1

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_z}))

        assert runtime.rebinding_action is None
        assert runtime.settings.keybindings[KEYBIND_COMMAND_SLOT_1] == "z"
        assert runtime.renderer.settings.keybindings[KEYBIND_COMMAND_SLOT_1] == "z"
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_rebinds_gather_hotkey() -> None:
    """Verify that runtime settings menu rebinds gather hotkey."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.renderer is not None
        settings_center = runtime.renderer.settings_button_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": settings_center})
        )
        row_center = runtime.renderer.settings_keybind_rect(
            runtime.screen,
            KEYBIND_GATHER_GOLD,
        ).center

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": row_center})
        )
        assert runtime.rebinding_action == KEYBIND_GATHER_GOLD

        runtime.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_y}))

        assert runtime.rebinding_action is None
        assert runtime.settings.keybindings[KEYBIND_GATHER_GOLD] == "y"
        assert runtime.renderer.settings.keybindings[KEYBIND_GATHER_GOLD] == "y"
    finally:
        runtime.shutdown()


def test_runtime_hut_placement_uses_click_x_and_snaps_to_building_line() -> None:
    """Verify that runtime hut placement uses click x and snaps to building line."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.active_building_placement = "hut"
        hut_count = sum("hut" in entity.tags for entity in runtime.world.entities.values())
        layout = terrain_layout_for_height(runtime.world.settings.world_height)
        click_pos = (900, round(layout.unit_walkable_top_y + 40))

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": click_pos},
            )
        )

        huts = [entity for entity in runtime.world.entities.values() if "hut" in entity.tags]
        construction_site = max(huts, key=lambda entity: int(entity.id))
        assert len(huts) == hut_count + 1
        assert construction_site.position.x == runtime.world.camera.screen_to_world(*click_pos).x
        assert construction_site.position.y == layout.building_lane_bottom_y
        assert runtime.active_building_placement is None
    finally:
        runtime.shutdown()


def test_runtime_hut_placement_costs_50_wood_and_requires_affordability() -> None:
    """Verify that runtime hut placement costs 50 wood and requires affordability."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.active_building_placement = "hut"
        runtime.world.resources["wood"] = 50
        hut_count = sum("hut" in entity.tags for entity in runtime.world.entities.values())
        layout = terrain_layout_for_height(runtime.world.settings.world_height)
        click_pos = (900, round(layout.unit_walkable_top_y + 40))

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": click_pos})
        )

        assert runtime.world.resources["wood"] == 0
        assert (
            sum("hut" in entity.tags for entity in runtime.world.entities.values())
            == hut_count + 1
        )

        runtime.active_building_placement = "hut"
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": (1100, click_pos[1])},
            )
        )

        assert (
            sum("hut" in entity.tags for entity in runtime.world.entities.values())
            == hut_count + 1
        )
        assert runtime.world.notifications[-1].message == "Needs wood."
    finally:
        runtime.shutdown()


def test_runtime_hut_placement_preview_is_locked_to_building_line() -> None:
    """Verify that runtime hut placement preview is locked to building line."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        runtime.active_building_placement = "hut"
        runtime.mouse_screen_pos = (900, 620)
        layout = terrain_layout_for_height(runtime.world.settings.world_height)

        preview = runtime._placement_preview()

        assert preview is not None
        assert preview.position.y == layout.building_lane_bottom_y
        assert preview.position.x == runtime.world.camera.screen_to_world(900, 620).x
        assert preview.valid is True
    finally:
        runtime.shutdown()


def test_runtime_valid_hut_placement_creates_site_and_orders_settler() -> None:
    """Verify that runtime valid hut placement creates site and orders settler."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.active_building_placement = "hut"
        layout = terrain_layout_for_height(runtime.world.settings.world_height)
        click_pos = (900, round((layout.building_lane_top_y + layout.building_lane_bottom_y) / 2))

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": click_pos})
        )

        huts = [entity for entity in runtime.world.entities.values() if "hut" in entity.tags]
        construction_site = max(huts, key=lambda entity: int(entity.id))
        queue = runtime.world.command_queues[settler.id].commands

        assert construction_site.complete is False
        assert construction_site.position.y == layout.building_lane_bottom_y
        assert construction_site.hp == 65
        assert construction_site.max_hp == 650
        assert runtime.active_building_placement is None
        assert runtime.selection_system.state.selected_ids == [settler.id]
        assert [command.type for command in queue[:2]] == ["move", "build"]
        assert queue[1].payload["building_id"] == "hut"
        assert queue[1].target_entity_id == construction_site.id
    finally:
        runtime.shutdown()


def test_runtime_valid_hut_placement_orders_all_selected_settlers() -> None:
    """Verify that runtime valid hut placement orders all selected settlers."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        layout = terrain_layout_for_height(runtime.world.settings.world_height)
        first = selected_settler(runtime)
        second = add_settler(runtime, first.position.x + 42, first.position.y)
        third = add_settler(runtime, first.position.x + 84, first.position.y)
        selected_builders = [first, second, third]
        runtime.selection_system.state.replace([builder.id for builder in selected_builders])
        runtime.active_building_placement = "hut"
        click_pos = (900, round((layout.building_lane_top_y + layout.building_lane_bottom_y) / 2))

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": click_pos})
        )

        construction_site = max(
            (entity for entity in runtime.world.entities.values() if "hut" in entity.tags),
            key=lambda entity: int(entity.id),
        )
        for builder in selected_builders:
            commands = runtime.world.command_queues[builder.id].commands
            assert [command.type for command in commands[:2]] == ["move", "build"]
            assert commands[1].target_entity_id == construction_site.id
            assert commands[1].payload["building_id"] == "hut"
    finally:
        runtime.shutdown()


def test_runtime_shift_placement_queues_multiple_hut_constructions() -> None:
    """Verify that runtime shift placement queues multiple hut constructions."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    previous_mods = pygame.key.get_mods()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.active_building_placement = "hut"
        layout = terrain_layout_for_height(runtime.world.settings.world_height)
        first_click = (900, round(layout.unit_walkable_top_y + 40))
        second_click = (1120, round(layout.unit_walkable_top_y + 40))

        pygame.key.set_mods(pygame.KMOD_SHIFT)
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": first_click})
        )
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": second_click})
        )

        huts = [
            entity
            for entity in runtime.world.entities.values()
            if "hut" in entity.tags and not getattr(entity, "complete", True)
        ]
        commands = runtime.world.command_queues[settler.id].commands
        assert len(huts) == 2
        assert [command.type for command in commands[:4]] == ["move", "build", "move", "build"]
        assert commands[1].target_entity_id != commands[3].target_entity_id
        assert runtime.active_building_placement == "hut"
    finally:
        pygame.key.set_mods(previous_mods)
        runtime.shutdown()


def test_runtime_right_click_incomplete_building_orders_selected_settlers_to_assist() -> None:
    """Verify that runtime right click incomplete building orders selected settlers to assist."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        first = selected_settler(runtime)
        second = add_settler(runtime, first.position.x + 42, first.position.y)
        runtime.selection_system.state.replace([first.id, second.id])
        site = runtime._create_hut_construction_site(WorldPosition(900, 300))
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(site.position.x, site.position.y - 50)
        )

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )

        for builder in (first, second):
            commands = runtime.world.command_queues[builder.id].commands
            assert [command.type for command in commands[:2]] == ["move", "build"]
            assert commands[1].target_entity_id == site.id
            assert commands[1].payload["building_id"] == "hut"
    finally:
        runtime.shutdown()


def test_runtime_chicken_farm_placement_spends_cost_and_creates_site() -> None:
    """Verify that runtime chicken farm placement spends cost and creates site."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.active_building_placement = "chicken_farm"
        starting_wood = runtime.world.resources["wood"]
        layout = terrain_layout_for_height(runtime.world.settings.world_height)
        click_pos = (980, round((layout.building_lane_top_y + layout.building_lane_bottom_y) / 2))

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": click_pos})
        )

        farms = [
            entity
            for entity in runtime.world.entities.values()
            if "chicken_farm" in entity.tags
        ]
        farm = max(farms, key=lambda entity: int(entity.id))
        commands = runtime.world.command_queues[settler.id].commands

        assert runtime.world.resources["wood"] == starting_wood - 75
        assert farm.complete is False
        assert farm.max_hp == 75
        assert commands[1].payload["building_id"] == "chicken_farm"
    finally:
        runtime.shutdown()


def test_runtime_right_click_completed_farm_assigns_selected_settler() -> None:
    """Verify that runtime right click completed farm assigns selected settler."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        farm = runtime._create_building_construction_site(
            "chicken_farm",
            WorldPosition(920, 300),
        )
        farm.complete = True
        farm.hp = farm.max_hp
        screen_pos = runtime.world.camera.world_to_screen(
            WorldPosition(farm.position.x, farm.position.y - 30)
        )

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": screen_pos})
        )

        assert farm.functions["assigned_worker_id"] == settler.id.to_json()
        assert runtime.world.notifications[-1].message == "Assigned worker to farm."
    finally:
        runtime.shutdown()


def test_runtime_build_placement_cancel_restores_normal_unit_actions() -> None:
    """Verify that runtime build placement cancel restores normal unit actions."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        settler = selected_settler(runtime)
        runtime.selection_system.state.replace([settler.id])
        runtime.active_building_placement = "hut"

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": override_ability_center(runtime, "Cancel", ("Cancel",))},
            )
        )

        assert runtime.active_building_placement is None
        assert runtime._ability_override() is None
        panel = selected_panel_for(runtime.world, runtime.selection_system.state.selected_ids)
        assert "Move" in panel.abilities
        assert "Build" in panel.abilities
    finally:
        runtime.shutdown()


def test_runtime_dropoff_button_toggles_placement_mode() -> None:
    """Verify that runtime dropoff button toggles placement mode."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])
        button_center = ability_center(runtime, "Dropoff")

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": button_center})
        )
        assert runtime.active_dropoff_building_id == hut.id
        assert runtime.drag_start_screen is None

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": button_center})
        )
        assert runtime.active_dropoff_building_id is None
    finally:
        runtime.shutdown()


def test_runtime_right_click_ground_with_hut_sets_rally_point() -> None:
    """Verify that runtime right click ground with hut sets rally point."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": (900, 510)})
        )

        assert hut.dropoff_point == clamp_unit_position_to_walkable_lane_for_height(
            runtime.world.camera.screen_to_world(900, 510),
            runtime.world.settings.world_height,
        )
    finally:
        runtime.shutdown()


def test_runtime_right_click_blocked_ground_with_hut_refuses_rally_point() -> None:
    """Verify that runtime right click blocked ground with hut refuses rally point."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        mine = next(
            entity for entity in runtime.world.entities.values() if "gold_mine" in entity.tags
        )
        runtime.selection_system.state.replace([hut.id])
        original = hut.dropoff_point

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 3, "pos": runtime.world.camera.world_to_screen(mine.position)},
            )
        )

        assert hut.dropoff_point == original
        assert runtime.world.notifications[-1].message == "Invalid rally point."
    finally:
        runtime.shutdown()


def test_runtime_dropoff_mode_places_flag_on_next_map_click() -> None:
    """Verify that runtime dropoff mode places flag on next map click."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Dropoff")},
            )
        )

        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (880, 500)})
        )

        assert hut.dropoff_point == clamp_unit_position_to_walkable_lane_for_height(
            runtime.world.camera.screen_to_world(880, 500),
            runtime.world.settings.world_height,
        )
        assert runtime.active_dropoff_building_id is None
        assert runtime.drag_start_screen is None
    finally:
        runtime.shutdown()


def test_runtime_dropoff_mode_clamps_flags_out_of_building_lane() -> None:
    """Verify that runtime dropoff mode clamps flags out of building lane."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        unit_walkable_top = terrain_layout_for_height(
            runtime.world.settings.world_height
        ).unit_walkable_top_y
        runtime.selection_system.state.replace([hut.id])
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Dropoff")},
            )
        )

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": (880, unit_walkable_top - 60)},
            )
        )

        assert hut.dropoff_point is not None
        assert hut.dropoff_point.y == unit_walkable_top
    finally:
        runtime.shutdown()


def test_runtime_produced_unit_uses_updated_dropoff_point() -> None:
    """Verify that runtime produced unit uses updated dropoff point."""
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Dropoff")},
            )
        )
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (900, 510)})
        )
        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                    {"button": 1, "pos": ability_center(runtime, "Train Spearman")},
            )
        )

        produced = max(runtime.world.entities.values(), key=lambda entity: int(entity.id))
        command = runtime.world.command_queues[produced.id].peek()
        assert "spearman" in produced.tags
        assert command is not None
        assert command.target_pos == hut.dropoff_point
    finally:
        runtime.shutdown()

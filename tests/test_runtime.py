from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from house_of_wolves.core.app import main
from house_of_wolves.core.runtime import GameRuntime
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.ui.selected_panel import selected_panel_for
from house_of_wolves.world.terrain import (
    clamp_unit_position_to_walkable_lane_for_height,
    terrain_layout_for_height,
)


def ability_center(runtime: GameRuntime, label: str) -> tuple[int, int]:
    assert runtime.screen is not None
    assert runtime.renderer is not None
    panel = selected_panel_for(runtime.world, runtime.selection_system.state.selected_ids)
    button = next(
        button for button in runtime.renderer.ability_buttons_for_panel(runtime.screen, panel)
        if button.label == label
    )
    return button.rect.center


def test_validate_cli_mode_keeps_data_validation_behavior(capsys) -> None:
    assert main(["--validate"]) == 0

    output = capsys.readouterr().out
    assert "House of Wolves scaffold validated" in output
    assert "units=9" in output


def test_runtime_initializes_updates_renders_and_shuts_down_windowless() -> None:
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        runtime.update(16)
        runtime.render()

        assert runtime.screen is not None
        assert isinstance(runtime.screen, pygame.Surface)
    finally:
        runtime.shutdown()


def test_runtime_fullscreen_mode_uses_display_size_for_world_height() -> None:
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.settings.fullscreen is True
        assert runtime.settings.virtual_size == runtime.screen.get_size()
        assert runtime.world.settings.world_height == runtime.screen.get_height()
        assert runtime.world.camera.viewport_height == runtime.screen.get_height()
    finally:
        runtime.shutdown()


def test_runtime_windowed_mode_keeps_configured_size() -> None:
    runtime = GameRuntime(AppSettings(fullscreen=False, virtual_width=960, virtual_height=540))

    runtime.initialize()
    try:
        assert runtime.screen is not None
        assert runtime.settings.fullscreen is False
        assert runtime.screen.get_size() == (960, 540)
        assert runtime.world.settings.world_height == 540
    finally:
        runtime.shutdown()


def test_runtime_settings_menu_toggles_borderless_windowed_mode() -> None:
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

        toggle_center = runtime.renderer.settings_display_toggle_rect(runtime.screen).center
        runtime.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": toggle_center})
        )

        assert runtime.settings.fullscreen is False
        assert runtime.settings_menu_open is False
        assert runtime.display_flags & pygame.NOFRAME
    finally:
        runtime.shutdown()


def test_runtime_clicking_hut_produce_button_spawns_unit() -> None:
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        hut = next(entity for entity in runtime.world.entities.values() if "hut" in entity.tags)
        runtime.selection_system.state.replace([hut.id])
        unit_count = sum("unit" in entity.tags for entity in runtime.world.entities.values())

        runtime.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": ability_center(runtime, "Produce Settler")},
            )
        )

        assert (
            sum("unit" in entity.tags for entity in runtime.world.entities.values())
            == unit_count + 1
        )
        assert runtime.drag_start_screen is None
    finally:
        runtime.shutdown()


def test_runtime_group_right_click_assigns_unique_move_targets() -> None:
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        units = [entity for entity in runtime.world.entities.values() if "unit" in entity.tags]
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


def test_runtime_dropoff_button_toggles_placement_mode() -> None:
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


def test_runtime_dropoff_mode_places_flag_on_next_map_click() -> None:
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
                {"button": 1, "pos": ability_center(runtime, "Produce Spearman")},
            )
        )

        produced = max(runtime.world.entities.values(), key=lambda entity: int(entity.id))
        command = runtime.world.command_queues[produced.id].peek()
        assert "spearman" in produced.tags
        assert command is not None
        assert command.target_pos == hut.dropoff_point
    finally:
        runtime.shutdown()

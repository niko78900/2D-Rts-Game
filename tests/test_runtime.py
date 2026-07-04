from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from house_of_wolves.core.app import main
from house_of_wolves.core.runtime import GameRuntime
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.ui.selected_panel import selected_panel_for


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

        assert hut.dropoff_point == runtime.world.camera.screen_to_world(880, 500)
        assert runtime.active_dropoff_building_id is None
        assert runtime.drag_start_screen is None
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

from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.core.renderer import GameRenderer, queued_move_targets
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.systems.commands import make_command
from house_of_wolves.ui.selected_panel import mutual_abilities, selected_panel_for
from house_of_wolves.world.demo import create_demo_world


def test_queued_move_targets_returns_all_move_commands_for_selected_units_only() -> None:
    world = create_demo_world()
    units = [entity for entity in world.entities.values() if "unit" in entity.tags]
    first_target = WorldPosition(800, 520)
    second_target = WorldPosition(1000, 520)

    world.enqueue_command(units[0].id, make_command("move", [units[0].id], target_pos=first_target))
    world.enqueue_command(
        units[0].id,
        make_command("move", [units[0].id], target_pos=second_target, queued=True),
    )
    world.enqueue_command(units[1].id, make_command("move", [units[1].id], target_pos=(900, 510)))

    assert queued_move_targets(world, [units[0].id]) == [
        (units[0].id, [first_target, second_target])
    ]


def test_queued_move_targets_hides_unselected_unit_destinations() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=(800, 520)))

    assert queued_move_targets(world, []) == []


def test_selected_panel_for_unit_shows_health_and_core_abilities() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)

    panel = selected_panel_for(world, [settler.id])

    assert panel.title == "Settler"
    assert panel.health == "Health: 40"
    assert "Move" in panel.abilities
    assert "Build" in panel.abilities
    assert "Gather Wood" in panel.abilities


def test_selected_panel_for_building_shows_production_options() -> None:
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)

    panel = selected_panel_for(world, [hut.id])

    assert panel.title == "Hut"
    assert panel.health == "Health: 650"
    assert "Produce Settler" in panel.abilities
    assert "Produce Spearman" in panel.abilities


def test_selected_panel_for_resource_shows_remaining_amount_and_gather_ability() -> None:
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)

    panel = selected_panel_for(world, [tree.id])

    assert panel.title == "Tree"
    assert panel.health == "Health: 1    Remaining Wood: 250"
    assert "Gather Wood" in panel.abilities


def test_multi_unit_panel_shows_only_mutual_actions_for_mixed_unit_types() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    spearman = next(entity for entity in world.entities.values() if "spearman" in entity.tags)

    panel = selected_panel_for(world, [settler.id, spearman.id])

    assert panel.title == "Multiple Units"
    assert panel.abilities == ("Move", "Attack Move", "Stop")


def test_mutual_abilities_keeps_shared_settler_actions_for_same_unit_type() -> None:
    world = create_demo_world()
    settlers = [entity for entity in world.entities.values() if "settler" in entity.tags]
    settler = settlers[0]

    assert mutual_abilities([settler, settler]) == (
        "Move",
        "Attack Move",
        "Stop",
        "Build",
        "Gather Wood",
        "Repair",
    )


def test_renderer_hit_tests_selected_panel_ability_buttons() -> None:
    pygame.init()
    try:
        world = create_demo_world()
        hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": [hut.id]})()
        panel = selected_panel_for(world, [hut.id])
        produce_settler = next(
            button for button in renderer.ability_buttons_for_panel(surface, panel)
            if button.label == "Produce Settler"
        )

        assert renderer.ability_at(surface, world, selection, produce_settler.rect.center) == (
            "Produce Settler"
        )
    finally:
        pygame.quit()


def test_renderer_highlights_active_dropoff_button() -> None:
    pygame.init()
    try:
        world = create_demo_world()
        hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": [hut.id]})()
        panel = selected_panel_for(world, [hut.id])
        dropoff = next(
            button for button in renderer.ability_buttons_for_panel(surface, panel)
            if button.label == "Dropoff"
        )

        renderer.render(surface, world, selection, fps=0, active_ability="Dropoff")

        assert surface.get_at((dropoff.rect.centerx, dropoff.rect.top))[:3] == (109, 176, 104)
    finally:
        pygame.quit()

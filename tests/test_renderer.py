from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.core.renderer import (
    ANIMAL_SPRITE_PATHS,
    HUT_CONSTRUCTION_SPRITES,
    HUT_STAGE_COMPLETE,
    HUT_STAGE_PARTIAL,
    HUT_STAGE_SCAFFOLDING,
    BuildingPlacementPreview,
    GameRenderer,
    dotted_line_points,
    gameplay_waypoint_links,
    gameplay_waypoint_markers,
    hut_construction_stage_for,
    hut_sprite_reference_for,
    queued_move_markers,
    queued_move_targets,
    status_bar_for_entity,
)
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.group_movement import issue_group_move_command
from house_of_wolves.ui.selected_panel import mutual_abilities, selected_panel_for
from house_of_wolves.world.collision import blocking_bounds_for_entity
from house_of_wolves.world.demo import create_demo_world


def test_queued_move_targets_returns_all_move_commands_for_selected_units_only() -> None:
    """Verify that queued move targets returns all move commands for selected units only."""
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
    """Verify that queued move targets hides unselected unit destinations."""
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    world.enqueue_command(unit.id, make_command("move", [unit.id], target_pos=(800, 520)))

    assert queued_move_targets(world, []) == []


def test_queued_move_markers_marks_attack_move_targets() -> None:
    """Verify that queued move markers marks attack move targets."""
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    target = WorldPosition(800, 520)
    world.enqueue_command(
        unit.id,
        make_command("move", [unit.id], target_pos=target, attack_move=True),
    )

    markers = queued_move_markers(world, [unit.id])

    assert markers[0][1][0].position == target
    assert markers[0][1][0].attack_move is True


def test_gameplay_waypoint_markers_collapse_group_formation_slots() -> None:
    """Verify that gameplay waypoint markers collapse group formation slots."""
    world = create_demo_world()
    units = [
        entity
        for entity in world.entities.values()
        if "unit" in entity.tags and entity.owner == "frontier"
    ]
    target = WorldPosition(900, 520)

    issue_group_move_command(world, [unit.id for unit in units], target, attack_move=True)

    debug_markers = queued_move_markers(world, [unit.id for unit in units])
    gameplay_markers = gameplay_waypoint_markers(world, [unit.id for unit in units])

    assert sum(len(markers) for _entity_id, markers in debug_markers) == len(units)
    assert len(gameplay_markers) == 1
    assert gameplay_markers[0].attack_move is True
    assert abs(gameplay_markers[0].position.x - target.x) < 1
    assert abs(gameplay_markers[0].position.y - target.y) < 20


def test_gameplay_waypoint_links_keep_one_route_per_selected_unit() -> None:
    """Verify that gameplay waypoint links keep one route per selected unit."""
    world = create_demo_world()
    units = [
        entity
        for entity in world.entities.values()
        if "unit" in entity.tags and entity.owner == "frontier"
    ]
    target = WorldPosition(900, 520)

    issue_group_move_command(world, [unit.id for unit in units], target)

    links = gameplay_waypoint_links(world, [unit.id for unit in units])

    assert len(links) == len(units)
    assert {origin for origin, _markers in links} == {unit.position for unit in units}
    assert all(len(markers) == 1 for _origin, markers in links)
    assert len({markers[0].position for _origin, markers in links}) == len(units)


def test_dotted_line_points_create_separated_waypoint_dots() -> None:
    """Verify that dotted line points create separated waypoint dots."""
    points = dotted_line_points((0, 0), (30, 0), spacing=10)

    assert points == [(0, 0), (10, 0), (20, 0), (30, 0)]


def test_gameplay_waypoint_links_draw_endpoint_dots_for_each_unit_slot() -> None:
    """Verify that gameplay waypoint links draw endpoint dots for each unit slot."""
    pygame.init()
    try:
        world = create_demo_world()
        units = [
            entity
            for entity in world.entities.values()
            if "unit" in entity.tags and entity.owner == "frontier"
        ]
        issue_group_move_command(world, [unit.id for unit in units], WorldPosition(900, 520))
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": [unit.id for unit in units]})()

        renderer.render(surface, world, selection, fps=0)

        for _origin, markers in gameplay_waypoint_links(world, [unit.id for unit in units]):
            endpoint = world.camera.world_to_screen(markers[0].position)
            assert _near_pixel_color(surface, endpoint, (238, 218, 111)) or _near_pixel_color(
                surface,
                endpoint,
                (123, 105, 47),
            )
    finally:
        pygame.quit()


def test_selected_panel_for_unit_shows_health_and_core_abilities() -> None:
    """Verify that selected panel for unit shows health and core abilities."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)

    panel = selected_panel_for(world, [settler.id])

    assert panel.title == "Settler"
    assert panel.health == "Health: 40"
    assert "Move" in panel.abilities
    assert "Attack" in panel.abilities
    assert "Build" in panel.abilities
    assert "Gather Wood" in panel.abilities
    assert "Gather Gold" in panel.abilities
    assert "Gather Ore" in panel.abilities
    assert "Gather Stone" in panel.abilities
    assert "Repair" not in panel.abilities


def test_selected_panel_for_building_shows_production_options() -> None:
    """Verify that selected panel for building shows production options."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)

    panel = selected_panel_for(world, [hut.id])

    assert panel.title == "Hut"
    assert panel.health == "Health: 650"
    assert "Train Settler" in panel.abilities
    assert "Train Spearman" in panel.abilities


def test_selected_panel_for_incomplete_hut_hides_production_options() -> None:
    """Verify that selected panel for incomplete hut hides production options."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    hut.complete = False

    panel = selected_panel_for(world, [hut.id])

    assert panel.details[0] == "Status: Under Construction"
    assert panel.abilities == ()


def test_selected_panel_for_resource_shows_remaining_amount_and_gather_ability() -> None:
    """Verify that selected panel for resource shows remaining amount and gather ability."""
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)

    panel = selected_panel_for(world, [tree.id])

    assert panel.title == "Tree"
    assert panel.health == "Health: 150    Remaining Wood: 150"
    assert "Gather Wood" in panel.abilities


def test_resource_placeholder_inner_colors_distinguish_ore_and_stone() -> None:
    """Verify that resource placeholder inner colors distinguish ore and stone."""
    renderer = GameRenderer(AppSettings())
    rect = pygame.Rect(20, 20, 90, 54)
    surface = pygame.Surface((140, 100))

    renderer._draw_resource(surface, rect, ("resource", "iron_deposit"))
    assert surface.get_at(rect.center)[:3] == (24, 24, 24)

    renderer._draw_resource(surface, rect, ("resource", "stone_outcrop"))
    assert surface.get_at(rect.center)[:3] == (154, 154, 148)


def test_named_animal_sprite_assets_exist_with_transparent_backgrounds() -> None:
    """Verify that named animal sprite assets exist with transparent backgrounds."""
    old_uuid_files = (
        ANIMAL_SPRITE_PATHS["pig"].parents[1] / "55e8e3d1-73ed-4119-b38a-0ccb3f6b2fdd.png",
        ANIMAL_SPRITE_PATHS["chicken"].parents[1] / "970e59ef-10f2-4178-96bd-99a1b1c3d875.png",
    )

    assert not any(path.exists() for path in old_uuid_files)
    for path in ANIMAL_SPRITE_PATHS.values():
        assert path.exists()
        sprite = pygame.image.load(str(path))
        assert sprite.get_at((0, 0)).a == 0


def test_renderer_loads_chicken_and_pig_sprites() -> None:
    """Verify that renderer loads chicken and pig sprites."""
    renderer = GameRenderer(AppSettings())

    assert set(renderer.animal_sprites) >= {"chicken", "pig"}


def test_selected_panel_for_enemy_unit_shows_stats_without_commands() -> None:
    """Verify that selected panel for enemy unit shows stats without commands."""
    world = create_demo_world()
    enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)

    panel = selected_panel_for(world, [enemy.id])

    assert panel.title == "Enemy Swordsman"
    assert panel.subtitle == "Wolves Unit"
    assert panel.health == "Health: 90"
    assert panel.abilities == ()


def test_status_bar_for_damaged_unit_uses_green_red_health_ratio() -> None:
    """Verify that status bar for damaged unit uses green red health ratio."""
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    unit.hp = 20

    spec = status_bar_for_entity(unit)

    assert spec is not None
    assert spec.ratio == 0.5
    assert spec.fill_color == (54, 174, 86)
    assert spec.empty_color == (139, 47, 43)


def test_status_bar_for_resource_uses_yellow_depletion_ratio() -> None:
    """Verify that status bar for resource uses yellow depletion ratio."""
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    tree.amount_remaining = 75

    spec = status_bar_for_entity(tree)

    assert spec is not None
    assert spec.ratio == 0.5
    assert spec.fill_color == (230, 193, 77)
    assert spec.empty_color == (118, 87, 35)


def test_status_bar_for_live_farm_animal_uses_health_ratio() -> None:
    """Verify that status bar for live farm animal uses health ratio."""
    animal = ResourceNode(
        id=EntityId(999),
        owner="neutral",
        position=WorldPosition(100, 100),
        footprint=Footprint(24, 20),
        hp=5,
        max_hp=10,
        tags=("resource", "farm_food", "food_animal", "chicken", "selectable"),
        resource_type="food",
        amount_remaining=20,
        max_amount_remaining=20,
    )

    spec = status_bar_for_entity(animal)

    assert spec is not None
    assert spec.ratio == 0.5
    assert spec.fill_color == (54, 174, 86)
    assert spec.empty_color == (139, 47, 43)


def test_hut_construction_stage_thresholds() -> None:
    """Verify that hut construction stage thresholds."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    hut.complete = False
    hut.build_time_ms = 1000

    hut.build_progress_ms = 0
    assert hut_construction_stage_for(hut) == HUT_STAGE_SCAFFOLDING

    hut.build_progress_ms = 330
    assert hut_construction_stage_for(hut) == HUT_STAGE_SCAFFOLDING

    hut.build_progress_ms = 340
    assert hut_construction_stage_for(hut) == HUT_STAGE_PARTIAL

    hut.build_progress_ms = 1000
    assert hut_construction_stage_for(hut) == HUT_STAGE_COMPLETE


def test_hut_construction_sprite_references_are_named_for_future_assets() -> None:
    """Verify that hut construction sprite references are named for future assets."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    hut.complete = False
    hut.build_time_ms = 1000
    hut.build_progress_ms = 0

    assert set(HUT_CONSTRUCTION_SPRITES) == {
        HUT_STAGE_SCAFFOLDING,
        HUT_STAGE_PARTIAL,
        HUT_STAGE_COMPLETE,
    }
    assert hut_sprite_reference_for(hut).endswith("hut_scaffolding.png")


def test_resource_hitbox_outline_is_hidden_by_default() -> None:
    """Verify that resource hitbox outline is hidden by default."""
    pygame.init()
    try:
        world = create_demo_world()
        mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": []})()

        renderer.render(surface, world, selection, fps=0)

        rect = _blocking_screen_rect(world, mine)
        assert surface.get_at((rect.centerx, rect.top))[:3] != (238, 218, 111)
    finally:
        pygame.quit()


def test_resource_hitbox_outline_draws_when_debug_setting_is_enabled() -> None:
    """Verify that resource hitbox outline draws when debug setting is enabled."""
    pygame.init()
    try:
        world = create_demo_world()
        mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)
        renderer = GameRenderer(AppSettings(show_resource_hitboxes=True))
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": []})()

        renderer.render(surface, world, selection, fps=0)

        rect = _blocking_screen_rect(world, mine)
        assert surface.get_at((rect.centerx, rect.top))[:3] == (238, 218, 111)
    finally:
        pygame.quit()


def test_unit_hitbox_outline_draws_when_debug_setting_is_enabled() -> None:
    """Verify that unit hitbox outline draws when debug setting is enabled."""
    pygame.init()
    try:
        world = create_demo_world()
        unit = next(entity for entity in world.entities.values() if "settler" in entity.tags)
        renderer = GameRenderer(AppSettings(show_unit_hitboxes=True))
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": []})()

        renderer.render(surface, world, selection, fps=0)

        rect = _entity_screen_rect(world, unit)
        assert surface.get_at((rect.left, rect.centery))[:3] == (87, 211, 239)
    finally:
        pygame.quit()


def test_building_hitbox_outline_draws_when_debug_setting_is_enabled() -> None:
    """Verify that building hitbox outline draws when debug setting is enabled."""
    pygame.init()
    try:
        world = create_demo_world()
        hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
        renderer = GameRenderer(AppSettings(show_building_hitboxes=True))
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": []})()

        renderer.render(surface, world, selection, fps=0)

        rect = _entity_screen_rect(world, hut)
        assert surface.get_at((rect.left, rect.centery))[:3] == (238, 112, 222)
    finally:
        pygame.quit()


def test_multi_unit_panel_shows_only_mutual_actions_for_mixed_unit_types() -> None:
    """Verify that multi unit panel shows only mutual actions for mixed unit types."""
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    spearman = next(entity for entity in world.entities.values() if "spearman" in entity.tags)

    panel = selected_panel_for(world, [settler.id, spearman.id])

    assert panel.title == "Multiple Units"
    assert panel.abilities == ("Move", "Attack", "Attack Move", "Stop")


def test_mutual_abilities_keeps_shared_settler_actions_for_same_unit_type() -> None:
    """Verify that mutual abilities keeps shared settler actions for same unit type."""
    world = create_demo_world()
    settlers = [entity for entity in world.entities.values() if "settler" in entity.tags]
    settler = settlers[0]

    assert mutual_abilities([settler, settler]) == (
        "Move",
        "Attack",
        "Attack Move",
        "Stop",
        "Build",
        "Gather Wood",
        "Gather Gold",
        "Gather Ore",
        "Gather Stone",
    )


def test_renderer_hit_tests_selected_panel_ability_buttons() -> None:
    """Verify that renderer hit tests selected panel ability buttons."""
    pygame.init()
    try:
        world = create_demo_world()
        hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": [hut.id]})()
        panel = selected_panel_for(world, [hut.id])
        train_settler = next(
            button for button in renderer.ability_buttons_for_panel(surface, panel)
            if button.label == "Train Settler"
        )

        assert renderer.ability_at(surface, world, selection, train_settler.rect.center) == (
            "Train Settler"
        )
        assert train_settler.display_label == "Train Settler [Q]"
    finally:
        pygame.quit()


def test_renderer_shows_keybind_near_ability_button_but_hit_tests_base_label() -> None:
    """Verify that renderer shows keybind near ability button but hit tests base label."""
    pygame.init()
    try:
        world = create_demo_world()
        settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        panel = selected_panel_for(world, [settler.id])
        build = next(
            button for button in renderer.ability_buttons_for_panel(surface, panel)
            if button.label == "Build"
        )

        assert build.display_label == "Build [Z]"
    finally:
        pygame.quit()


def test_renderer_settings_keybind_rows_are_hit_testable() -> None:
    """Verify that renderer settings keybind rows are hit testable."""
    pygame.init()
    try:
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        row = renderer.settings_keybind_rect(surface, "build")
        slot_row = renderer.settings_keybind_rect(surface, "command_slot_1")

        assert renderer.settings_keybind_action_at(surface, row.center) == "build"
        assert renderer.settings_keybind_action_at(surface, slot_row.center) == "command_slot_1"
    finally:
        pygame.quit()


def test_renderer_caches_notification_text_surfaces() -> None:
    """Verify that renderer caches notification text surfaces."""
    pygame.init()
    try:
        world = create_demo_world()
        world.notify("Cannot reach resource.")
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": []})()

        renderer.render(surface, world, selection, fps=0)
        cached = renderer._notification_surface_cache[
            ("Cannot reach resource.", (247, 229, 169))
        ]
        renderer.render(surface, world, selection, fps=0)

        assert renderer._notification_surface_cache[
            ("Cannot reach resource.", (247, 229, 169))
        ] is cached
    finally:
        pygame.quit()


def _entity_screen_rect(world: object, entity: object) -> pygame.Rect:
    """Provide test helper logic for entity screen rect."""
    left, top, width, height = entity.bounds
    screen_pos = world.camera.world_to_screen(WorldPosition(left, top))
    return pygame.Rect(screen_pos[0], screen_pos[1], round(width), round(height))


def _blocking_screen_rect(world: object, entity: object) -> pygame.Rect:
    """Provide test helper logic for blocking screen rect."""
    left, top, width, height = blocking_bounds_for_entity(entity)
    screen_pos = world.camera.world_to_screen(WorldPosition(left, top))
    return pygame.Rect(screen_pos[0], screen_pos[1], round(width), round(height))


def _near_pixel_color(
    surface: pygame.Surface,
    center: tuple[int, int],
    color: tuple[int, int, int],
    *,
    radius: int = 2,
) -> bool:
    """Provide test helper logic for near pixel color."""
    for x in range(center[0] - radius, center[0] + radius + 1):
        for y in range(center[1] - radius, center[1] + radius + 1):
            if surface.get_rect().collidepoint(x, y) and surface.get_at((x, y))[:3] == color:
                return True
    return False


def test_renderer_highlights_active_dropoff_button() -> None:
    """Verify that renderer highlights active dropoff button."""
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


def test_renderer_draws_enemy_selection_marker_red() -> None:
    """Verify that renderer draws enemy selection marker red."""
    pygame.init()
    try:
        world = create_demo_world()
        enemy = next(entity for entity in world.entities.values() if "enemy" in entity.tags)
        world.update_entity_position(enemy.id, WorldPosition(700, enemy.position.y))
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": [enemy.id]})()

        renderer.render(surface, world, selection, fps=0)

        left, top, width, height = enemy.bounds
        screen_pos = world.camera.world_to_screen(WorldPosition(left, top))
        rect = pygame.Rect(screen_pos[0], screen_pos[1], round(width), round(height))
        marker = pygame.Rect(rect.left - 5, rect.bottom - 12, rect.width + 10, 18)
        assert any(
            surface.get_at((x, y))[:3] == (231, 84, 72)
            for x in range(marker.left, marker.right)
            for y in range(marker.top, marker.bottom)
            if surface.get_rect().collidepoint(x, y)
        )
    finally:
        pygame.quit()


def test_renderer_draws_valid_hut_placement_preview() -> None:
    """Verify that renderer draws valid hut placement preview."""
    pygame.init()
    try:
        world = create_demo_world()
        renderer = GameRenderer(AppSettings())
        surface = pygame.Surface(AppSettings().virtual_size)
        selection = type("Selection", (), {"selected_ids": []})()
        preview = BuildingPlacementPreview(
            "hut",
            WorldPosition(900, 360),
            Footprint(150, 116),
            True,
        )

        renderer.render(surface, world, selection, fps=0, placement_preview=preview)

        rect = _entity_screen_rect(world, preview)
        assert surface.get_at((rect.left, rect.centery))[:3] == (104, 190, 112)
    finally:
        pygame.quit()

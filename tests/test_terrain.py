from __future__ import annotations

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.core.settings import UI_PANEL_HEIGHT
from house_of_wolves.world.terrain import (
    BUILDING_LANE_SCREEN_FRACTION,
    UNIT_WALKABLE_SCREEN_FRACTION,
    clamp_unit_position_to_walkable_lane_for_height,
    terrain_layout_for_height,
)


def test_terrain_layout_uses_fullscreen_screen_fractions() -> None:
    """Verify that terrain layout uses fullscreen screen fractions."""
    layout = terrain_layout_for_height(1000)
    map_bottom = 1000 - UI_PANEL_HEIGHT

    assert layout.unit_walkable_bottom_y == map_bottom
    assert layout.building_lane_bottom_y - layout.building_lane_top_y == (
        1000 * BUILDING_LANE_SCREEN_FRACTION
    )
    assert layout.unit_walkable_bottom_y - layout.unit_walkable_top_y == (
        1000 * UNIT_WALKABLE_SCREEN_FRACTION
    )
    assert layout.sky_bottom_y == map_bottom - (
        1000 * BUILDING_LANE_SCREEN_FRACTION
    ) - (1000 * UNIT_WALKABLE_SCREEN_FRACTION)


def test_unit_clamp_uses_current_world_height() -> None:
    """Verify that unit clamp uses current world height."""
    layout = terrain_layout_for_height(1080)

    assert clamp_unit_position_to_walkable_lane_for_height(
        WorldPosition(40, 100),
        1080,
    ) == WorldPosition(40, layout.unit_walkable_top_y)


def test_unit_clamp_keeps_units_above_ui_panel() -> None:
    """Verify that unit clamp keeps units above ui panel."""
    layout = terrain_layout_for_height(1080)

    assert clamp_unit_position_to_walkable_lane_for_height(
        WorldPosition(40, 1080),
        1080,
    ) == WorldPosition(40, layout.unit_walkable_bottom_y)

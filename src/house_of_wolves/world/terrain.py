"""Continuous side-scroller terrain bands."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.core.settings import UI_PANEL_HEIGHT

DEFAULT_TERRAIN_HEIGHT = 720
BUILDING_LANE_SCREEN_FRACTION = 0.015
UNIT_WALKABLE_SCREEN_FRACTION = 0.45


@dataclass(frozen=True, slots=True)
class TerrainLayout:
    sky_top_y: float
    sky_bottom_y: float
    building_lane_top_y: float
    building_lane_bottom_y: float
    unit_walkable_top_y: float
    unit_walkable_bottom_y: float


def terrain_layout_for_height(world_height: int | float = DEFAULT_TERRAIN_HEIGHT) -> TerrainLayout:
    """Build the terrain lane layout for a screen height."""
    screen_height = float(world_height)
    map_bottom = max(0.0, screen_height - UI_PANEL_HEIGHT)
    building_height = min(map_bottom, screen_height * BUILDING_LANE_SCREEN_FRACTION)
    unit_height = min(map_bottom, screen_height * UNIT_WALKABLE_SCREEN_FRACTION)
    sky_bottom = max(0.0, map_bottom - building_height - unit_height)
    building_bottom = sky_bottom + building_height
    return TerrainLayout(
        sky_top_y=0,
        sky_bottom_y=sky_bottom,
        building_lane_top_y=sky_bottom,
        building_lane_bottom_y=building_bottom,
        unit_walkable_top_y=building_bottom,
        unit_walkable_bottom_y=map_bottom,
    )


_DEFAULT_LAYOUT = terrain_layout_for_height()
BUILDING_LANE_TOP_Y = _DEFAULT_LAYOUT.building_lane_top_y
BUILDING_LANE_BOTTOM_Y = _DEFAULT_LAYOUT.building_lane_bottom_y
UNIT_WALKABLE_TOP_Y = _DEFAULT_LAYOUT.unit_walkable_top_y
UNIT_WALKABLE_BOTTOM_Y = _DEFAULT_LAYOUT.unit_walkable_bottom_y


@dataclass(frozen=True, slots=True)
class TerrainBand:
    name: str
    top_y: float
    bottom_y: float
    walkable: bool = True

    def contains_y(self, y: float) -> bool:
        """Return whether the y coordinate is inside this band."""
        return self.top_y <= y <= self.bottom_y


def clamp_unit_position_to_walkable_lane(position: WorldPosition) -> WorldPosition:
    """Keep mobile units out of the reserved building lane."""

    return clamp_unit_position_to_walkable_lane_for_height(position)


def clamp_unit_position_to_walkable_lane_for_height(
    position: WorldPosition,
    world_height: int | float = DEFAULT_TERRAIN_HEIGHT,
) -> WorldPosition:
    """Keep mobile units out of the reserved building lane for a world height."""

    layout = terrain_layout_for_height(world_height)
    return WorldPosition(
        position.x,
        min(max(position.y, layout.unit_walkable_top_y), layout.unit_walkable_bottom_y),
    )


def is_building_lane_y(y: float) -> bool:
    """Return whether a y position is on the building lane."""
    return BUILDING_LANE_TOP_Y <= y <= BUILDING_LANE_BOTTOM_Y


def terrain_bands_for_height(world_height: int | float) -> tuple[TerrainBand, ...]:
    """Build drawable terrain bands for a screen height."""
    layout = terrain_layout_for_height(world_height)
    return (
        TerrainBand("sky", layout.sky_top_y, layout.sky_bottom_y, walkable=False),
        TerrainBand(
            "building_lane",
            layout.building_lane_top_y,
            layout.building_lane_bottom_y,
            walkable=False,
        ),
        TerrainBand(
            "frontier_ground",
            layout.unit_walkable_top_y,
            layout.unit_walkable_bottom_y,
            walkable=True,
        ),
    )


DEFAULT_TERRAIN_BANDS = terrain_bands_for_height(DEFAULT_TERRAIN_HEIGHT)

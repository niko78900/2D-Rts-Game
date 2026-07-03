"""Continuous side-scroller terrain bands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TerrainBand:
    name: str
    top_y: float
    bottom_y: float
    walkable: bool = True

    def contains_y(self, y: float) -> bool:
        return self.top_y <= y <= self.bottom_y


DEFAULT_TERRAIN_BANDS = (
    TerrainBand("sky", 0, 360, walkable=False),
    TerrainBand("frontier_ground", 360, 650, walkable=True),
    TerrainBand("ui_margin", 650, 720, walkable=False),
)

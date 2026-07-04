"""Project and runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data"
SCHEMA_ROOT = DATA_ROOT / "schemas"
ASSET_ROOT = PROJECT_ROOT / "assets"
SAVE_ROOT = PROJECT_ROOT / "saves"
UI_PANEL_HEIGHT = 112


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Configuration for the future Pygame app shell."""

    window_title: str = "House of Wolves Remastered"
    fullscreen: bool = True
    virtual_width: int = 1280
    virtual_height: int = 720
    target_fps: int = 60
    fixed_step_ms: int = 16
    camera_pan_speed: int = 720
    edge_scroll_margin: int = 24
    selection_drag_threshold: int = 6
    ui_panel_height: int = UI_PANEL_HEIGHT
    world_width: int = 7200
    world_height: int = 720
    data_root: Path = DATA_ROOT
    schema_root: Path = SCHEMA_ROOT
    asset_root: Path = ASSET_ROOT
    save_root: Path = SAVE_ROOT

    @property
    def virtual_size(self) -> tuple[int, int]:
        return (self.virtual_width, self.virtual_height)

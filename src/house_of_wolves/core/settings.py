"""Project and runtime settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from house_of_wolves.core.keybindings import default_keybindings

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
    fullscreen: bool = False
    display_index: int = 0
    show_resource_hitboxes: bool = False
    show_unit_hitboxes: bool = False
    show_building_hitboxes: bool = False
    show_debug_waypoints: bool = False
    show_performance_overlay: bool = False
    waves_enabled: bool = True
    wave_timer_enabled: bool = True
    wave_timer_seconds: int = 120
    initial_wave_delay_seconds: int = 120
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
    default_unit_pop_cost: int = 1
    hut_pop_cap_bonus: int = 10
    data_root: Path = DATA_ROOT
    schema_root: Path = SCHEMA_ROOT
    asset_root: Path = ASSET_ROOT
    save_root: Path = SAVE_ROOT
    keybindings: dict[str, str] = field(default_factory=default_keybindings)

    @property
    def virtual_size(self) -> tuple[int, int]:
        """Return the configured virtual screen size."""
        return (self.virtual_width, self.virtual_height)

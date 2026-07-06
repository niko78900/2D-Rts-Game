from __future__ import annotations

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.world.camera import Camera


def test_camera_clamps_to_world_bounds() -> None:
    """Verify that camera clamps to world bounds."""
    camera = Camera(viewport_width=300, viewport_height=200, world_width=1000, world_height=200)

    camera.move_by(900)
    assert camera.x == 700

    camera.move_by(-900)
    assert camera.x == 0


def test_camera_converts_between_screen_and_world_coordinates() -> None:
    """Verify that camera converts between screen and world coordinates."""
    camera = Camera(x=125, y=20, viewport_width=300, viewport_height=200)

    assert camera.world_to_screen(WorldPosition(175, 70)) == (50, 50)
    assert camera.screen_to_world(50, 50) == WorldPosition(175, 70)

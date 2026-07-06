"""Side-scrolling camera model."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import WorldPosition


@dataclass(slots=True)
class Camera:
    x: float = 0
    y: float = 0
    viewport_width: int = 1280
    viewport_height: int = 720
    world_width: int = 7200
    world_height: int = 720

    def clamp(self) -> None:
        """Clamp the camera inside world bounds."""
        self.x = min(max(0, self.x), max(0, self.world_width - self.viewport_width))
        self.y = min(max(0, self.y), max(0, self.world_height - self.viewport_height))

    def move_by(self, dx: float, dy: float = 0) -> None:
        """Move the camera by a delta and clamp it."""
        self.x += dx
        self.y += dy
        self.clamp()

    def world_to_screen(self, position: WorldPosition) -> tuple[int, int]:
        """Convert a world position into screen coordinates."""
        return (round(position.x - self.x), round(position.y - self.y))

    def screen_to_world(self, x: float, y: float) -> WorldPosition:
        """Convert a screen position into world coordinates."""
        return WorldPosition(self.x + x, self.y + y)

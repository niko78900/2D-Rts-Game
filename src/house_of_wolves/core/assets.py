"""Placeholder asset factories and asset registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pygame

Color = tuple[int, int, int, int]


class SilentSound:
    """Drop-in stand-in for pygame sounds before real audio is available."""

    def __init__(self, name: str = "silent") -> None:
        """Initialize this object with its runtime dependencies."""
        self.name = name
        self.volume = 1.0
        self.play_count = 0

    def play(self, *_args: object, **_kwargs: object) -> None:
        """Play this placeholder sound if audio is enabled."""
        self.play_count += 1

    def stop(self) -> None:
        """Stop this placeholder sound."""
        return None

    def set_volume(self, volume: float) -> None:
        """Set this placeholder sound volume."""
        self.volume = max(0.0, min(1.0, volume))


@dataclass(slots=True)
class PlaceholderAssetFactory:
    """Creates simple generated surfaces that keep scaffold tests windowless."""

    default_size: tuple[int, int] = (64, 64)
    background: Color = (31, 34, 36, 255)
    foreground: Color = (218, 199, 151, 255)
    accent: Color = (105, 142, 92, 255)

    def make_surface(
        self,
        label: str,
        size: tuple[int, int] | None = None,
        color: Color | None = None,
    ) -> pygame.Surface:
        """Create a generated placeholder surface."""
        if not pygame.get_init():
            pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()

        surface_size = size or self.default_size
        surface = pygame.Surface(surface_size, pygame.SRCALPHA)
        surface.fill(color or self.background)
        pygame.draw.rect(surface, self.foreground, surface.get_rect(), width=2)

        if label:
            font = pygame.font.Font(None, max(14, min(surface_size) // 3))
            text = font.render(label[:3].upper(), True, self.accent)
            surface.blit(text, text.get_rect(center=surface.get_rect().center))

        return surface

    def make_icon(self, key: str) -> pygame.Surface:
        """Create a generated command or UI icon surface."""
        return self.make_surface(key, (48, 48))

    def make_world_sprite(self, key: str) -> pygame.Surface:
        """Create a generated world sprite surface."""
        return self.make_surface(key, (72, 96))

    def make_sound(self, key: str) -> SilentSound:
        """Create a silent placeholder sound object."""
        return SilentSound(key)


@dataclass(slots=True)
class AssetRegistry:
    """In-memory registry for generated or loaded assets."""

    asset_root: Path
    factory: PlaceholderAssetFactory = field(default_factory=PlaceholderAssetFactory)
    surfaces: dict[str, pygame.Surface] = field(default_factory=dict)
    sounds: dict[str, SilentSound] = field(default_factory=dict)

    def surface(self, key: str, size: tuple[int, int] | None = None) -> pygame.Surface:
        """Return a generated placeholder surface for an asset key."""
        if key not in self.surfaces:
            self.surfaces[key] = self.factory.make_surface(key, size)
        return self.surfaces[key]

    def sound(self, key: str) -> SilentSound:
        """Return a generated silent sound for an asset key."""
        if key not in self.sounds:
            self.sounds[key] = self.factory.make_sound(key)
        return self.sounds[key]

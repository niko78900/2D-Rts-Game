from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from house_of_wolves.core.assets import PlaceholderAssetFactory


def test_placeholder_surface_factory_returns_surface() -> None:
    factory = PlaceholderAssetFactory()
    surface = factory.make_icon("settler")

    assert isinstance(surface, pygame.Surface)
    assert surface.get_size() == (48, 48)


def test_silent_sound_tracks_volume_and_play_count() -> None:
    sound = PlaceholderAssetFactory().make_sound("confirm")
    sound.set_volume(0.25)
    sound.play()

    assert sound.volume == 0.25
    assert sound.play_count == 1

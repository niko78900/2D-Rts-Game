from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from house_of_wolves.core.app import main
from house_of_wolves.core.runtime import GameRuntime
from house_of_wolves.core.settings import AppSettings


def test_validate_cli_mode_keeps_data_validation_behavior(capsys) -> None:
    assert main(["--validate"]) == 0

    output = capsys.readouterr().out
    assert "House of Wolves scaffold validated" in output
    assert "units=9" in output


def test_runtime_initializes_updates_renders_and_shuts_down_windowless() -> None:
    runtime = GameRuntime(AppSettings())

    runtime.initialize()
    try:
        runtime.update(16)
        runtime.render()

        assert runtime.screen is not None
        assert isinstance(runtime.screen, pygame.Surface)
    finally:
        runtime.shutdown()

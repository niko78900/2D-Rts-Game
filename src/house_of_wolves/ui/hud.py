"""HUD shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HudViewModel:
    resources: dict[str, int]
    population: tuple[int, int]
    wave_timer_ms: int | None = None

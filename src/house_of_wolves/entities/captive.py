"""Rescue objective entity."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class Captive(Entity):
    rescued: bool = False
    reward_units: tuple[str, ...] = ()

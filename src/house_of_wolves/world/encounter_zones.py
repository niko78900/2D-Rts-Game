"""Named map zones for raids, rescues, camps, and boss encounters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EncounterZone:
    id: str
    label: str
    x_start: float
    x_end: float
    faction: str

    def contains_x(self, x: float) -> bool:
        """Return whether the x coordinate is inside this zone."""
        return self.x_start <= x <= self.x_end


DEFAULT_ENCOUNTER_ZONES = (
    EncounterZone("west_frontier", "West Frontier", 0, 1200, "wolves"),
    EncounterZone("central_wilds", "Central Wilds", 1200, 4800, "neutral"),
    EncounterZone("vilereck_hold", "Lord Vilereck's Hold", 4800, 7200, "vilereck"),
)

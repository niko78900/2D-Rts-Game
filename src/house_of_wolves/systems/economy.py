"""Economy system shell."""

from __future__ import annotations

from dataclasses import dataclass, field

RESOURCE_TYPES = ("wood", "food", "stone", "iron", "gold")


@dataclass(slots=True)
class ResourceWallet:
    amounts: dict[str, int] = field(default_factory=lambda: {key: 0 for key in RESOURCE_TYPES})

    def can_afford(self, cost: dict[str, int]) -> bool:
        return all(self.amounts.get(resource, 0) >= amount for resource, amount in cost.items())

    def spend(self, cost: dict[str, int]) -> bool:
        if not self.can_afford(cost):
            return False
        for resource, amount in cost.items():
            self.amounts[resource] = self.amounts.get(resource, 0) - amount
        return True


@dataclass(slots=True)
class EconomySystem:
    def update(self, world: object, dt_ms: int) -> None:
        return None

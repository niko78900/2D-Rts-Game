"""Base entity model."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, Footprint, JsonObject, WorldPosition


@dataclass(slots=True)
class Entity:
    id: EntityId
    owner: str
    position: WorldPosition
    footprint: Footprint
    hp: int = 1
    max_hp: int | None = None
    alive: bool = True
    tags: tuple[str, ...] = ()

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Return the entity world-space bounds."""
        return self.footprint.bounds_at(self.position)

    def to_json(self) -> JsonObject:
        """Serialize this object into JSON-compatible data."""
        return {
            "id": self.id.to_json(),
            "owner": self.owner,
            "position": self.position.to_json(),
            "footprint": self.footprint.to_json(),
            "hp": self.hp,
            "max_hp": self.max_hp,
            "alive": self.alive,
            "tags": list(self.tags),
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> Entity:
        """Build this object from JSON-compatible data."""
        return cls(
            id=EntityId.from_json(value["id"]),
            owner=str(value["owner"]),
            position=WorldPosition.from_json(value["position"]),
            footprint=Footprint.from_json(value["footprint"]),
            hp=int(value.get("hp", 1)),
            max_hp=(
                int(value["max_hp"]) if value.get("max_hp") is not None else None
            ),
            alive=bool(value.get("alive", True)),
            tags=tuple(value.get("tags", [])),
        )

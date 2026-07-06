"""Stable contracts shared by world, entity, system, and UI modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True, order=True)
class EntityId:
    """Stable simulation identifier for one entity."""

    value: int

    def __post_init__(self) -> None:
        """Normalize derived state after dataclass initialization."""
        if self.value < 0:
            raise ValueError("EntityId must be non-negative")

    def __int__(self) -> int:
        """Return this identifier as an integer."""
        return self.value

    def to_json(self) -> int:
        """Serialize this object into JSON-compatible data."""
        return self.value

    @classmethod
    def from_json(cls, value: int) -> EntityId:
        """Build this object from JSON-compatible data."""
        return cls(int(value))


@dataclass(frozen=True, slots=True)
class WorldPosition:
    """Position in continuous world pixels."""

    x: float
    y: float

    def to_tuple(self) -> tuple[float, float]:
        """Return this position as an (x, y) tuple."""
        return (self.x, self.y)

    def to_json(self) -> list[float]:
        """Serialize this object into JSON-compatible data."""
        return [self.x, self.y]

    @classmethod
    def from_json(cls, value: list[float] | tuple[float, float]) -> WorldPosition:
        """Build this object from JSON-compatible data."""
        return cls(float(value[0]), float(value[1]))


@dataclass(frozen=True, slots=True)
class Footprint:
    """World-space footprint anchored to a position."""

    width: float
    height: float
    anchor_x: float = 0.5
    anchor_y: float = 1.0

    def __post_init__(self) -> None:
        """Normalize derived state after dataclass initialization."""
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Footprint dimensions must be positive")

    def bounds_at(self, position: WorldPosition) -> tuple[float, float, float, float]:
        """Return this footprint placed at a world position."""
        left = position.x - (self.width * self.anchor_x)
        top = position.y - (self.height * self.anchor_y)
        return (left, top, self.width, self.height)

    def to_json(self) -> JsonObject:
        """Serialize this object into JSON-compatible data."""
        return {
            "width": self.width,
            "height": self.height,
            "anchor_x": self.anchor_x,
            "anchor_y": self.anchor_y,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> Footprint:
        """Build this object from JSON-compatible data."""
        return cls(
            width=float(value["width"]),
            height=float(value["height"]),
            anchor_x=float(value.get("anchor_x", 0.5)),
            anchor_y=float(value.get("anchor_y", 1.0)),
        )


@dataclass(frozen=True, slots=True)
class ResourceAmount:
    """One resource quantity in the five-resource economy."""

    resource_type: str
    amount: int

    def __post_init__(self) -> None:
        """Normalize derived state after dataclass initialization."""
        if not self.resource_type:
            raise ValueError("resource_type is required")
        if self.amount < 0:
            raise ValueError("resource amount must be non-negative")

    def to_json(self) -> JsonObject:
        """Serialize this object into JSON-compatible data."""
        return {"resource_type": self.resource_type, "amount": self.amount}

    @classmethod
    def from_json(cls, value: JsonObject) -> ResourceAmount:
        """Build this object from JSON-compatible data."""
        return cls(resource_type=str(value["resource_type"]), amount=int(value["amount"]))


@dataclass(slots=True)
class ProductionQueueItem:
    """An item waiting in a building production queue."""

    item_id: str
    remaining_ms: int
    quantity: int = 1

    def __post_init__(self) -> None:
        """Normalize derived state after dataclass initialization."""
        if not self.item_id:
            raise ValueError("item_id is required")
        if self.remaining_ms < 0:
            raise ValueError("remaining_ms must be non-negative")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")

    def to_json(self) -> JsonObject:
        """Serialize this object into JSON-compatible data."""
        return {
            "item_id": self.item_id,
            "remaining_ms": self.remaining_ms,
            "quantity": self.quantity,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> ProductionQueueItem:
        """Build this object from JSON-compatible data."""
        return cls(
            item_id=str(value["item_id"]),
            remaining_ms=int(value["remaining_ms"]),
            quantity=int(value.get("quantity", 1)),
        )


@dataclass(frozen=True, slots=True)
class Command:
    """Serializable order issued to one or more entities."""

    type: str
    issuer_ids: tuple[EntityId, ...]
    target_entity_id: EntityId | None = None
    target_pos: WorldPosition | None = None
    queued: bool = False
    payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize derived state after dataclass initialization."""
        if not self.type:
            raise ValueError("command type is required")
        if not self.issuer_ids:
            raise ValueError("command requires at least one issuer")

    def to_json(self) -> JsonObject:
        """Serialize this object into JSON-compatible data."""
        return {
            "type": self.type,
            "issuer_ids": [issuer.to_json() for issuer in self.issuer_ids],
            "target_entity_id": (
                self.target_entity_id.to_json() if self.target_entity_id is not None else None
            ),
            "target_pos": self.target_pos.to_json() if self.target_pos is not None else None,
            "queued": self.queued,
            "payload": self.payload,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> Command:
        """Build this object from JSON-compatible data."""
        target_entity_id = value.get("target_entity_id")
        target_pos = value.get("target_pos")
        return cls(
            type=str(value["type"]),
            issuer_ids=tuple(EntityId.from_json(item) for item in value["issuer_ids"]),
            target_entity_id=(
                EntityId.from_json(target_entity_id) if target_entity_id is not None else None
            ),
            target_pos=WorldPosition.from_json(target_pos) if target_pos is not None else None,
            queued=bool(value.get("queued", False)),
            payload=dict(value.get("payload", {})),
        )


@dataclass(slots=True)
class CommandQueue:
    """Per-entity command queue."""

    owner_id: EntityId
    commands: list[Command] = field(default_factory=list)

    def replace(self, command: Command) -> None:
        """Replace the queued commands with a single command."""
        self.commands = [command]

    def append(self, command: Command) -> None:
        """Append a command to the queue."""
        self.commands.append(command)

    def clear(self) -> None:
        """Clear the current collection or command queue."""
        self.commands.clear()

    def pop_next(self) -> Command | None:
        """Pop and return the next queued command."""
        if not self.commands:
            return None
        return self.commands.pop(0)

    def peek(self) -> Command | None:
        """Return the next queued command without removing it."""
        if not self.commands:
            return None
        return self.commands[0]

    def to_json(self) -> JsonObject:
        """Serialize this object into JSON-compatible data."""
        return {
            "owner_id": self.owner_id.to_json(),
            "commands": [command.to_json() for command in self.commands],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> CommandQueue:
        """Build this object from JSON-compatible data."""
        return cls(
            owner_id=EntityId.from_json(value["owner_id"]),
            commands=[Command.from_json(command) for command in value.get("commands", [])],
        )


class System(Protocol):
    """Update interface shared by scaffold systems."""

    def update(self, world: Any, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""

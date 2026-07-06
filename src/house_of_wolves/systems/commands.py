"""Command object helpers and validation."""

from __future__ import annotations

from collections.abc import Iterable

from house_of_wolves.core.contracts import Command, EntityId, WorldPosition

VALID_COMMAND_TYPES = {
    "move",
    "attack",
    "gather",
    "build",
    "repair",
    "produce",
    "upgrade",
    "rescue",
    "cancel",
}

COMMAND_REQUIREMENTS = {
    "move": {"target_pos"},
    "attack": {"target_entity_id"},
    "gather": {"target_entity_id"},
    "build": {"target_pos", "building_id"},
    "repair": {"target_entity_id"},
    "produce": {"producer_id", "unit_id"},
    "upgrade": {"producer_id", "upgrade_id"},
    "rescue": {"target_entity_id"},
    "cancel": set(),
}


class CommandValidationError(ValueError):
    """Raised when a command is malformed for its command type."""


def _normalize_entity_id(value: EntityId | int | None) -> EntityId | None:
    """Return entity identifiers for normalize entity id."""
    if value is None:
        return None
    if isinstance(value, EntityId):
        return value
    return EntityId(int(value))


def _normalize_position(value: WorldPosition | tuple[float, float] | None) -> WorldPosition | None:
    """Return the position used for normalize position."""
    if value is None:
        return None
    if isinstance(value, WorldPosition):
        return value
    return WorldPosition(float(value[0]), float(value[1]))


def make_command(
    command_type: str,
    issuer_ids: Iterable[EntityId | int],
    *,
    target_entity_id: EntityId | int | None = None,
    target_pos: WorldPosition | tuple[float, float] | None = None,
    queued: bool = False,
    **payload: object,
) -> Command:
    """Create and validate a command object."""
    normalized_issuer_ids = tuple(
        EntityId(int(item)) if not isinstance(item, EntityId) else item for item in issuer_ids
    )
    command = Command(
        type=command_type,
        issuer_ids=normalized_issuer_ids,
        target_entity_id=_normalize_entity_id(target_entity_id),
        target_pos=_normalize_position(target_pos),
        queued=queued,
        payload=payload,
    )
    return validate_command(command)


def validate_command(command: Command) -> Command:
    """Validate a command payload and type."""
    if command.type not in VALID_COMMAND_TYPES:
        raise CommandValidationError(f"Invalid command type: {command.type}")

    requirements = COMMAND_REQUIREMENTS[command.type]
    if "target_entity_id" in requirements and command.target_entity_id is None:
        raise CommandValidationError(f"{command.type} requires target_entity_id")
    if "target_pos" in requirements and command.target_pos is None:
        raise CommandValidationError(f"{command.type} requires target_pos")

    missing_payload = sorted(
        requirement
        for requirement in requirements
        if requirement not in {"target_entity_id", "target_pos"}
        and requirement not in command.payload
    )
    if missing_payload:
        joined = ", ".join(missing_payload)
        raise CommandValidationError(f"{command.type} missing payload field(s): {joined}")

    return command

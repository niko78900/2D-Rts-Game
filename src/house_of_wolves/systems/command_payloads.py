"""Helpers for reading entity ids from command payload dictionaries."""

from __future__ import annotations

from house_of_wolves.core.contracts import Command, EntityId


def payload_entity_id(command: Command, key: str) -> EntityId | None:
    """Return an entity id from a command payload, or None when missing."""
    return entity_id_from_value(command.payload.get(key))


def entity_id_from_value(value: object) -> EntityId | None:
    """Return an entity id from a serialized id value, or None when missing."""
    if value is None:
        return None
    return EntityId(int(value))

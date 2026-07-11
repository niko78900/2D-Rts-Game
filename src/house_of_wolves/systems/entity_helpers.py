"""Small entity predicates and state helpers shared by simulation systems."""

from __future__ import annotations


def is_settler(entity: object | None) -> bool:
    """Return whether an entity is a live Settler."""
    return (
        entity is not None
        and getattr(entity, "alive", False)
        and "settler" in getattr(entity, "tags", ())
    )


def set_state(entity: object, state: str) -> None:
    """Set an entity state when the entity supports stateful behavior."""
    if hasattr(entity, "state"):
        entity.state = state

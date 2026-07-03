"""Serialization helpers for scaffold dataclasses."""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convert scaffold objects into JSON-friendly values."""

    if hasattr(value, "to_json"):
        return value.to_json()
    if is_dataclass(value):
        return {
            key: to_jsonable(item)
            for key, item in value.__dict__.items()
            if not key.startswith("_")
        }
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value

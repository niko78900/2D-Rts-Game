"""Cursor state shell."""

from __future__ import annotations

from enum import StrEnum


class CursorState(StrEnum):
    DEFAULT = "default"
    MOVE = "move"
    ATTACK = "attack"
    GATHER = "gather"
    BUILD_VALID = "build_valid"
    BUILD_INVALID = "build_invalid"
    REPAIR = "repair"

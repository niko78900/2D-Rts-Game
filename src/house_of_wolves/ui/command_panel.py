"""Command panel shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandButton:
    id: str
    label: str
    command_type: str
    enabled: bool = True

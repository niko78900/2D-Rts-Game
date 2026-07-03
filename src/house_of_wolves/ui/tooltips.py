"""Tooltip shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tooltip:
    title: str
    body: str
    cost: dict[str, int] | None = None

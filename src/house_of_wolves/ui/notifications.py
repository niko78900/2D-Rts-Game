"""Notification shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Notification:
    message: str
    ttl_ms: int = 3000
    severity: str = "info"

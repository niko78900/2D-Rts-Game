"""Small frame profiler used by the RTS runtime and debug overlay."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter


@dataclass(slots=True)
class PerformanceCounters:
    """Per-frame counters for expensive simulation work."""

    path_jobs_processed: int = 0
    full_path_calculations: int = 0
    resource_searches: int = 0
    resource_candidates_checked: int = 0
    collision_checks: int = 0
    notifications_created: int = 0
    notifications_suppressed: int = 0
    notifications_active: int = 0
    active_projectiles: int = 0
    active_combat_effects: int = 0
    attacks_started: int = 0
    projectile_hits: int = 0

    def reset(self) -> None:
        """Reset accumulated counters to their initial values."""
        self.path_jobs_processed = 0
        self.full_path_calculations = 0
        self.resource_searches = 0
        self.resource_candidates_checked = 0
        self.collision_checks = 0
        self.notifications_created = 0
        self.notifications_suppressed = 0
        self.attacks_started = 0
        self.projectile_hits = 0


@dataclass(slots=True)
class PerformanceStats:
    """Frame timing and object-count snapshot for optional diagnostics."""

    timings_ms: dict[str, float] = field(default_factory=dict)
    counters: PerformanceCounters = field(default_factory=PerformanceCounters)
    fps: float = 0.0
    entity_count: int = 0
    unit_count: int = 0
    resource_count: int = 0
    building_count: int = 0

    def reset_frame(self) -> None:
        """Reset counters that are scoped to a single frame."""
        self.timings_ms.clear()
        self.counters.reset()

    def record_timing(self, name: str, elapsed_ms: float) -> None:
        """Record elapsed time for a named performance bucket."""
        self.timings_ms[name] = self.timings_ms.get(name, 0.0) + elapsed_ms

    def snapshot_world_counts(self, world: object) -> None:
        """Snapshot current world entity counts for profiling."""
        entities = [
            entity
            for entity in getattr(world, "entities", {}).values()
            if getattr(entity, "alive", False)
        ]
        self.entity_count = len(entities)
        self.unit_count = sum("unit" in getattr(entity, "tags", ()) for entity in entities)
        self.resource_count = sum(
            "resource" in getattr(entity, "tags", ()) for entity in entities
        )
        self.building_count = sum(
            "building" in getattr(entity, "tags", ()) for entity in entities
        )


@contextmanager
def time_block(stats: PerformanceStats, name: str) -> Iterator[None]:
    """Record elapsed wall-clock time for one frame block."""

    start = perf_counter()
    try:
        yield
    finally:
        stats.record_timing(name, (perf_counter() - start) * 1000.0)


def add_collision_checks(world: object, count: int = 1) -> None:
    """Increment collision diagnostics when the world carries perf stats."""

    stats = getattr(world, "performance_stats", None)
    if stats is not None:
        stats.counters.collision_checks += max(0, int(count))

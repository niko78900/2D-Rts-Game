from __future__ import annotations

from house_of_wolves.core.performance import PerformanceStats, add_collision_checks
from house_of_wolves.world.demo import create_demo_world


def test_performance_stats_reset_keeps_world_count_snapshot_separate() -> None:
    stats = PerformanceStats()
    world = create_demo_world()

    stats.record_timing("movement", 1.25)
    stats.counters.path_jobs_processed = 2
    add_collision_checks(type("WorldLike", (), {"performance_stats": stats})(), 7)
    stats.snapshot_world_counts(world)

    assert stats.unit_count > 0
    assert stats.resource_count > 0
    assert stats.counters.collision_checks == 7

    stats.reset_frame()

    assert stats.timings_ms == {}
    assert stats.counters.path_jobs_processed == 0
    assert stats.counters.collision_checks == 0
    assert stats.unit_count > 0

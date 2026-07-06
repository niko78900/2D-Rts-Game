from __future__ import annotations

from house_of_wolves.core.performance import PerformanceStats, add_collision_checks
from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.world import WorldState


def test_performance_stats_reset_keeps_world_count_snapshot_separate() -> None:
    """Verify that performance stats reset keeps world count snapshot separate."""
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


def test_world_notifications_dedupe_refresh_and_expire() -> None:
    """Verify that world notifications dedupe refresh and expire."""
    world = WorldState()

    world.notify("Cannot reach resource.", duration_ms=1000)
    world.notify("Cannot reach resource.", duration_ms=2500)

    assert len(world.notifications) == 1
    assert world.notifications[0].remaining_ms == 2500
    assert world.performance_stats.counters.notifications_created == 1
    assert world.performance_stats.counters.notifications_suppressed == 1
    assert world.performance_stats.counters.notifications_active == 1

    world.update_notifications(2500)

    assert world.notifications == []
    assert world.performance_stats.counters.notifications_active == 0

from __future__ import annotations

from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.terrain import (
    BUILDING_LANE_BOTTOM_Y,
    UNIT_WALKABLE_TOP_Y,
    is_building_lane_y,
)


def test_demo_world_bootstrap_creates_expected_placeholder_entities() -> None:
    world = create_demo_world()
    tag_sets = [set(entity.tags) for entity in world.entities.values()]

    assert sum("unit" in tags for tags in tag_sets) == 3
    assert sum("resource" in tags for tags in tag_sets) == 2
    assert sum("building" in tags for tags in tag_sets) == 1
    assert sum("selectable" in tags for tags in tag_sets) == 6
    assert all("movable" in tags for tags in tag_sets if "unit" in tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    assert hut.position.y == BUILDING_LANE_BOTTOM_Y
    assert is_building_lane_y(hut.position.y)
    assert hut.dropoff_point is not None
    assert hut.dropoff_point.y == UNIT_WALKABLE_TOP_Y
    assert hut.production_config.dropoff is True
    assert hut.production_config.population_cap_bonus == 5
    assert hut.production_config.trainable_units == ("settler", "spearman")
    assert world.resources["wood"] == 120

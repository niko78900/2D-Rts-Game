from __future__ import annotations

from house_of_wolves.systems.economy import active_resource_nodes
from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.terrain import (
    BUILDING_LANE_BOTTOM_Y,
    UNIT_WALKABLE_TOP_Y,
    is_building_lane_y,
)


def test_demo_world_bootstrap_creates_expected_placeholder_entities() -> None:
    world = create_demo_world()
    tag_sets = [set(entity.tags) for entity in world.entities.values()]

    assert sum("unit" in tags for tags in tag_sets) == 4
    assert sum("unit" in tags and "selectable" in tags for tags in tag_sets) == 4
    assert sum("enemy" in tags for tags in tag_sets) == 1
    assert any("raider_swordsman" in tags for tags in tag_sets)
    assert sum("resource" in tags for tags in tag_sets) == 55
    assert sum("building" in tags for tags in tag_sets) == 1
    assert sum("selectable" in tags for tags in tag_sets) == 60
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
    assert len(active_resource_nodes(world, "wood")) == 40
    assert len(active_resource_nodes(world, "gold")) == 5
    assert len(active_resource_nodes(world, "stone")) == 5
    assert len(active_resource_nodes(world, "iron")) == 5


def test_resource_nodes_use_smaller_blocking_bounds_than_visual_bounds() -> None:
    world = create_demo_world()
    tree = next(entity for entity in world.entities.values() if "wood_tree" in entity.tags)
    mine = next(entity for entity in world.entities.values() if "gold_mine" in entity.tags)

    assert tree.blocking_bounds[2] < tree.bounds[2]
    assert tree.blocking_bounds[3] < tree.bounds[3]
    assert tree.blocking_bounds[1] > tree.bounds[1]
    assert mine.blocking_bounds[2] < mine.bounds[2]
    assert mine.blocking_bounds[3] < mine.bounds[3]
    assert mine.blocking_bounds[2] >= 120


def test_demo_resource_nodes_are_spread_out_without_blocking_overlap() -> None:
    world = create_demo_world()
    resources = active_resource_nodes(world)
    xs = [resource.position.x for resource in resources]

    assert max(xs) - min(xs) > world.settings.world_width * 0.8
    for index, resource in enumerate(resources):
        for other in resources[index + 1 :]:
            assert not _bounds_intersect(resource.blocking_bounds, other.blocking_bounds)


def _bounds_intersect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    return not (
        first_left + first_width < second_left
        or second_left + second_width < first_left
        or first_top + first_height < second_top
        or second_top + second_height < first_top
    )

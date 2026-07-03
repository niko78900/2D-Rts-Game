from __future__ import annotations

from house_of_wolves.world.demo import create_demo_world


def test_demo_world_bootstrap_creates_expected_placeholder_entities() -> None:
    world = create_demo_world()
    tag_sets = [set(entity.tags) for entity in world.entities.values()]

    assert sum("unit" in tags for tags in tag_sets) == 3
    assert sum("resource" in tags for tags in tag_sets) == 2
    assert sum("building" in tags for tags in tag_sets) == 1
    assert sum("selectable" in tags for tags in tag_sets) == 6
    assert all("movable" in tags for tags in tag_sets if "unit" in tags)
    assert world.resources["wood"] == 120

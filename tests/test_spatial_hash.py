from __future__ import annotations

from house_of_wolves.core.contracts import EntityId
from house_of_wolves.world.spatial_hash import SpatialHash


def test_spatial_hash_insert_query_move_remove() -> None:
    spatial = SpatialHash(cell_size=100)
    first = EntityId(1)
    second = EntityId(2)

    spatial.insert(first, (10, 10, 20, 20))
    spatial.insert(second, (220, 10, 20, 20))

    assert spatial.query((0, 0, 100, 100)) == {first}

    spatial.move(second, (50, 50, 20, 20))
    assert spatial.query((0, 0, 100, 100)) == {first, second}

    spatial.remove(first)
    assert spatial.query((0, 0, 100, 100)) == {second}

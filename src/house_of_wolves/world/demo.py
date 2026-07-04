"""Deterministic demo-world bootstrap for the minimal playable slice."""

from __future__ import annotations

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.entities.unit import Unit
from house_of_wolves.world.camera import Camera
from house_of_wolves.world.terrain import terrain_bands_for_height, terrain_layout_for_height
from house_of_wolves.world.world import WorldState


def create_demo_world(settings: AppSettings | None = None) -> WorldState:
    """Create a small deterministic scene for the first playable slice."""

    app_settings = settings or AppSettings()
    world = WorldState(settings=app_settings)
    world.camera = Camera(
        viewport_width=app_settings.virtual_width,
        viewport_height=app_settings.virtual_height,
        world_width=app_settings.world_width,
        world_height=app_settings.world_height,
    )
    world.terrain_bands = terrain_bands_for_height(app_settings.world_height)
    terrain = terrain_layout_for_height(app_settings.world_height)
    unit_lane_height = terrain.unit_walkable_bottom_y - terrain.unit_walkable_top_y
    world.resources.update({"wood": 120, "food": 80, "stone": 40, "iron": 0, "gold": 0})

    _add_unit(
        world,
        "settler",
        360,
        terrain.unit_walkable_top_y + unit_lane_height * 0.35,
        speed=92,
        hp=40,
    )
    _add_unit(
        world,
        "spearman",
        430,
        terrain.unit_walkable_top_y + unit_lane_height * 0.38,
        speed=78,
        hp=70,
    )
    _add_unit(
        world,
        "archer",
        500,
        terrain.unit_walkable_top_y + unit_lane_height * 0.33,
        speed=82,
        hp=55,
    )

    _add_tree(world, 760, terrain.unit_walkable_top_y + unit_lane_height * 0.38)
    _add_gold_mine(world, 1120, terrain.unit_walkable_top_y + unit_lane_height * 0.43)
    _add_hut(world, 230, terrain.building_lane_bottom_y)

    return world


def _add_unit(
    world: WorldState,
    unit_id: str,
    x: float,
    y: float,
    *,
    speed: float,
    hp: int,
) -> None:
    entity = Unit(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(x, y),
        footprint=Footprint(38, 58),
        hp=hp,
        tags=("unit", unit_id, "selectable", "movable"),
        speed=speed,
    )
    world.add_entity(entity)


def _add_tree(world: WorldState, x: float, y: float) -> None:
    entity = ResourceNode(
        id=world.allocate_entity_id(),
        owner="neutral",
        position=WorldPosition(x, y),
        footprint=Footprint(82, 126),
        hp=1,
        tags=("resource", "wood_tree", "selectable"),
        resource_type="wood",
        amount_remaining=250,
        gather_time_ms=900,
        harvest_slots=2,
        depleted_replacement="tree_stump",
    )
    world.add_entity(entity)


def _add_gold_mine(world: WorldState, x: float, y: float) -> None:
    entity = ResourceNode(
        id=world.allocate_entity_id(),
        owner="neutral",
        position=WorldPosition(x, y),
        footprint=Footprint(132, 86),
        hp=1,
        tags=("resource", "gold_mine", "selectable"),
        resource_type="gold",
        amount_remaining=400,
        gather_time_ms=1200,
        harvest_slots=3,
        depleted_replacement="gold_mine_empty",
    )
    world.add_entity(entity)


def _add_hut(world: WorldState, x: float, y: float) -> None:
    entity = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(x, y),
        footprint=Footprint(150, 116),
        hp=650,
        tags=("building", "hut", "selectable"),
        build_time_ms=12000,
        complete=True,
        functions=Building.production_functions(
            dropoff=True,
            population_cap_bonus=5,
            trainable_units=("settler", "spearman"),
        ),
        dropoff_point=WorldPosition(
            x + 220,
            terrain_layout_for_height(world.settings.world_height).unit_walkable_top_y,
        ),
    )
    world.add_entity(entity)

"""Deterministic demo-world bootstrap for the minimal playable slice."""

from __future__ import annotations

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.core.game_specs import building_spec_from_data, resource_spec_from_type
from house_of_wolves.core.geometry import bounds_intersect as _bounds_intersect
from house_of_wolves.core.geometry import inflate_bounds as _inflate_bounds
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.systems.production import create_combat_unit
from house_of_wolves.world.camera import Camera
from house_of_wolves.world.terrain import terrain_bands_for_height, terrain_layout_for_height
from house_of_wolves.world.world import WorldState

BASE_RESOURCE_LAYOUT_WIDTH = 7200
INITIAL_TREE_COUNT = 40
INITIAL_MINE_COUNT_PER_TYPE = 5
TREE_ROW_FACTORS = (0.58, 0.86, 0.72, 0.46, 0.64)
TREE_CLEARANCE_PX = 18
GOLD_MINE_LAYOUT = (
    (1120, 0.43),
    (2480, 0.76),
    (3880, 0.34),
    (5280, 0.66),
    (6680, 0.45),
)
STONE_OUTCROP_LAYOUT = (
    (1320, 0.62),
    (2860, 0.27),
    (4260, 0.82),
    (5660, 0.38),
    (6920, 0.72),
)
IRON_DEPOSIT_LAYOUT = (
    (1420, 0.28),
    (3180, 0.55),
    (4580, 0.24),
    (5980, 0.78),
    (6420, 0.32),
)


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
    world.resources.update({"wood": 120, "food": 80, "stone": 40, "iron": 20, "gold": 0})

    _add_unit(
        world,
        "settler",
        360,
        terrain.unit_walkable_top_y + unit_lane_height * 0.35,
    )
    _add_unit(
        world,
        "spearman",
        430,
        terrain.unit_walkable_top_y + unit_lane_height * 0.38,
    )
    _add_unit(
        world,
        "archer",
        500,
        terrain.unit_walkable_top_y + unit_lane_height * 0.33,
    )
    _add_enemy_unit(world, 1520, terrain.unit_walkable_top_y + unit_lane_height * 0.36)

    _add_initial_resource_nodes(world, unit_lane_height)
    _add_hut(world, 230, terrain.building_lane_bottom_y)

    return world


def _add_initial_resource_nodes(world: WorldState, unit_lane_height: float) -> None:
    """Seed the map at configured resource caps with deterministic spread."""

    _add_tree(world, _scaled_resource_x(world, 760), _resource_y(world, unit_lane_height, 0.38))

    for x, row_factor in GOLD_MINE_LAYOUT[:INITIAL_MINE_COUNT_PER_TYPE]:
        _add_gold_mine(
            world,
            _scaled_resource_x(world, x),
            _resource_y(world, unit_lane_height, row_factor),
        )
    for x, row_factor in STONE_OUTCROP_LAYOUT[:INITIAL_MINE_COUNT_PER_TYPE]:
        _add_stone_outcrop(
            world,
            _scaled_resource_x(world, x),
            _resource_y(world, unit_lane_height, row_factor),
        )
    for x, row_factor in IRON_DEPOSIT_LAYOUT[:INITIAL_MINE_COUNT_PER_TYPE]:
        _add_iron_deposit(
            world,
            _scaled_resource_x(world, x),
            _resource_y(world, unit_lane_height, row_factor),
        )

    tree_step = 160
    for index in range(1, INITIAL_TREE_COUNT):
        x = 760 + (index * tree_step)
        row_factor = TREE_ROW_FACTORS[index % len(TREE_ROW_FACTORS)]
        _add_tree_at_clear_position(world, x, unit_lane_height, row_factor)


def _resource_y(world: WorldState, unit_lane_height: float, row_factor: float) -> float:
    """Return a terrain-aligned y position for resources."""
    terrain = terrain_layout_for_height(world.settings.world_height)
    return terrain.unit_walkable_top_y + unit_lane_height * row_factor


def _scaled_resource_x(world: WorldState, base_x: float) -> float:
    """Scale a resource x position to the configured world width."""
    scale = world.settings.world_width / BASE_RESOURCE_LAYOUT_WIDTH
    return min(max(base_x * scale, 80), world.settings.world_width - 80)


def _add_tree_at_clear_position(
    world: WorldState,
    base_x: float,
    unit_lane_height: float,
    preferred_row_factor: float,
) -> None:
    """Add tree at clear position."""
    x_offsets = (0, 52, -52, 104, -104, 156, -156, 208, -208, 260, -260, 312, -312)
    row_factors = (preferred_row_factor, *TREE_ROW_FACTORS)
    for x_offset in x_offsets:
        x = _scaled_resource_x(world, base_x + x_offset)
        for row_factor in row_factors:
            position = WorldPosition(x, _resource_y(world, unit_lane_height, row_factor))
            if _resource_bounds_clear(
                world,
                resource_spec_from_type("wood").blocking_footprint.bounds_at(position),
            ):
                _add_tree(world, position.x, position.y)
                return

    for fallback_x in range(760, round(world.settings.world_width) - 80, 96):
        x = _scaled_resource_x(world, fallback_x)
        for row_factor in TREE_ROW_FACTORS:
            position = WorldPosition(x, _resource_y(world, unit_lane_height, row_factor))
            if _resource_bounds_clear(
                world,
                resource_spec_from_type("wood").blocking_footprint.bounds_at(position),
            ):
                _add_tree(world, position.x, position.y)
                return

    raise RuntimeError("could not place initial tree without overlapping another object")


def _resource_bounds_clear(
    world: WorldState,
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return the bounds used for resource bounds clear."""
    padded = _inflate_bounds(bounds, TREE_CLEARANCE_PX)
    return all(
        not _bounds_intersect(
            padded,
            _inflate_bounds(getattr(entity, "blocking_bounds", entity.bounds), TREE_CLEARANCE_PX),
        )
        for entity in world.entities.values()
        if getattr(entity, "alive", False)
    )


def _add_unit(
    world: WorldState,
    unit_id: str,
    x: float,
    y: float,
) -> None:
    """Add unit."""
    entity = create_combat_unit(world, unit_id, "frontier", WorldPosition(x, y))
    world.add_entity(entity)


def _add_enemy_unit(world: WorldState, x: float, y: float) -> None:
    """Add enemy unit."""
    entity = create_combat_unit(world, "enemy_swordsman", "wolves", WorldPosition(x, y))
    world.add_entity(entity)


def _add_tree(world: WorldState, x: float, y: float) -> None:
    """Add tree."""
    _add_resource_node(world, "wood", x, y)


def _add_gold_mine(world: WorldState, x: float, y: float) -> None:
    """Add gold mine."""
    _add_resource_node(world, "gold", x, y)


def _add_stone_outcrop(world: WorldState, x: float, y: float) -> None:
    """Add stone outcrop."""
    _add_resource_node(world, "stone", x, y)


def _add_iron_deposit(world: WorldState, x: float, y: float) -> None:
    """Add iron deposit."""
    _add_resource_node(world, "iron", x, y)


def _add_resource_node(world: WorldState, resource_type: str, x: float, y: float) -> None:
    """Create a neutral resource node from the canonical resource data."""
    spec = resource_spec_from_type(resource_type)
    hp = spec.amount
    entity = ResourceNode(
        id=world.allocate_entity_id(),
        owner="neutral",
        position=WorldPosition(x, y),
        footprint=spec.footprint,
        hp=hp,
        max_hp=hp,
        tags=spec.tags,
        resource_type=resource_type,
        amount_remaining=hp,
        max_amount_remaining=hp,
        gather_time_ms=spec.gather_time_ms,
        harvest_slots=spec.harvest_slots,
        depleted_replacement=spec.depleted_replacement,
        blocking_footprint=spec.blocking_footprint,
    )
    world.add_entity(entity)


def _add_hut(world: WorldState, x: float, y: float) -> None:
    """Add hut."""
    spec = building_spec_from_data("hut")
    functions = spec.functions
    entity = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(x, y),
        footprint=spec.footprint,
        hp=spec.hp,
        max_hp=spec.hp,
        tags=("building", "hut", "selectable"),
        build_time_ms=spec.build_time_ms,
        complete=True,
        functions=Building.production_functions(
            dropoff=bool(functions.get("dropoff", False)),
            population_cap_bonus=world.settings.hut_pop_cap_bonus,
            trainable_units=tuple(str(unit_id) for unit_id in functions["trainable_units"]),
        ),
        dropoff_point=WorldPosition(
            x + 220,
            terrain_layout_for_height(world.settings.world_height).unit_walkable_top_y,
        ),
    )
    world.add_entity(entity)

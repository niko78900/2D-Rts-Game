from __future__ import annotations

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.combat_unit import CombatUnit
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.construction import (
    ConstructionSystem,
    construction_hp_for_progress,
    construction_progress,
    starting_construction_hp,
)
from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.terrain import terrain_layout_for_height


def test_construction_progress_raises_hp_and_completes_site() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    site = _add_hut_site(world, build_time_ms=1000)
    world.update_entity_position(settler.id, site.position)
    world.enqueue_command(
        settler.id,
        make_command(
            "build",
            [settler.id],
            target_entity_id=site.id,
            target_pos=site.position,
            building_id="hut",
        ),
    )

    system = ConstructionSystem()
    system.update(world, 500)

    assert construction_progress(site) == 0.5
    assert site.hp == construction_hp_for_progress(650, 0.5)
    assert site.complete is False
    assert world.command_queues[settler.id].peek() is not None
    assert settler.state == "building"

    system.update(world, 500)

    assert construction_progress(site) == 1.0
    assert site.complete is True
    assert site.hp == 650
    assert world.command_queues[settler.id].peek() is None
    assert settler.state == "idle"


def test_multiple_builders_speed_up_construction() -> None:
    world = create_demo_world()
    site = _add_hut_site(world, build_time_ms=1000)
    builders = [
        _add_settler(world, site.position.x + (index * 2), site.position.y)
        for index in range(3)
    ]
    for builder in builders:
        world.enqueue_command(
            builder.id,
            make_command(
                "build",
                [builder.id],
                target_entity_id=site.id,
                target_pos=site.position,
                building_id="hut",
            ),
        )

    ConstructionSystem().update(world, 100)

    assert site.build_progress_ms == 300
    assert site.hp == construction_hp_for_progress(650, 0.3)
    assert all(builder.state == "building" for builder in builders)


def test_construction_speed_boost_caps_at_ten_builders() -> None:
    world = create_demo_world()
    site = _add_hut_site(world, build_time_ms=2000)
    builders = [
        _add_settler(world, site.position.x + (index * 2), site.position.y)
        for index in range(12)
    ]
    for builder in builders:
        world.enqueue_command(
            builder.id,
            make_command(
                "build",
                [builder.id],
                target_entity_id=site.id,
                target_pos=site.position,
                building_id="hut",
            ),
        )

    ConstructionSystem(max_builder_speed_boost=10).update(world, 100)

    assert site.build_progress_ms == 1000
    assert site.complete is False
    assert site.hp == construction_hp_for_progress(650, 0.5)


def test_hut_population_bonus_counts_only_after_completion_and_removal() -> None:
    world = create_demo_world()
    starting_cap = world.max_population
    site = _add_hut_site(world, build_time_ms=100)

    assert world.max_population == starting_cap

    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    world.update_entity_position(settler.id, site.position)
    world.enqueue_command(
        settler.id,
        make_command(
            "build",
            [settler.id],
            target_entity_id=site.id,
            target_pos=site.position,
            building_id="hut",
        ),
    )

    ConstructionSystem().update(world, 100)

    assert site.complete is True
    assert world.max_population == starting_cap + site.production_config.population_cap_bonus

    current_population = world.current_population
    world.remove_entity(site.id)

    assert world.max_population == starting_cap
    assert world.current_population == current_population


def test_construction_site_starts_at_ten_percent_hp() -> None:
    world = create_demo_world()
    site = _add_hut_site(world, build_time_ms=1000)

    assert site.build_progress_ms == 0
    assert site.hp == 65
    assert site.hp == starting_construction_hp(650)
    assert construction_progress(site) == 0.0


def test_builder_must_be_near_construction_site_to_progress() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    site = _add_hut_site(world, x=2600, build_time_ms=1000)
    world.enqueue_command(
        settler.id,
        make_command(
            "build",
            [settler.id],
            target_entity_id=site.id,
            target_pos=site.position,
            building_id="hut",
        ),
    )

    ConstructionSystem().update(world, 500)

    assert site.build_progress_ms == 0
    assert site.hp == starting_construction_hp(650)
    assert site.complete is False
    assert settler.state == "moving"


def test_build_command_with_missing_site_is_removed() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    world.enqueue_command(
        settler.id,
        make_command("build", [settler.id], target_pos=(500, 300), building_id="hut"),
    )

    ConstructionSystem().update(world, 500)

    assert world.command_queues[settler.id].peek() is None


def test_settler_repair_command_restores_damaged_building_hp() -> None:
    world = create_demo_world()
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    hut.hp = 300
    world.update_entity_position(settler.id, hut.position)
    world.enqueue_command(
        settler.id,
        make_command("repair", [settler.id], target_entity_id=hut.id, target_pos=hut.position),
    )

    ConstructionSystem(repair_hp_per_second=100).update(world, 1000)

    assert hut.hp == 400
    assert world.command_queues[settler.id].peek() is not None
    assert settler.state == "repairing"


def test_repair_command_completes_and_only_settlers_can_repair() -> None:
    world = create_demo_world()
    spearman = next(entity for entity in world.entities.values() if "spearman" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    hut.hp = 600
    world.update_entity_position(spearman.id, hut.position)
    world.enqueue_command(
        spearman.id,
        make_command("repair", [spearman.id], target_entity_id=hut.id, target_pos=hut.position),
    )

    ConstructionSystem(repair_hp_per_second=100).update(world, 1000)

    assert hut.hp == 600
    assert world.command_queues[spearman.id].peek() is None

    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    world.update_entity_position(settler.id, hut.position)
    world.enqueue_command(
        settler.id,
        make_command("repair", [settler.id], target_entity_id=hut.id, target_pos=hut.position),
    )

    ConstructionSystem(repair_hp_per_second=100).update(world, 1000)

    assert hut.hp == 650
    assert world.command_queues[settler.id].peek() is None
    assert settler.state == "idle"


def _add_hut_site(
    world: object,
    *,
    x: float = 620,
    build_time_ms: int,
) -> Building:
    layout = terrain_layout_for_height(world.settings.world_height)
    site = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(x, layout.building_lane_bottom_y),
        footprint=Footprint(150, 116),
        hp=starting_construction_hp(650),
        max_hp=650,
        tags=("building", "hut", "selectable"),
        build_time_ms=build_time_ms,
        complete=False,
        functions=Building.production_functions(
            dropoff=True,
            population_cap_bonus=5,
            trainable_units=("settler", "spearman"),
        ),
    )
    world.add_entity(site)
    return site


def _add_settler(world: object, x: float, y: float) -> CombatUnit:
    settler = CombatUnit(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(x, y),
        footprint=Footprint(38, 58),
        hp=40,
        max_hp=40,
        tags=("unit", "settler", "selectable", "movable"),
        speed=92,
        attack_range=115,
        damage=6,
        attack_cooldown_ms=900,
    )
    world.add_entity(settler)
    return settler

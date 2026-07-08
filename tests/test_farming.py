from __future__ import annotations

from house_of_wolves.core.contracts import Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.construction import starting_construction_hp
from house_of_wolves.systems.economy import hut_deposit_position
from house_of_wolves.systems.farming import (
    CHICKEN_CARCASS_HARVEST_DURATION_MS,
    CHICKEN_FARM_ID,
    CHICKEN_RESPAWN_DELAY_MS,
    FARM_ANIMAL_SWING_MS,
    FARM_BUILDING_SPECS,
    FARM_STATE_DISABLED_NO_HUT,
    FARM_STATE_IDLE_NO_WORKER,
    FARM_STATE_WAITING_FOR_ANIMAL,
    PIG_CARCASS_HARVEST_DURATION_MS,
    PIG_FARM_ID,
    PIG_RESPAWN_DELAY_MS,
    FarmSystem,
    animal_area_bounds,
    animal_harvest_area_bounds,
    animal_harvest_slot_candidates,
    animal_interaction_position,
    assigned_worker_id,
    farm_animal,
    farm_carcass,
    farm_resource,
    farm_state,
    is_worker_in_animal_harvest_range,
)
from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.terrain import terrain_layout_for_height


def test_completed_farm_assigns_one_worker_and_refuses_second() -> None:
    """Verify that completed farm assigns one worker and refuses second."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settlers = [entity for entity in world.entities.values() if "settler" in entity.tags]
    second = _add_settler_like(
        world,
        WorldPosition(settlers[0].position.x + 42, settlers[0].position.y),
    )

    assert system.assign_worker(world, farm, settlers[0].id) == "Assigned worker to farm."
    assert system.assign_worker(world, farm, second.id) == "Farm already has a worker."
    assert assigned_worker_id(farm) == settlers[0].id


def test_under_construction_farm_cannot_be_worked() -> None:
    """Verify that under construction farm cannot be worked."""
    world = create_demo_world()
    system = FarmSystem()
    site = _add_farm_site(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)

    assert system.assign_worker(world, site, settler.id) == "Farm is not completed."
    system.update(world, 16)

    assert assigned_worker_id(site) is None
    assert farm_resource(world, site) is None


def test_completed_farm_spawns_animal_without_worker() -> None:
    """Verify that completed farm spawns animal without worker."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)

    system.update(world, 16)

    animal = farm_animal(world, farm)
    assert animal is not None
    assert "chicken" in animal.tags
    assert assigned_worker_id(farm) is None
    assert farm_state(farm) == "animal_alive"


def test_chicken_farm_loop_kills_harvests_and_deposits_food() -> None:
    """Verify that chicken farm loop kills harvests and deposits food."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    starting_food = world.resources["food"]

    system.assign_worker(world, farm, settler.id)
    system.update(world, 16)
    animal = farm_resource(world, farm)

    assert animal is not None
    assert "chicken" in animal.tags
    assert animal.hp == 10
    assert animal.amount_remaining == 0

    world.update_entity_position(settler.id, animal.position)
    world.command_queues[settler.id].clear()
    system.update(world, FARM_ANIMAL_SWING_MS * 10)

    carcass = farm_resource(world, farm)
    assert carcass is animal
    assert "food_carcass" in carcass.tags
    assert carcass.amount_remaining == 20

    world.command_queues[settler.id].clear()
    system.update(world, 16)
    assert settler.carry_type is None
    assert settler.carry_amount == 0
    assert carcass.amount_remaining == 20

    _advance_farm(world, system, _pickup_interval_ms(farm))
    assert settler.carry_type == "food"
    assert settler.carry_amount == 5
    assert carcass.amount_remaining == 15

    world.update_entity_position(settler.id, hut_deposit_position(world, hut, settler.id))
    world.command_queues[settler.id].clear()
    system.update(world, 16)

    assert world.resources["food"] == starting_food + 5
    assert settler.carry_amount == 0
    assert farm_state(farm) == "carcass_available"


def test_farm_worker_must_reach_hut_before_meat_deposits() -> None:
    """Verify that farm worker must reach hut before meat deposits."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    starting_food = world.resources["food"]

    _spawn_and_kill_farm_animal(world, system, farm, settler)
    _harvest_one_meat_pickup(world, system, farm, settler)
    assert settler.carry_type == "food"
    assert settler.carry_amount == 5

    deposit = hut_deposit_position(world, hut, settler.id)
    world.update_entity_position(settler.id, WorldPosition(deposit.x + 70, deposit.y))
    world.command_queues[settler.id].clear()
    system.update(world, 16)

    assert world.resources["food"] == starting_food
    assert settler.carry_amount == 5

    world.update_entity_position(settler.id, deposit)
    world.command_queues[settler.id].clear()
    system.update(world, 16)

    assert world.resources["food"] == starting_food + 5
    assert settler.carry_amount == 0


def test_chicken_carcass_lasts_four_trips_then_respawns_after_delay() -> None:
    """Verify that chicken carcass lasts four trips then respawns after delay."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    starting_food = world.resources["food"]

    _spawn_and_kill_farm_animal(world, system, farm, settler)
    assert farm.functions["farm_spawn_due_ms"] == CHICKEN_RESPAWN_DELAY_MS
    for _ in range(4):
        _harvest_and_deposit_one_trip(world, system, farm, settler, hut)

    assert farm_carcass(world, farm) is None
    assert farm_animal(world, farm) is not None
    assert world.resources["food"] == starting_food + 20
    assert world.elapsed_ms >= CHICKEN_CARCASS_HARVEST_DURATION_MS


def test_pig_farm_uses_pig_balance_and_sixty_second_respawn() -> None:
    """Verify that pig farm uses pig balance and sixty second respawn."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world, PIG_FARM_ID)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)

    system.assign_worker(world, farm, settler.id)
    system.update(world, 16)
    animal = farm_resource(world, farm)

    assert animal is not None
    assert "pig" in animal.tags
    assert animal.hp == 20
    assert animal.amount_remaining == 0

    _kill_farm_animal(world, system, farm, settler, animal)
    carcass = farm_resource(world, farm)
    assert carcass is animal
    assert carcass.amount_remaining == 20
    assert farm.functions["farm_spawn_due_ms"] == PIG_RESPAWN_DELAY_MS

    world.update_entity_position(settler.id, carcass.position)
    world.command_queues[settler.id].clear()
    _advance_farm(world, system, _pickup_interval_ms(farm) - 1)
    assert settler.carry_type is None
    assert carcass.amount_remaining == 20

    for _ in range(4):
        _harvest_and_deposit_one_trip(world, system, farm, settler, hut)

    assert farm_carcass(world, farm) is None
    assert farm_animal(world, farm) is not None
    assert world.elapsed_ms >= PIG_CARCASS_HARVEST_DURATION_MS


def test_spawn_timer_ready_does_not_stack_animal_while_carcass_exists() -> None:
    """Verify that spawn timer ready does not stack animal while carcass exists."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)

    _spawn_and_kill_farm_animal(world, system, farm, settler)
    carcass = farm_carcass(world, farm)
    assert carcass is not None

    world.elapsed_ms = CHICKEN_RESPAWN_DELAY_MS
    system.update(world, 16)

    assert farm_carcass(world, farm) is carcass
    assert farm_animal(world, farm) is None
    assert farm.functions["farm_spawn_ready"] is True


def test_live_farm_animal_wanders_inside_its_farm_area() -> None:
    """Verify that live farm animal wanders inside its farm area."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)

    system.update(world, 16)
    animal = farm_animal(world, farm)
    assert animal is not None
    starting = animal.position

    bounds = animal_area_bounds(world, farm)
    for _ in range(40):
        system.update(world, 100)
        assert _position_in_bounds(animal.position, bounds)

    moved = abs(animal.position.x - starting.x) + abs(animal.position.y - starting.y)
    assert moved > 1.0


def test_chicken_and_pig_have_distinct_side_harvest_slots() -> None:
    """Verify farm animals expose clear left and right worker positions."""
    for building_id in (CHICKEN_FARM_ID, PIG_FARM_ID):
        world = create_demo_world()
        system = FarmSystem()
        farm = _add_completed_farm(world, building_id)
        system.update(world, 16)
        animal = farm_animal(world, farm)

        assert animal is not None
        slots = animal_harvest_slot_candidates(world, animal)
        assert len(slots) == 2
        assert slots[0].x < animal.bounds[0]
        assert slots[1].x > animal.bounds[0] + animal.bounds[2]
        assert all(
            _position_in_bounds(slot, animal_harvest_area_bounds(animal))
            for slot in slots
        )


def test_animal_interaction_retains_nearest_side() -> None:
    """Verify crossing the animal does not flip an active worker's side slot."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    system.assign_worker(world, farm, settler.id)
    system.update(world, 16)
    animal = farm_animal(world, farm)

    assert animal is not None
    world.update_entity_position(
        settler.id,
        WorldPosition(animal.position.x - 140, animal.position.y),
    )
    left_slot = animal_interaction_position(world, farm, animal, settler.id)
    world.update_entity_position(
        settler.id,
        WorldPosition(animal.position.x + 140, animal.position.y),
    )
    retained_slot = animal_interaction_position(world, farm, animal, settler.id)

    assert left_slot.x < animal.position.x
    assert retained_slot.x < animal.position.x


def test_blocked_animal_side_falls_back_to_opposite_side() -> None:
    """Verify a hard blocker redirects a farm worker to the other animal side."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    system.assign_worker(world, farm, settler.id)
    system.update(world, 16)
    animal = farm_animal(world, farm)

    assert animal is not None
    slots = animal_harvest_slot_candidates(world, animal, settler.id)
    assert len(slots) == 2
    blocker = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=slots[0],
        footprint=Footprint(72, 72),
        hp=100,
        max_hp=100,
        tags=("building", "test_blocker"),
        complete=True,
    )
    world.add_entity(blocker)
    world.update_entity_position(
        settler.id,
        WorldPosition(animal.position.x - 140, animal.position.y),
    )

    interaction = animal_interaction_position(world, farm, animal, settler.id)

    assert interaction.x > animal.position.x


def test_worker_harvest_range_uses_animal_rectangle() -> None:
    """Verify a settler at a farm-animal side slot may work the target."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world, PIG_FARM_ID)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    system.update(world, 16)
    animal = farm_animal(world, farm)

    assert animal is not None
    side_slot = animal_harvest_slot_candidates(world, animal, settler.id)[0]
    world.update_entity_position(settler.id, side_slot)

    assert is_worker_in_animal_harvest_range(settler, animal)
    assert not (
        animal.bounds[0] <= settler.position.x <= animal.bounds[0] + animal.bounds[2]
    )


def test_live_animal_side_remains_valid_after_carcass_conversion() -> None:
    """Verify the worker uses the retained side after an animal becomes a carcass."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    system.assign_worker(world, farm, settler.id)
    system.update(world, 16)
    animal = farm_animal(world, farm)

    assert animal is not None
    world.update_entity_position(
        settler.id,
        WorldPosition(animal.position.x - 140, animal.position.y),
    )
    side_slot = animal_interaction_position(world, farm, animal, settler.id)
    world.update_entity_position(settler.id, side_slot)
    world.command_queues[settler.id].clear()
    system.update(world, FARM_ANIMAL_SWING_MS * animal.max_hp)
    carcass = farm_carcass(world, farm)

    assert carcass is animal
    retained_slot = animal_interaction_position(world, farm, carcass, settler.id)
    assert retained_slot.x < carcass.position.x
    assert is_worker_in_animal_harvest_range(settler, carcass)


def test_farm_without_completed_hut_pauses_and_notifies() -> None:
    """Verify that farm without completed hut pauses and notifies."""
    world = create_demo_world()
    hut = next(entity for entity in world.entities.values() if "hut" in entity.tags)
    world.remove_entity(hut.id)
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)

    system.assign_worker(world, farm, settler.id)
    system.update(world, 16)

    assert farm_state(farm) == FARM_STATE_DISABLED_NO_HUT
    assert world.notifications[-1].message == "Needs hut to deposit."


def test_manual_order_unassigns_farm_worker() -> None:
    """Verify that manual order unassigns farm worker."""
    world = create_demo_world()
    system = FarmSystem()
    farm = _add_completed_farm(world)
    settler = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    system.assign_worker(world, farm, settler.id)

    world.enqueue_command(
        settler.id,
        make_command("move", [settler.id], target_pos=WorldPosition(1800, settler.position.y)),
    )
    system.update(world, 16)

    assert assigned_worker_id(farm) is None
    assert farm_state(farm) == FARM_STATE_IDLE_NO_WORKER


def _add_completed_farm(world, building_id: str = CHICKEN_FARM_ID) -> Building:
    """Add completed farm test fixture data."""
    spec = FARM_BUILDING_SPECS[building_id]
    layout = terrain_layout_for_height(world.settings.world_height)
    farm = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(860, layout.building_lane_bottom_y),
        footprint=spec.footprint,
        hp=spec.hp,
        max_hp=spec.hp,
        tags=("building", building_id, "selectable"),
        build_time_ms=spec.build_time_ms,
        build_progress_ms=spec.build_time_ms,
        complete=True,
        functions={
            "farm_type": spec.farm_type,
            "farm_state": FARM_STATE_WAITING_FOR_ANIMAL,
            "food_output": spec.animal_food_yield,
        },
    )
    world.add_entity(farm)
    return farm


def _add_farm_site(world, building_id: str = CHICKEN_FARM_ID) -> Building:
    """Add farm site test fixture data."""
    spec = FARM_BUILDING_SPECS[building_id]
    layout = terrain_layout_for_height(world.settings.world_height)
    farm = Building(
        id=world.allocate_entity_id(),
        owner="frontier",
        position=WorldPosition(860, layout.building_lane_bottom_y),
        footprint=spec.footprint,
        hp=starting_construction_hp(spec.hp),
        max_hp=spec.hp,
        tags=("building", building_id, "selectable"),
        build_time_ms=spec.build_time_ms,
        complete=False,
        functions={"farm_type": spec.farm_type, "farm_state": FARM_STATE_IDLE_NO_WORKER},
    )
    world.add_entity(farm)
    return farm


def _spawn_and_kill_farm_animal(
    world,
    system: FarmSystem,
    farm: Building,
    settler,
):
    """Spawn a farm animal and advance it to carcass state."""
    system.assign_worker(world, farm, settler.id)
    system.update(world, 16)
    animal = farm_resource(world, farm)
    assert animal is not None
    _kill_farm_animal(world, system, farm, settler, animal)
    return animal


def _kill_farm_animal(
    world,
    system: FarmSystem,
    farm: Building,
    settler,
    animal,
) -> None:
    """Advance combat until the farm animal becomes a carcass."""
    spec = _spec_for_farm(farm)
    world.update_entity_position(settler.id, animal.position)
    world.command_queues[settler.id].clear()
    system.update(world, FARM_ANIMAL_SWING_MS * spec.animal_hp)


def _harvest_and_deposit_one_trip(
    world,
    system: FarmSystem,
    farm: Building,
    settler,
    hut,
) -> None:
    """Advance a farm worker through one deposit trip."""
    _harvest_one_meat_pickup(world, system, farm, settler)
    assert settler.carry_type == "food"
    assert settler.carry_amount > 0
    world.update_entity_position(settler.id, hut_deposit_position(world, hut, settler.id))
    world.command_queues[settler.id].clear()
    system.update(world, 16)
    assert settler.carry_amount == 0


def _harvest_one_meat_pickup(
    world,
    system: FarmSystem,
    farm: Building,
    settler,
) -> None:
    """Advance a worker until one meat pickup completes."""
    carcass = farm_resource(world, farm)
    assert carcass is not None
    world.update_entity_position(settler.id, carcass.position)
    world.command_queues[settler.id].clear()
    _advance_farm(world, system, _pickup_interval_ms(farm))


def _advance_farm(world, system: FarmSystem, dt_ms: int) -> None:
    """Advance the farm system by a test step."""
    world.elapsed_ms += dt_ms
    system.update(world, dt_ms)


def _pickup_interval_ms(farm: Building) -> int:
    """Return the farm carcass pickup interval for tests."""
    spec = _spec_for_farm(farm)
    trips = max(1, (spec.animal_food_yield + 4) // 5)
    return max(1, spec.carcass_harvest_duration_ms // trips)


def _spec_for_farm(farm: Building):
    """Return the farm spec used by a test farm."""
    farm_type = farm.functions["farm_type"]
    return next(spec for spec in FARM_BUILDING_SPECS.values() if spec.farm_type == farm_type)


def _position_in_bounds(
    position: WorldPosition,
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return whether a test position lies inside bounds."""
    left, top, width, height = bounds
    return left <= position.x <= left + width and top <= position.y <= top + height


def _add_settler_like(world, position: WorldPosition):
    """Add settler like test fixture data."""
    template = next(entity for entity in world.entities.values() if "settler" in entity.tags)
    entity = type(template)(
        id=world.allocate_entity_id(),
        owner=template.owner,
        position=position,
        footprint=Footprint(template.footprint.width, template.footprint.height),
        hp=template.hp,
        max_hp=template.max_hp,
        tags=template.tags,
        speed=template.speed,
        attack_range=template.attack_range,
        damage=template.damage,
        attack_cooldown_ms=template.attack_cooldown_ms,
    )
    world.add_entity(entity)
    return entity

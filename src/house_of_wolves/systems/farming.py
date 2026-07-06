"""Chicken and pig farm food production loops."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, hypot

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.economy import (
    GATHER_CARRY_AMOUNT,
    closest_deposit_hut,
    completed_deposit_huts,
    hut_deposit_position,
)
from house_of_wolves.world.collision import nearest_free_position
from house_of_wolves.world.terrain import (
    clamp_unit_position_to_walkable_lane_for_height,
    terrain_layout_for_height,
)
from house_of_wolves.world.world import WorldState

CHICKEN_FARM_ID = "chicken_farm"
PIG_FARM_ID = "pig_farm"
FARM_BUILDING_IDS = (CHICKEN_FARM_ID, PIG_FARM_ID)

FARM_STATE_IDLE_NO_WORKER = "idle_no_worker"
FARM_STATE_WAITING_FOR_ANIMAL = "waiting_for_animal"
FARM_STATE_ANIMAL_ALIVE = "animal_alive"
FARM_STATE_CARCASS_AVAILABLE = "carcass_available"
FARM_STATE_WAITING_FOR_WORKER_RETURN = "waiting_for_worker_return"
FARM_STATE_DISABLED_NO_HUT = "disabled_no_hut"
FARM_STATE_DESTROYED = "destroyed"

WORKER_STATE_ASSIGNED_TO_FARM = "assigned_to_farm"
WORKER_STATE_MOVING_TO_FARM_ANIMAL = "moving_to_farm_animal"
WORKER_STATE_KILLING_FARM_ANIMAL = "killing_farm_animal"
WORKER_STATE_HARVESTING_FOOD = "harvesting_food"
WORKER_STATE_CARRYING_FOOD_TO_HUT = "carrying_food_to_hut"
WORKER_STATE_RETURNING_TO_FARM = "returning_to_farm"

FARM_ANIMAL_SWING_MS = 650
FARM_WORKER_DAMAGE_PER_SWING = 1
CHICKEN_RESPAWN_DELAY_MS = 120_000
PIG_RESPAWN_DELAY_MS = 60_000
CHICKEN_CARCASS_HARVEST_DURATION_MS = 120_000
PIG_CARCASS_HARVEST_DURATION_MS = 60_000
FARM_INTERACTION_RANGE = 66.0
FARM_DEPOSIT_RANGE = 18.0
FARM_MOVE_KEY = "farm_move_key"
FARM_ANIMAL_AREA_HEIGHT = 112.0
FARM_ANIMAL_AREA_MIN_WIDTH = 170.0
FARM_ANIMAL_IDLE_MIN_MS = 700
FARM_ANIMAL_IDLE_MAX_MS = 1800
FARM_ANIMAL_TARGET_RADIUS = 4.0


@dataclass(frozen=True, slots=True)
class FarmBuildingSpec:
    building_id: str
    display_name: str
    farm_type: str
    animal_tag: str
    carcass_tag: str
    footprint: Footprint
    hp: int
    build_time_ms: int
    cost: dict[str, int]
    animal_hp: int
    animal_food_yield: int
    animal_footprint: Footprint
    respawn_delay_ms: int
    carcass_harvest_duration_ms: int
    wander_speed: float


FARM_BUILDING_SPECS: dict[str, FarmBuildingSpec] = {
    CHICKEN_FARM_ID: FarmBuildingSpec(
        building_id=CHICKEN_FARM_ID,
        display_name="Chicken Farm",
        farm_type="chicken",
        animal_tag="chicken",
        carcass_tag="chicken_carcass",
        footprint=Footprint(118, 76),
        hp=75,
        build_time_ms=8_000,
        cost={"wood": 75},
        animal_hp=10,
        animal_food_yield=20,
        animal_footprint=Footprint(24, 20),
        respawn_delay_ms=CHICKEN_RESPAWN_DELAY_MS,
        carcass_harvest_duration_ms=CHICKEN_CARCASS_HARVEST_DURATION_MS,
        wander_speed=20.0,
    ),
    PIG_FARM_ID: FarmBuildingSpec(
        building_id=PIG_FARM_ID,
        display_name="Pig Farm",
        farm_type="pig",
        animal_tag="pig",
        carcass_tag="pig_carcass",
        footprint=Footprint(152, 88),
        hp=300,
        build_time_ms=10_000,
        cost={"wood": 60, "stone": 20},
        animal_hp=20,
        animal_food_yield=20,
        animal_footprint=Footprint(34, 24),
        respawn_delay_ms=PIG_RESPAWN_DELAY_MS,
        carcass_harvest_duration_ms=PIG_CARCASS_HARVEST_DURATION_MS,
        wander_speed=16.0,
    ),
}


@dataclass(slots=True)
class FarmSystem:
    """Runs one-settler food loops for completed Chicken/Pig farms."""

    interaction_range: float = FARM_INTERACTION_RANGE
    deposit_range: float = FARM_DEPOSIT_RANGE
    animal_swing_ms: int = FARM_ANIMAL_SWING_MS

    def update(self, world: WorldState, dt_ms: int) -> None:
        self._cleanup_orphaned_farm_resources(world)
        for farm in list(world.entities.values()):
            if not is_farm_building(farm):
                continue
            if not getattr(farm, "alive", False):
                self._cleanup_farm_resource(world, farm)
                _set_farm_state(farm, FARM_STATE_DESTROYED)
                continue
            self._update_farm(world, farm, dt_ms)

    def assign_worker(
        self,
        world: WorldState,
        farm: Building,
        worker_id: EntityId,
    ) -> str | None:
        if not farm.complete:
            return "Farm is not completed."
        if not is_farm_building(farm):
            return None
        worker = world.entities.get(worker_id)
        if not _is_settler(worker) or worker.owner != farm.owner:
            return None
        assigned = assigned_worker_id(farm)
        if assigned is not None and assigned != worker_id and _worker_alive(world, assigned):
            return "Farm already has a worker."
        self.unassign_worker_from_other_farms(world, worker_id)
        farm.functions["assigned_worker_id"] = worker_id.to_json()
        farm.functions.pop("farm_no_hut_notified", None)
        queue = world.command_queues.get(worker_id)
        if queue is not None:
            queue.clear()
        _set_state(worker, WORKER_STATE_ASSIGNED_TO_FARM)
        return "Assigned worker to farm."

    def unassign_farm(
        self,
        world: WorldState,
        farm: Building,
    ) -> None:
        worker_id = assigned_worker_id(farm)
        if worker_id is not None:
            worker = world.entities.get(worker_id)
            if worker is not None:
                if getattr(worker, "carry_type", None) == "food":
                    worker.carry_type = None
                    worker.carry_amount = 0
                _set_state(worker, "idle")
            queue = world.command_queues.get(worker_id)
            if queue is not None and _queue_owned_by_farm(queue.peek(), farm.id):
                queue.clear()
        farm.functions.pop("assigned_worker_id", None)
        farm.functions.pop(FARM_MOVE_KEY, None)
        if getattr(farm, "alive", False):
            farm.functions["farm_state"] = FARM_STATE_IDLE_NO_WORKER

    def unassign_worker_from_other_farms(
        self,
        world: WorldState,
        worker_id: EntityId,
    ) -> None:
        for farm in _farm_buildings(world):
            if assigned_worker_id(farm) == worker_id:
                self.unassign_farm(world, farm)

    def _update_farm(self, world: WorldState, farm: Building, dt_ms: int) -> None:
        if not farm.complete:
            self.unassign_farm(world, farm)
            return
        self._update_farm_lifecycle(world, farm, dt_ms)
        worker_id = assigned_worker_id(farm)
        if worker_id is None:
            return
        worker = world.entities.get(worker_id)
        if not _is_settler(worker):
            self.unassign_farm(world, farm)
            return
        queue = world.command_queues.get(worker_id)
        command = queue.peek() if queue is not None else None
        if command is not None and not _queue_owned_by_farm(command, farm.id):
            self.unassign_farm(world, farm)
            return

        if not _completed_hut_available(world, farm.owner):
            _set_farm_state(farm, FARM_STATE_DISABLED_NO_HUT)
            if queue is not None and _queue_owned_by_farm(queue.peek(), farm.id):
                queue.clear()
                farm.functions.pop(FARM_MOVE_KEY, None)
            if not bool(farm.functions.get("farm_no_hut_notified", False)):
                world.notify("Needs hut to deposit.")
                farm.functions["farm_no_hut_notified"] = True
            return
        farm.functions.pop("farm_no_hut_notified", None)

        if getattr(worker, "carry_type", None) == "food" and int(worker.carry_amount) > 0:
            self._deliver_food(world, farm, worker, queue)
            return

        animal = _farm_animal(world, farm)
        carcass = _farm_carcass(world, farm)
        if _is_farm_animal_alive(animal):
            self._update_animal_kill(world, farm, worker, queue, animal, dt_ms)
            return
        if carcass is not None:
            self._update_carcass_harvest(world, farm, worker, queue, carcass, dt_ms)
            return
        _set_state(worker, WORKER_STATE_ASSIGNED_TO_FARM)

    def _update_farm_lifecycle(
        self,
        world: WorldState,
        farm: Building,
        dt_ms: int,
    ) -> None:
        animal = _farm_animal(world, farm)
        if animal is not None:
            if not _assigned_worker_close_to_animal(world, farm, animal, self.interaction_range):
                self._update_animal_wander(world, farm, animal, dt_ms)
            _set_farm_state(farm, FARM_STATE_ANIMAL_ALIVE)
            return
        carcass = _farm_carcass(world, farm)
        if carcass is not None:
            _mark_spawn_ready_if_due(world, farm)
            _set_farm_state(farm, FARM_STATE_CARCASS_AVAILABLE)
            return
        self._spawn_or_wait(world, farm)

    def _spawn_or_wait(self, world: WorldState, farm: Building) -> None:
        if _farm_animal(world, farm) is not None or _farm_carcass(world, farm) is not None:
            return
        if "farm_spawn_due_ms" not in farm.functions:
            farm.functions["farm_spawn_due_ms"] = world.elapsed_ms
        due_ms = int(farm.functions.get("farm_spawn_due_ms", 0) or 0)
        if due_ms > world.elapsed_ms:
            _set_farm_state(farm, FARM_STATE_WAITING_FOR_ANIMAL)
            return
        animal = self._spawn_animal(world, farm)
        farm.functions["farm_animal_id"] = animal.id.to_json()
        farm.functions.pop("farm_carcass_id", None)
        farm.functions["farm_spawn_due_ms"] = 0
        farm.functions.pop("farm_spawn_ready", None)
        farm.functions["farm_has_spawned_once"] = True
        farm.functions["farm_action_elapsed_ms"] = 0
        farm.functions["farm_harvest_progress_ms"] = 0
        farm.functions["farm_food_remaining"] = 0
        _set_farm_state(farm, FARM_STATE_ANIMAL_ALIVE)

    def _spawn_animal(self, world: WorldState, farm: Building) -> ResourceNode:
        spec = farm_spec_for(farm)
        if spec is None:
            raise ValueError("farm building has no farm spec")
        position = _animal_spawn_position(world, farm)
        animal = ResourceNode(
            id=world.allocate_entity_id(),
            owner=farm.owner,
            position=position,
            footprint=spec.animal_footprint,
            hp=spec.animal_hp,
            max_hp=spec.animal_hp,
            tags=("resource", "farm_food", "food_animal", spec.animal_tag, "selectable"),
            resource_type="food",
            amount_remaining=0,
            max_amount_remaining=0,
            gather_time_ms=self.animal_swing_ms,
            harvest_slots=1,
            depleted_replacement=f"{spec.animal_tag}_bones",
            blocking_footprint=Footprint(1, 1),
            respawn_enabled=False,
            source_entity_id=farm.id,
        )
        world.add_entity(animal)
        _clear_animal_wander_state(farm)
        return animal

    def _update_animal_wander(
        self,
        world: WorldState,
        farm: Building,
        animal: ResourceNode,
        dt_ms: int,
    ) -> None:
        spec = farm_spec_for(farm)
        if spec is None or dt_ms <= 0:
            return
        bounds = animal_area_bounds(world, farm)
        if not _position_in_area(animal.position, bounds):
            world.update_entity_position(
                animal.id,
                _clamp_to_area(animal.position, bounds),
            )
        idle_ms = int(farm.functions.get("animal_idle_remaining_ms", 0) or 0)
        if idle_ms > 0:
            farm.functions["animal_idle_remaining_ms"] = max(0, idle_ms - int(dt_ms))
            return
        target = _animal_wander_target(farm)
        if target is None or not _position_in_area(target, bounds):
            _choose_animal_wander_target(world, farm, bounds)
            return

        dx = target.x - animal.position.x
        dy = target.y - animal.position.y
        distance = hypot(dx, dy)
        if distance <= FARM_ANIMAL_TARGET_RADIUS:
            _start_animal_idle(world, farm)
            _clear_animal_wander_target(farm)
            return

        step = min(distance, spec.wander_speed * (dt_ms / 1000.0))
        desired = WorldPosition(
            animal.position.x + (dx / distance) * step,
            animal.position.y + (dy / distance) * step,
        )
        next_position = _clamp_to_area(
            nearest_free_position(
                world,
                desired,
                ignore_id=animal.id,
                min_distance=4.0,
            ),
            bounds,
        )
        if hypot(next_position.x - animal.position.x, next_position.y - animal.position.y) < 0.1:
            _start_animal_idle(world, farm)
            _clear_animal_wander_target(farm)
            return
        world.update_entity_position(animal.id, next_position)

    def _update_animal_kill(
        self,
        world: WorldState,
        farm: Building,
        worker: object,
        queue: object,
        animal: ResourceNode,
        dt_ms: int,
    ) -> None:
        interaction = _interaction_position(world, animal, worker.id)
        if not _within(worker.position, interaction, self.interaction_range):
            self._issue_farm_move(
                world,
                farm,
                worker.id,
                interaction,
                WORKER_STATE_MOVING_TO_FARM_ANIMAL,
            )
            return
        _clear_completed_farm_move(farm)
        _set_state(worker, WORKER_STATE_KILLING_FARM_ANIMAL)
        _set_farm_state(farm, FARM_STATE_ANIMAL_ALIVE)
        elapsed = int(farm.functions.get("farm_action_elapsed_ms", 0) or 0) + max(0, int(dt_ms))
        while elapsed >= self.animal_swing_ms and animal.hp > 0:
            elapsed -= self.animal_swing_ms
            animal.hp = max(0, animal.hp - FARM_WORKER_DAMAGE_PER_SWING)
        farm.functions["farm_action_elapsed_ms"] = elapsed
        if animal.hp > 0:
            return
        self._convert_to_carcass(world, farm, animal)

    def _convert_to_carcass(
        self,
        world: WorldState,
        farm: Building,
        animal: ResourceNode,
    ) -> None:
        spec = farm_spec_for(farm)
        if spec is None:
            return
        animal.hp = 1
        animal.max_hp = 1
        animal.amount_remaining = spec.animal_food_yield
        animal.max_amount_remaining = spec.animal_food_yield
        animal.tags = ("resource", "farm_food", "food_carcass", spec.carcass_tag, "selectable")
        animal.state = "active"
        world.spatial_hash.move(animal.id, animal.bounds)
        farm.functions.pop("farm_animal_id", None)
        farm.functions["farm_carcass_id"] = animal.id.to_json()
        farm.functions["farm_action_elapsed_ms"] = 0
        farm.functions["farm_harvest_progress_ms"] = 0
        farm.functions["farm_food_remaining"] = animal.amount_remaining
        farm.functions["farm_spawn_due_ms"] = world.elapsed_ms + _farm_respawn_delay_ms(farm)
        farm.functions.pop("farm_spawn_ready", None)
        _set_farm_state(farm, FARM_STATE_CARCASS_AVAILABLE)

    def _update_carcass_harvest(
        self,
        world: WorldState,
        farm: Building,
        worker: object,
        queue: object,
        carcass: ResourceNode,
        dt_ms: int,
    ) -> None:
        if carcass.amount_remaining <= 0:
            _set_farm_state(farm, FARM_STATE_WAITING_FOR_WORKER_RETURN)
            self._finish_carcass_if_empty(world, farm, worker)
            return
        interaction = _interaction_position(world, carcass, worker.id)
        if not _within(worker.position, interaction, self.interaction_range):
            self._issue_farm_move(
                world,
                farm,
                worker.id,
                interaction,
                WORKER_STATE_RETURNING_TO_FARM,
            )
            return
        _clear_completed_farm_move(farm)
        _set_state(worker, WORKER_STATE_HARVESTING_FOOD)
        interval_ms = _carcass_pickup_interval_ms(farm)
        progress_ms = int(farm.functions.get("farm_harvest_progress_ms", 0) or 0)
        progress_ms = min(interval_ms, progress_ms + max(0, int(dt_ms)))
        farm.functions["farm_harvest_progress_ms"] = progress_ms
        if progress_ms < interval_ms:
            _set_farm_state(farm, FARM_STATE_CARCASS_AVAILABLE)
            return
        amount = min(GATHER_CARRY_AMOUNT, max(0, int(carcass.amount_remaining)))
        if amount <= 0:
            self._finish_carcass_if_empty(world, farm, worker)
            return
        carcass.amount_remaining -= amount
        farm.functions["farm_harvest_progress_ms"] = 0
        farm.functions["farm_food_remaining"] = carcass.amount_remaining
        worker.carry_type = "food"
        worker.carry_amount = amount
        _set_farm_state(farm, FARM_STATE_WAITING_FOR_WORKER_RETURN)
        self._deliver_food(world, farm, worker, queue)

    def _deliver_food(
        self,
        world: WorldState,
        farm: Building,
        worker: object,
        queue: object,
    ) -> None:
        hut = closest_deposit_hut(world, worker.position, farm.owner, worker.id)
        if hut is None:
            _set_farm_state(farm, FARM_STATE_DISABLED_NO_HUT)
            if not bool(farm.functions.get("farm_no_hut_notified", False)):
                world.notify("Needs hut to deposit.")
                farm.functions["farm_no_hut_notified"] = True
            return
        deposit = hut_deposit_position(world, hut, worker.id)
        if not _within(worker.position, deposit, self.deposit_range):
            self._issue_farm_move(
                world,
                farm,
                worker.id,
                deposit,
                WORKER_STATE_CARRYING_FOOD_TO_HUT,
            )
            return
        _clear_completed_farm_move(farm)
        amount = max(0, int(getattr(worker, "carry_amount", 0)))
        if amount > 0:
            world.resources["food"] = world.resources.get("food", 0) + amount
        worker.carry_type = None
        worker.carry_amount = 0
        _set_state(worker, WORKER_STATE_ASSIGNED_TO_FARM)
        carcass = _farm_carcass(world, farm)
        if carcass is not None and carcass.amount_remaining <= 0:
            self._finish_carcass_if_empty(world, farm, worker)
            return
        _set_farm_state(farm, FARM_STATE_CARCASS_AVAILABLE)

    def _finish_carcass_if_empty(
        self,
        world: WorldState,
        farm: Building,
        worker: object,
    ) -> None:
        carcass = _farm_carcass(world, farm)
        if carcass is not None and carcass.amount_remaining <= 0:
            world.remove_entity(carcass.id)
            farm.functions.pop("farm_carcass_id", None)
            farm.functions["farm_food_remaining"] = 0
            farm.functions["farm_harvest_progress_ms"] = 0
            _clear_animal_wander_state(farm)
        _set_state(worker, WORKER_STATE_ASSIGNED_TO_FARM)
        self._spawn_or_wait(world, farm)

    def _issue_farm_move(
        self,
        world: WorldState,
        farm: Building,
        worker_id: EntityId,
        target: WorldPosition,
        worker_state: str,
    ) -> None:
        queue = world.command_queues.get(worker_id)
        command = queue.peek() if queue is not None else None
        move_key = _move_key(farm.id, target)
        if _queue_owned_by_farm(command, farm.id) and farm.functions.get(FARM_MOVE_KEY) == move_key:
            return
        farm.functions[FARM_MOVE_KEY] = move_key
        world.enqueue_command(
            worker_id,
            make_command(
                "move",
                [worker_id],
                target_pos=target,
                farm_work=True,
                farm_id=farm.id.to_json(),
                farm_move_key=move_key,
                gather_move=True,
            ),
        )
        worker = world.entities.get(worker_id)
        if worker is not None:
            _set_state(worker, worker_state)

    def _cleanup_farm_resource(self, world: WorldState, farm: Building) -> None:
        for key in ("farm_animal_id", "farm_carcass_id"):
            resource_id = _payload_entity_id(farm.functions.get(key))
            resource = world.entities.get(resource_id) if resource_id is not None else None
            if isinstance(resource, ResourceNode):
                world.remove_entity(resource.id)
            farm.functions.pop(key, None)
        farm.functions.pop("farm_animal_id", None)
        farm.functions.pop("farm_carcass_id", None)
        farm.functions["farm_food_remaining"] = 0
        farm.functions["farm_harvest_progress_ms"] = 0
        farm.functions.pop("farm_spawn_due_ms", None)
        farm.functions.pop("farm_spawn_ready", None)

    def _cleanup_orphaned_farm_resources(self, world: WorldState) -> None:
        for resource in list(world.entities.values()):
            if not isinstance(resource, ResourceNode) or "farm_food" not in resource.tags:
                continue
            source_id = resource.source_entity_id
            source = world.entities.get(source_id) if source_id is not None else None
            if not is_farm_building(source) or not getattr(source, "alive", False):
                world.remove_entity(resource.id)


def is_farm_building(entity: object | None) -> bool:
    return (
        isinstance(entity, Building)
        and "building" in getattr(entity, "tags", ())
        and str(getattr(entity, "functions", {}).get("farm_type", "")) in {"chicken", "pig"}
    )


def farm_spec_for(farm: Building) -> FarmBuildingSpec | None:
    farm_type = str(farm.functions.get("farm_type", ""))
    for spec in FARM_BUILDING_SPECS.values():
        if spec.farm_type == farm_type:
            return spec
    return None


def assigned_worker_id(farm: Building) -> EntityId | None:
    return _payload_entity_id(farm.functions.get("assigned_worker_id"))


def farm_state(farm: Building) -> str:
    return str(farm.functions.get("farm_state", FARM_STATE_IDLE_NO_WORKER))


def farm_resource(world: WorldState, farm: Building) -> ResourceNode | None:
    return _farm_resource(world, farm)


def farm_animal(world: WorldState, farm: Building) -> ResourceNode | None:
    return _farm_animal(world, farm)


def farm_carcass(world: WorldState, farm: Building) -> ResourceNode | None:
    return _farm_carcass(world, farm)


def animal_area_bounds(world: WorldState, farm: Building) -> tuple[float, float, float, float]:
    """Return the local pen area used for farm animal spawning and wandering."""

    layout = terrain_layout_for_height(world.settings.world_height)
    width = max(FARM_ANIMAL_AREA_MIN_WIDTH, farm.footprint.width * 1.42)
    left = max(0.0, farm.position.x - (width / 2.0))
    right = min(float(world.settings.world_width), left + width)
    left = max(0.0, right - width)
    top = layout.unit_walkable_top_y + 10.0
    bottom = min(layout.unit_walkable_bottom_y - 12.0, top + FARM_ANIMAL_AREA_HEIGHT)
    if bottom <= top:
        bottom = min(layout.unit_walkable_bottom_y, top + 1.0)
    return (left, top, max(1.0, right - left), max(1.0, bottom - top))


def _farm_buildings(world: WorldState) -> list[Building]:
    return [
        entity
        for entity in world.entities.values()
        if is_farm_building(entity) and getattr(entity, "alive", False)
    ]


def _farm_resource(world: WorldState, farm: Building) -> ResourceNode | None:
    return _farm_carcass(world, farm) or _farm_animal(world, farm)


def _farm_animal(world: WorldState, farm: Building) -> ResourceNode | None:
    resource = _farm_resource_for_key(world, farm, "farm_animal_id", "food_animal")
    if resource is not None:
        return resource
    return None


def _farm_carcass(world: WorldState, farm: Building) -> ResourceNode | None:
    resource = _farm_resource_for_key(world, farm, "farm_carcass_id", "food_carcass")
    if resource is not None:
        return resource
    return None


def _farm_resource_for_key(
    world: WorldState,
    farm: Building,
    key: str,
    required_tag: str,
) -> ResourceNode | None:
    resource_id = _payload_entity_id(farm.functions.get(key))
    resource = world.entities.get(resource_id) if resource_id is not None else None
    if isinstance(resource, ResourceNode) and resource.alive and required_tag in resource.tags:
        return resource
    farm.functions.pop(key, None)
    return None


def _is_farm_animal_alive(resource: ResourceNode | None) -> bool:
    return resource is not None and "food_animal" in resource.tags and resource.hp > 0


def _assigned_worker_close_to_animal(
    world: WorldState,
    farm: Building,
    animal: ResourceNode,
    interaction_range: float,
) -> bool:
    worker_id = assigned_worker_id(farm)
    worker = world.entities.get(worker_id) if worker_id is not None else None
    if not _is_settler(worker):
        return False
    return _within(
        worker.position,
        _interaction_position(world, animal, worker.id),
        interaction_range * 0.85,
    )


def _mark_spawn_ready_if_due(world: WorldState, farm: Building) -> None:
    due_ms = int(farm.functions.get("farm_spawn_due_ms", 0) or 0)
    if due_ms > 0 and due_ms <= world.elapsed_ms:
        farm.functions["farm_spawn_ready"] = True


def _completed_hut_available(world: WorldState, owner: str) -> bool:
    return bool(completed_deposit_huts(world, owner))


def _worker_alive(world: WorldState, worker_id: EntityId) -> bool:
    worker = world.entities.get(worker_id)
    return _is_settler(worker)


def _is_settler(entity: object | None) -> bool:
    return (
        entity is not None
        and getattr(entity, "alive", False)
        and "settler" in getattr(entity, "tags", ())
    )


def _queue_owned_by_farm(command: object | None, farm_id: EntityId) -> bool:
    return (
        command is not None
        and getattr(command, "payload", {}).get("farm_work") is True
        and _payload_entity_id(getattr(command, "payload", {}).get("farm_id")) == farm_id
    )


def _clear_completed_farm_move(farm: Building) -> None:
    farm.functions.pop(FARM_MOVE_KEY, None)


def _set_farm_state(farm: Building, state: str) -> None:
    farm.functions["farm_state"] = state


def _set_state(entity: object, state: str) -> None:
    if hasattr(entity, "state"):
        entity.state = state


def _interaction_position(
    world: WorldState,
    resource: ResourceNode,
    worker_id: EntityId,
) -> WorldPosition:
    target = WorldPosition(resource.position.x, resource.position.y + 26)
    return nearest_free_position(
        world,
        clamp_unit_position_to_walkable_lane_for_height(
            target,
            world.settings.world_height,
        ),
        ignore_id=worker_id,
    )


def _animal_spawn_position(world: WorldState, farm: Building) -> WorldPosition:
    bounds = animal_area_bounds(world, farm)
    left, top, width, height = bounds
    preferred = WorldPosition(left + width * 0.5, top + height * 0.44)
    return _clamp_to_area(
        nearest_free_position(
            world,
            clamp_unit_position_to_walkable_lane_for_height(
                preferred,
                world.settings.world_height,
            ),
            min_distance=4.0,
        ),
        bounds,
    )


def _within(first: WorldPosition, second: WorldPosition, radius: float) -> bool:
    return hypot(first.x - second.x, first.y - second.y) <= radius


def _farm_respawn_delay_ms(farm: Building) -> int:
    spec = farm_spec_for(farm)
    if spec is None:
        return PIG_RESPAWN_DELAY_MS
    return spec.respawn_delay_ms


def _carcass_pickup_interval_ms(farm: Building) -> int:
    spec = farm_spec_for(farm)
    if spec is None:
        return PIG_CARCASS_HARVEST_DURATION_MS
    trips = max(1, ceil(spec.animal_food_yield / max(1, GATHER_CARRY_AMOUNT)))
    return max(1, ceil(spec.carcass_harvest_duration_ms / trips))


def _animal_wander_target(farm: Building) -> WorldPosition | None:
    x = farm.functions.get("animal_wander_target_x")
    y = farm.functions.get("animal_wander_target_y")
    if x is None or y is None:
        return None
    return WorldPosition(float(x), float(y))


def _choose_animal_wander_target(
    world: WorldState,
    farm: Building,
    bounds: tuple[float, float, float, float],
) -> None:
    left, top, width, height = bounds
    farm.functions["animal_wander_target_x"] = world.rng.uniform(left, left + width)
    farm.functions["animal_wander_target_y"] = world.rng.uniform(top, top + height)


def _start_animal_idle(world: WorldState, farm: Building) -> None:
    farm.functions["animal_idle_remaining_ms"] = world.rng.randint(
        FARM_ANIMAL_IDLE_MIN_MS,
        FARM_ANIMAL_IDLE_MAX_MS,
    )


def _clear_animal_wander_target(farm: Building) -> None:
    farm.functions.pop("animal_wander_target_x", None)
    farm.functions.pop("animal_wander_target_y", None)


def _clear_animal_wander_state(farm: Building) -> None:
    _clear_animal_wander_target(farm)
    farm.functions.pop("animal_idle_remaining_ms", None)


def _position_in_area(
    position: WorldPosition,
    bounds: tuple[float, float, float, float],
) -> bool:
    left, top, width, height = bounds
    return left <= position.x <= left + width and top <= position.y <= top + height


def _clamp_to_area(
    position: WorldPosition,
    bounds: tuple[float, float, float, float],
) -> WorldPosition:
    left, top, width, height = bounds
    return WorldPosition(
        min(max(position.x, left), left + width),
        min(max(position.y, top), top + height),
    )


def _payload_entity_id(value: object) -> EntityId | None:
    if value is None:
        return None
    return EntityId(int(value))


def _move_key(farm_id: EntityId, target: WorldPosition) -> str:
    return f"farm:{int(farm_id)}:{round(target.x)}:{round(target.y)}"

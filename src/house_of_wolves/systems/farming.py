"""Chicken and pig farm food production loops."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, hypot

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.core.game_specs import building_spec_from_data
from house_of_wolves.core.geometry import distance as _distance
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.systems.command_payloads import entity_id_from_value as _payload_entity_id
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.economy import (
    GATHER_CARRY_AMOUNT,
    closest_deposit_hut,
    completed_deposit_huts,
    hut_deposit_position,
)
from house_of_wolves.systems.entity_helpers import is_settler as _is_settler
from house_of_wolves.systems.entity_helpers import set_state as _set_state
from house_of_wolves.world.collision import (
    UNIT_COLLISION_RADIUS,
    nearest_free_position,
    occupied_by_unit,
    position_blocked_by_hard_obstacle,
)
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
FARM_ANIMAL_HARVEST_AREA_MIN_WIDTH = 100.0
FARM_ANIMAL_HARVEST_AREA_MIN_HEIGHT = 64.0
FARM_ANIMAL_HARVEST_HORIZONTAL_PADDING = 38.0
FARM_ANIMAL_HARVEST_VERTICAL_PADDING = 20.0
FARM_ANIMAL_HARVEST_SLOT_INSET = 8.0
FARM_INTERACTION_RESOURCE_KEY = "farm_interaction_resource_id"
FARM_INTERACTION_SIDE_KEY = "farm_interaction_side_index"


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


def _farm_building_spec(building_id: str) -> FarmBuildingSpec:
    """Build a food-farm spec from validated building data."""
    spec = building_spec_from_data(building_id)
    functions = spec.functions
    animal_width, animal_height = functions["animal_footprint_px"]
    return FarmBuildingSpec(
        building_id=building_id,
        display_name=spec.display_name,
        farm_type=str(functions["farm_type"]),
        animal_tag=str(functions["animal_tag"]),
        carcass_tag=str(functions["carcass_tag"]),
        footprint=spec.footprint,
        hp=spec.hp,
        build_time_ms=spec.build_time_ms,
        cost=spec.cost,
        animal_hp=int(functions["animal_hp"]),
        animal_food_yield=int(functions["animal_food_yield"]),
        animal_footprint=Footprint(int(animal_width), int(animal_height)),
        respawn_delay_ms=int(functions["respawn_delay_ms"]),
        carcass_harvest_duration_ms=int(functions["carcass_harvest_duration_ms"]),
        wander_speed=float(functions["wander_speed"]),
    )


FARM_BUILDING_SPECS: dict[str, FarmBuildingSpec] = {
    CHICKEN_FARM_ID: _farm_building_spec(CHICKEN_FARM_ID),
    PIG_FARM_ID: _farm_building_spec(PIG_FARM_ID),
}


@dataclass(slots=True)
class FarmSystem:
    """Runs one-settler food loops for completed Chicken/Pig farms."""

    interaction_range: float = FARM_INTERACTION_RANGE
    deposit_range: float = FARM_DEPOSIT_RANGE
    animal_swing_ms: int = FARM_ANIMAL_SWING_MS

    def update(self, world: WorldState, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
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
        """Assign a settler as the active worker for a farm."""
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
        _clear_farm_interaction_slot(farm)
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
        """Remove the current worker assignment from a farm."""
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
        _clear_farm_interaction_slot(farm)
        if getattr(farm, "alive", False):
            farm.functions["farm_state"] = FARM_STATE_IDLE_NO_WORKER

    def unassign_worker_from_other_farms(
        self,
        world: WorldState,
        worker_id: EntityId,
    ) -> None:
        """Clear any farm assignment already using this worker."""
        for farm in _farm_buildings(world):
            if assigned_worker_id(farm) == worker_id:
                self.unassign_farm(world, farm)

    def _update_farm(self, world: WorldState, farm: Building, dt_ms: int) -> None:
        """Advance farm for the current frame."""
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
        """Advance farm lifecycle for the current frame."""
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
        """Spawn or wait."""
        if _farm_animal(world, farm) is not None or _farm_carcass(world, farm) is not None:
            return
        if "farm_spawn_due_ms" not in farm.functions:
            farm.functions["farm_spawn_due_ms"] = world.elapsed_ms
        due_ms = int(farm.functions.get("farm_spawn_due_ms", 0) or 0)
        if due_ms > world.elapsed_ms:
            _set_farm_state(farm, FARM_STATE_WAITING_FOR_ANIMAL)
            return
        animal = self._spawn_animal(world, farm)
        _clear_farm_interaction_slot(farm)
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
        """Spawn animal."""
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
        """Advance animal wander for the current frame."""
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
        """Advance animal kill for the current frame."""
        interaction = animal_interaction_position(world, farm, animal, worker.id)
        if not is_worker_in_animal_harvest_range(worker, animal):
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
        """Convert to carcass."""
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
        """Advance carcass harvest for the current frame."""
        if carcass.amount_remaining <= 0:
            _set_farm_state(farm, FARM_STATE_WAITING_FOR_WORKER_RETURN)
            self._finish_carcass_if_empty(world, farm, worker)
            return
        interaction = animal_interaction_position(world, farm, carcass, worker.id)
        if not is_worker_in_animal_harvest_range(worker, carcass):
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
        """Deposit carried farm food into the player wallet."""
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
        """Finish carcass if empty."""
        carcass = _farm_carcass(world, farm)
        if carcass is not None and carcass.amount_remaining <= 0:
            world.remove_entity(carcass.id)
            farm.functions.pop("farm_carcass_id", None)
            farm.functions["farm_food_remaining"] = 0
            farm.functions["farm_harvest_progress_ms"] = 0
            _clear_animal_wander_state(farm)
            _clear_farm_interaction_slot(farm)
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
        """Issue farm move commands."""
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
        """Clean up farm resource."""
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
        _clear_farm_interaction_slot(farm)

    def _cleanup_orphaned_farm_resources(self, world: WorldState) -> None:
        """Clean up orphaned farm resources."""
        for resource in list(world.entities.values()):
            if not isinstance(resource, ResourceNode) or "farm_food" not in resource.tags:
                continue
            source_id = resource.source_entity_id
            source = world.entities.get(source_id) if source_id is not None else None
            if not is_farm_building(source) or not getattr(source, "alive", False):
                world.remove_entity(resource.id)


def is_farm_building(entity: object | None) -> bool:
    """Return whether a building type supports farm production."""
    return (
        isinstance(entity, Building)
        and "building" in getattr(entity, "tags", ())
        and str(getattr(entity, "functions", {}).get("farm_type", "")) in {"chicken", "pig"}
    )


def farm_spec_for(farm: Building) -> FarmBuildingSpec | None:
    """Return the food farm configuration for a building type."""
    farm_type = str(farm.functions.get("farm_type", ""))
    for spec in FARM_BUILDING_SPECS.values():
        if spec.farm_type == farm_type:
            return spec
    return None


def assigned_worker_id(farm: Building) -> EntityId | None:
    """Return the settler currently assigned to a farm."""
    return _payload_entity_id(farm.functions.get("assigned_worker_id"))


def farm_state(farm: Building) -> str:
    """Return the current farm state label."""
    return str(farm.functions.get("farm_state", FARM_STATE_IDLE_NO_WORKER))


def farm_resource(world: WorldState, farm: Building) -> ResourceNode | None:
    """Return the resource entity owned by a farm."""
    return _farm_resource(world, farm)


def farm_animal(world: WorldState, farm: Building) -> ResourceNode | None:
    """Return the live farm animal entity if present."""
    return _farm_animal(world, farm)


def farm_carcass(world: WorldState, farm: Building) -> ResourceNode | None:
    """Return the farm carcass entity if present."""
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


def animal_harvest_area_bounds(
    animal: ResourceNode,
) -> tuple[float, float, float, float]:
    """Return the rectangular interaction area surrounding a farm animal."""
    left, top, width, height = animal.bounds
    area_width = max(
        FARM_ANIMAL_HARVEST_AREA_MIN_WIDTH,
        width + FARM_ANIMAL_HARVEST_HORIZONTAL_PADDING * 2,
    )
    area_height = max(
        FARM_ANIMAL_HARVEST_AREA_MIN_HEIGHT,
        height + FARM_ANIMAL_HARVEST_VERTICAL_PADDING * 2,
    )
    center_x = left + width / 2
    center_y = top + height / 2
    return (
        center_x - area_width / 2,
        center_y - area_height / 2,
        area_width,
        area_height,
    )


def animal_harvest_slot_candidates(
    world: WorldState,
    animal: ResourceNode,
    worker_id: EntityId | None = None,
) -> list[WorldPosition]:
    """Return valid left and right interaction slots for a farm animal."""
    if "farm_food" not in animal.tags:
        return []
    candidates: list[WorldPosition] = []
    for side_index in range(2):
        candidate = _animal_harvest_slot_for_side(
            world,
            animal,
            side_index,
            worker_id,
        )
        if candidate is not None and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def animal_interaction_position(
    world: WorldState,
    farm: Building,
    animal: ResourceNode,
    worker_id: EntityId,
) -> WorldPosition:
    """Return a stable side interaction position for a farm worker."""
    stored_resource_id = _payload_entity_id(
        farm.functions.get(FARM_INTERACTION_RESOURCE_KEY)
    )
    stored_side = farm.functions.get(FARM_INTERACTION_SIDE_KEY)
    if stored_resource_id == animal.id and stored_side in (0, 1):
        side_order = (int(stored_side), 1 - int(stored_side))
    else:
        worker = world.entities.get(worker_id)
        origin = worker.position if worker is not None else animal.position
        raw_slots = _raw_animal_harvest_slots(animal)
        nearest_side = min(
            range(2),
            key=lambda index: hypot(
                origin.x - raw_slots[index].x,
                origin.y - raw_slots[index].y,
            ),
        )
        side_order = (nearest_side, 1 - nearest_side)

    for side_index in side_order:
        candidate = _animal_harvest_slot_for_side(
            world,
            animal,
            side_index,
            worker_id,
        )
        if candidate is None:
            continue
        farm.functions[FARM_INTERACTION_RESOURCE_KEY] = animal.id.to_json()
        farm.functions[FARM_INTERACTION_SIDE_KEY] = side_index
        return candidate

    fallback = nearest_free_position(
        world,
        _raw_animal_harvest_slots(animal)[side_order[0]],
        ignore_id=worker_id,
        min_distance=UNIT_COLLISION_RADIUS,
    )
    farm.functions[FARM_INTERACTION_RESOURCE_KEY] = animal.id.to_json()
    farm.functions[FARM_INTERACTION_SIDE_KEY] = side_order[0]
    return fallback


def is_worker_in_animal_harvest_range(
    worker: object,
    animal: ResourceNode,
) -> bool:
    """Return whether a worker stands inside an animal's interaction area."""
    return _position_in_area(worker.position, animal_harvest_area_bounds(animal))


def _farm_buildings(world: WorldState) -> list[Building]:
    """Iterate completed and active farm buildings."""
    return [
        entity
        for entity in world.entities.values()
        if is_farm_building(entity) and getattr(entity, "alive", False)
    ]


def _farm_resource(world: WorldState, farm: Building) -> ResourceNode | None:
    """Return a farm-owned resource by payload key."""
    return _farm_carcass(world, farm) or _farm_animal(world, farm)


def _farm_animal(world: WorldState, farm: Building) -> ResourceNode | None:
    """Return a farm-owned live animal if present."""
    resource = _farm_resource_for_key(world, farm, "farm_animal_id", "food_animal")
    if resource is not None:
        return resource
    return None


def _farm_carcass(world: WorldState, farm: Building) -> ResourceNode | None:
    """Return a farm-owned carcass if present."""
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
    """Return a farm resource using its stored payload key."""
    resource_id = _payload_entity_id(farm.functions.get(key))
    resource = world.entities.get(resource_id) if resource_id is not None else None
    if isinstance(resource, ResourceNode) and resource.alive and required_tag in resource.tags:
        return resource
    farm.functions.pop(key, None)
    return None


def _is_farm_animal_alive(resource: ResourceNode | None) -> bool:
    """Return whether farm animal alive."""
    return resource is not None and "food_animal" in resource.tags and resource.hp > 0


def _assigned_worker_close_to_animal(
    world: WorldState,
    farm: Building,
    animal: ResourceNode,
    interaction_range: float,
) -> bool:
    """Return whether the worker can strike the farm animal."""
    del interaction_range
    worker_id = assigned_worker_id(farm)
    worker = world.entities.get(worker_id) if worker_id is not None else None
    if not _is_settler(worker):
        return False
    return is_worker_in_animal_harvest_range(worker, animal)


def _mark_spawn_ready_if_due(world: WorldState, farm: Building) -> None:
    """Mark a farm ready to spawn when its timer expires."""
    due_ms = int(farm.functions.get("farm_spawn_due_ms", 0) or 0)
    if due_ms > 0 and due_ms <= world.elapsed_ms:
        farm.functions["farm_spawn_ready"] = True


def _completed_hut_available(world: WorldState, owner: str) -> bool:
    """Return completed hut available."""
    return bool(completed_deposit_huts(world, owner))


def _worker_alive(world: WorldState, worker_id: EntityId) -> bool:
    """Return whether the assigned farm worker still exists."""
    worker = world.entities.get(worker_id)
    return _is_settler(worker)


def _queue_owned_by_farm(command: object | None, farm_id: EntityId) -> bool:
    """Queue owned by farm work for later processing."""
    return (
        command is not None
        and getattr(command, "payload", {}).get("farm_work") is True
        and _payload_entity_id(getattr(command, "payload", {}).get("farm_id")) == farm_id
    )


def _clear_completed_farm_move(farm: Building) -> None:
    """Clear completed farm move."""
    farm.functions.pop(FARM_MOVE_KEY, None)


def _clear_farm_interaction_slot(farm: Building) -> None:
    """Forget the side slot retained for the current farm resource."""
    farm.functions.pop(FARM_INTERACTION_RESOURCE_KEY, None)
    farm.functions.pop(FARM_INTERACTION_SIDE_KEY, None)


def _set_farm_state(farm: Building, state: str) -> None:
    """Set farm state."""
    farm.functions["farm_state"] = state


def _raw_animal_harvest_slots(
    animal: ResourceNode,
) -> tuple[WorldPosition, WorldPosition]:
    """Return the preferred left and right farm-animal interaction points."""
    left, top, width, height = animal_harvest_area_bounds(animal)
    slot_y = min(
        max(animal.position.y, top + FARM_ANIMAL_HARVEST_SLOT_INSET),
        top + height - FARM_ANIMAL_HARVEST_SLOT_INSET,
    )
    return (
        WorldPosition(left + FARM_ANIMAL_HARVEST_SLOT_INSET, slot_y),
        WorldPosition(left + width - FARM_ANIMAL_HARVEST_SLOT_INSET, slot_y),
    )


def _animal_harvest_slot_for_side(
    world: WorldState,
    animal: ResourceNode,
    side_index: int,
    worker_id: EntityId | None,
) -> WorldPosition | None:
    """Return a free point near one requested side of a farm animal."""
    area = animal_harvest_area_bounds(animal)
    desired = _raw_animal_harvest_slots(animal)[int(side_index) % 2]
    direction = -1.0 if int(side_index) % 2 == 0 else 1.0
    offsets = (
        (0.0, 0.0),
        (direction * 8.0, 0.0),
        (-direction * 8.0, 0.0),
        (0.0, -8.0),
        (0.0, 8.0),
        (direction * 12.0, -10.0),
        (direction * 12.0, 10.0),
        (-direction * 12.0, -10.0),
        (-direction * 12.0, 10.0),
        (direction * 16.0, 0.0),
    )
    for dx, dy in offsets:
        candidate = clamp_unit_position_to_walkable_lane_for_height(
            WorldPosition(desired.x + dx, desired.y + dy),
            world.settings.world_height,
        )
        if not _position_in_area(candidate, area):
            continue
        if position_blocked_by_hard_obstacle(
            world,
            candidate,
            ignore_id=worker_id,
        ):
            continue
        if occupied_by_unit(
            world,
            candidate,
            ignore_id=worker_id,
            min_distance=UNIT_COLLISION_RADIUS,
        ):
            continue
        return candidate
    return None


def _animal_spawn_position(world: WorldState, farm: Building) -> WorldPosition:
    """Return the position used for animal spawn position."""
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
    """Return whether two positions are within a radius."""
    return _distance(first, second) <= radius


def _farm_respawn_delay_ms(farm: Building) -> int:
    """Return the animal respawn delay for a farm."""
    spec = farm_spec_for(farm)
    if spec is None:
        return PIG_RESPAWN_DELAY_MS
    return spec.respawn_delay_ms


def _carcass_pickup_interval_ms(farm: Building) -> int:
    """Return work time needed for each carcass pickup."""
    spec = farm_spec_for(farm)
    if spec is None:
        return PIG_CARCASS_HARVEST_DURATION_MS
    trips = max(1, ceil(spec.animal_food_yield / max(1, GATHER_CARRY_AMOUNT)))
    return max(1, ceil(spec.carcass_harvest_duration_ms / trips))


def _animal_wander_target(farm: Building) -> WorldPosition | None:
    """Return the position used for animal wander target."""
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
    """Return the position used for choose animal wander target."""
    left, top, width, height = bounds
    farm.functions["animal_wander_target_x"] = world.rng.uniform(left, left + width)
    farm.functions["animal_wander_target_y"] = world.rng.uniform(top, top + height)


def _start_animal_idle(world: WorldState, farm: Building) -> None:
    """Return entity identifiers for start animal idle."""
    farm.functions["animal_idle_remaining_ms"] = world.rng.randint(
        FARM_ANIMAL_IDLE_MIN_MS,
        FARM_ANIMAL_IDLE_MAX_MS,
    )


def _clear_animal_wander_target(farm: Building) -> None:
    """Clear animal wander target."""
    farm.functions.pop("animal_wander_target_x", None)
    farm.functions.pop("animal_wander_target_y", None)


def _clear_animal_wander_state(farm: Building) -> None:
    """Clear animal wander state."""
    _clear_animal_wander_target(farm)
    farm.functions.pop("animal_idle_remaining_ms", None)


def _position_in_area(
    position: WorldPosition,
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return the position used for position in area."""
    left, top, width, height = bounds
    return left <= position.x <= left + width and top <= position.y <= top + height


def _clamp_to_area(
    position: WorldPosition,
    bounds: tuple[float, float, float, float],
) -> WorldPosition:
    """Clamp an animal position inside its farm area."""
    left, top, width, height = bounds
    return WorldPosition(
        min(max(position.x, left), left + width),
        min(max(position.y, top), top + height),
    )


def _move_key(farm_id: EntityId, target: WorldPosition) -> str:
    """Move key."""
    return f"farm:{int(farm_id)}:{round(target.x)}:{round(target.y)}"

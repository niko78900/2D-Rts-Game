"""Resource gathering, deposit, safety, and respawn systems."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from math import hypot

from house_of_wolves.core.contracts import Command, CommandQueue, EntityId, Footprint, WorldPosition
from house_of_wolves.core.geometry import (
    bounds_intersect as _bounds_intersect,
)
from house_of_wolves.core.geometry import (
    distance as _distance,
)
from house_of_wolves.core.geometry import (
    inflate_bounds as _inflate_bounds,
)
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode, resource_hp_for_type
from house_of_wolves.systems.command_payloads import payload_entity_id as _payload_entity_id
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.entity_helpers import is_settler as _is_settler
from house_of_wolves.systems.entity_helpers import set_state as _set_state
from house_of_wolves.systems.pathing import move_waypoints_around_blockers
from house_of_wolves.world.collision import (
    UNIT_COLLISION_RADIUS,
    UNIT_HITBOX_RADIUS,
    blocking_bounds_for_entity,
    nearest_free_position,
    occupied_by_unit,
    position_blocked_by_hard_obstacle,
)
from house_of_wolves.world.terrain import (
    clamp_unit_position_to_walkable_lane_for_height,
    terrain_layout_for_height,
)
from house_of_wolves.world.world import WorldState

RESOURCE_TYPES = ("wood", "food", "stone", "iron", "gold")
GATHER_CARRY_AMOUNT = 5
GATHER_SWINGS_PER_LOAD = 5
GATHER_DAMAGE_PER_SWING = 1
GATHER_SWING_MS = 650
GATHER_INTERACTION_RANGE = 76.0
RESOURCE_INTERACTION_PADDING = UNIT_HITBOX_RADIUS + 8.0
RESOURCE_INTERACTION_MAX_RETRIES = 3
HUT_DEPOSIT_MAX_RETRIES = 3
HUT_DEPOSIT_REFRESH_MS = 1500
TREE_HARVEST_MIN_SLOTS = 4
TREE_HARVEST_MAX_SLOTS = 8
TREE_HARVEST_AREA_WIDTH = 136.0
TREE_HARVEST_AREA_HEIGHT = 104.0
TREE_HARVEST_AREA_TOP_OFFSET_FROM_BLOCKER_BOTTOM = -24.0
MINE_HARVEST_MIN_SLOTS = 4
MINE_HARVEST_MAX_SLOTS = 8
MINE_HARVEST_AREA_MIN_WIDTH = 190.0
MINE_HARVEST_AREA_MIN_HEIGHT = 125.0
MINE_HARVEST_AREA_HORIZONTAL_PADDING = 48.0
MINE_HARVEST_AREA_VERTICAL_PADDING = 34.0
RESOURCE_DESTRUCTION_MS = 1500
TREE_RESPAWN_DELAY_SECONDS = 60
STONE_RESPAWN_DELAY_SECONDS = 60
ORE_RESPAWN_DELAY_SECONDS = 60
GOLD_RESPAWN_DELAY_SECONDS = 60
TREE_RESPAWN_DELAY_MS = TREE_RESPAWN_DELAY_SECONDS * 1000
STONE_RESPAWN_DELAY_MS = STONE_RESPAWN_DELAY_SECONDS * 1000
ORE_RESPAWN_DELAY_MS = ORE_RESPAWN_DELAY_SECONDS * 1000
GOLD_RESPAWN_DELAY_MS = GOLD_RESPAWN_DELAY_SECONDS * 1000
RESPAWN_RETRY_MS = 5000
RESPAWN_AVOID_RADIUS = 140.0
MAX_PATH_JOBS_PER_FRAME = 2
MAX_RESOURCE_CANDIDATES_TO_PATHCHECK = 5
SAFETY_CACHE_REFRESH_SECONDS = 1.0
SAFETY_CACHE_REFRESH_MS = round(SAFETY_CACHE_REFRESH_SECONDS * 1000)
MAX_ACTIVE_TREES = 40
MAX_ACTIVE_STONE_NODES = 5
MAX_ACTIVE_IRON_NODES = 5
MAX_ACTIVE_GOLD_NODES = 5
AUTO_DISTRIBUTION_LOAD_PENALTY = 260.0
MINE_RESOURCE_TYPES = ("stone", "iron", "gold")
RESPAWNABLE_RESOURCE_TYPES = ("wood", "stone", "iron", "gold")

GATHER_STATE_MOVING_TO_RESOURCE = "moving_to_resource"
GATHER_STATE_GATHERING = "gathering"
GATHER_STATE_CARRYING_RESOURCE = "carrying_resource"
GATHER_STATE_MOVING_TO_HUT = "moving_to_hut"
GATHER_STATE_DEPOSITING = "depositing"
GATHER_STATE_RETURNING_TO_RESOURCE = "returning_to_resource"
GATHER_STATE_IDLE = "idle"
GATHER_STATE_DEFENDING = "defending"


@dataclass(frozen=True, slots=True)
class ResourceNodeSpec:
    tags: tuple[str, ...]
    footprint: Footprint
    blocking_footprint: Footprint
    gather_time_ms: int
    depleted_replacement: str


RESOURCE_NODE_SPECS = {
    "wood": ResourceNodeSpec(
        tags=("resource", "wood_tree", "selectable"),
        footprint=Footprint(82, 126),
        blocking_footprint=Footprint(42, 92),
        gather_time_ms=900,
        depleted_replacement="tree_stump",
    ),
    "stone": ResourceNodeSpec(
        tags=("resource", "stone_outcrop", "selectable"),
        footprint=Footprint(118, 74),
        blocking_footprint=Footprint(104, 54),
        gather_time_ms=1200,
        depleted_replacement="stone_rubble",
    ),
    "iron": ResourceNodeSpec(
        tags=("resource", "iron_deposit", "selectable"),
        footprint=Footprint(118, 74),
        blocking_footprint=Footprint(104, 54),
        gather_time_ms=1200,
        depleted_replacement="empty_iron_deposit",
    ),
    "gold": ResourceNodeSpec(
        tags=("resource", "gold_mine", "selectable"),
        footprint=Footprint(132, 86),
        blocking_footprint=Footprint(124, 64),
        gather_time_ms=1200,
        depleted_replacement="gold_mine_empty",
    ),
}


@dataclass(slots=True)
class ResourceWallet:
    amounts: dict[str, int] = field(default_factory=lambda: {key: 0 for key in RESOURCE_TYPES})

    def can_afford(self, cost: dict[str, int]) -> bool:
        """Return whether the wallet can pay the resource cost."""
        return all(self.amounts.get(resource, 0) >= amount for resource, amount in cost.items())

    def spend(self, cost: dict[str, int]) -> bool:
        """Subtract a resource cost if the wallet can afford it."""
        if not self.can_afford(cost):
            return False
        for resource, amount in cost.items():
            self.amounts[resource] = self.amounts.get(resource, 0) - amount
        return True


@dataclass(slots=True)
class ResourceRespawn:
    resource_type: str
    due_ms: int
    destroyed_position: WorldPosition


@dataclass(slots=True)
class ResourceSafetyCacheEntry:
    safe: bool
    checked_ms: int


@dataclass(slots=True)
class GatherAssignmentJob:
    gatherer_id: EntityId
    resource_type: str
    owner: str
    queued: bool = False
    safe: bool = True
    manual: bool = False
    existing_command: bool = False
    notify_on_failure: bool = False


@dataclass(slots=True)
class GatherPerformanceCounters:
    path_jobs_processed: int = 0
    resource_searches: int = 0
    resource_candidates_checked: int = 0
    full_path_calculations: int = 0


@dataclass(slots=True)
class EconomySystem:
    gather_interaction_range: float = GATHER_INTERACTION_RANGE
    deposit_interaction_range: float = 140.0
    gather_swing_ms: int = GATHER_SWING_MS
    tree_respawn_delay_ms: int = TREE_RESPAWN_DELAY_MS
    stone_respawn_delay_ms: int = STONE_RESPAWN_DELAY_MS
    ore_respawn_delay_ms: int = ORE_RESPAWN_DELAY_MS
    gold_respawn_delay_ms: int = GOLD_RESPAWN_DELAY_MS
    respawn_retry_ms: int = RESPAWN_RETRY_MS
    max_path_jobs_per_frame: int = MAX_PATH_JOBS_PER_FRAME
    max_resource_candidates_to_pathcheck: int = MAX_RESOURCE_CANDIDATES_TO_PATHCHECK
    safety_cache_refresh_ms: int = SAFETY_CACHE_REFRESH_MS
    deposit_target_refresh_ms: int = HUT_DEPOSIT_REFRESH_MS
    debug_gather_performance: bool = False
    max_active_trees: int = MAX_ACTIVE_TREES
    max_nodes_by_type: dict[str, int] = field(
        default_factory=lambda: {
            "stone": MAX_ACTIVE_STONE_NODES,
            "iron": MAX_ACTIVE_IRON_NODES,
            "gold": MAX_ACTIVE_GOLD_NODES,
        }
    )
    respawns: list[ResourceRespawn] = field(default_factory=list)
    gather_assignment_jobs: list[GatherAssignmentJob] = field(default_factory=list)
    safety_cache: dict[tuple[EntityId, str], ResourceSafetyCacheEntry] = field(
        default_factory=dict
    )
    last_frame_stats: GatherPerformanceCounters = field(
        default_factory=GatherPerformanceCounters
    )

    def update(self, world: WorldState, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
        self.last_frame_stats = GatherPerformanceCounters()
        self._update_resource_lifecycle(world, dt_ms)
        self._update_respawns(world)
        self._process_gather_assignment_jobs(world)
        for worker_id, queue in list(world.command_queues.items()):
            self._update_worker(world, worker_id, queue, dt_ms)
        if self.debug_gather_performance:
            _debug_log_gather_performance(self.last_frame_stats)

    def queue_auto_gather(
        self,
        world: WorldState,
        gatherer_ids: list[EntityId],
        resource_type: str,
        *,
        owner: str = "frontier",
    ) -> str | None:
        """Queue auto gather work for later processing."""
        resource_type = normalize_resource_type(resource_type)
        if not completed_deposit_huts(world, owner):
            return "Needs hut to deposit."
        if not cached_active_resource_nodes(world, resource_type):
            return f"No safe {display_resource_name(resource_type).lower()} source found."
        for index, gatherer_id in enumerate(gatherer_ids):
            self.gather_assignment_jobs.append(
                GatherAssignmentJob(
                    gatherer_id=gatherer_id,
                    resource_type=resource_type,
                    owner=owner,
                    safe=True,
                    manual=False,
                    notify_on_failure=index == 0,
                )
            )
        return None

    def _queue_gather_reassignment(
        self,
        worker: object,
        command: Command,
        resource_type: str,
    ) -> None:
        """Queue gather reassignment work for later processing."""
        resource_type = normalize_resource_type(resource_type)
        if command.payload.get("reassignment_pending") is True:
            return
        command.payload["reassignment_pending"] = True
        self.gather_assignment_jobs.append(
            GatherAssignmentJob(
                gatherer_id=worker.id,
                resource_type=resource_type,
                owner=worker.owner,
                safe=False,
                manual=bool(command.payload.get("manual", False)),
                existing_command=True,
            )
        )

    def _process_gather_assignment_jobs(self, world: WorldState) -> None:
        """Process queued gather assignment jobs work."""
        pending: list[GatherAssignmentJob] = []
        budget = max(0, int(self.max_path_jobs_per_frame))
        for job in self.gather_assignment_jobs:
            if budget <= 0:
                pending.append(job)
                continue
            self._process_gather_assignment_job(world, job)
            budget -= 1
            self.last_frame_stats.path_jobs_processed += 1
        self.gather_assignment_jobs = pending

    def _process_gather_assignment_job(
        self,
        world: WorldState,
        job: GatherAssignmentJob,
    ) -> bool:
        """Process queued gather assignment job work."""
        gatherer = world.entities.get(job.gatherer_id)
        if not _is_settler(gatherer):
            return False
        if job.existing_command:
            queue = world.command_queues.get(job.gatherer_id)
            command = queue.peek() if queue is not None else None
            if command is None or command.type != "gather":
                return False
            command.payload.pop("reassignment_pending", None)

        resource = self._find_nearest_resource_node(
            world,
            job.gatherer_id,
            gatherer.position,
            job.resource_type,
            safe=job.safe,
            owner=job.owner,
        )
        if resource is None:
            self._handle_gather_assignment_failure(world, gatherer, job)
            return False

        if job.existing_command:
            self._assign_existing_gather_command(world, gatherer, resource)
        else:
            slot_index = _next_gather_slot_index(world, resource)
            issue_gather_command(
                world,
                resource,
                job.gatherer_id,
                queued=job.queued,
                manual=job.manual,
                slot_index=slot_index,
            )
        return True

    def _assign_existing_gather_command(
        self,
        world: WorldState,
        worker: object,
        resource: ResourceNode,
    ) -> None:
        """Assign existing gather command."""
        queue = world.command_queues.get(worker.id)
        command = queue.peek() if queue is not None else None
        if command is None or command.type != "gather":
            return
        command.payload["current_resource_id"] = resource.id.to_json()
        command.payload["resource_type"] = resource.resource_type
        command.payload["phase"] = GATHER_STATE_RETURNING_TO_RESOURCE
        command.payload["resource_interaction_candidate_index"] = _next_gather_slot_index(
            world,
            resource,
        )
        interaction_point = _cached_resource_interaction_position(
            world,
            command,
            resource,
            worker.id,
        )
        _insert_move_before_gather(
            queue,
            worker.id,
            interaction_point,
            command,
            _move_key("resource", resource.id),
        )
        _set_state(worker, GATHER_STATE_RETURNING_TO_RESOURCE)

    def _handle_gather_assignment_failure(
        self,
        world: WorldState,
        gatherer: object,
        job: GatherAssignmentJob,
    ) -> None:
        """Handle gather assignment failure input or UI flow."""
        queue = world.command_queues.get(job.gatherer_id)
        command = queue.peek() if queue is not None else None
        if job.existing_command and command is not None and command.type == "gather":
            command.payload.pop("reassignment_pending", None)
            if self._should_wait_for_resource_respawn(world, command, job.resource_type):
                command.payload["reassignment_pending"] = True
                command.payload["phase"] = GATHER_STATE_IDLE
                _set_state(gatherer, GATHER_STATE_IDLE)
                return
            _clear_gather_job(gatherer, queue)
            return
        if job.notify_on_failure:
            world.notify(
                f"No safe {display_resource_name(job.resource_type).lower()} source found."
            )
        _set_state(gatherer, GATHER_STATE_IDLE)

    def _find_nearest_resource_node(
        self,
        world: WorldState,
        entity_id: EntityId,
        origin: WorldPosition,
        resource_type: str,
        *,
        safe: bool,
        owner: str = "frontier",
    ) -> ResourceNode | None:
        """Find nearest resource node."""
        resource_type = normalize_resource_type(resource_type)
        candidates = closest_resource_candidates(
            world,
            resource_type,
            origin,
            max_candidates=self.max_resource_candidates_to_pathcheck,
            safety_checker=(
                lambda node: self._resource_safe_for_auto_gather(world, node, owner)
                if safe
                else True
            ),
            stats=self.last_frame_stats,
        )
        if not candidates:
            return None

        load_by_resource = _active_gather_load(world, resource_type)
        return min(
            candidates,
            key=lambda node: (
                self._estimated_travel_distance(
                    world,
                    entity_id,
                    origin,
                    resource_interaction_position(
                        world,
                        node,
                        entity_id,
                        candidate_index=_slot_index_for_load(load_by_resource, node),
                    ),
                )
                + load_by_resource.get(node.id, 0) * AUTO_DISTRIBUTION_LOAD_PENALTY
            ),
        )

    def _estimated_travel_distance(
        self,
        world: WorldState,
        entity_id: EntityId | None,
        origin: WorldPosition,
        target: WorldPosition,
    ) -> float:
        """Return the distance used for estimated travel distance."""
        self.last_frame_stats.full_path_calculations += 1
        return estimated_travel_distance(world, entity_id, origin, target)

    def _resource_safe_for_auto_gather(
        self,
        world: WorldState,
        resource: ResourceNode,
        owner: str,
    ) -> bool:
        """Return whether auto-gather may choose a resource."""
        key = (resource.id, owner)
        cached = self.safety_cache.get(key)
        if (
            cached is not None
            and world.elapsed_ms - cached.checked_ms < self.safety_cache_refresh_ms
        ):
            return cached.safe
        safe = resource_node_safe_for_auto_gather(world, resource, owner)
        self.safety_cache[key] = ResourceSafetyCacheEntry(safe, world.elapsed_ms)
        return safe

    def _update_worker(
        self,
        world: WorldState,
        worker_id: EntityId,
        queue: CommandQueue,
        dt_ms: int,
    ) -> None:
        """Advance worker for the current frame."""
        worker = world.entities.get(worker_id)
        if not _is_settler(worker):
            return
        command = queue.peek()
        if command is None:
            return
        if command.type != "gather":
            self._refresh_active_deposit_move(world, worker, queue, command)
            return

        if _enemy_can_hit_position(world, worker.position, worker.owner):
            queue.clear()
            _set_state(worker, GATHER_STATE_DEFENDING)
            return

        resource_type = _command_resource_type(world, command)
        if resource_type is None:
            queue.pop_next()
            _set_state(worker, GATHER_STATE_IDLE)
            return
        if not completed_deposit_huts(world, worker.owner):
            world.notify("Needs hut to deposit.")
            _clear_gather_job(worker, queue)
            return
        if _gather_target_type_invalid(world, command, resource_type):
            _clear_gather_job(worker, queue)
            return

        if int(getattr(worker, "carry_amount", 0)) > 0:
            self._advance_deposit(world, worker, queue, command, resource_type)
            return

        if command.payload.get("reassignment_pending") is True:
            if self._assignment_job_pending(worker.id, resource_type):
                _set_state(worker, GATHER_STATE_IDLE)
                return
            if not cached_active_resource_nodes(world, resource_type):
                _set_state(worker, GATHER_STATE_IDLE)
                return
            command.payload.pop("reassignment_pending", None)

        resource = _current_or_replacement_resource(world, command, resource_type, worker)
        if resource is None:
            self._request_reassignment_or_idle(world, worker, command, resource_type)
            return
        command.payload["current_resource_id"] = resource.id.to_json()
        command.payload["phase"] = GATHER_STATE_MOVING_TO_RESOURCE

        if is_unit_in_gather_range(worker, resource, self.gather_interaction_range):
            command.payload.pop("pending_move_key", None)
            self._swing_at_resource(world, worker, queue, command, resource, resource_type, dt_ms)
            return

        interaction_point = _cached_resource_interaction_position(
            world,
            command,
            resource,
            worker.id,
        )
        if not _within(worker.position, interaction_point, self.gather_interaction_range):
            if _pending_move_failed(command, _move_key("resource", resource.id)):
                if self._retry_resource_interaction_move(world, worker, queue, command, resource):
                    _set_state(worker, GATHER_STATE_MOVING_TO_RESOURCE)
                    return
                world.notify("Cannot reach resource.")
                _clear_gather_job(worker, queue)
                return
            _insert_move_before_gather(
                queue,
                worker.id,
                interaction_point,
                command,
                _move_key("resource", resource.id),
            )
            _set_state(worker, GATHER_STATE_MOVING_TO_RESOURCE)
            return
        command.payload.pop("pending_move_key", None)
        self._swing_at_resource(world, worker, queue, command, resource, resource_type, dt_ms)

    def _retry_resource_interaction_move(
        self,
        world: WorldState,
        worker: object,
        queue: CommandQueue,
        command: Command,
        resource: ResourceNode,
    ) -> bool:
        """Retry resource interaction move."""
        retry_count = int(command.payload.get("resource_interaction_retry_count", 0) or 0)
        if retry_count >= RESOURCE_INTERACTION_MAX_RETRIES:
            return False
        command.payload["resource_interaction_retry_count"] = retry_count + 1
        interaction_point = _cached_resource_interaction_position(
            world,
            command,
            resource,
            worker.id,
            force_refresh=True,
        )
        if is_unit_in_gather_range(worker, resource, self.gather_interaction_range):
            return False
        _insert_move_before_gather(
            queue,
            worker.id,
            interaction_point,
            command,
            _move_key("resource", resource.id),
        )
        return True

    def _swing_at_resource(
        self,
        world: WorldState,
        worker: object,
        queue: CommandQueue,
        command: Command,
        resource: ResourceNode,
        resource_type: str,
        dt_ms: int,
    ) -> None:
        """Advance one worker swing cycle against a resource."""
        _set_state(worker, GATHER_STATE_GATHERING)
        _face_worker_toward_resource(worker, resource)
        elapsed = int(command.payload.get("swing_elapsed_ms", 0)) + max(0, int(dt_ms))
        swings = int(command.payload.get("successful_swings", 0))
        while elapsed >= self.gather_swing_ms and swings < GATHER_SWINGS_PER_LOAD:
            elapsed -= self.gather_swing_ms
            if not active_resource(resource):
                command.payload["successful_swings"] = swings
                command.payload["swing_elapsed_ms"] = elapsed
                self._request_reassignment_or_idle(world, worker, command, resource_type)
                return
            _damage_resource(world, resource, GATHER_DAMAGE_PER_SWING)
            swings += 1

        command.payload["successful_swings"] = swings
        command.payload["swing_elapsed_ms"] = elapsed
        if swings < GATHER_SWINGS_PER_LOAD:
            return

        worker.carry_type = resource_type
        worker.carry_amount = GATHER_CARRY_AMOUNT
        command.payload["successful_swings"] = 0
        command.payload["swing_elapsed_ms"] = 0
        command.payload["phase"] = GATHER_STATE_CARRYING_RESOURCE
        self._advance_deposit(world, worker, queue, command, resource_type)

    def _advance_deposit(
        self,
        world: WorldState,
        worker: object,
        queue: CommandQueue,
        command: Command,
        resource_type: str,
    ) -> None:
        """Move a loaded worker to a hut and deposit resources."""
        hut, deposit_point = _cached_deposit_target(
            world,
            command,
            worker,
            force_refresh=command.payload.get("pending_move_key") is None,
        )
        if hut is None:
            world.notify("Needs hut to deposit.")
            _clear_gather_job(worker, queue)
            return
        if not _within(worker.position, deposit_point, self.deposit_interaction_range):
            if _pending_move_failed(command, _move_key("hut", hut.id)):
                if self._retry_hut_deposit_move(world, worker, queue, command):
                    _set_state(worker, GATHER_STATE_MOVING_TO_HUT)
                    return
                world.notify("Cannot reach hut.")
                _clear_gather_job(worker, queue)
                return
            _insert_move_before_gather(
                queue,
                worker.id,
                deposit_point,
                command,
                _move_key("hut", hut.id),
            )
            _set_state(worker, GATHER_STATE_MOVING_TO_HUT)
            return

        command.payload.pop("pending_move_key", None)
        _set_state(worker, GATHER_STATE_DEPOSITING)
        carry_type = worker.carry_type or resource_type
        carry_amount = int(getattr(worker, "carry_amount", 0))
        if carry_amount > 0:
            world.resources[carry_type] = world.resources.get(carry_type, 0) + carry_amount
        worker.carry_type = None
        worker.carry_amount = 0
        command.payload["phase"] = GATHER_STATE_RETURNING_TO_RESOURCE

        resource = _current_or_replacement_resource(world, command, resource_type, worker)
        if resource is None:
            self._request_reassignment_or_idle(world, worker, command, resource_type)
            return
        command.payload["current_resource_id"] = resource.id.to_json()
        interaction_point = _cached_resource_interaction_position(
            world,
            command,
            resource,
            worker.id,
        )
        _insert_move_before_gather(
            queue,
            worker.id,
            interaction_point,
            command,
            _move_key("resource", resource.id),
        )
        _set_state(worker, GATHER_STATE_RETURNING_TO_RESOURCE)

    def _refresh_active_deposit_move(
        self,
        world: WorldState,
        worker: object,
        queue: CommandQueue,
        move_command: Command,
    ) -> None:
        """Retarget an in-progress deposit move to the currently closest hut."""
        if move_command.type != "move" or int(getattr(worker, "carry_amount", 0)) <= 0:
            return
        if len(queue.commands) < 2:
            return
        gather_command = queue.commands[1]
        if gather_command.type != "gather":
            return
        pending_key = gather_command.payload.get("pending_move_key")
        if not isinstance(pending_key, str) or not pending_key.startswith("hut:"):
            return
        last_checked_ms = int(
            gather_command.payload.get(
                "deposit_target_checked_ms",
                -self.deposit_target_refresh_ms,
            )
        )
        if world.elapsed_ms - last_checked_ms < self.deposit_target_refresh_ms:
            return

        old_hut_id = _payload_entity_id(gather_command, "deposit_hut_id")
        hut, deposit_point = _cached_deposit_target(
            world,
            gather_command,
            worker,
            force_refresh=True,
        )
        gather_command.payload["deposit_target_checked_ms"] = world.elapsed_ms
        if hut is None:
            return
        if (
            old_hut_id == hut.id
            and move_command.target_pos is not None
            and _distance(move_command.target_pos, deposit_point) < 1.0
        ):
            return

        gather_command.payload["pending_move_key"] = _move_key("hut", hut.id)
        queue.commands[0] = make_command(
            "move",
            [worker.id],
            target_pos=deposit_point,
            gather_move=True,
        )
        _set_state(worker, GATHER_STATE_MOVING_TO_HUT)

    def _retry_hut_deposit_move(
        self,
        world: WorldState,
        worker: object,
        queue: CommandQueue,
        command: Command,
    ) -> bool:
        """Retry a hut deposit route before reporting the deposit as unreachable."""
        retry_count = int(command.payload.get("hut_deposit_retry_count", 0) or 0)
        if retry_count >= HUT_DEPOSIT_MAX_RETRIES:
            return False

        command.payload["hut_deposit_retry_count"] = retry_count + 1
        command.payload.pop("pending_move_key", None)
        command.payload.pop("deposit_hut_id", None)
        command.payload.pop("deposit_hut_x", None)
        command.payload.pop("deposit_hut_y", None)
        hut, deposit_point = _cached_deposit_target(world, command, worker)
        if hut is None:
            return False
        _insert_move_before_gather(
            queue,
            worker.id,
            deposit_point,
            command,
            _move_key("hut", hut.id),
        )
        return True

    def _request_reassignment_or_idle(
        self,
        world: WorldState,
        worker: object,
        command: Command,
        resource_type: str,
    ) -> None:
        """Request reassignment or idle."""
        if (
            not cached_active_resource_nodes(world, resource_type)
            and self._should_wait_for_resource_respawn(world, command, resource_type)
        ):
            command.payload["phase"] = GATHER_STATE_IDLE
            _set_state(worker, GATHER_STATE_IDLE)
            return
        self._queue_gather_reassignment(worker, command, resource_type)
        command.payload["phase"] = GATHER_STATE_IDLE
        _set_state(worker, GATHER_STATE_IDLE)

    def _assignment_job_pending(self, gatherer_id: EntityId, resource_type: str) -> bool:
        """Return whether a gather reassignment is already queued."""
        return any(
            job.gatherer_id == gatherer_id
            and job.resource_type == resource_type
            and job.existing_command
            for job in self.gather_assignment_jobs
        )

    def _update_resource_lifecycle(self, world: WorldState, dt_ms: int) -> None:
        """Advance resource lifecycle for the current frame."""
        for resource in list(world.entities.values()):
            if not isinstance(resource, ResourceNode) or resource.state != "destroying":
                continue
            resource.destruction_remaining_ms -= max(0, int(dt_ms))
            if resource.destruction_remaining_ms > 0:
                continue
            resource_type = resource.resource_type
            respawn_enabled = resource.respawn_enabled
            destroyed_position = resource.position
            world.remove_entity(resource.id)
            if respawn_enabled:
                self._schedule_respawn(world, resource_type, destroyed_position)

    def _schedule_respawn(
        self,
        world: WorldState,
        resource_type: str,
        destroyed_position: WorldPosition,
    ) -> None:
        """Schedule respawn."""
        if resource_type not in RESPAWNABLE_RESOURCE_TYPES:
            return
        self.respawns.append(
            ResourceRespawn(
                resource_type,
                world.elapsed_ms + self._respawn_delay_for(resource_type),
                destroyed_position,
            )
        )

    def _update_respawns(self, world: WorldState) -> None:
        """Advance respawns for the current frame."""
        pending: list[ResourceRespawn] = []
        for respawn in self.respawns:
            if respawn.due_ms > world.elapsed_ms:
                pending.append(respawn)
                continue
            if respawn.resource_type not in RESPAWNABLE_RESOURCE_TYPES:
                continue
            if self._active_resource_count(world, respawn.resource_type) >= self._cap_for(
                respawn.resource_type
            ):
                # Trees are a renewable background pool; mines are strict capped rewards.
                if respawn.resource_type == "wood":
                    respawn.due_ms = world.elapsed_ms + self.respawn_retry_ms
                    pending.append(respawn)
                continue
            if not self._spawn_resource(
                world,
                respawn.resource_type,
                avoid_position=respawn.destroyed_position,
            ):
                respawn.due_ms = world.elapsed_ms + self.respawn_retry_ms
                pending.append(respawn)
        self.respawns = pending

    def _active_resource_count(self, world: WorldState, resource_type: str) -> int:
        """Return the active resource count."""
        return len(active_resource_nodes(world, resource_type))

    def _cap_for(self, resource_type: str) -> int:
        """Return the active-node cap for a resource type."""
        resource_type = normalize_resource_type(resource_type)
        if resource_type == "wood":
            return self.max_active_trees
        return self.max_nodes_by_type.get(resource_type, 0)

    def _respawn_delay_for(self, resource_type: str) -> int:
        """Return the respawn delay for a resource type."""
        resource_type = normalize_resource_type(resource_type)
        if resource_type == "wood":
            return self.tree_respawn_delay_ms
        if resource_type == "stone":
            return self.stone_respawn_delay_ms
        if resource_type == "iron":
            return self.ore_respawn_delay_ms
        if resource_type == "gold":
            return self.gold_respawn_delay_ms
        return 0

    def _should_wait_for_resource_respawn(
        self,
        world: WorldState,
        command: Command,
        resource_type: str,
    ) -> bool:
        """Return whether wait for resource respawn should happen."""
        if resource_type != "wood":
            return False
        current = _resource_target(world, _payload_entity_id(command, "current_resource_id"))
        target = _resource_target(world, command.target_entity_id)
        for resource in (current, target):
            if (
                resource is not None
                and resource.resource_type == "wood"
                and resource.state == "destroying"
            ):
                return True
        return any(respawn.resource_type == "wood" for respawn in self.respawns)

    def _spawn_resource(
        self,
        world: WorldState,
        resource_type: str,
        *,
        avoid_position: WorldPosition | None = None,
    ) -> bool:
        """Spawn resource."""
        spec = RESOURCE_NODE_SPECS.get(resource_type)
        if spec is None:
            return False
        fallback_position: WorldPosition | None = None
        for _ in range(120):
            x = world.rng.uniform(320, max(321, world.settings.world_width - 320))
            y = world.rng.uniform(
                _walkable_top(world) + 36,
                max(_walkable_top(world) + 37, _walkable_bottom(world) - 56),
            )
            position = WorldPosition(x, y)
            if not _resource_spawn_position_valid(world, position, spec):
                continue
            if (
                avoid_position is not None
                and _distance(position, avoid_position) <= RESPAWN_AVOID_RADIUS
            ):
                fallback_position = fallback_position or position
                continue
            self._add_resource_node(world, resource_type, position, spec)
            return True
        if fallback_position is not None:
            self._add_resource_node(world, resource_type, fallback_position, spec)
            return True
        return False

    def _add_resource_node(
        self,
        world: WorldState,
        resource_type: str,
        position: WorldPosition,
        spec: ResourceNodeSpec,
    ) -> None:
        """Add resource node."""
        hp = resource_hp_for_type(resource_type)
        node = ResourceNode(
            id=world.allocate_entity_id(),
            owner="neutral",
            position=position,
            footprint=spec.footprint,
            hp=hp,
            max_hp=hp,
            tags=spec.tags,
            resource_type=resource_type,
            amount_remaining=hp,
            max_amount_remaining=hp,
            gather_time_ms=spec.gather_time_ms,
            depleted_replacement=spec.depleted_replacement,
            blocking_footprint=spec.blocking_footprint,
        )
        world.add_entity(node)


def completed_deposit_huts(world: WorldState, owner: str = "frontier") -> list[Building]:
    """Return completed player-owned huts that accept deposits."""
    cached_ids = getattr(world, "completed_deposit_huts_by_owner", {}).get(owner)
    if cached_ids is not None:
        huts: list[Building] = []
        for entity_id in cached_ids:
            entity = world.entities.get(entity_id)
            if (
                isinstance(entity, Building)
                and entity.owner == owner
                and entity.complete
                and bool(entity.functions.get("dropoff"))
                and entity.alive
            ):
                huts.append(entity)
        return huts
    return [
        entity
        for entity in world.entities.values()
        if isinstance(entity, Building)
        and entity.owner == owner
        and entity.complete
        and bool(entity.functions.get("dropoff"))
        and entity.alive
    ]


def closest_deposit_hut(
    world: WorldState,
    position: WorldPosition,
    owner: str,
    entity_id: EntityId | None = None,
) -> Building | None:
    """Return the nearest completed deposit hut for a worker."""
    huts = completed_deposit_huts(world, owner)
    if not huts:
        return None
    return min(
        huts,
        key=lambda hut: estimated_travel_distance(
            world,
            entity_id,
            position,
            hut_deposit_position(world, hut, entity_id),
        ),
    )


def assign_auto_gather_targets(
    world: WorldState,
    gatherer_ids: list[EntityId],
    resource_type: str,
    *,
    owner: str = "frontier",
) -> tuple[dict[EntityId, ResourceNode], str | None]:
    """Assign auto-gather jobs across available resource nodes."""
    resource_type = normalize_resource_type(resource_type)
    if not completed_deposit_huts(world, owner):
        return {}, "Needs hut to deposit."

    if not cached_active_resource_nodes(world, resource_type):
        return {}, f"No safe {display_resource_name(resource_type).lower()} source found."

    assignments: dict[EntityId, ResourceNode] = {}
    assigned_counts: dict[EntityId, int] = _active_gather_load(world, resource_type)
    for gatherer_id in gatherer_ids:
        gatherer = world.entities.get(gatherer_id)
        if gatherer is None:
            continue
        candidates = closest_resource_candidates(
            world,
            resource_type,
            gatherer.position,
            max_candidates=MAX_RESOURCE_CANDIDATES_TO_PATHCHECK,
            safety_checker=lambda node: resource_node_safe_for_auto_gather(
                world,
                node,
                owner,
            ),
        )
        if not candidates:
            continue
        node = min(
            candidates,
            key=lambda candidate: (
                estimated_travel_distance(
                    world,
                    gatherer_id,
                    gatherer.position,
                    resource_interaction_position(world, candidate, gatherer_id),
                )
                + assigned_counts[candidate.id] * AUTO_DISTRIBUTION_LOAD_PENALTY
            ),
        )
        assigned_counts[node.id] += 1
        assignments[gatherer_id] = node
    if not assignments:
        return {}, f"No safe {display_resource_name(resource_type).lower()} source found."
    return assignments, None


def find_nearest_resource_node(
    world: WorldState,
    entity_id: EntityId,
    origin: WorldPosition,
    resource_type: str,
    *,
    safe: bool,
    owner: str = "frontier",
) -> ResourceNode | None:
    """Find the best resource node for a gatherer."""
    resource_type = normalize_resource_type(resource_type)
    candidates = closest_resource_candidates(
        world,
        resource_type,
        origin,
        max_candidates=MAX_RESOURCE_CANDIDATES_TO_PATHCHECK,
        safety_checker=(
            lambda node: resource_node_safe_for_auto_gather(world, node, owner)
            if safe
            else True
        ),
    )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda node: estimated_travel_distance(
            world,
            entity_id,
            origin,
            resource_interaction_position(world, node, entity_id),
        ),
    )


def active_resource_nodes(
    world: WorldState,
    resource_type: str | None = None,
) -> list[ResourceNode]:
    """Return active resource nodes of a type."""
    return cached_active_resource_nodes(world, resource_type)


def cached_active_resource_nodes(
    world: WorldState,
    resource_type: str | None = None,
) -> list[ResourceNode]:
    """Return cached active resource node ids of a type."""
    indexed_ids = _cached_resource_ids(world, resource_type)
    if indexed_ids is None:
        normalized = normalize_resource_type(resource_type) if resource_type is not None else None
        return [
            entity
            for entity in world.entities.values()
            if isinstance(entity, ResourceNode)
            and active_resource(entity)
            and (normalized is None or entity.resource_type == normalized)
        ]
    nodes: list[ResourceNode] = []
    for entity_id in indexed_ids:
        entity = world.entities.get(entity_id)
        if not isinstance(entity, ResourceNode) or not active_resource(entity):
            continue
        if (
            resource_type is not None
            and entity.resource_type != normalize_resource_type(resource_type)
        ):
            continue
        nodes.append(entity)
    return nodes


def closest_resource_candidates(
    world: WorldState,
    resource_type: str,
    origin: WorldPosition,
    *,
    max_candidates: int = MAX_RESOURCE_CANDIDATES_TO_PATHCHECK,
    safety_checker: Callable[[ResourceNode], bool] | None = None,
    stats: GatherPerformanceCounters | None = None,
) -> list[ResourceNode]:
    """Return nearby resource candidates using cheap distance."""
    if stats is not None:
        stats.resource_searches += 1
    ordered = sorted(
        cached_active_resource_nodes(world, resource_type),
        key=lambda node: _cheap_distance_sq(origin, node.position),
    )
    candidates: list[ResourceNode] = []
    for node in ordered:
        if stats is not None:
            stats.resource_candidates_checked += 1
        if safety_checker is not None and not safety_checker(node):
            continue
        candidates.append(node)
        if len(candidates) >= max(1, int(max_candidates)):
            break
    return candidates


def issue_gather_command(
    world: WorldState,
    resource: ResourceNode,
    gatherer_id: EntityId,
    *,
    queued: bool,
    manual: bool,
    slot_index: int = 0,
) -> None:
    """Issue a gather command against a specific resource node."""
    interaction_point = resource_interaction_position(
        world,
        resource,
        gatherer_id,
        candidate_index=slot_index,
    )
    world.enqueue_command(
        gatherer_id,
        make_command("move", [gatherer_id], target_pos=interaction_point, queued=queued),
    )
    world.enqueue_command(
        gatherer_id,
        make_command(
            "gather",
            [gatherer_id],
            target_entity_id=resource.id,
            target_pos=interaction_point,
            queued=True,
            resource_type=resource.resource_type,
            current_resource_id=resource.id.to_json(),
            resource_interaction_resource_id=resource.id.to_json(),
            resource_interaction_candidate_index=slot_index,
            resource_interaction_x=interaction_point.x,
            resource_interaction_y=interaction_point.y,
            manual=manual,
        ),
    )


def active_resource(resource: ResourceNode) -> bool:
    """Return an active resource node by id if it can be gathered."""
    return (
        resource.alive
        and resource.state == "active"
        and resource.hp > 0
        and resource.amount_remaining > 0
    )


def resource_node_safe_for_auto_gather(
    world: WorldState,
    resource: ResourceNode,
    owner: str = "frontier",
) -> bool:
    """Return whether auto-gather may safely use a node."""
    interaction = resource_interaction_position(world, resource)
    return not _enemy_can_hit_position(world, interaction, owner)


def resource_interaction_candidates(
    world: WorldState,
    resource: ResourceNode,
    gatherer_id: EntityId | None = None,
) -> list[WorldPosition]:
    """Return valid approach points near the resource blocker edge."""
    if is_tree_resource(resource):
        return tree_harvest_slot_candidates(world, resource, gatherer_id)
    if is_mine_resource(resource):
        return mine_harvest_slot_candidates(world, resource, gatherer_id)

    left, top, width, height = blocking_bounds_for_entity(resource)
    right = left + width
    bottom = top + height
    origin = _entity_position(world, gatherer_id) or resource.position
    offset = RESOURCE_INTERACTION_PADDING
    nearest_x = min(max(origin.x, left), right)
    nearest_y = min(max(origin.y, top), bottom)
    raw_candidates = (
        WorldPosition(nearest_x, top - offset),
        WorldPosition(nearest_x, bottom + offset),
        WorldPosition(left - offset, nearest_y),
        WorldPosition(right + offset, nearest_y),
        WorldPosition(left + (width / 2), bottom + offset),
        WorldPosition(left + (width / 2), top - offset),
        WorldPosition(left - offset, top + (height / 2)),
        WorldPosition(right + offset, top + (height / 2)),
        WorldPosition(left - offset, bottom + offset),
        WorldPosition(right + offset, bottom + offset),
        WorldPosition(left - offset, top - offset),
        WorldPosition(right + offset, top - offset),
    )
    candidates: list[WorldPosition] = []
    seen: set[tuple[int, int]] = set()
    for raw in sorted(raw_candidates, key=lambda candidate: _distance(origin, candidate)):
        clamped = clamp_unit_position_to_walkable_lane_for_height(
            raw,
            world.settings.world_height,
        )
        candidate = nearest_free_position(
            world,
            clamped,
            ignore_id=gatherer_id,
            min_distance=UNIT_COLLISION_RADIUS,
        )
        if position_blocked_by_hard_obstacle(world, candidate, ignore_id=gatherer_id):
            continue
        if resource_edge_distance(candidate, resource) > GATHER_INTERACTION_RANGE:
            continue
        key = (round(candidate.x), round(candidate.y))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def resource_interaction_position(
    world: WorldState,
    resource: ResourceNode,
    gatherer_id: EntityId | None = None,
    *,
    candidate_index: int = 0,
) -> WorldPosition:
    """Return a reachable edge position for gathering a resource."""
    candidates = resource_interaction_candidates(world, resource, gatherer_id)
    if candidates:
        if gather_slot_count_for_resource(resource) > 0:
            return candidates[int(candidate_index) % len(candidates)]
        return candidates[min(max(0, int(candidate_index)), len(candidates) - 1)]
    return nearest_free_position(
        world,
        resource.position,
        ignore_id=gatherer_id,
        min_distance=UNIT_COLLISION_RADIUS,
    )


def _cached_resource_interaction_position(
    world: WorldState,
    command: Command,
    resource: ResourceNode,
    worker_id: EntityId,
    *,
    force_refresh: bool = False,
) -> WorldPosition:
    """Return cached resource interaction position."""
    cached_id = _payload_entity_id(command, "resource_interaction_resource_id")
    cached_x = command.payload.get("resource_interaction_x")
    cached_y = command.payload.get("resource_interaction_y")
    if (
        not force_refresh
        and cached_id == resource.id
        and isinstance(cached_x, (int, float))
        and isinstance(cached_y, (int, float))
    ):
        return WorldPosition(float(cached_x), float(cached_y))
    if force_refresh:
        candidate_index = int(command.payload.get("resource_interaction_candidate_index", 0) or 0)
        candidate_index += 1
    else:
        candidate_index = int(command.payload.get("resource_interaction_candidate_index", 0) or 0)
    position = resource_interaction_position(
        world,
        resource,
        worker_id,
        candidate_index=candidate_index,
    )
    command.payload["resource_interaction_resource_id"] = resource.id.to_json()
    command.payload["resource_interaction_candidate_index"] = candidate_index
    command.payload["resource_interaction_x"] = position.x
    command.payload["resource_interaction_y"] = position.y
    return position


def is_unit_in_gather_range(
    unit: object,
    resource: ResourceNode,
    gather_range: float = GATHER_INTERACTION_RANGE,
) -> bool:
    """Return whether a worker can interact with a resource now."""
    if is_tree_resource(resource):
        return _point_in_bounds(unit.position, tree_harvest_area_bounds(resource))
    if is_mine_resource(resource):
        return _point_in_bounds(unit.position, mine_harvest_area_bounds(resource))
    return resource_edge_distance(unit.position, resource) <= gather_range


def resource_edge_distance(position: WorldPosition, resource: ResourceNode) -> float:
    """Return distance from a unit to a resource blocking edge."""
    left, top, width, height = blocking_bounds_for_entity(resource)
    right = left + width
    bottom = top + height
    dx = max(left - position.x, 0.0, position.x - right)
    dy = max(top - position.y, 0.0, position.y - bottom)
    return hypot(dx, dy)


def is_tree_resource(resource: ResourceNode) -> bool:
    """Return whether a resource node should use tree-only harvest slots."""
    return resource.resource_type == "wood" and "wood_tree" in getattr(resource, "tags", ())


def is_mine_resource(resource: ResourceNode) -> bool:
    """Return whether a resource node should use mine harvest slots."""
    return resource.resource_type in MINE_RESOURCE_TYPES


def gather_slot_count_for_resource(resource: ResourceNode) -> int:
    """Return unique gather slots supported by a resource node."""
    if is_tree_resource(resource):
        return TREE_HARVEST_MAX_SLOTS
    if is_mine_resource(resource):
        return MINE_HARVEST_MAX_SLOTS
    return 0


def tree_harvest_area_bounds(tree: ResourceNode) -> tuple[float, float, float, float]:
    """Return the front rectangle where settlers may chop a tree."""
    left, _top, width, height = blocking_bounds_for_entity(tree)
    center_x = left + (width / 2)
    blocker_bottom = _top + height
    return (
        center_x - (TREE_HARVEST_AREA_WIDTH / 2),
        blocker_bottom + TREE_HARVEST_AREA_TOP_OFFSET_FROM_BLOCKER_BOTTOM,
        TREE_HARVEST_AREA_WIDTH,
        TREE_HARVEST_AREA_HEIGHT,
    )


def tree_harvest_slot_candidates(
    world: WorldState,
    tree: ResourceNode,
    gatherer_id: EntityId | None = None,
) -> list[WorldPosition]:
    """Return stable tree-front harvesting slots, capped to eight positions."""
    if not is_tree_resource(tree):
        return []

    candidates: list[WorldPosition] = []
    seen: set[tuple[int, int]] = set()
    for raw in _raw_tree_harvest_slots(tree):
        candidate = _tree_slot_free_position(world, tree, raw, gatherer_id)
        if candidate is None:
            continue
        key = (round(candidate.x), round(candidate.y))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= TREE_HARVEST_MAX_SLOTS:
            break
    return candidates


def _raw_tree_harvest_slots(tree: ResourceNode) -> tuple[WorldPosition, ...]:
    """Return preferred visual slot centers inside the tree harvest area."""
    left, top, width, height = tree_harvest_area_bounds(tree)
    rows = (
        (0.66, (0.24, 0.42, 0.58, 0.76)),
        (0.42, (0.30, 0.45, 0.55, 0.70)),
    )
    return tuple(
        WorldPosition(left + width * x_factor, top + height * y_factor)
        for y_factor, x_factors in rows
        for x_factor in x_factors
    )


def _tree_slot_free_position(
    world: WorldState,
    tree: ResourceNode,
    desired: WorldPosition,
    gatherer_id: EntityId | None,
) -> WorldPosition | None:
    """Return a nearby free tree slot without leaving the harvest rectangle."""
    area = tree_harvest_area_bounds(tree)
    offsets = (
        (0.0, 0.0),
        (-10.0, 0.0),
        (10.0, 0.0),
        (0.0, -10.0),
        (0.0, 10.0),
        (-14.0, -8.0),
        (14.0, -8.0),
        (-14.0, 8.0),
        (14.0, 8.0),
        (-22.0, 0.0),
        (22.0, 0.0),
    )
    for dx, dy in offsets:
        raw = WorldPosition(desired.x + dx, desired.y + dy)
        candidate = clamp_unit_position_to_walkable_lane_for_height(
            raw,
            world.settings.world_height,
        )
        if not _point_in_bounds(candidate, area):
            continue
        if position_blocked_by_hard_obstacle(world, candidate, ignore_id=gatherer_id):
            continue
        if occupied_by_unit(
            world,
            candidate,
            ignore_id=gatherer_id,
            min_distance=UNIT_COLLISION_RADIUS,
        ):
            continue
        return candidate
    return None


def mine_harvest_area_bounds(mine: ResourceNode) -> tuple[float, float, float, float]:
    """Return the rectangle where settlers may mine a node."""
    left, top, width, height = blocking_bounds_for_entity(mine)
    center_x = left + (width / 2)
    center_y = top + (height / 2)
    area_width = max(MINE_HARVEST_AREA_MIN_WIDTH, width + MINE_HARVEST_AREA_HORIZONTAL_PADDING * 2)
    area_height = max(MINE_HARVEST_AREA_MIN_HEIGHT, height + MINE_HARVEST_AREA_VERTICAL_PADDING * 2)
    return (
        center_x - (area_width / 2),
        center_y - (area_height / 2),
        area_width,
        area_height,
    )


def mine_harvest_slot_candidates(
    world: WorldState,
    mine: ResourceNode,
    gatherer_id: EntityId | None = None,
) -> list[WorldPosition]:
    """Return stable mining slots around a mine resource."""
    if not is_mine_resource(mine):
        return []

    candidates: list[WorldPosition] = []
    seen: set[tuple[int, int]] = set()
    for raw in _raw_mine_harvest_slots(mine):
        candidate = _mine_slot_free_position(world, mine, raw, gatherer_id)
        if candidate is None:
            continue
        key = (round(candidate.x), round(candidate.y))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= MINE_HARVEST_MAX_SLOTS:
            break
    return candidates


def _raw_mine_harvest_slots(mine: ResourceNode) -> tuple[WorldPosition, ...]:
    """Return preferred mining slot centers inside the mine harvest area."""
    left, top, width, height = mine_harvest_area_bounds(mine)
    slots = (
        (0.18, 0.28),
        (0.18, 0.50),
        (0.18, 0.72),
        (0.82, 0.28),
        (0.82, 0.50),
        (0.82, 0.72),
        (0.38, 0.82),
        (0.62, 0.82),
    )
    return tuple(WorldPosition(left + width * x, top + height * y) for x, y in slots)


def _mine_slot_free_position(
    world: WorldState,
    mine: ResourceNode,
    desired: WorldPosition,
    gatherer_id: EntityId | None,
) -> WorldPosition | None:
    """Return a nearby free mine slot without leaving the mine harvest rectangle."""
    return _resource_slot_free_position(
        world,
        mine,
        desired,
        mine_harvest_area_bounds(mine),
        gatherer_id,
    )


def _resource_slot_free_position(
    world: WorldState,
    resource: ResourceNode,
    desired: WorldPosition,
    area: tuple[float, float, float, float],
    gatherer_id: EntityId | None,
) -> WorldPosition | None:
    """Return a nearby free slot inside a resource harvest area."""
    offsets = (
        (0.0, 0.0),
        (-10.0, 0.0),
        (10.0, 0.0),
        (0.0, -10.0),
        (0.0, 10.0),
        (-14.0, -8.0),
        (14.0, -8.0),
        (-14.0, 8.0),
        (14.0, 8.0),
        (-22.0, 0.0),
        (22.0, 0.0),
    )
    for dx, dy in offsets:
        raw = WorldPosition(desired.x + dx, desired.y + dy)
        candidate = clamp_unit_position_to_walkable_lane_for_height(
            raw,
            world.settings.world_height,
        )
        if not _point_in_bounds(candidate, area):
            continue
        if position_blocked_by_hard_obstacle(world, candidate, ignore_id=gatherer_id):
            continue
        if resource_edge_distance(candidate, resource) > GATHER_INTERACTION_RANGE:
            continue
        if occupied_by_unit(
            world,
            candidate,
            ignore_id=gatherer_id,
            min_distance=UNIT_COLLISION_RADIUS,
        ):
            continue
        return candidate
    return None


def _point_in_bounds(position: WorldPosition, bounds: tuple[float, float, float, float]) -> bool:
    """Return whether a position is inside rectangular world bounds."""
    left, top, width, height = bounds
    return left <= position.x <= left + width and top <= position.y <= top + height


def hut_deposit_position(
    world: WorldState,
    hut: Building,
    worker_id: EntityId | None = None,
) -> WorldPosition:
    """Return the interaction position used to deposit at a hut."""
    target = WorldPosition(hut.position.x, _walkable_top(world) + 14)
    return nearest_free_position(world, target, ignore_id=worker_id)


def _cached_deposit_target(
    world: WorldState,
    command: Command,
    worker: object,
    *,
    force_refresh: bool = False,
) -> tuple[Building | None, WorldPosition]:
    """Return cached deposit target."""
    cached_id = _payload_entity_id(command, "deposit_hut_id")
    cached_x = command.payload.get("deposit_hut_x")
    cached_y = command.payload.get("deposit_hut_y")
    if cached_id is not None and not force_refresh:
        cached_hut = world.entities.get(cached_id)
        if (
            isinstance(cached_hut, Building)
            and cached_hut.owner == getattr(worker, "owner", None)
            and cached_hut.complete
            and cached_hut.alive
            and bool(cached_hut.functions.get("dropoff"))
            and isinstance(cached_x, (int, float))
            and isinstance(cached_y, (int, float))
        ):
            return cached_hut, WorldPosition(float(cached_x), float(cached_y))

    hut = closest_deposit_hut(world, worker.position, worker.owner, worker.id)
    if hut is None:
        command.payload.pop("deposit_hut_id", None)
        command.payload.pop("deposit_hut_x", None)
        command.payload.pop("deposit_hut_y", None)
        return None, worker.position
    position = hut_deposit_position(world, hut, worker.id)
    command.payload["deposit_hut_id"] = hut.id.to_json()
    command.payload["deposit_hut_x"] = position.x
    command.payload["deposit_hut_y"] = position.y
    command.payload["deposit_target_checked_ms"] = world.elapsed_ms
    return hut, position


def estimated_travel_distance(
    world: WorldState,
    entity_id: EntityId | None,
    origin: WorldPosition,
    target: WorldPosition,
) -> float:
    """Estimate travel distance using current blocker detours."""
    if entity_id is None:
        return _distance(origin, target)
    waypoints = move_waypoints_around_blockers(world, entity_id, origin, target)
    if not waypoints:
        return _distance(origin, target)
    total = 0.0
    previous = origin
    for waypoint in waypoints:
        total += _distance(previous, waypoint)
        previous = waypoint
    return total


def display_resource_name(resource_type: str) -> str:
    """Return the display name for a resource type."""
    return "iron" if normalize_resource_type(resource_type) == "iron" else resource_type


def normalize_resource_type(resource_type: str) -> str:
    """Normalize resource aliases to internal resource keys."""
    return "iron" if resource_type == "ore" else resource_type


def _command_resource_type(world: WorldState, command: Command) -> str | None:
    """Return the resource type stored on a gather command."""
    value = command.payload.get("resource_type")
    if isinstance(value, str):
        return normalize_resource_type(value)
    resource = _resource_target(world, command.target_entity_id)
    return resource.resource_type if resource is not None else None


def _current_or_replacement_resource(
    world: WorldState,
    command: Command,
    resource_type: str,
    worker: object,
) -> ResourceNode | None:
    """Return the current target or a replacement resource."""
    resource = _resource_target(world, _payload_entity_id(command, "current_resource_id"))
    if resource is not None and active_resource(resource):
        if resource.resource_type != resource_type:
            return None
        return resource
    resource = _resource_target(world, command.target_entity_id)
    if resource is not None and resource.resource_type != resource_type:
        return None
    if (
        resource is not None
        and active_resource(resource)
        and resource.resource_type == resource_type
    ):
        return resource
    return None


def _damage_resource(world: WorldState, resource: ResourceNode, amount: int) -> None:
    """Apply damage to resource."""
    resource.hp = max(0, resource.hp - max(0, int(amount)))
    resource.amount_remaining = min(resource.amount_remaining, resource.hp)
    if resource.hp > 0:
        return
    resource.amount_remaining = 0
    resource.state = "destroying"
    resource.destruction_remaining_ms = RESOURCE_DESTRUCTION_MS
    world.unindex_resource_node(resource.id)
    for queue in world.command_queues.values():
        for command in queue.commands:
            if (
                command.type == "gather"
                and _payload_entity_id(command, "current_resource_id") == resource.id
            ):
                command.payload.pop("current_resource_id", None)


def _insert_move_before_gather(
    queue: CommandQueue,
    worker_id: EntityId,
    target_pos: WorldPosition,
    command: Command,
    move_key: str,
) -> None:
    """Insert move before gather."""
    command.payload["pending_move_key"] = move_key
    move = make_command(
        "move",
        [worker_id],
        target_pos=target_pos,
        gather_move=True,
    )
    queue.commands[0:1] = [move, command]


def _pending_move_failed(command: Command, move_key: str) -> bool:
    """Return whether a queued move failed for the expected target."""
    return command.payload.get("pending_move_key") == move_key


def _move_key(kind: str, entity_id: EntityId) -> str:
    """Move key."""
    return f"{kind}:{int(entity_id)}"


def _resource_target(world: WorldState, target_id: EntityId | None) -> ResourceNode | None:
    """Return the position used for resource target."""
    if target_id is None:
        return None
    target = world.entities.get(target_id)
    return target if isinstance(target, ResourceNode) else None


def _gather_target_type_invalid(
    world: WorldState,
    command: Command,
    resource_type: str,
) -> bool:
    """Return the position used for gather target type invalid."""
    for target_id in (
        _payload_entity_id(command, "current_resource_id"),
        command.target_entity_id,
    ):
        resource = _resource_target(world, target_id)
        if resource is not None and resource.resource_type != resource_type:
            return True
    return False


def _cached_resource_ids(
    world: WorldState,
    resource_type: str | None,
) -> list[EntityId] | None:
    """Return cached resource ids."""
    cache = getattr(world, "resource_nodes_by_type", None)
    if cache is None:
        return None
    if resource_type is not None:
        return list(cache.get(normalize_resource_type(resource_type), []))
    ids: list[EntityId] = []
    seen: set[EntityId] = set()
    for bucket in cache.values():
        for entity_id in bucket:
            if entity_id in seen:
                continue
            seen.add(entity_id)
            ids.append(entity_id)
    return ids


def _active_gather_load(world: WorldState, resource_type: str) -> dict[EntityId, int]:
    """Return the active gather load."""
    normalized = normalize_resource_type(resource_type)
    counts: dict[EntityId, int] = {
        node.id: 0 for node in cached_active_resource_nodes(world, normalized)
    }
    for queue in world.command_queues.values():
        for command in queue.commands:
            if command.type != "gather":
                continue
            target = _resource_target(world, _payload_entity_id(command, "current_resource_id"))
            if target is None:
                target = _resource_target(world, command.target_entity_id)
            if (
                target is None
                or not active_resource(target)
                or target.resource_type != normalized
                or target.id not in counts
            ):
                continue
            counts[target.id] += 1
    return counts


def _next_gather_slot_index(world: WorldState, resource: ResourceNode) -> int:
    """Return the next stable tree slot index from current gather load."""
    return _slot_index_for_load(_active_gather_load(world, resource.resource_type), resource)


def _slot_index_for_load(load_by_resource: dict[EntityId, int], resource: ResourceNode) -> int:
    """Return a slotted-resource index from gather load, or zero for simple resources."""
    slot_count = gather_slot_count_for_resource(resource)
    if slot_count <= 0:
        return 0
    return load_by_resource.get(resource.id, 0) % slot_count


def _cheap_distance_sq(first: WorldPosition, second: WorldPosition) -> float:
    """Return the distance used for cheap distance sq."""
    dx = first.x - second.x
    dy = first.y - second.y
    return (dx * dx) + (dy * dy)


def _debug_log_gather_performance(stats: GatherPerformanceCounters) -> None:
    """Print gather performance counters when debugging is enabled."""
    print(
        "gather_perf "
        f"jobs={stats.path_jobs_processed} "
        f"searches={stats.resource_searches} "
        f"candidates={stats.resource_candidates_checked} "
        f"paths={stats.full_path_calculations}"
    )


def _clear_gather_job(worker: object, queue: CommandQueue) -> None:
    """Clear gather job."""
    worker.carry_type = None
    worker.carry_amount = 0
    queue.pop_next()
    _set_state(worker, GATHER_STATE_IDLE)


def _face_worker_toward_resource(worker: object, resource: ResourceNode) -> None:
    """Point a gathering settler's tool toward the active resource."""
    if not hasattr(worker, "facing_x"):
        return
    dx = resource.position.x - worker.position.x
    dy = resource.position.y - worker.position.y
    distance = hypot(dx, dy)
    if distance <= 0.0001:
        return
    worker.facing_x = dx / distance
    worker.facing_y = dy / distance


def _within(first: WorldPosition, second: WorldPosition, radius: float) -> bool:
    """Return whether two positions are within a radius."""
    return _distance(first, second) <= radius


def _entity_position(world: WorldState, entity_id: EntityId | None) -> WorldPosition | None:
    """Return the position used for entity position."""
    if entity_id is None:
        return None
    entity = world.entities.get(entity_id)
    return entity.position if entity is not None else None


def _enemy_can_hit_position(
    world: WorldState,
    position: WorldPosition,
    friendly_owner: str,
) -> bool:
    """Return the position used for enemy can hit position."""
    for entity in _entities_near_position(world, position, 512.0):
        if not getattr(entity, "alive", False):
            continue
        owner = getattr(entity, "owner", "neutral")
        if owner in {friendly_owner, "neutral"}:
            continue
        if not _has_attack_threat(entity):
            continue
        if _distance(entity.position, position) <= _threat_radius(entity):
            return True
    return False


def _has_attack_threat(entity: object) -> bool:
    """Return whether attack threat exists."""
    return int(getattr(entity, "damage", 0)) > 0 and float(getattr(entity, "attack_range", 0)) > 0


def _threat_radius(entity: object) -> float:
    """Return the range value used for threat radius."""
    attack_range = max(0.0, float(getattr(entity, "attack_range", 0)))
    if attack_range <= 55:
        return max(160.0, attack_range + 90.0)
    return attack_range + 24.0


def _walkable_top(world: WorldState) -> float:
    """Return the top y bound of the unit walkable lane."""
    return terrain_layout_for_height(world.settings.world_height).unit_walkable_top_y


def _walkable_bottom(world: WorldState) -> float:
    """Return the bottom y bound of the unit walkable lane."""
    return terrain_layout_for_height(world.settings.world_height).unit_walkable_bottom_y


def _resource_spawn_position_valid(
    world: WorldState,
    position: WorldPosition,
    spec: ResourceNodeSpec,
) -> bool:
    """Return the position used for resource spawn position valid."""
    bounds = spec.blocking_footprint.bounds_at(position)
    if position_blocked_by_hard_obstacle(world, position):
        return False
    if occupied_by_unit(world, position, min_distance=70):
        return False
    query_bounds = _inflate_bounds(bounds, 96.0)
    for entity_id in world.spatial_hash.query(query_bounds):
        entity = world.entities.get(entity_id)
        if entity is None:
            continue
        if not getattr(entity, "alive", False):
            continue
        if _bounds_intersect(bounds, blocking_bounds_for_entity(entity)):
            return False
    return True


def _entities_near_position(
    world: WorldState,
    position: WorldPosition,
    radius: float,
) -> list[object]:
    """Return the position used for entities near position."""
    bounds = (
        position.x - radius,
        position.y - radius,
        radius * 2,
        radius * 2,
    )
    entities: list[object] = []
    for entity_id in world.spatial_hash.query(bounds):
        entity = world.entities.get(entity_id)
        if entity is not None:
            entities.append(entity)
    return entities



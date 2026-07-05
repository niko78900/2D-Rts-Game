"""Resource gathering, deposit, safety, and respawn systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Any

from house_of_wolves.core.contracts import Command, CommandQueue, EntityId, Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode, resource_hp_for_type
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.pathing import move_waypoints_around_blockers
from house_of_wolves.world.collision import (
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
RESOURCE_DESTRUCTION_MS = 1500
RESPAWN_MIN_MS = 60_000
RESPAWN_MAX_MS = 180_000
MAX_ACTIVE_RESOURCE_NODES = 15
MAX_ACTIVE_STONE_NODES = 5
MAX_ACTIVE_IRON_NODES = 5
MAX_ACTIVE_GOLD_NODES = 5
AUTO_DISTRIBUTION_LOAD_PENALTY = 260.0

GATHER_STATE_MOVING_TO_RESOURCE = "moving_to_resource"
GATHER_STATE_GATHERING = "gathering"
GATHER_STATE_CARRYING_RESOURCE = "carrying_resource"
GATHER_STATE_MOVING_TO_HUT = "moving_to_hut"
GATHER_STATE_DEPOSITING = "depositing"
GATHER_STATE_RETURNING_TO_RESOURCE = "returning_to_resource"
GATHER_STATE_IDLE = "idle"
GATHER_STATE_DEFENDING = "defending"

RESOURCE_NODE_SPECS = {
    "wood": {
        "tags": ("resource", "wood_tree", "selectable"),
        "footprint": Footprint(82, 126),
        "blocking_footprint": Footprint(42, 92),
        "gather_time_ms": 900,
        "depleted_replacement": "tree_stump",
    },
    "stone": {
        "tags": ("resource", "stone_outcrop", "selectable"),
        "footprint": Footprint(118, 74),
        "blocking_footprint": Footprint(104, 54),
        "gather_time_ms": 1200,
        "depleted_replacement": "stone_rubble",
    },
    "iron": {
        "tags": ("resource", "iron_deposit", "selectable"),
        "footprint": Footprint(118, 74),
        "blocking_footprint": Footprint(104, 54),
        "gather_time_ms": 1200,
        "depleted_replacement": "empty_iron_deposit",
    },
    "gold": {
        "tags": ("resource", "gold_mine", "selectable"),
        "footprint": Footprint(132, 86),
        "blocking_footprint": Footprint(124, 64),
        "gather_time_ms": 1200,
        "depleted_replacement": "gold_mine_empty",
    },
}


@dataclass(slots=True)
class ResourceWallet:
    amounts: dict[str, int] = field(default_factory=lambda: {key: 0 for key in RESOURCE_TYPES})

    def can_afford(self, cost: dict[str, int]) -> bool:
        return all(self.amounts.get(resource, 0) >= amount for resource, amount in cost.items())

    def spend(self, cost: dict[str, int]) -> bool:
        if not self.can_afford(cost):
            return False
        for resource, amount in cost.items():
            self.amounts[resource] = self.amounts.get(resource, 0) - amount
        return True


@dataclass(slots=True)
class ResourceRespawn:
    resource_type: str
    due_ms: int


@dataclass(slots=True)
class EconomySystem:
    gather_interaction_range: float = 76.0
    deposit_interaction_range: float = 140.0
    gather_swing_ms: int = GATHER_SWING_MS
    respawn_min_ms: int = RESPAWN_MIN_MS
    respawn_max_ms: int = RESPAWN_MAX_MS
    max_total_nodes: int = MAX_ACTIVE_RESOURCE_NODES
    max_nodes_by_type: dict[str, int] = field(
        default_factory=lambda: {
            "stone": MAX_ACTIVE_STONE_NODES,
            "iron": MAX_ACTIVE_IRON_NODES,
            "gold": MAX_ACTIVE_GOLD_NODES,
        }
    )
    include_wood_in_total_cap: bool = True
    respawns: list[ResourceRespawn] = field(default_factory=list)

    def update(self, world: WorldState, dt_ms: int) -> None:
        self._update_resource_lifecycle(world, dt_ms)
        self._update_respawns(world)
        for worker_id, queue in list(world.command_queues.items()):
            self._update_worker(world, worker_id, queue, dt_ms)

    def _update_worker(
        self,
        world: WorldState,
        worker_id: EntityId,
        queue: CommandQueue,
        dt_ms: int,
    ) -> None:
        worker = world.entities.get(worker_id)
        if not _is_settler(worker):
            return
        command = queue.peek()
        if command is None or command.type != "gather":
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

        if int(getattr(worker, "carry_amount", 0)) > 0:
            self._advance_deposit(world, worker, queue, command, resource_type)
            return

        resource = _current_or_replacement_resource(world, command, resource_type, worker)
        if resource is None:
            _clear_gather_job(worker, queue)
            return
        command.payload["current_resource_id"] = resource.id.to_json()
        command.payload["phase"] = GATHER_STATE_MOVING_TO_RESOURCE

        interaction_point = resource_interaction_position(world, resource, worker.id)
        if not _within(worker.position, interaction_point, self.gather_interaction_range):
            if _pending_move_failed(command, _move_key("resource", resource.id)):
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
        _set_state(worker, GATHER_STATE_GATHERING)
        elapsed = int(command.payload.get("swing_elapsed_ms", 0)) + max(0, int(dt_ms))
        swings = int(command.payload.get("successful_swings", 0))
        while elapsed >= self.gather_swing_ms and swings < GATHER_SWINGS_PER_LOAD:
            elapsed -= self.gather_swing_ms
            if not active_resource(resource):
                replacement = find_nearest_resource_node(
                    world,
                    worker.id,
                    worker.position,
                    resource_type,
                    safe=False,
                )
                if replacement is None:
                    command.payload["successful_swings"] = swings
                    command.payload["swing_elapsed_ms"] = elapsed
                    _clear_gather_job(worker, queue)
                    return
                resource = replacement
                command.payload["current_resource_id"] = resource.id.to_json()
                interaction_point = resource_interaction_position(world, resource, worker.id)
                _insert_move_before_gather(
                    queue,
                    worker.id,
                    interaction_point,
                    command,
                    _move_key("resource", resource.id),
                )
                _set_state(worker, GATHER_STATE_RETURNING_TO_RESOURCE)
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
        hut = closest_deposit_hut(world, worker.position, worker.owner, worker.id)
        if hut is None:
            world.notify("Needs hut to deposit.")
            _clear_gather_job(worker, queue)
            return
        deposit_point = hut_deposit_position(world, hut, worker.id)
        if not _within(worker.position, deposit_point, self.deposit_interaction_range):
            if _pending_move_failed(command, _move_key("hut", hut.id)):
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
            _clear_gather_job(worker, queue)
            return
        command.payload["current_resource_id"] = resource.id.to_json()
        interaction_point = resource_interaction_position(world, resource, worker.id)
        _insert_move_before_gather(
            queue,
            worker.id,
            interaction_point,
            command,
            _move_key("resource", resource.id),
        )
        _set_state(worker, GATHER_STATE_RETURNING_TO_RESOURCE)

    def _update_resource_lifecycle(self, world: WorldState, dt_ms: int) -> None:
        for resource in list(world.entities.values()):
            if not isinstance(resource, ResourceNode) or resource.state != "destroying":
                continue
            resource.destruction_remaining_ms -= max(0, int(dt_ms))
            if resource.destruction_remaining_ms > 0:
                continue
            resource_type = resource.resource_type
            respawn_enabled = resource.respawn_enabled
            world.remove_entity(resource.id)
            if respawn_enabled:
                self._schedule_respawn(world, resource_type)

    def _schedule_respawn(self, world: WorldState, resource_type: str) -> None:
        delay = world.rng.randint(self.respawn_min_ms, self.respawn_max_ms)
        self.respawns.append(ResourceRespawn(resource_type, world.elapsed_ms + delay))

    def _update_respawns(self, world: WorldState) -> None:
        pending: list[ResourceRespawn] = []
        for respawn in self.respawns:
            if respawn.due_ms > world.elapsed_ms:
                pending.append(respawn)
                continue
            if not self._can_spawn_resource(world, respawn.resource_type):
                respawn.due_ms = world.elapsed_ms + 5000
                pending.append(respawn)
                continue
            if not self._spawn_resource(world, respawn.resource_type):
                respawn.due_ms = world.elapsed_ms + 5000
                pending.append(respawn)
        self.respawns = pending

    def _can_spawn_resource(self, world: WorldState, resource_type: str) -> bool:
        if (
            (self.include_wood_in_total_cap or resource_type != "wood")
            and len(active_resource_nodes(world)) >= self.max_total_nodes
        ):
            return False
        cap = self.max_nodes_by_type.get(resource_type)
        return not (
            cap is not None
            and len(active_resource_nodes(world, resource_type)) >= cap
        )

    def _spawn_resource(self, world: WorldState, resource_type: str) -> bool:
        spec = RESOURCE_NODE_SPECS.get(resource_type)
        if spec is None:
            return False
        for _ in range(80):
            x = world.rng.uniform(320, max(321, world.settings.world_width - 320))
            y = world.rng.uniform(
                _walkable_top(world) + 36,
                max(_walkable_top(world) + 37, _walkable_bottom(world) - 56),
            )
            position = WorldPosition(x, y)
            if not _resource_spawn_position_valid(world, position, spec):
                continue
            hp = resource_hp_for_type(resource_type)
            node = ResourceNode(
                id=world.allocate_entity_id(),
                owner="neutral",
                position=position,
                footprint=spec["footprint"],
                hp=hp,
                max_hp=hp,
                tags=spec["tags"],
                resource_type=resource_type,
                amount_remaining=hp,
                max_amount_remaining=hp,
                gather_time_ms=int(spec["gather_time_ms"]),
                depleted_replacement=str(spec["depleted_replacement"]),
                blocking_footprint=spec["blocking_footprint"],
            )
            world.add_entity(node)
            return True
        return False


def completed_deposit_huts(world: WorldState, owner: str = "frontier") -> list[Building]:
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
    if not completed_deposit_huts(world, owner):
        return {}, "Needs hut to deposit."

    safe_nodes = [
        node for node in active_resource_nodes(world, resource_type)
        if resource_node_safe_for_auto_gather(world, node, owner)
    ]
    if not safe_nodes:
        return {}, f"No safe {display_resource_name(resource_type).lower()} source found."

    assigned_counts: dict[EntityId, int] = {node.id: 0 for node in safe_nodes}
    assignments: dict[EntityId, ResourceNode] = {}
    for gatherer_id in gatherer_ids:
        gatherer = world.entities.get(gatherer_id)
        if gatherer is None:
            continue
        node = min(
            safe_nodes,
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
    nodes = active_resource_nodes(world, resource_type)
    if safe:
        nodes = [
            node for node in nodes
            if resource_node_safe_for_auto_gather(world, node, owner)
        ]
    if not nodes:
        return None
    return min(
        nodes,
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
    return [
        entity
        for entity in world.entities.values()
        if isinstance(entity, ResourceNode)
        and active_resource(entity)
        and (resource_type is None or entity.resource_type == resource_type)
    ]


def active_resource(resource: ResourceNode) -> bool:
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
    interaction = resource_interaction_position(world, resource)
    return not _enemy_can_hit_position(world, interaction, owner)


def resource_interaction_position(
    world: WorldState,
    resource: ResourceNode,
    gatherer_id: EntityId | None = None,
) -> WorldPosition:
    left, top, width, height = blocking_bounds_for_entity(resource)
    candidates = (
        WorldPosition(left + (width / 2), top + height + 28),
        WorldPosition(left + (width / 2), top - 18),
        WorldPosition(left - 26, top + (height / 2)),
        WorldPosition(left + width + 26, top + (height / 2)),
    )
    origin = _entity_position(world, gatherer_id) or resource.position
    ordered = sorted(candidates, key=lambda candidate: _distance(origin, candidate))
    for candidate in ordered:
        clamped = clamp_unit_position_to_walkable_lane_for_height(
            candidate,
            world.settings.world_height,
        )
        return nearest_free_position(world, clamped, ignore_id=gatherer_id)
    return nearest_free_position(world, resource.position, ignore_id=gatherer_id)


def hut_deposit_position(
    world: WorldState,
    hut: Building,
    worker_id: EntityId | None = None,
) -> WorldPosition:
    target = WorldPosition(hut.position.x, _walkable_top(world) + 14)
    return nearest_free_position(world, target, ignore_id=worker_id)


def estimated_travel_distance(
    world: WorldState,
    entity_id: EntityId | None,
    origin: WorldPosition,
    target: WorldPosition,
) -> float:
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
    return "ore" if resource_type == "iron" else resource_type


def _command_resource_type(world: WorldState, command: Command) -> str | None:
    value = command.payload.get("resource_type")
    if isinstance(value, str):
        return value
    resource = _resource_target(world, command.target_entity_id)
    return resource.resource_type if resource is not None else None


def _current_or_replacement_resource(
    world: WorldState,
    command: Command,
    resource_type: str,
    worker: object,
) -> ResourceNode | None:
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
    return find_nearest_resource_node(
        world,
        worker.id,
        worker.position,
        resource_type,
        safe=False,
        owner=worker.owner,
    )


def _damage_resource(world: WorldState, resource: ResourceNode, amount: int) -> None:
    resource.hp = max(0, resource.hp - max(0, int(amount)))
    resource.amount_remaining = min(resource.amount_remaining, resource.hp)
    if resource.hp > 0:
        return
    resource.amount_remaining = 0
    resource.state = "destroying"
    resource.destruction_remaining_ms = RESOURCE_DESTRUCTION_MS
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
    command.payload["pending_move_key"] = move_key
    move = make_command(
        "move",
        [worker_id],
        target_pos=target_pos,
        gather_move=True,
    )
    queue.commands[0:1] = [move, command]


def _pending_move_failed(command: Command, move_key: str) -> bool:
    return command.payload.get("pending_move_key") == move_key


def _move_key(kind: str, entity_id: EntityId) -> str:
    return f"{kind}:{int(entity_id)}"


def _resource_target(world: WorldState, target_id: EntityId | None) -> ResourceNode | None:
    if target_id is None:
        return None
    target = world.entities.get(target_id)
    return target if isinstance(target, ResourceNode) else None


def _payload_entity_id(command: Command, key: str) -> EntityId | None:
    value = command.payload.get(key)
    if value is None:
        return None
    return EntityId(int(value))


def _clear_gather_job(worker: object, queue: CommandQueue) -> None:
    worker.carry_type = None
    worker.carry_amount = 0
    queue.pop_next()
    _set_state(worker, GATHER_STATE_IDLE)


def _is_settler(entity: object | None) -> bool:
    return (
        entity is not None
        and getattr(entity, "alive", False)
        and "settler" in getattr(entity, "tags", ())
    )


def _set_state(entity: object, state: str) -> None:
    if hasattr(entity, "state"):
        entity.state = state


def _within(first: WorldPosition, second: WorldPosition, radius: float) -> bool:
    return _distance(first, second) <= radius


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def _entity_position(world: WorldState, entity_id: EntityId | None) -> WorldPosition | None:
    if entity_id is None:
        return None
    entity = world.entities.get(entity_id)
    return entity.position if entity is not None else None


def _enemy_can_hit_position(
    world: WorldState,
    position: WorldPosition,
    friendly_owner: str,
) -> bool:
    for entity in world.entities.values():
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
    return int(getattr(entity, "damage", 0)) > 0 and float(getattr(entity, "attack_range", 0)) > 0


def _threat_radius(entity: object) -> float:
    attack_range = max(0.0, float(getattr(entity, "attack_range", 0)))
    if attack_range <= 55:
        return max(160.0, attack_range + 90.0)
    return attack_range + 24.0


def _walkable_top(world: WorldState) -> float:
    return terrain_layout_for_height(world.settings.world_height).unit_walkable_top_y


def _walkable_bottom(world: WorldState) -> float:
    return terrain_layout_for_height(world.settings.world_height).unit_walkable_bottom_y


def _resource_spawn_position_valid(
    world: WorldState,
    position: WorldPosition,
    spec: dict[str, Any],
) -> bool:
    blocking_footprint = spec["blocking_footprint"]
    bounds = blocking_footprint.bounds_at(position)
    if position_blocked_by_hard_obstacle(world, position):
        return False
    if occupied_by_unit(world, position, min_distance=70):
        return False
    for entity in world.entities.values():
        if not getattr(entity, "alive", False):
            continue
        if _bounds_intersect(bounds, blocking_bounds_for_entity(entity)):
            return False
    return True


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

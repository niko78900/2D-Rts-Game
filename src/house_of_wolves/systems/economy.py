"""Economy system shell."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

from house_of_wolves.core.contracts import CommandQueue, EntityId, WorldPosition
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.world.world import WorldState

RESOURCE_TYPES = ("wood", "food", "stone", "iron", "gold")
GATHER_CHUNK_SIZE = 10


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
class EconomySystem:
    gather_interaction_range: float = 95.0

    def update(self, world: WorldState, dt_ms: int) -> None:
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
        if (
            worker is None
            or not getattr(worker, "alive", False)
            or "settler" not in getattr(worker, "tags", ())
        ):
            return
        command = queue.peek()
        if command is None or command.type != "gather":
            return

        resource = _resource_target(world, command.target_entity_id)
        if resource is None or resource.amount_remaining <= 0:
            queue.pop_next()
            _set_state(worker, "idle")
            return

        expected_type = command.payload.get("resource_type")
        if isinstance(expected_type, str) and expected_type != resource.resource_type:
            queue.pop_next()
            _set_state(worker, "idle")
            return

        if _distance(worker.position, _interaction_position(command.target_pos, resource)) > (
            self.gather_interaction_range
        ):
            _set_state(worker, "moving")
            return

        _set_state(worker, "gathering")
        elapsed = int(command.payload.get("gather_elapsed_ms", 0)) + max(0, int(dt_ms))
        gather_time = max(1, int(getattr(resource, "gather_time_ms", 1000)))
        while elapsed >= gather_time and resource.amount_remaining > 0:
            elapsed -= gather_time
            amount = min(GATHER_CHUNK_SIZE, resource.amount_remaining)
            resource.amount_remaining -= amount
            world.resources[resource.resource_type] = (
                world.resources.get(resource.resource_type, 0) + amount
            )

        command.payload["gather_elapsed_ms"] = elapsed
        if resource.amount_remaining <= 0:
            queue.pop_next()
            _set_state(worker, "idle")


def _resource_target(world: WorldState, target_id: EntityId | None) -> ResourceNode | None:
    if target_id is None:
        return None
    target = world.entities.get(target_id)
    return target if isinstance(target, ResourceNode) else None


def _interaction_position(
    target_pos: WorldPosition | None,
    resource: ResourceNode,
) -> WorldPosition:
    return target_pos if target_pos is not None else resource.position


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def _set_state(entity: object, state: str) -> None:
    if hasattr(entity, "state"):
        entity.state = state

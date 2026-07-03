"""Straight-line movement system for the first playable slice."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.world.world import WorldState


@dataclass(slots=True)
class MovementSystem:
    """Consumes move commands and advances movable units toward their destination."""

    arrival_radius: float = 4.0

    def update(self, world: WorldState, dt_ms: int) -> None:
        world.elapsed_ms += dt_ms
        for entity_id in list(world.command_queues):
            self._update_entity(world, entity_id, dt_ms)

    def _update_entity(self, world: WorldState, entity_id: EntityId, dt_ms: int) -> None:
        entity = world.entities.get(entity_id)
        if entity is None or not _is_movable(entity):
            return

        queue = world.command_queues.get(entity_id)
        command = queue.peek() if queue is not None else None
        if command is None:
            if hasattr(entity, "state"):
                entity.state = "idle"
            return
        if command.type != "move":
            return
        if command.target_pos is None:
            queue.pop_next()
            return

        target = command.target_pos
        dx = target.x - entity.position.x
        dy = target.y - entity.position.y
        distance = hypot(dx, dy)
        if distance <= self.arrival_radius:
            world.update_entity_position(entity_id, target)
            queue.pop_next()
            if hasattr(entity, "state"):
                entity.state = "idle"
            return

        speed = max(0.0, float(getattr(entity, "speed", 0.0)))
        step = speed * (dt_ms / 1000)
        if step <= 0:
            return
        if step >= distance:
            new_position = target
            queue.pop_next()
            if hasattr(entity, "state"):
                entity.state = "idle"
        else:
            ratio = step / distance
            new_position = WorldPosition(
                entity.position.x + dx * ratio,
                entity.position.y + dy * ratio,
            )
            if hasattr(entity, "state"):
                entity.state = "moving"
        world.update_entity_position(entity_id, new_position)


def _is_movable(entity: object) -> bool:
    return (
        getattr(entity, "alive", False)
        and getattr(entity, "owner", None) == "frontier"
        and "movable" in getattr(entity, "tags", ())
    )

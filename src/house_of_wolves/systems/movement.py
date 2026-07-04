"""Straight-line movement system for the first playable slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

from house_of_wolves.core.contracts import Command, CommandQueue, EntityId, WorldPosition
from house_of_wolves.world.collision import (
    MAX_COLLISION_ADJUSTMENT,
    MAX_SHOVE_PUSH,
    UNIT_COLLISION_RADIUS,
    occupied_by_unit,
    resolve_unit_position,
    separate_overlapping_units,
    shove_units_from_movement,
)
from house_of_wolves.world.world import WorldState


@dataclass(slots=True)
class MovementProgress:
    """Per-command progress used to abandon unreachable move targets."""

    command_token: int
    best_distance: float
    stagnant_ms: int = 0


@dataclass(slots=True)
class MovementSystem:
    """Consumes move commands and advances movable units toward their destination."""

    arrival_radius: float = 4.0
    shared_destination_radius: float = UNIT_COLLISION_RADIUS * 1.5
    collision_slide_px: float = MAX_COLLISION_ADJUSTMENT
    max_shove_px: float = MAX_SHOVE_PUSH
    unreachable_timeout_ms: int = 1500
    min_progress_px: float = 0.75
    _progress_by_entity: dict[EntityId, MovementProgress] = field(default_factory=dict)

    def update(self, world: WorldState, dt_ms: int) -> None:
        world.elapsed_ms += dt_ms
        for entity_id in list(world.command_queues):
            self._update_entity(world, entity_id, dt_ms)
        separate_overlapping_units(world)

    def _update_entity(self, world: WorldState, entity_id: EntityId, dt_ms: int) -> None:
        entity = world.entities.get(entity_id)
        if entity is None or not _is_movable(entity):
            return

        queue = world.command_queues.get(entity_id)
        command = queue.peek() if queue is not None else None
        if command is None:
            self._clear_progress(entity_id)
            if hasattr(entity, "state"):
                entity.state = "idle"
            return
        if command.type != "move":
            self._clear_progress(entity_id)
            return
        if command.target_pos is None:
            queue.pop_next()
            self._clear_progress(entity_id)
            return

        target = command.target_pos
        progress = self._progress_for(entity_id, command, target, entity.position)
        dx = target.x - entity.position.x
        dy = target.y - entity.position.y
        distance = hypot(dx, dy)
        if distance <= self.arrival_radius:
            world.update_entity_position(
                entity_id,
                resolve_unit_position(
                    world,
                    entity_id,
                    target,
                    current=entity.position,
                    max_adjustment=self.collision_slide_px,
                ),
            )
            self._finish_move(entity_id, queue)
            if hasattr(entity, "state"):
                entity.state = "idle"
            return
        if self._arrived_near_shared_destination(world, entity_id, target, distance):
            self._finish_move(entity_id, queue)
            if hasattr(entity, "state"):
                entity.state = "idle"
            return

        speed = max(0.0, float(getattr(entity, "speed", 0.0)))
        step = speed * (dt_ms / 1000)
        if step <= 0:
            self._stop_if_unreachable(world, entity_id, queue, target, progress, dt_ms)
            return
        finish_after_move = False
        if step >= distance:
            new_position = target
            finish_after_move = True
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
        shove_units_from_movement(
            world,
            entity_id,
            entity.position,
            new_position,
            max_push=min(self.max_shove_px, max(step * 0.55, 0.0)),
        )
        world.update_entity_position(
            entity_id,
            resolve_unit_position(
                world,
                entity_id,
                new_position,
                current=entity.position,
                max_adjustment=self.collision_slide_px,
            ),
        )
        if finish_after_move:
            self._finish_move(entity_id, queue)
        else:
            self._stop_if_unreachable(world, entity_id, queue, target, progress, dt_ms)

    def _arrived_near_shared_destination(
        self,
        world: WorldState,
        entity_id: EntityId,
        target: WorldPosition,
        distance: float,
    ) -> bool:
        return distance <= self.shared_destination_radius and occupied_by_unit(
            world,
            target,
            ignore_id=entity_id,
        )

    def _progress_for(
        self,
        entity_id: EntityId,
        command: Command,
        target: WorldPosition,
        position: WorldPosition,
    ) -> MovementProgress:
        command_token = id(command)
        progress = self._progress_by_entity.get(entity_id)
        if progress is None or progress.command_token != command_token:
            progress = MovementProgress(
                command_token=command_token,
                best_distance=_distance(position, target),
            )
            self._progress_by_entity[entity_id] = progress
        return progress

    def _stop_if_unreachable(
        self,
        world: WorldState,
        entity_id: EntityId,
        queue: CommandQueue,
        target: WorldPosition,
        progress: MovementProgress,
        dt_ms: int,
    ) -> bool:
        entity = world.entities.get(entity_id)
        if entity is None:
            self._clear_progress(entity_id)
            return False
        distance = _distance(entity.position, target)
        if distance < progress.best_distance - self.min_progress_px:
            progress.best_distance = distance
            progress.stagnant_ms = 0
            return False

        progress.stagnant_ms += dt_ms
        if progress.stagnant_ms < self.unreachable_timeout_ms:
            return False

        self._finish_move(entity_id, queue)
        if hasattr(entity, "state"):
            entity.state = "idle"
        return True

    def _finish_move(self, entity_id: EntityId, queue: CommandQueue) -> None:
        queue.pop_next()
        self._clear_progress(entity_id)

    def _clear_progress(self, entity_id: EntityId) -> None:
        self._progress_by_entity.pop(entity_id, None)


def _is_movable(entity: object) -> bool:
    return (
        getattr(entity, "alive", False)
        and getattr(entity, "owner", None) == "frontier"
        and "movable" in getattr(entity, "tags", ())
    )


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)

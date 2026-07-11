"""Straight-line movement system for the first playable slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

from house_of_wolves.core.contracts import Command, CommandQueue, EntityId, WorldPosition
from house_of_wolves.core.geometry import distance as _distance
from house_of_wolves.systems.command_payloads import payload_entity_id as _payload_entity_id
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.pathing import move_waypoints_around_blockers
from house_of_wolves.world.collision import (
    MAX_COLLISION_ADJUSTMENT,
    MAX_SHOVE_PUSH,
    UNIT_COLLISION_RADIUS,
    is_unit,
    occupied_by_unit,
    resolve_unit_position,
    separate_overlapping_units,
    shove_units_from_movement,
)
from house_of_wolves.world.terrain import clamp_unit_position_to_walkable_lane_for_height
from house_of_wolves.world.world import WorldState


@dataclass(slots=True)
class MovementProgress:
    """Per-command progress used to abandon unreachable move targets."""

    command_token: int
    best_distance: float
    stagnant_ms: int = 0
    friendly_collision_anchor: WorldPosition | None = None
    friendly_collision_count: int = 0
    friendly_ghost_until_ms: int = 0
    friendly_collision_check_elapsed_ms: int = 10_000


@dataclass(slots=True)
class MovementSystem:
    """Consumes move commands and advances movable units toward their destination."""

    arrival_radius: float = 4.0
    group_arrival_radius: float = 16.0
    detour_arrival_radius: float = 12.0
    shared_destination_radius: float = UNIT_COLLISION_RADIUS * 1.5
    collision_slide_px: float = MAX_COLLISION_ADJUSTMENT
    max_shove_px: float = MAX_SHOVE_PUSH
    unreachable_timeout_ms: int = 1500
    min_progress_px: float = 0.75
    friendly_ghost_collision_limit: int = 10
    friendly_ghost_area_px: float = 12.0
    friendly_ghost_reset_distance_px: float = 24.0
    friendly_ghost_duration_ms: int = 750
    friendly_ghost_check_interval_ms: int = 48
    shove_interval_ms: int = 48
    separation_interval_ms: int = 48
    max_path_replans: int = 3
    _progress_by_entity: dict[EntityId, MovementProgress] = field(default_factory=dict)
    _last_shove_ms_by_entity: dict[EntityId, int] = field(default_factory=dict)
    _separation_elapsed_ms: int = 10_000

    def update(self, world: WorldState, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
        world.elapsed_ms += dt_ms
        active_ghost_ids = self._active_friendly_ghost_ids(world)
        for entity_id in list(getattr(world, "unit_ids", world.command_queues.keys())):
            self._update_entity(world, entity_id, dt_ms, active_ghost_ids)
        self._separation_elapsed_ms += max(0, int(dt_ms))
        if self._separation_elapsed_ms >= self.separation_interval_ms:
            separate_overlapping_units(
                world,
                friendly_ghost_ids=self._active_friendly_ghost_ids(world),
            )
            self._separation_elapsed_ms = 0

    def _update_entity(
        self,
        world: WorldState,
        entity_id: EntityId,
        dt_ms: int,
        active_ghost_ids: set[EntityId],
    ) -> None:
        """Advance entity for the current frame."""
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
        command = self._plan_path_if_needed(world, entity_id, queue, command)
        if command is None or command.target_pos is None:
            return
        if _movement_paused_for_attack(command, world.elapsed_ms):
            if hasattr(entity, "state") and entity.state not in {
                "attack_windup",
                "attack_cooldown",
            }:
                entity.state = "attacking"
            return

        target, chasing_attack_target = _movement_target_for_command(world, command)
        progress = self._progress_for(entity_id, command, target, entity.position)
        dx = target.x - entity.position.x
        dy = target.y - entity.position.y
        distance = hypot(dx, dy)
        if distance > 0.0001 and hasattr(entity, "facing_x"):
            entity.facing_x = dx / distance
            entity.facing_y = dy / distance
        if chasing_attack_target and distance <= _attack_range_for(entity):
            if hasattr(entity, "state"):
                entity.state = "attacking"
            return
        arrival_radius = self._arrival_radius_for(command)
        if not chasing_attack_target and distance <= arrival_radius:
            if command.payload.get("group_move") is True:
                self._finish_move(entity_id, queue)
                if hasattr(entity, "state"):
                    entity.state = "idle"
                return
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
        if (
            not chasing_attack_target
            and self._arrived_near_shared_destination(world, entity_id, target, distance)
        ):
            self._finish_move(entity_id, queue)
            if hasattr(entity, "state"):
                entity.state = "idle"
            return

        speed = max(0.0, float(getattr(entity, "speed", 0.0)))
        step = speed * (dt_ms / 1000)
        if step <= 0:
            self._stop_if_unreachable(world, entity_id, queue, command, target, progress, dt_ms)
            return
        finish_after_move = False
        if step >= distance:
            new_position = target
            finish_after_move = not chasing_attack_target
            if hasattr(entity, "state"):
                entity.state = "moving" if chasing_attack_target else "idle"
        else:
            ratio = step / distance
            new_position = WorldPosition(
                entity.position.x + dx * ratio,
                entity.position.y + dy * ratio,
            )
            if hasattr(entity, "state"):
                entity.state = "moving"
        if self._should_shove(world, entity_id):
            shove_units_from_movement(
                world,
                entity_id,
                entity.position,
                new_position,
                max_push=min(self.max_shove_px, max(step * 0.55, 0.0)),
                friendly_ghost_ids=active_ghost_ids,
            )
        old_position = entity.position
        world.update_entity_position(
            entity_id,
            resolve_unit_position(
                world,
                entity_id,
                new_position,
                current=entity.position,
                max_adjustment=self.collision_slide_px,
                friendly_ghost_ids=active_ghost_ids,
            ),
        )
        if finish_after_move:
            self._finish_move(entity_id, queue)
        else:
            self._update_friendly_ghosting(
                world,
                entity_id,
                progress,
                old_position,
                new_position,
                dt_ms,
            )
            if not chasing_attack_target:
                self._stop_if_unreachable(
                    world,
                    entity_id,
                    queue,
                    command,
                    target,
                    progress,
                    dt_ms,
                )

    def _arrived_near_shared_destination(
        self,
        world: WorldState,
        entity_id: EntityId,
        target: WorldPosition,
        distance: float,
    ) -> bool:
        """Return whether a unit has reached its loose group slot."""
        return distance <= self.shared_destination_radius and occupied_by_unit(
            world,
            target,
            ignore_id=entity_id,
        )

    def _arrival_radius_for(self, command: Command) -> float:
        """Return the range value used for arrival radius for."""
        if command.payload.get("path_detour") is True:
            return self.detour_arrival_radius
        if command.payload.get("group_move") is True:
            return self.group_arrival_radius
        return self.arrival_radius

    def _plan_path_if_needed(
        self,
        world: WorldState,
        entity_id: EntityId,
        queue: CommandQueue,
        command: Command,
    ) -> Command | None:
        """Create detour waypoints for a move command when needed."""
        if command.payload.get("path_planned") is True:
            return command
        path_target = _path_planning_target_for_command(world, command)
        if path_target is None:
            return command
        entity = world.entities.get(entity_id)
        if entity is None:
            return command

        waypoints = move_waypoints_around_blockers(
            world,
            entity_id,
            entity.position,
            path_target,
        )
        if not waypoints:
            command.payload["path_planned"] = True
            return command
        if len(waypoints) == 1 and _distance(waypoints[0], path_target) < 0.001:
            command.payload["path_planned"] = True
            return command

        replacement = [
            _copy_move_command_with_target(
                command,
                waypoint,
                queued=command.queued if index == 0 else True,
                path_detour=index < len(waypoints) - 1,
                final_target=path_target,
            )
            for index, waypoint in enumerate(waypoints)
        ]
        _replace_current_path_commands(queue, replacement, path_target)
        self._clear_progress(entity_id)
        return queue.peek()

    def _progress_for(
        self,
        entity_id: EntityId,
        command: Command,
        target: WorldPosition,
        position: WorldPosition,
    ) -> MovementProgress:
        """Return or create movement progress tracking for a unit."""
        command_token = id(command)
        progress = self._progress_by_entity.get(entity_id)
        if progress is None or progress.command_token != command_token:
            progress = MovementProgress(
                command_token=command_token,
                best_distance=_distance(position, target),
            )
            self._progress_by_entity[entity_id] = progress
        return progress

    def _update_friendly_ghosting(
        self,
        world: WorldState,
        entity_id: EntityId,
        progress: MovementProgress,
        previous_position: WorldPosition,
        attempted_position: WorldPosition,
        dt_ms: int,
    ) -> None:
        """Advance friendly ghosting for the current frame."""
        entity = world.entities.get(entity_id)
        if entity is None:
            self._clear_progress(entity_id)
            return

        if progress.friendly_ghost_until_ms > world.elapsed_ms:
            progress.friendly_collision_anchor = None
            progress.friendly_collision_count = 0
            return

        moved_distance = _distance(previous_position, entity.position)
        if moved_distance >= self.friendly_ghost_reset_distance_px:
            self._reset_friendly_collision_progress(progress)

        progress.friendly_collision_check_elapsed_ms += max(0, int(dt_ms))
        if (
            self.friendly_ghost_check_interval_ms > 0
            and progress.friendly_collision_check_elapsed_ms
            < self.friendly_ghost_check_interval_ms
        ):
            return
        progress.friendly_collision_check_elapsed_ms = 0

        collision_position = _nearest_friendly_collision_position(
            world,
            entity_id,
            attempted_position,
        ) or _nearest_friendly_collision_position(world, entity_id, entity.position)
        if collision_position is None:
            self._reset_friendly_collision_progress(progress)
            return

        if (
            progress.friendly_collision_anchor is None
            or _distance(collision_position, progress.friendly_collision_anchor)
            > self.friendly_ghost_area_px
        ):
            progress.friendly_collision_anchor = collision_position
            progress.friendly_collision_count = 1
            return

        progress.friendly_collision_count += 1
        if progress.friendly_collision_count < self.friendly_ghost_collision_limit:
            return

        progress.friendly_ghost_until_ms = world.elapsed_ms + self.friendly_ghost_duration_ms
        self._reset_friendly_collision_progress(progress)

    def _reset_friendly_collision_progress(self, progress: MovementProgress) -> None:
        """Reset collision-stuck tracking for a unit."""
        progress.friendly_collision_anchor = None
        progress.friendly_collision_count = 0

    def _should_shove(self, world: WorldState, entity_id: EntityId) -> bool:
        """Return whether shove should happen."""
        last_ms = self._last_shove_ms_by_entity.get(entity_id)
        if last_ms is not None and world.elapsed_ms - last_ms < self.shove_interval_ms:
            return False
        self._last_shove_ms_by_entity[entity_id] = world.elapsed_ms
        return True

    def _active_friendly_ghost_ids(self, world: WorldState) -> set[EntityId]:
        """Return the active friendly ghost ids."""
        return {
            entity_id
            for entity_id, progress in self._progress_by_entity.items()
            if progress.friendly_ghost_until_ms > world.elapsed_ms
        }

    def _stop_if_unreachable(
        self,
        world: WorldState,
        entity_id: EntityId,
        queue: CommandQueue,
        command: Command,
        target: WorldPosition,
        progress: MovementProgress,
        dt_ms: int,
    ) -> bool:
        """Stop a move command that cannot make useful progress."""
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

        if self._replan_unreachable_move(world, entity_id, queue, command):
            return False

        self._finish_move(entity_id, queue)
        if hasattr(entity, "state"):
            entity.state = "idle"
        return True

    def _replan_unreachable_move(
        self,
        world: WorldState,
        entity_id: EntityId,
        queue: CommandQueue,
        command: Command,
    ) -> bool:
        """Try a fresh blocker route before giving up on a stuck move."""
        entity = world.entities.get(entity_id)
        if entity is None or command.target_pos is None:
            return False
        replan_count = int(command.payload.get("path_replan_count", 0) or 0)
        if replan_count >= self.max_path_replans:
            return False

        final_target = _path_planning_target_for_command(world, command) or _path_final_target(
            command
        )
        waypoints = move_waypoints_around_blockers(
            world,
            entity_id,
            entity.position,
            final_target,
        )
        if not waypoints:
            return False
        if len(waypoints) == 1 and _distance(waypoints[0], command.target_pos) < 0.001:
            return False

        replacement = [
            _copy_move_command_with_target(
                command,
                waypoint,
                queued=command.queued if index == 0 else True,
                path_detour=index < len(waypoints) - 1,
                final_target=final_target,
                replan_count=replan_count + 1,
            )
            for index, waypoint in enumerate(waypoints)
        ]
        _replace_current_path_commands(queue, replacement, final_target)
        self._clear_progress(entity_id)
        return True

    def _finish_move(self, entity_id: EntityId, queue: CommandQueue) -> None:
        """Finish move."""
        queue.pop_next()
        self._clear_progress(entity_id)

    def _clear_progress(self, entity_id: EntityId) -> None:
        """Clear progress."""
        self._progress_by_entity.pop(entity_id, None)
        self._last_shove_ms_by_entity.pop(entity_id, None)


def _is_movable(entity: object) -> bool:
    """Return whether movable."""
    return (
        getattr(entity, "alive", False)
        and "movable" in getattr(entity, "tags", ())
    )


def _copy_move_command_with_target(
    command: Command,
    target_pos: WorldPosition,
    *,
    queued: bool,
    path_detour: bool,
    final_target: WorldPosition | None = None,
    replan_count: int | None = None,
) -> Command:
    """Return the position used for copy move command with target."""
    payload = dict(command.payload)
    payload["path_planned"] = True
    final = final_target or _path_final_target(command)
    payload["path_final_x"] = final.x
    payload["path_final_y"] = final.y
    if replan_count is not None:
        payload["path_replan_count"] = replan_count
    if path_detour:
        payload["path_detour"] = True
    else:
        payload.pop("path_detour", None)
    return make_command(
        "move",
        command.issuer_ids,
        target_pos=target_pos,
        queued=queued,
        **payload,
    )


def _movement_paused_for_attack(command: Command, elapsed_ms: int) -> bool:
    """Return whether combat temporarily pauses movement."""
    pause_until = command.payload.get("pause_movement_until_ms")
    return isinstance(pause_until, int) and pause_until > elapsed_ms


def _movement_target_for_command(
    world: WorldState,
    command: Command,
) -> tuple[WorldPosition, bool]:
    """Return the position used for movement target for command."""
    assert command.target_pos is not None
    if command.payload.get("path_detour") is True:
        return (
            clamp_unit_position_to_walkable_lane_for_height(
                command.target_pos,
                world.settings.world_height,
            ),
            False,
        )
    chase_target_id = _payload_entity_id(command, "attack_move_chase_target_id")
    if command.payload.get("attack_move") is True and chase_target_id is not None:
        chase_target = world.entities.get(chase_target_id)
        if chase_target is not None and getattr(chase_target, "alive", False):
            return (
                clamp_unit_position_to_walkable_lane_for_height(
                    chase_target.position,
                    world.settings.world_height,
                ),
                True,
            )
    return (
        clamp_unit_position_to_walkable_lane_for_height(
            command.target_pos,
            world.settings.world_height,
        ),
        False,
    )


def _path_final_target(command: Command) -> WorldPosition:
    """Return the final destination represented by a path-planned move chain."""
    x = command.payload.get("path_final_x")
    y = command.payload.get("path_final_y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return WorldPosition(float(x), float(y))
    assert command.target_pos is not None
    return command.target_pos


def _path_planning_target_for_command(
    world: WorldState,
    command: Command,
) -> WorldPosition | None:
    """Return the hard-obstacle path target for a command, or None for direct chase."""
    if command.target_pos is None:
        return None
    chase_target_id = _payload_entity_id(command, "attack_move_chase_target_id")
    if chase_target_id is None:
        return command.target_pos
    chase_target = world.entities.get(chase_target_id)
    if chase_target is None or not getattr(chase_target, "alive", False):
        return command.target_pos
    if "building" in getattr(chase_target, "tags", ()):
        return chase_target.position
    # Moving unit targets shift every frame, so keep those as direct pursuit.
    return None


def _same_path_final(command: Command, final_target: WorldPosition) -> bool:
    """Return whether a queued path segment belongs to the same planned route."""
    if command.type != "move" or command.payload.get("path_planned") is not True:
        return False
    command_final = _path_final_target(command)
    return _distance(command_final, final_target) < 0.001


def _replace_current_path_commands(
    queue: CommandQueue,
    replacement: list[Command],
    final_target: WorldPosition,
) -> None:
    """Replace the current stale path and its queued continuation commands."""
    drop_count = 1
    while drop_count < len(queue.commands) and _same_path_final(
        queue.commands[drop_count],
        final_target,
    ):
        drop_count += 1
    queue.commands[0:drop_count] = replacement


def _attack_range_for(entity: object) -> float:
    """Return the range value used for attack range for."""
    return max(0.0, float(getattr(entity, "attack_range", 0.0)))


def _nearest_friendly_collision_position(
    world: WorldState,
    entity_id: EntityId,
    position: WorldPosition,
) -> WorldPosition | None:
    """Return the nearest friendly collision position."""
    entity = world.entities.get(entity_id)
    if entity is None:
        return None

    nearest_position: WorldPosition | None = None
    nearest_distance = UNIT_COLLISION_RADIUS
    query_bounds = (
        position.x - UNIT_COLLISION_RADIUS,
        position.y - UNIT_COLLISION_RADIUS,
        UNIT_COLLISION_RADIUS * 2,
        UNIT_COLLISION_RADIUS * 2,
    )
    for other_id in world.spatial_hash.query(query_bounds):
        other = world.entities.get(other_id)
        if other is None:
            continue
        if (
            other.id == entity_id
            or not is_unit(other)
            or getattr(other, "owner", None) != getattr(entity, "owner", None)
        ):
            continue
        distance = _distance(other.position, position)
        if distance < nearest_distance:
            nearest_position = other.position
            nearest_distance = distance
    return nearest_position

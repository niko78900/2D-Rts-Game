"""Minimal combat resolution for attack-move orders."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from house_of_wolves.core.contracts import Command, EntityId, WorldPosition
from house_of_wolves.world.collision import (
    MAX_COLLISION_ADJUSTMENT,
    MAX_SHOVE_PUSH,
    resolve_unit_position,
    shove_units_from_movement,
)
from house_of_wolves.world.terrain import clamp_unit_position_to_walkable_lane_for_height
from house_of_wolves.world.world import WorldState

DEFAULT_ATTACK_MOVE_RADIUS = 180.0
DEFAULT_GUARD_RADIUS = 230.0
ATTACK_MOVE_HOLD_MS = 250
ATTACK_MOVE_CHASE_TIMEOUT_MS = 7000
NEUTRAL_OWNER = "neutral"


@dataclass(slots=True)
class CombatSystem:
    attack_move_radius: float = DEFAULT_ATTACK_MOVE_RADIUS
    guard_radius: float = DEFAULT_GUARD_RADIUS
    attack_hold_ms: int = ATTACK_MOVE_HOLD_MS
    chase_timeout_ms: int = ATTACK_MOVE_CHASE_TIMEOUT_MS

    def update(self, world: WorldState, dt_ms: int) -> None:
        for entity in list(world.entities.values()):
            if not _can_attack(entity):
                continue
            entity.cooldown_remaining_ms = max(0, entity.cooldown_remaining_ms - dt_ms)
            command = _current_command(world, entity.id)
            if command is None:
                self._update_guard_unit(world, entity, dt_ms)
                continue
            if command.type == "attack":
                self._update_attack_command(world, entity, command, dt_ms)
                continue
            if _is_gather_related_command(command):
                if self._update_gather_defense(world, entity, dt_ms):
                    continue
                continue
            if not _is_attack_move_command(command):
                continue
            target = _locked_or_nearest_enemy_unit(
                world,
                entity.id,
                command,
                max(self.attack_move_radius, float(getattr(entity, "attack_range", 0.0))),
            )
            if target is None:
                _clear_attack_target(command)
                continue
            command.payload["attack_move_target_id"] = target.id.to_json()
            command.payload["attack_move_chase_target_id"] = target.id.to_json()

            distance = _distance(entity.position, target.position)
            if distance > _attack_range_for(entity):
                last_contact_ms = _last_contact_ms(command, world.elapsed_ms)
                if world.elapsed_ms - last_contact_ms >= self.chase_timeout_ms:
                    command.payload["attack_move_ignored_target_id"] = target.id.to_json()
                    _clear_attack_target(command)
                elif hasattr(entity, "state"):
                    entity.state = "moving"
                continue

            command.payload["attack_move_last_contact_ms"] = world.elapsed_ms
            command.payload["pause_movement_until_ms"] = world.elapsed_ms + self.attack_hold_ms
            if _attack_target(world, entity, target):
                command.payload["last_attack_target_id"] = target.id.to_json()
                _clear_attack_target(command)

    def _update_attack_command(
        self,
        world: WorldState,
        entity: object,
        command: Command,
        dt_ms: int,
    ) -> None:
        queue = world.command_queues.get(entity.id)
        target = world.entities.get(command.target_entity_id)
        if target is None or not _is_enemy_unit(entity, target):
            if queue is not None:
                queue.pop_next()
            _clear_attack_target_state(entity)
            return

        if _distance(entity.position, target.position) > _attack_range_for(entity):
            _move_entity_toward(world, entity, target.position, dt_ms)
            return

        if _attack_target(world, entity, target) and queue is not None:
            queue.pop_next()

    def _update_guard_unit(self, world: WorldState, entity: object, dt_ms: int) -> None:
        if not _is_guard_unit(entity):
            _clear_attack_target_state(entity)
            return
        target = _nearest_enemy_unit(world, entity.id, self.guard_radius)
        if target is None:
            _clear_attack_target_state(entity)
            return

        distance = _distance(entity.position, target.position)
        if distance <= _attack_range_for(entity):
            _attack_target(world, entity, target)
            return
        _move_entity_toward(world, entity, target.position, dt_ms)

    def _update_gather_defense(
        self,
        world: WorldState,
        entity: object,
        dt_ms: int,
    ) -> bool:
        target = _nearest_enemy_threatening_unit(world, entity.id)
        if target is None:
            return False
        queue = world.command_queues.get(entity.id)
        if queue is not None:
            queue.clear()
        if _distance(entity.position, target.position) > _attack_range_for(entity):
            _move_entity_toward(world, entity, target.position, dt_ms)
            return True
        _attack_target(world, entity, target)
        return True


def _current_command(world: WorldState, entity_id: EntityId) -> Command | None:
    queue = world.command_queues.get(entity_id)
    return queue.peek() if queue is not None else None


def _is_attack_move_command(command: Command) -> bool:
    return command.type == "move" and command.payload.get("attack_move") is True


def _is_gather_related_command(command: Command) -> bool:
    return command.type == "gather" or command.payload.get("gather_move") is True


def _nearest_enemy_unit(
    world: WorldState,
    entity_id: EntityId,
    radius: float,
    *,
    ignored_id: EntityId | None = None,
) -> object | None:
    entity = world.entities.get(entity_id)
    if entity is None:
        return None
    nearest: object | None = None
    nearest_distance = radius
    for other in _entities_near_position(world, entity.position, radius):
        if ignored_id is not None and other.id == ignored_id:
            continue
        if not _is_enemy_unit(entity, other):
            continue
        distance = _distance(entity.position, other.position)
        if distance <= nearest_distance:
            nearest = other
            nearest_distance = distance
    return nearest


def _nearest_enemy_threatening_unit(
    world: WorldState,
    entity_id: EntityId,
) -> object | None:
    entity = world.entities.get(entity_id)
    if entity is None:
        return None
    nearest: object | None = None
    nearest_distance = float("inf")
    for other in _entities_near_position(world, entity.position, 512.0):
        if not _is_enemy_unit(entity, other):
            continue
        distance = _distance(entity.position, other.position)
        if distance > _attack_range_for(other) + 12:
            continue
        if distance < nearest_distance:
            nearest = other
            nearest_distance = distance
    return nearest


def _entities_near_position(
    world: WorldState,
    position: WorldPosition,
    radius: float,
) -> list[object]:
    bounds = (
        position.x - radius,
        position.y - radius,
        radius * 2,
        radius * 2,
    )
    entities: list[object] = []
    query_ids = world.spatial_hash.query(bounds)
    unit_ids = getattr(world, "unit_ids", set())
    if unit_ids:
        query_ids = query_ids & unit_ids
    for entity_id in query_ids:
        entity = world.entities.get(entity_id)
        if entity is not None:
            entities.append(entity)
    return entities


def _locked_or_nearest_enemy_unit(
    world: WorldState,
    entity_id: EntityId,
    command: Command,
    radius: float,
) -> object | None:
    ignored_id = _payload_entity_id(command, "attack_move_ignored_target_id")
    locked_id = _payload_entity_id(command, "attack_move_target_id")
    if locked_id is not None and locked_id != ignored_id:
        target = world.entities.get(locked_id)
        if target is not None and _is_enemy_unit(world.entities.get(entity_id), target):
            return target
        _clear_attack_target(command)

    target = _nearest_enemy_unit(world, entity_id, radius, ignored_id=ignored_id)
    if target is not None:
        command.payload["attack_move_last_contact_ms"] = world.elapsed_ms
    return target


def _can_attack(entity: object) -> bool:
    return (
        getattr(entity, "alive", False)
        and "unit" in getattr(entity, "tags", ())
        and int(getattr(entity, "damage", 0)) > 0
        and int(getattr(entity, "attack_cooldown_ms", 0)) > 0
    )


def _is_guard_unit(entity: object) -> bool:
    return _can_attack(entity) and getattr(entity, "owner", NEUTRAL_OWNER) != NEUTRAL_OWNER


def _is_enemy_unit(entity: object, other: object) -> bool:
    return (
        entity is not None
        and other is not entity
        and getattr(other, "alive", False)
        and "unit" in getattr(other, "tags", ())
        and getattr(other, "owner", NEUTRAL_OWNER) != NEUTRAL_OWNER
        and getattr(other, "owner", None) != getattr(entity, "owner", None)
    )


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def _attack_range_for(entity: object) -> float:
    return max(0.0, float(getattr(entity, "attack_range", 0.0)))


def _last_contact_ms(command: Command, elapsed_ms: int) -> int:
    value = command.payload.get("attack_move_last_contact_ms")
    if isinstance(value, int):
        return value
    command.payload["attack_move_last_contact_ms"] = elapsed_ms
    return elapsed_ms


def _payload_entity_id(command: Command, key: str) -> EntityId | None:
    value = command.payload.get(key)
    if value is None:
        return None
    return EntityId(int(value))


def _clear_attack_target(command: Command) -> None:
    command.payload.pop("attack_move_target_id", None)
    command.payload.pop("attack_move_chase_target_id", None)
    command.payload.pop("attack_move_last_contact_ms", None)


def _clear_attack_target_state(entity: object) -> None:
    if getattr(entity, "state", None) in {"attacking", "moving"}:
        entity.state = "idle"


def _attack_target(world: WorldState, attacker: object, target: object) -> bool:
    attacker.state = "attacking"
    if int(getattr(attacker, "cooldown_remaining_ms", 0)) > 0:
        return False
    target.hp = max(0, int(getattr(target, "hp", 0)) - int(getattr(attacker, "damage", 0)))
    attacker.cooldown_remaining_ms = int(getattr(attacker, "attack_cooldown_ms", 0))
    if target.hp <= 0:
        target.alive = False
        world.remove_entity(target.id)
        return True
    return False


def _move_entity_toward(
    world: WorldState,
    entity: object,
    target: WorldPosition,
    dt_ms: int,
) -> None:
    dx = target.x - entity.position.x
    dy = target.y - entity.position.y
    distance = hypot(dx, dy)
    if distance <= _attack_range_for(entity):
        entity.state = "attacking"
        return

    speed = max(0.0, float(getattr(entity, "speed", 0.0)))
    step = speed * (dt_ms / 1000)
    if step <= 0:
        return
    ratio = min(1.0, step / max(distance, 0.0001))
    desired = clamp_unit_position_to_walkable_lane_for_height(
        WorldPosition(
            entity.position.x + dx * ratio,
            entity.position.y + dy * ratio,
        ),
        world.settings.world_height,
    )
    shove_units_from_movement(
        world,
        entity.id,
        entity.position,
        desired,
        max_push=min(MAX_SHOVE_PUSH, max(step * 0.55, 0.0)),
    )
    world.update_entity_position(
        entity.id,
        resolve_unit_position(
            world,
            entity.id,
            desired,
            current=entity.position,
            max_adjustment=MAX_COLLISION_ADJUSTMENT,
        ),
    )
    entity.state = "moving"

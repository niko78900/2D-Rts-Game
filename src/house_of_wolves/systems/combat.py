"""Combat targeting and damage resolution for units and wave pressure."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from house_of_wolves.core.contracts import Command, EntityId, Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.combat_effect import CombatEffect
from house_of_wolves.entities.projectile import Projectile
from house_of_wolves.systems.buildings import start_building_destruction
from house_of_wolves.systems.commands import make_command
from house_of_wolves.world.collision import (
    MAX_COLLISION_ADJUSTMENT,
    MAX_SHOVE_PUSH,
    blocking_bounds_for_entity,
    resolve_unit_position,
    shove_units_from_movement,
)
from house_of_wolves.world.terrain import clamp_unit_position_to_walkable_lane_for_height
from house_of_wolves.world.world import WorldState

DEFAULT_ATTACK_MOVE_RADIUS = 180.0
DEFAULT_GUARD_RADIUS = 230.0
ATTACK_MOVE_HOLD_MS = 250
ATTACK_MOVE_CHASE_TIMEOUT_MS = 7000
RANGED_ATTACK_WINDUP_MS = 250
MELEE_ATTACK_WINDUP_MS = 120
ARROW_PROJECTILE_SPEED = 620.0
ARROW_PROJECTILE_LIFETIME_MS = 1800
ARROW_PROJECTILE_HIT_RADIUS = 12.0
MELEE_STRIKE_EFFECT_MS = 170
HIT_FLASH_EFFECT_MS = 180
DAMAGE_NUMBER_EFFECT_MS = 700
UNIT_FALL_EFFECT_MS = 800
NEUTRAL_OWNER = "neutral"
# Limit combat targets to units/buildings so resource nodes and farm animals are
# ignored by wave pressure and idle guard scans.
TARGET_TAGS = {"unit", "building"}


@dataclass(slots=True)
class CombatSystem:
    attack_move_radius: float = DEFAULT_ATTACK_MOVE_RADIUS
    guard_radius: float = DEFAULT_GUARD_RADIUS
    attack_hold_ms: int = ATTACK_MOVE_HOLD_MS
    chase_timeout_ms: int = ATTACK_MOVE_CHASE_TIMEOUT_MS
    ranged_windup_ms: int = RANGED_ATTACK_WINDUP_MS
    melee_windup_ms: int = MELEE_ATTACK_WINDUP_MS
    projectile_speed: float = ARROW_PROJECTILE_SPEED
    projectile_lifetime_ms: int = ARROW_PROJECTILE_LIFETIME_MS

    def update(self, world: WorldState, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
        self._update_projectiles(world, dt_ms)
        self._update_effects(world, dt_ms)
        for entity in list(world.entities.values()):
            if not _can_attack(entity):
                continue
            _advance_attack_timers(entity, dt_ms)
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
                _clear_attack_target_state(entity)
                continue
            if not _is_attack_move_command(command):
                _clear_attack_target_state(entity)
                continue
            target = _locked_or_nearest_enemy_target(
                world,
                entity.id,
                command,
                max(self.attack_move_radius, float(getattr(entity, "attack_range", 0.0))),
            )
            if target is None:
                _clear_attack_target(command)
                _clear_attack_target_state(entity)
                continue
            command.payload["attack_move_target_id"] = target.id.to_json()
            command.payload["attack_move_chase_target_id"] = target.id.to_json()

            if _attack_distance(entity, target) > _attack_range_for(entity):
                _cancel_attack_windup(entity)
                last_contact_ms = _last_contact_ms(command, world.elapsed_ms)
                if world.elapsed_ms - last_contact_ms >= self.chase_timeout_ms:
                    command.payload["attack_move_ignored_target_id"] = target.id.to_json()
                    _clear_attack_target(command)
                elif hasattr(entity, "state"):
                    entity.state = "moving"
                continue

            command.payload["attack_move_last_contact_ms"] = world.elapsed_ms
            command.payload["pause_movement_until_ms"] = world.elapsed_ms + self.attack_hold_ms
            if self._attack_target(world, entity, target):
                command.payload["last_attack_target_id"] = target.id.to_json()
                _clear_attack_target(command)
        world.performance_stats.counters.active_projectiles = len(world.projectiles)
        world.performance_stats.counters.active_combat_effects = len(world.combat_effects)

    def _update_attack_command(
        self,
        world: WorldState,
        entity: object,
        command: Command,
        dt_ms: int,
    ) -> None:
        """Advance attack command for the current frame."""
        queue = world.command_queues.get(entity.id)
        target = world.entities.get(command.target_entity_id)
        if target is None or not _is_enemy_target(entity, target):
            if queue is not None:
                queue.pop_next()
            _clear_attack_target_state(entity)
            return

        if _attack_distance(entity, target) > _attack_range_for(entity):
            _cancel_attack_windup(entity)
            _move_entity_toward(world, entity, target.position, dt_ms)
            return

        if self._attack_target(world, entity, target) and queue is not None:
            queue.pop_next()

    def _update_guard_unit(self, world: WorldState, entity: object, dt_ms: int) -> None:
        """Advance guard unit for the current frame."""
        if not _is_guard_unit(entity):
            _clear_attack_target_state(entity)
            return
        target = _nearest_enemy_target(world, entity.id, self.guard_radius)
        if target is None:
            # Enemy wave units keep drifting toward player structures even when
            # no immediate target is inside their local guard radius.
            if getattr(entity, "owner", NEUTRAL_OWNER) != "frontier":
                objective = _primary_enemy_objective(world)
                if objective is not None:
                    _queue_enemy_objective_move(world, entity, objective)
                    return
            _clear_attack_target_state(entity)
            return

        if _attack_distance(entity, target) <= _attack_range_for(entity):
            self._attack_target(world, entity, target)
            return
        _cancel_attack_windup(entity)
        _move_entity_toward(world, entity, target.position, dt_ms)

    def _update_gather_defense(
        self,
        world: WorldState,
        entity: object,
        dt_ms: int,
    ) -> bool:
        """Advance gather defense for the current frame."""
        target = _nearest_enemy_threatening_unit(world, entity.id)
        if target is None:
            return False
        queue = world.command_queues.get(entity.id)
        if queue is not None:
            queue.clear()
        if _distance(entity.position, target.position) > _attack_range_for(entity):
            _cancel_attack_windup(entity)
            _move_entity_toward(world, entity, target.position, dt_ms)
            return True
        self._attack_target(world, entity, target)
        return True

    def _attack_target(
        self,
        world: WorldState,
        attacker: object,
        target: object,
    ) -> bool:
        """Advance one wind-up and release an attack when ready."""
        _face_toward(attacker, target.position)
        pending_target_id = getattr(attacker, "pending_attack_target_id", None)
        if pending_target_id is not None and pending_target_id != target.id:
            _cancel_attack_windup(attacker)
            pending_target_id = None

        if pending_target_id == target.id:
            attacker.state = "attack_windup"
            if int(getattr(attacker, "attack_windup_remaining_ms", 0)) > 0:
                return False
            attacker.pending_attack_target_id = None
            if _is_ranged_attacker(attacker):
                self._spawn_projectile(world, attacker, target)
                target_killed = False
            else:
                self._spawn_melee_strike(world, attacker, target)
                impact_direction = _direction_to(attacker.position, target.position)
                target_killed = self._apply_damage(
                    world,
                    target,
                    int(getattr(attacker, "damage", 0)),
                    attacker.owner,
                    impact_direction,
                )
            attacker.cooldown_remaining_ms = int(
                getattr(attacker, "attack_cooldown_ms", 0)
            )
            attacker.state = "attacking"
            return target_killed

        if int(getattr(attacker, "cooldown_remaining_ms", 0)) > 0:
            attacker.state = "attack_cooldown"
            return False

        attacker.pending_attack_target_id = target.id
        attacker.attack_windup_remaining_ms = (
            self.ranged_windup_ms
            if _is_ranged_attacker(attacker)
            else self.melee_windup_ms
        )
        attacker.state = "attack_windup"
        world.performance_stats.counters.attacks_started += 1
        return False

    def _spawn_projectile(
        self,
        world: WorldState,
        attacker: object,
        target: object,
    ) -> None:
        """Launch one arrow toward a target without spatial-hash registration."""
        target_pos = _visual_center(target)
        origin = _attack_origin(attacker, target_pos)
        projectile = Projectile(
            id=world.allocate_entity_id(),
            owner=str(getattr(attacker, "owner", NEUTRAL_OWNER)),
            position=origin,
            footprint=Footprint(1, 1),
            hp=1,
            max_hp=1,
            alive=True,
            tags=("projectile", "arrow"),
            target_entity_id=target.id,
            target_pos=target_pos,
            source_entity_id=attacker.id,
            damage=int(getattr(attacker, "damage", 0)),
            speed=self.projectile_speed,
            remaining_lifetime_ms=self.projectile_lifetime_ms,
            hit_radius=ARROW_PROJECTILE_HIT_RADIUS,
        )
        world.projectiles.append(projectile)

    def _spawn_melee_strike(
        self,
        world: WorldState,
        attacker: object,
        target: object,
    ) -> None:
        """Create a short directional slash or thrust at melee impact."""
        direction_x, direction_y = _direction_to(attacker.position, target.position)
        world.add_combat_effect(
            CombatEffect(
                kind="melee_strike",
                position=_visual_center(attacker),
                duration_ms=MELEE_STRIKE_EFFECT_MS,
                remaining_ms=MELEE_STRIKE_EFFECT_MS,
                owner=str(getattr(attacker, "owner", NEUTRAL_OWNER)),
                direction_x=direction_x,
                direction_y=direction_y,
            )
        )

    def _update_projectiles(self, world: WorldState, dt_ms: int) -> None:
        """Move arrows directly toward their target or last known position."""
        survivors: list[Projectile] = []
        dt_seconds = max(0, int(dt_ms)) / 1000.0
        for projectile in world.projectiles:
            projectile.remaining_lifetime_ms -= max(0, int(dt_ms))
            if projectile.remaining_lifetime_ms <= 0 or projectile.target_pos is None:
                continue
            target = world.entities.get(projectile.target_entity_id)
            target_is_valid = (
                target is not None
                and _is_projectile_target(projectile, target)
            )
            if target_is_valid:
                projectile.target_pos = _visual_center(target)

            dx = projectile.target_pos.x - projectile.position.x
            dy = projectile.target_pos.y - projectile.position.y
            distance = hypot(dx, dy)
            step = max(0.0, projectile.speed) * dt_seconds
            if distance <= projectile.hit_radius + step:
                impact_direction = (
                    (dx / distance, dy / distance)
                    if distance > 0.0001
                    else (1.0, 0.0)
                )
                projectile.position = projectile.target_pos
                if target_is_valid:
                    self._apply_damage(
                        world,
                        target,
                        projectile.damage,
                        projectile.owner,
                        impact_direction,
                    )
                    world.performance_stats.counters.projectile_hits += 1
                continue
            if distance > 0 and step > 0:
                ratio = min(1.0, step / distance)
                projectile.position = WorldPosition(
                    projectile.position.x + dx * ratio,
                    projectile.position.y + dy * ratio,
                )
            survivors.append(projectile)
        world.projectiles = survivors

    def _update_effects(self, world: WorldState, dt_ms: int) -> None:
        """Expire transient combat visuals without touching world entities."""
        elapsed = max(0, int(dt_ms))
        for effect in world.combat_effects:
            effect.remaining_ms -= elapsed
        world.combat_effects = [
            effect for effect in world.combat_effects if effect.remaining_ms > 0
        ]

    def _apply_damage(
        self,
        world: WorldState,
        target: object,
        damage: int,
        attacker_owner: str,
        impact_direction: tuple[float, float],
    ) -> bool:
        """Apply combat damage and emit bounded hit/death feedback."""
        if not getattr(target, "alive", False):
            return True
        amount = max(0, int(damage))
        target.hp = max(0, int(getattr(target, "hp", 0)) - amount)
        position = _visual_center(target)
        world.add_combat_effect(
            CombatEffect(
                kind="hit_flash",
                position=position,
                duration_ms=HIT_FLASH_EFFECT_MS,
                remaining_ms=HIT_FLASH_EFFECT_MS,
                owner=str(getattr(target, "owner", NEUTRAL_OWNER)),
                target_entity_id=target.id,
            )
        )
        if amount > 0:
            world.add_combat_effect(
                CombatEffect(
                    kind="damage_number",
                    position=position,
                    duration_ms=DAMAGE_NUMBER_EFFECT_MS,
                    remaining_ms=DAMAGE_NUMBER_EFFECT_MS,
                    owner=attacker_owner,
                    value=amount,
                )
            )
        if target.hp > 0:
            return False

        if isinstance(target, Building):
            start_building_destruction(world, target)
            return True
        if "unit" in getattr(target, "tags", ()):
            world.add_combat_effect(
                CombatEffect(
                    kind="unit_fall",
                    position=target.position,
                    duration_ms=UNIT_FALL_EFFECT_MS,
                    remaining_ms=UNIT_FALL_EFFECT_MS,
                    owner=str(getattr(target, "owner", NEUTRAL_OWNER)),
                    direction_x=impact_direction[0],
                    direction_y=impact_direction[1],
                    visual_tags=tuple(getattr(target, "tags", ())),
                    visual_width=float(target.footprint.width),
                    visual_height=float(target.footprint.height),
                )
            )
        target.alive = False
        world.remove_entity(target.id)
        return True


def _current_command(world: WorldState, entity_id: EntityId) -> Command | None:
    """Return the current command for an entity if one exists."""
    queue = world.command_queues.get(entity_id)
    return queue.peek() if queue is not None else None


def _is_attack_move_command(command: Command) -> bool:
    """Return whether attack move command."""
    return command.type == "move" and command.payload.get("attack_move") is True


def _is_gather_related_command(command: Command) -> bool:
    """Return whether gather related command."""
    return command.type == "gather" or command.payload.get("gather_move") is True


def _nearest_enemy_target(
    world: WorldState,
    entity_id: EntityId,
    radius: float,
    *,
    ignored_id: EntityId | None = None,
) -> object | None:
    """Return the nearest enemy unit."""
    entity = world.entities.get(entity_id)
    if entity is None:
        return None
    nearest: object | None = None
    nearest_distance = radius
    for other in _entities_near_position(world, entity.position, radius):
        if ignored_id is not None and other.id == ignored_id:
            continue
        if not _is_enemy_target(entity, other):
            continue
        distance = _attack_distance(entity, other)
        if distance <= nearest_distance:
            nearest = other
            nearest_distance = distance
    return nearest


def _nearest_enemy_threatening_unit(
    world: WorldState,
    entity_id: EntityId,
) -> object | None:
    """Return the nearest enemy threatening unit."""
    entity = world.entities.get(entity_id)
    if entity is None:
        return None
    nearest: object | None = None
    nearest_distance = float("inf")
    for other in _entities_near_position(world, entity.position, 512.0):
        # Gather-defense only reacts to enemy units that can hit the worker now;
        # enemy buildings are attackable targets elsewhere, not active threats here.
        if not _is_enemy_target(entity, other) or "unit" not in getattr(other, "tags", ()):
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
    """Return the position used for entities near position."""
    bounds = (
        position.x - radius,
        position.y - radius,
        radius * 2,
        radius * 2,
    )
    entities: list[object] = []
    query_ids = world.spatial_hash.query(bounds)
    for entity_id in query_ids:
        entity = world.entities.get(entity_id)
        if entity is not None:
            entities.append(entity)
    return entities


def _locked_or_nearest_enemy_target(
    world: WorldState,
    entity_id: EntityId,
    command: Command,
    radius: float,
) -> object | None:
    """Return the locked target or nearest valid enemy."""
    ignored_id = _payload_entity_id(command, "attack_move_ignored_target_id")
    locked_id = _payload_entity_id(command, "attack_move_target_id")
    if locked_id is not None and locked_id != ignored_id:
        target = world.entities.get(locked_id)
        if target is not None and _is_enemy_target(world.entities.get(entity_id), target):
            return target
        _clear_attack_target(command)

    target = _nearest_enemy_target(world, entity_id, radius, ignored_id=ignored_id)
    if target is not None:
        command.payload["attack_move_last_contact_ms"] = world.elapsed_ms
    return target


def _can_attack(entity: object) -> bool:
    """Return whether attack can proceed."""
    return (
        getattr(entity, "alive", False)
        and "unit" in getattr(entity, "tags", ())
        and int(getattr(entity, "damage", 0)) > 0
        and int(getattr(entity, "attack_cooldown_ms", 0)) > 0
    )


def _is_guard_unit(entity: object) -> bool:
    """Return whether guard unit."""
    return _can_attack(entity) and getattr(entity, "owner", NEUTRAL_OWNER) != NEUTRAL_OWNER


def _is_enemy_unit(entity: object, other: object) -> bool:
    """Return whether enemy unit."""
    return _is_enemy_target(entity, other) and "unit" in getattr(other, "tags", ())


def _is_enemy_target(entity: object, other: object) -> bool:
    """Return whether another entity is an attackable enemy target."""
    return (
        entity is not None
        and other is not entity
        and getattr(other, "alive", False)
        and bool(TARGET_TAGS & set(getattr(other, "tags", ())))
        and getattr(other, "owner", NEUTRAL_OWNER) != NEUTRAL_OWNER
        and getattr(other, "owner", None) != getattr(entity, "owner", None)
    )


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    """Return center-to-center distance between two world positions."""
    return hypot(first.x - second.x, first.y - second.y)


def _attack_distance(attacker: object, target: object) -> float:
    """Return how far an attacker is from being able to damage a target."""
    if "building" not in getattr(target, "tags", ()):
        return _distance(attacker.position, target.position)

    # Buildings block movement as rectangles, so melee range must be measured
    # to the wall edge instead of the unreachable center point.
    left, top, width, height = blocking_bounds_for_entity(target)
    right = left + width
    bottom = top + height
    dx = max(left - attacker.position.x, 0.0, attacker.position.x - right)
    dy = max(top - attacker.position.y, 0.0, attacker.position.y - bottom)
    return hypot(dx, dy)


def _attack_range_for(entity: object) -> float:
    """Return the configured attack range for an entity."""
    return max(0.0, float(getattr(entity, "attack_range", 0.0)))


def _last_contact_ms(command: Command, elapsed_ms: int) -> int:
    """Return the last time an attacker could hit its target."""
    value = command.payload.get("attack_move_last_contact_ms")
    if isinstance(value, int):
        return value
    command.payload["attack_move_last_contact_ms"] = elapsed_ms
    return elapsed_ms


def _payload_entity_id(command: Command, key: str) -> EntityId | None:
    """Return entity identifiers for payload entity id."""
    value = command.payload.get(key)
    if value is None:
        return None
    return EntityId(int(value))


def _clear_attack_target(command: Command) -> None:
    """Clear attack target."""
    command.payload.pop("attack_move_target_id", None)
    command.payload.pop("attack_move_chase_target_id", None)
    command.payload.pop("attack_move_last_contact_ms", None)


def _clear_attack_target_state(entity: object) -> None:
    """Clear attack target state."""
    _cancel_attack_windup(entity)
    if getattr(entity, "state", None) in {
        "attacking",
        "attack_windup",
        "attack_cooldown",
        "moving",
    }:
        entity.state = "idle"


def _advance_attack_timers(entity: object, dt_ms: int) -> None:
    """Advance cooldown and wind-up clocks once per combat frame."""
    elapsed = max(0, int(dt_ms))
    entity.cooldown_remaining_ms = max(
        0,
        int(getattr(entity, "cooldown_remaining_ms", 0)) - elapsed,
    )
    entity.attack_windup_remaining_ms = max(
        0,
        int(getattr(entity, "attack_windup_remaining_ms", 0)) - elapsed,
    )
    if (
        entity.cooldown_remaining_ms > 0
        and getattr(entity, "state", None) == "attacking"
    ):
        entity.state = "attack_cooldown"


def _cancel_attack_windup(entity: object) -> None:
    """Cancel an unreleased attack without resetting its normal cooldown."""
    if hasattr(entity, "pending_attack_target_id"):
        entity.pending_attack_target_id = None
    if hasattr(entity, "attack_windup_remaining_ms"):
        entity.attack_windup_remaining_ms = 0
    if getattr(entity, "state", None) == "attack_windup":
        entity.state = "idle"


def _is_ranged_attacker(entity: object) -> bool:
    """Return whether a unit should release an arrow projectile."""
    tags = tuple(getattr(entity, "tags", ()))
    return "settler" in tags or any(
        tag == "archer" or tag.endswith("_archer")
        for tag in tags
    )


def _is_projectile_target(projectile: Projectile, target: object) -> bool:
    """Validate only the arrow's assigned target without nearby scans."""
    return (
        getattr(target, "alive", False)
        and bool(TARGET_TAGS & set(getattr(target, "tags", ())))
        and getattr(target, "owner", NEUTRAL_OWNER) != NEUTRAL_OWNER
        and getattr(target, "owner", None) != projectile.owner
    )


def _visual_center(entity: object) -> WorldPosition:
    """Return the visual center of an entity's anchored footprint."""
    left, top, width, height = entity.bounds
    return WorldPosition(left + width / 2, top + height / 2)


def _attack_origin(attacker: object, target_pos: WorldPosition) -> WorldPosition:
    """Return a projectile launch point slightly ahead of its attacker."""
    center = _visual_center(attacker)
    direction_x, direction_y = _direction_to(center, target_pos)
    return WorldPosition(
        center.x + direction_x * 14.0,
        center.y + direction_y * 14.0,
    )


def _direction_to(
    origin: WorldPosition,
    target: WorldPosition,
) -> tuple[float, float]:
    """Return a normalized direction with a deterministic right-facing fallback."""
    dx = target.x - origin.x
    dy = target.y - origin.y
    distance = hypot(dx, dy)
    if distance <= 0.0001:
        return (1.0, 0.0)
    return (dx / distance, dy / distance)


def _face_toward(entity: object, target: WorldPosition) -> None:
    """Update a combat unit's lightweight facing direction."""
    if not hasattr(entity, "facing_x"):
        return
    entity.facing_x, entity.facing_y = _direction_to(entity.position, target)


def _move_entity_toward(
    world: WorldState,
    entity: object,
    target: WorldPosition,
    dt_ms: int,
) -> None:
    """Move a combat unit toward a target position using normal collision."""
    dx = target.x - entity.position.x
    dy = target.y - entity.position.y
    distance = hypot(dx, dy)
    _face_toward(entity, target)
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


def _queue_enemy_objective_move(world: WorldState, entity: object, objective: object) -> None:
    """Queue idle enemy base pressure through the blocker-aware movement system."""
    world.enqueue_command(
        entity.id,
        make_command(
            "move",
            [entity.id],
            target_pos=objective.position,
            attack_move=True,
            group_move=True,
            wave_attack=True,
        ),
    )
    entity.state = "moving"


def _primary_enemy_objective(world: WorldState) -> object | None:
    """Return the nearest player building for right-side enemy pressure."""
    buildings = [
        entity
        for entity in world.entities.values()
        if getattr(entity, "owner", None) == "frontier"
        and "building" in getattr(entity, "tags", ())
        and getattr(entity, "alive", False)
    ]
    if not buildings:
        return None
    huts = [entity for entity in buildings if "hut" in getattr(entity, "tags", ())]
    return max(huts or buildings, key=lambda entity: entity.position.x)

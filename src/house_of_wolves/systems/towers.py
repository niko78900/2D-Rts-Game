"""Defensive tower building specs and autonomous tower combat."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.combat_effect import CombatEffect
from house_of_wolves.entities.projectile import Projectile
from house_of_wolves.systems.combat import (
    ARROW_PROJECTILE_HIT_RADIUS,
    ARROW_PROJECTILE_LIFETIME_MS,
    ARROW_PROJECTILE_SPEED,
)
from house_of_wolves.world.world import WorldState

WOODEN_ARCHER_TOWER_ID = "wooden_archer_tower"
STONE_ARCHER_TOWER_ID = "stone_archer_tower"
WIZARD_TOWER_ID = "wizard_tower"
TOWER_IDS = (WOODEN_ARCHER_TOWER_ID, STONE_ARCHER_TOWER_ID, WIZARD_TOWER_ID)
TOWER_TARGET_SCAN_MS = 300
STONE_ARCHER_TOWER_ALTERNATING_COOLDOWN_MS = 550
STONE_ARCHER_TOWER_PROJECTILE_SPEED = ARROW_PROJECTILE_SPEED * 2
MAGIC_PROJECTILE_SPEED = 480.0
MAGIC_PROJECTILE_LIFETIME_MS = 2200
MAGIC_PROJECTILE_HIT_RADIUS = 16.0
MAGIC_CAST_EFFECT_MS = 280


@dataclass(frozen=True, slots=True)
class TowerSpec:
    """Configures one autonomous defensive tower building."""

    building_id: str
    display_name: str
    footprint: Footprint
    hp: int
    build_time_ms: int
    cost: dict[str, int]
    attack_range: float
    damage: int
    attack_cooldown_ms: int
    windup_ms: int
    projectile_kind: str
    shots_per_attack: int
    projectile_speed: float
    projectile_lifetime_ms: int
    projectile_hit_radius: float


WOODEN_ARCHER_TOWER_SPEC = TowerSpec(
    building_id=WOODEN_ARCHER_TOWER_ID,
    display_name="Wooden Archer Tower",
    footprint=Footprint(92, 155),
    hp=450,
    build_time_ms=10_000,
    cost={"wood": 80, "stone": 20},
    attack_range=260.0,
    damage=5,
    attack_cooldown_ms=1000,
    windup_ms=120,
    projectile_kind="arrow",
    shots_per_attack=1,
    projectile_speed=ARROW_PROJECTILE_SPEED,
    projectile_lifetime_ms=ARROW_PROJECTILE_LIFETIME_MS,
    projectile_hit_radius=ARROW_PROJECTILE_HIT_RADIUS,
)
STONE_ARCHER_TOWER_SPEC = TowerSpec(
    building_id=STONE_ARCHER_TOWER_ID,
    display_name="Stone Archer Tower",
    footprint=Footprint(106, 172),
    hp=850,
    build_time_ms=16_000,
    cost={"wood": 120, "stone": 90, "iron": 20},
    attack_range=420.0,
    damage=8,
    attack_cooldown_ms=STONE_ARCHER_TOWER_ALTERNATING_COOLDOWN_MS,
    windup_ms=120,
    projectile_kind="arrow",
    shots_per_attack=1,
    projectile_speed=STONE_ARCHER_TOWER_PROJECTILE_SPEED,
    projectile_lifetime_ms=ARROW_PROJECTILE_LIFETIME_MS,
    projectile_hit_radius=ARROW_PROJECTILE_HIT_RADIUS,
)
WIZARD_TOWER_SPEC = TowerSpec(
    building_id=WIZARD_TOWER_ID,
    display_name="Wizard Tower",
    footprint=Footprint(112, 182),
    hp=750,
    build_time_ms=18_000,
    cost={"wood": 150, "stone": 120, "iron": 40, "gold": 30},
    attack_range=320.0,
    damage=27,
    attack_cooldown_ms=1800,
    windup_ms=300,
    projectile_kind="magic",
    shots_per_attack=1,
    projectile_speed=MAGIC_PROJECTILE_SPEED,
    projectile_lifetime_ms=MAGIC_PROJECTILE_LIFETIME_MS,
    projectile_hit_radius=MAGIC_PROJECTILE_HIT_RADIUS,
)
TOWER_SPECS: dict[str, TowerSpec] = {
    WOODEN_ARCHER_TOWER_ID: WOODEN_ARCHER_TOWER_SPEC,
    STONE_ARCHER_TOWER_ID: STONE_ARCHER_TOWER_SPEC,
    WIZARD_TOWER_ID: WIZARD_TOWER_SPEC,
}


@dataclass(slots=True)
class TowerCombatSystem:
    """Lets completed player towers acquire enemies and fire lightweight projectiles."""

    target_scan_ms: int = TOWER_TARGET_SCAN_MS

    def update(self, world: WorldState, dt_ms: int) -> None:
        """Advance all completed tower weapons for one simulation tick."""
        elapsed = max(0, int(dt_ms))
        for tower in _tower_buildings(world):
            spec = tower_spec_for(tower)
            if spec is None:
                continue
            self._update_tower(world, tower, spec, elapsed)
        world.performance_stats.counters.active_projectiles = len(world.projectiles)
        world.performance_stats.counters.active_combat_effects = len(world.combat_effects)

    def _update_tower(
        self,
        world: WorldState,
        tower: Building,
        spec: TowerSpec,
        elapsed_ms: int,
    ) -> None:
        """Advance one completed tower's target scan, wind-up, and cooldown."""
        functions = tower.functions
        _tick_timer(functions, "tower_cooldown_remaining_ms", elapsed_ms)
        _tick_timer(functions, "tower_windup_remaining_ms", elapsed_ms)
        _tick_timer(functions, "tower_scan_remaining_ms", elapsed_ms)

        target = _stored_target(world, tower, spec)
        if target is None and int(functions.get("tower_scan_remaining_ms", 0) or 0) <= 0:
            target = _acquire_tower_target(world, tower, spec)
            functions["tower_scan_remaining_ms"] = self.target_scan_ms
            functions["tower_target_id"] = target.id.to_json() if target is not None else None

        if target is None:
            functions["tower_state"] = "idle"
            functions.pop("tower_pending_target_id", None)
            return
        if int(functions.get("tower_cooldown_remaining_ms", 0) or 0) > 0:
            functions["tower_state"] = "cooldown"
            return

        pending_id = functions.get("tower_pending_target_id")
        if pending_id == target.id.to_json():
            functions["tower_state"] = "aiming"
            if int(functions.get("tower_windup_remaining_ms", 0) or 0) > 0:
                return
            _fire_tower_projectiles(world, tower, spec, target)
            functions["tower_cooldown_remaining_ms"] = spec.attack_cooldown_ms
            functions["tower_state"] = "attacking"
            functions.pop("tower_pending_target_id", None)
            return

        functions["tower_pending_target_id"] = target.id.to_json()
        functions["tower_windup_remaining_ms"] = spec.windup_ms
        functions["tower_active_shooter_index"] = _next_tower_shooter_index(tower, spec)
        functions["tower_state"] = "aiming"
        world.performance_stats.counters.attacks_started += 1


def tower_functions_for(spec: TowerSpec) -> dict[str, object]:
    """Return the serializable behavior payload stored on a tower building."""
    return {
        "tower": True,
        "tower_id": spec.building_id,
        "tower_state": "idle",
        "attack_range": spec.attack_range,
        "damage": spec.damage,
        "attack_cooldown_ms": spec.attack_cooldown_ms,
        "shots_per_attack": spec.shots_per_attack,
        "projectile_kind": spec.projectile_kind,
        "tower_windup_ms": spec.windup_ms,
        "tower_shooter_count": _tower_shooter_count(spec),
        "tower_active_shooter_index": 0,
        "tower_next_shooter_index": 0,
        "tower_scan_remaining_ms": 0,
        "tower_cooldown_remaining_ms": 0,
        "tower_windup_remaining_ms": 0,
    }


def is_tower_building(entity: object) -> bool:
    """Return whether an entity is one of the player-buildable defensive towers."""
    return isinstance(entity, Building) and any(
        tower_id in getattr(entity, "tags", ()) for tower_id in TOWER_IDS
    )


def tower_spec_for(entity: object) -> TowerSpec | None:
    """Return the configured tower spec for an entity or id."""
    if isinstance(entity, str):
        return TOWER_SPECS.get(entity)
    tags = set(getattr(entity, "tags", ()))
    for tower_id, spec in TOWER_SPECS.items():
        if tower_id in tags:
            return spec
    return None


def _tower_buildings(world: WorldState) -> list[Building]:
    """Return towers that are complete and currently allowed to attack."""
    towers: list[Building] = []
    for entity in world.entities.values():
        if (
            isinstance(entity, Building)
            and entity.alive
            and entity.complete
            and is_tower_building(entity)
        ):
            towers.append(entity)
    return towers


def _tick_timer(functions: dict[str, object], key: str, elapsed_ms: int) -> None:
    """Tick one tower timer stored in the building function payload."""
    functions[key] = max(0, int(functions.get(key, 0) or 0) - elapsed_ms)


def _tower_shooter_count(spec: TowerSpec) -> int:
    """Return the number of visible shooter positions a tower cycles through."""
    return 2 if spec.building_id == STONE_ARCHER_TOWER_ID else 1


def _next_tower_shooter_index(tower: Building, spec: TowerSpec) -> int:
    """Return the shooter index that should perform the next tower attack."""
    count = max(1, _tower_shooter_count(spec))
    return int(tower.functions.get("tower_next_shooter_index", 0) or 0) % count


def _advance_tower_shooter_index(tower: Building, spec: TowerSpec) -> None:
    """Advance alternating tower shooter state after a projectile launch."""
    count = max(1, _tower_shooter_count(spec))
    current = int(tower.functions.get("tower_active_shooter_index", 0) or 0) % count
    tower.functions["tower_next_shooter_index"] = (current + 1) % count


def _stored_target(world: WorldState, tower: Building, spec: TowerSpec) -> object | None:
    """Return the currently locked target if it remains valid and in range."""
    target_id = tower.functions.get("tower_target_id")
    if target_id is None:
        return None
    target = world.entities.get(EntityId(int(target_id)))
    if not _valid_tower_target(tower, target):
        return None
    if not _target_in_horizontal_tower_range(tower, target, spec):
        return None
    return target


def _acquire_tower_target(
    world: WorldState,
    tower: Building,
    spec: TowerSpec,
) -> object | None:
    """Pick the closest enemy unit in range, then prefer lower HP on ties."""
    bounds = (
        tower.position.x - spec.attack_range,
        0,
        spec.attack_range * 2,
        max(1.0, float(world.settings.world_height)),
    )
    best: object | None = None
    best_key: tuple[float, int] | None = None
    for entity_id in world.spatial_hash.query(bounds):
        candidate = world.entities.get(entity_id)
        if not _valid_tower_target(tower, candidate):
            continue
        if not _target_in_horizontal_tower_range(tower, candidate, spec):
            continue
        key = (
            abs(candidate.position.x - tower.position.x),
            max(0, int(getattr(candidate, "hp", 0))),
        )
        if best_key is None or key < best_key:
            best = candidate
            best_key = key
    return best


def _target_in_horizontal_tower_range(
    tower: Building,
    target: object,
    spec: TowerSpec,
) -> bool:
    """Return whether a target is between a tower's left/right ground range lines."""
    return abs(target.position.x - tower.position.x) <= spec.attack_range


def _valid_tower_target(tower: Building, target: object | None) -> bool:
    """Return whether a tower is allowed to shoot this target."""
    if target is None or not getattr(target, "alive", False):
        return False
    tags = set(getattr(target, "tags", ()))
    return (
        "unit" in tags
        and "food_animal" not in tags
        and getattr(target, "owner", None) != getattr(tower, "owner", None)
        and getattr(target, "owner", None) not in {"neutral", None}
    )


def _fire_tower_projectiles(
    world: WorldState,
    tower: Building,
    spec: TowerSpec,
    target: object,
) -> None:
    """Launch one tower attack as one or more projectiles."""
    target_pos = _visual_center(target)
    shooter_index = _next_tower_shooter_index(tower, spec)
    tower.functions["tower_active_shooter_index"] = shooter_index
    base_origin = _tower_projectile_origin(tower, shooter_index=shooter_index)
    direction_x, direction_y = _direction_to(base_origin, target_pos)
    perpendicular = (-direction_y, direction_x)
    shot_count = max(1, int(spec.shots_per_attack))
    for shot_index in range(shot_count):
        offset = (shot_index - ((shot_count - 1) / 2)) * 9.0
        origin = base_origin
        origin = WorldPosition(
            origin.x + perpendicular[0] * offset,
            origin.y + perpendicular[1] * offset,
        )
        projectile = Projectile(
            id=world.allocate_entity_id(),
            owner=tower.owner,
            position=origin,
            footprint=Footprint(1, 1),
            hp=1,
            max_hp=1,
            alive=True,
            tags=("projectile", spec.projectile_kind),
            target_entity_id=target.id,
            target_pos=target_pos,
            source_entity_id=tower.id,
            damage=spec.damage,
            speed=spec.projectile_speed,
            remaining_lifetime_ms=spec.projectile_lifetime_ms,
            hit_radius=spec.projectile_hit_radius,
        )
        world.projectiles.append(projectile)
    _advance_tower_shooter_index(tower, spec)
    if spec.projectile_kind == "magic":
        world.add_combat_effect(
            CombatEffect(
                kind="magic_cast",
                position=_tower_projectile_origin(tower),
                duration_ms=MAGIC_CAST_EFFECT_MS,
                remaining_ms=MAGIC_CAST_EFFECT_MS,
                owner=tower.owner,
            )
        )


def _tower_projectile_origin(tower: Building, *, shooter_index: int = 0) -> WorldPosition:
    """Return the top-platform launch point for a tower projectile."""
    left, top, width, height = tower.bounds
    if STONE_ARCHER_TOWER_ID in getattr(tower, "tags", ()):
        count = max(1, int(tower.functions.get("tower_shooter_count", 2) or 2))
        if count > 1:
            x_ratio = 0.38 if shooter_index % count == 0 else 0.62
            return WorldPosition(left + width * x_ratio, top + max(16.0, height * 0.20))
    return WorldPosition(left + width / 2, top + max(16.0, height * 0.20))


def _visual_center(entity: object) -> WorldPosition:
    """Return the visual center of an anchored entity footprint."""
    left, top, width, height = entity.bounds
    return WorldPosition(left + width / 2, top + height / 2)


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    """Return center-to-center distance between two world positions."""
    return hypot(first.x - second.x, first.y - second.y)


def _direction_to(
    origin: WorldPosition,
    target: WorldPosition,
) -> tuple[float, float]:
    """Return a normalized direction with a deterministic fallback."""
    dx = target.x - origin.x
    dy = target.y - origin.y
    distance = hypot(dx, dy)
    if distance <= 0.0001:
        return (1.0, 0.0)
    return (dx / distance, dy / distance)

"""Timer-based enemy wave spawning for the first combat pass."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId, WorldPosition
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.production import create_combat_unit
from house_of_wolves.world.collision import nearest_free_position
from house_of_wolves.world.terrain import terrain_layout_for_height
from house_of_wolves.world.world import WorldState

WAVE_TARGET_FALLBACK_X = 520.0


@dataclass(frozen=True, slots=True)
class WaveComposition:
    """Defines how many enemy units a wave should spawn."""

    swordsmen: int
    archers: int = 0


WAVE_COMPOSITIONS = (
    # Early waves stay intentionally small; later waves scale in wave_composition_for.
    WaveComposition(swordsmen=2),
    WaveComposition(swordsmen=3),
    WaveComposition(swordsmen=3, archers=1),
)


@dataclass(slots=True)
class WaveSystem:
    """Spawns small enemy waves and sends them toward player buildings."""

    spawn_x: float = 72.0
    spawn_spacing: float = 42.0

    def update(self, world: WorldState, dt_ms: int) -> None:
        """Advance the wave timer and spawn due automatic waves."""
        # Store the next due time on the world so the HUD and debug controls read
        # the same countdown the spawner uses.
        if world.next_wave_due_ms <= 0:
            world.next_wave_due_ms = (
                world.elapsed_ms + max(0, world.settings.initial_wave_delay_seconds) * 1000
            )
        if not world.settings.waves_enabled or not world.settings.wave_timer_enabled:
            return
        if world.elapsed_ms < world.next_wave_due_ms:
            return
        self.start_wave_now(world)

    def start_wave_now(self, world: WorldState) -> list[EntityId]:
        """Spawn the next configured enemy wave immediately."""
        world.wave_number += 1
        composition = wave_composition_for(world.wave_number)
        spawn_ids: list[EntityId] = []
        for _index in range(composition.swordsmen):
            spawn_ids.append(self._spawn_enemy(world, "enemy_swordsman", len(spawn_ids)))
        for _index in range(composition.archers):
            spawn_ids.append(self._spawn_enemy(world, "enemy_archer", len(spawn_ids)))
        target = primary_wave_target(world)
        for entity_id in spawn_ids:
            # Wave units use attack-move so they travel to the base but still stop
            # and fight player units or buildings they encounter.
            world.enqueue_command(
                entity_id,
                make_command(
                    "move",
                    [entity_id],
                    target_pos=target,
                    attack_move=True,
                    group_move=True,
                    wave_attack=True,
                ),
            )
        world.next_wave_due_ms = world.elapsed_ms + max(1, world.settings.wave_timer_seconds) * 1000
        world.notify("Enemy wave incoming!")
        return spawn_ids

    def _spawn_enemy(self, world: WorldState, unit_id: str, index: int) -> EntityId:
        """Create one enemy wave unit at the configured spawn edge."""
        layout = terrain_layout_for_height(world.settings.world_height)
        # Stagger spawn rows and columns so a wave does not start fully overlapped.
        row = index % 5
        column = index // 5
        desired = WorldPosition(
            self.spawn_x - column * self.spawn_spacing,
            layout.unit_walkable_top_y + 32 + row * self.spawn_spacing,
        )
        position = nearest_free_position(world, desired)
        unit = create_combat_unit(world, unit_id, "wolves", position)
        world.add_entity(unit)
        return unit.id


def wave_composition_for(wave_number: int) -> WaveComposition:
    """Return the configured composition for a wave number."""
    if wave_number <= len(WAVE_COMPOSITIONS):
        return WAVE_COMPOSITIONS[max(0, wave_number - 1)]
    extra = max(0, wave_number - len(WAVE_COMPOSITIONS))
    return WaveComposition(
        swordsmen=3 + extra,
        archers=1 + (extra // 2),
    )


def primary_wave_target(world: WorldState) -> WorldPosition:
    """Return the player building position enemy waves should pressure."""
    target = _nearest_player_building(world, prefer_hut=True) or _nearest_player_building(
        world,
        prefer_hut=False,
    )
    if target is not None:
        return target.position
    layout = terrain_layout_for_height(world.settings.world_height)
    return WorldPosition(WAVE_TARGET_FALLBACK_X, layout.unit_walkable_top_y)


def _nearest_player_building(world: WorldState, *, prefer_hut: bool) -> object | None:
    """Return the closest matching player building to the western spawn edge."""
    candidates = [
        entity
        for entity in world.entities.values()
        if getattr(entity, "owner", None) == "frontier"
        and "building" in getattr(entity, "tags", ())
        and getattr(entity, "alive", False)
        and (not prefer_hut or "hut" in getattr(entity, "tags", ()))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda entity: entity.position.x)

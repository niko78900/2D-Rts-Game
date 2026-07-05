"""Construction progress and HP growth for building sites."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from house_of_wolves.core.contracts import CommandQueue, EntityId, WorldPosition
from house_of_wolves.entities.building import Building
from house_of_wolves.world.world import WorldState

MIN_CONSTRUCTION_HP_RATIO = 0.10


@dataclass(frozen=True, slots=True)
class ActiveBuilder:
    builder_id: EntityId
    queue: CommandQueue


@dataclass(slots=True)
class ConstructionSystem:
    """Consumes build/repair commands and advances building work."""

    builder_interaction_range: float = 140.0
    max_builder_speed_boost: int = 10
    repair_hp_per_second: float = 45.0

    def update(self, world: WorldState, dt_ms: int) -> None:
        active_by_site: dict[EntityId, tuple[Building, list[ActiveBuilder]]] = {}
        repairs_by_site: dict[EntityId, tuple[Building, list[ActiveBuilder]]] = {}
        for builder_id, queue in list(world.command_queues.items()):
            assignment = self._prepare_builder(world, builder_id, queue)
            if assignment is not None:
                site, active_builder = assignment
                _stored_site, builders = active_by_site.setdefault(site.id, (site, []))
                builders.append(active_builder)
                continue
            repair_assignment = self._prepare_repairer(world, builder_id, queue)
            if repair_assignment is None:
                continue
            site, active_builder = repair_assignment
            _stored_site, repairers = repairs_by_site.setdefault(site.id, (site, []))
            repairers.append(active_builder)

        for site, builders in active_by_site.values():
            self._advance_site(world, site, builders, dt_ms)
        for site, repairers in repairs_by_site.values():
            self._repair_site(world, site, repairers, dt_ms)

    def _prepare_builder(
        self,
        world: WorldState,
        builder_id: EntityId,
        queue: CommandQueue,
    ) -> tuple[Building, ActiveBuilder] | None:
        builder = world.entities.get(builder_id)
        if builder is None or not getattr(builder, "alive", False):
            return None

        command = queue.peek()
        if command is None or command.type != "build":
            return None

        site = _build_target(world, command.target_entity_id)
        if site is None:
            queue.pop_next()
            return None
        if site.complete:
            site.hp = _max_hp(site)
            queue.pop_next()
            _set_state(builder, "idle")
            return None
        if _distance(builder.position, _interaction_position(command.target_pos, site)) > (
            self.builder_interaction_range
        ):
            _set_state(builder, "moving")
            return None

        return site, ActiveBuilder(builder_id, queue)

    def _prepare_repairer(
        self,
        world: WorldState,
        builder_id: EntityId,
        queue: CommandQueue,
    ) -> tuple[Building, ActiveBuilder] | None:
        builder = world.entities.get(builder_id)
        if builder is None or not getattr(builder, "alive", False):
            return None

        command = queue.peek()
        if command is None or command.type != "repair":
            return None
        if "settler" not in getattr(builder, "tags", ()):
            queue.pop_next()
            _set_state(builder, "idle")
            return None

        site = _build_target(world, command.target_entity_id)
        if site is None or site.owner != getattr(builder, "owner", None) or not site.complete:
            queue.pop_next()
            return None

        if site.hp >= _max_hp(site):
            site.hp = _max_hp(site)
            queue.pop_next()
            _set_state(builder, "idle")
            return None

        if _distance(builder.position, _interaction_position(command.target_pos, site)) > (
            self.builder_interaction_range
        ):
            _set_state(builder, "moving")
            return None

        return site, ActiveBuilder(builder_id, queue)

    def _advance_site(
        self,
        world: WorldState,
        site: Building,
        builders: list[ActiveBuilder],
        dt_ms: int,
    ) -> None:
        for active_builder in builders:
            builder = world.entities.get(active_builder.builder_id)
            if builder is not None:
                _set_state(builder, "building")

        speed_boost = min(len(builders), self.max_builder_speed_boost)
        site.build_progress_ms = min(
            _build_time(site),
            site.build_progress_ms + (max(0, int(dt_ms)) * speed_boost),
        )
        progress = construction_progress(site)
        site.hp = construction_hp_for_progress(_max_hp(site), progress)

        if progress >= 1.0:
            site.complete = True
            site.hp = _max_hp(site)
            world.recalculate_population()
            for active_builder in builders:
                active_builder.queue.pop_next()
                builder = world.entities.get(active_builder.builder_id)
                if builder is not None:
                    _set_state(builder, "idle")

    def _repair_site(
        self,
        world: WorldState,
        site: Building,
        repairers: list[ActiveBuilder],
        dt_ms: int,
    ) -> None:
        for active_builder in repairers:
            builder = world.entities.get(active_builder.builder_id)
            if builder is not None:
                _set_state(builder, "repairing")

        speed_boost = min(len(repairers), self.max_builder_speed_boost)
        repair_amount = round((max(0, int(dt_ms)) / 1000) * self.repair_hp_per_second * speed_boost)
        site.hp = min(_max_hp(site), site.hp + max(1, repair_amount))

        if site.hp >= _max_hp(site):
            site.hp = _max_hp(site)
            for active_builder in repairers:
                active_builder.queue.pop_next()
                builder = world.entities.get(active_builder.builder_id)
                if builder is not None:
                    _set_state(builder, "idle")


def construction_progress(site: Building) -> float:
    """Return a normalized construction progress value for a building."""

    if site.complete:
        return 1.0
    build_time = _build_time(site)
    if build_time <= 0:
        return 1.0
    return max(0.0, min(1.0, site.build_progress_ms / build_time))


def construction_hp_for_progress(max_hp: int, progress: float) -> int:
    """Map construction progress onto HP, starting at 10% and ending at full HP."""

    if max_hp <= 0:
        return 0
    clamped = max(0.0, min(1.0, progress))
    ratio = MIN_CONSTRUCTION_HP_RATIO + ((1.0 - MIN_CONSTRUCTION_HP_RATIO) * clamped)
    return max(1, min(max_hp, round(max_hp * ratio)))


def starting_construction_hp(max_hp: int) -> int:
    """HP assigned to a newly placed construction site."""

    return construction_hp_for_progress(max_hp, 0.0)


def _build_target(world: WorldState, target_id: EntityId | None) -> Building | None:
    if target_id is None:
        return None
    target = world.entities.get(target_id)
    return target if isinstance(target, Building) else None


def _interaction_position(target_pos: WorldPosition | None, site: Building) -> WorldPosition:
    return target_pos if target_pos is not None else site.position


def _build_time(site: Building) -> int:
    return max(0, int(getattr(site, "build_time_ms", 0)))


def _max_hp(site: Building) -> int:
    return max(0, int(getattr(site, "max_hp", 0) or getattr(site, "hp", 0)))


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def _set_state(entity: object, state: str) -> None:
    if hasattr(entity, "state"):
        entity.state = state

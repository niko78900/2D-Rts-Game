"""Selection state and system shell."""

from __future__ import annotations

from dataclasses import dataclass, field

from house_of_wolves.core.contracts import EntityId, WorldPosition

Bounds = tuple[float, float, float, float]


@dataclass(slots=True)
class SelectionState:
    selected_ids: list[EntityId] = field(default_factory=list)

    def replace(self, entity_ids: list[EntityId]) -> None:
        """Replace the queued commands with a single command."""
        self.selected_ids = list(dict.fromkeys(entity_ids))

    def add(self, entity_id: EntityId) -> None:
        """Add an entity id to the current selection."""
        if entity_id not in self.selected_ids:
            self.selected_ids.append(entity_id)

    def remove(self, entity_id: EntityId) -> None:
        """Remove an entity bounds record from the spatial hash."""
        if entity_id in self.selected_ids:
            self.selected_ids.remove(entity_id)

    def clear(self) -> None:
        """Clear the current collection or command queue."""
        self.selected_ids.clear()


@dataclass(slots=True)
class SelectionSystem:
    state: SelectionState = field(default_factory=SelectionState)

    def pick_at(self, world: object, world_pos: WorldPosition) -> EntityId | None:
        """Return the top selectable entity under a world position."""
        candidates = [
            entity
            for entity in world.entities.values()
            if _is_selectable(entity) and _point_in_bounds(world_pos, entity.bounds)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda entity: (entity.position.y, int(entity.id)), reverse=True)
        return candidates[0].id

    def select_at(
        self,
        world: object,
        world_pos: WorldPosition,
        *,
        add: bool = False,
    ) -> EntityId | None:
        """Select the entity under a world position."""
        entity_id = self.pick_at(world, world_pos)
        if entity_id is None:
            if not add:
                self.state.clear()
            return None

        entity = world.entities[entity_id]
        if _is_enemy_unit(entity):
            self.state.replace([entity_id])
        elif add and _is_player_unit(entity) and self._current_selection_is_player_units(world):
            self.state.add(entity_id)
        else:
            self.state.replace([entity_id])
        return entity_id

    def box_select(self, world: object, bounds: Bounds, *, add: bool = False) -> list[EntityId]:
        """Select player units inside a world-space rectangle."""
        normalized = _normalize_bounds(bounds)
        selected = [
            entity.id
            for entity in world.entities.values()
            if _is_selectable_player_unit(entity) and _bounds_intersect(normalized, entity.bounds)
        ]
        selected.sort(key=int)
        if add and self._current_selection_is_player_units(world):
            for entity_id in selected:
                self.state.add(entity_id)
        else:
            self.state.replace(selected)
        return selected

    def update(self, world: object, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
        return None

    def _current_selection_is_player_units(self, world: object) -> bool:
        """Return whether the selection is only player units."""
        if not self.state.selected_ids:
            return True
        return all(
            _is_player_unit(world.entities.get(entity_id))
            for entity_id in self.state.selected_ids
        )


def _is_selectable(entity: object) -> bool:
    """Return whether selectable."""
    return getattr(entity, "alive", False) and "selectable" in getattr(entity, "tags", ())


def _is_selectable_player_unit(entity: object) -> bool:
    """Return whether selectable player unit."""
    return _is_selectable(entity) and _is_player_unit(entity)


def _is_unit(entity: object) -> bool:
    """Return whether unit."""
    return entity is not None and "unit" in getattr(entity, "tags", ())


def _is_player_unit(entity: object) -> bool:
    """Return whether player unit."""
    return _is_unit(entity) and getattr(entity, "owner", None) == "frontier"


def _is_enemy_unit(entity: object) -> bool:
    """Return whether enemy unit."""
    return (
        _is_unit(entity)
        and getattr(entity, "owner", "neutral") not in {"frontier", "neutral"}
    )


def _point_in_bounds(position: WorldPosition, bounds: Bounds) -> bool:
    """Return the bounds used for point in bounds."""
    left, top, width, height = bounds
    return left <= position.x <= left + width and top <= position.y <= top + height


def _normalize_bounds(bounds: Bounds) -> Bounds:
    """Return the bounds used for normalize bounds."""
    left, top, width, height = bounds
    if width < 0:
        left += width
        width = abs(width)
    if height < 0:
        top += height
        height = abs(height)
    return (left, top, width, height)


def _bounds_intersect(first: Bounds, second: Bounds) -> bool:
    """Return the bounds used for bounds intersect."""
    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    return not (
        first_left + first_width < second_left
        or second_left + second_width < first_left
        or first_top + first_height < second_top
        or second_top + second_height < first_top
    )

"""Uniform-grid spatial hash for broad-phase queries."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import floor

from house_of_wolves.core.contracts import EntityId

Bounds = tuple[float, float, float, float]
Cell = tuple[int, int]


@dataclass(slots=True)
class SpatialHash:
    """Maps entity bounds into coarse world cells."""

    cell_size: int = 96
    _cells: dict[Cell, set[EntityId]] = field(default_factory=lambda: defaultdict(set))
    _bounds_by_id: dict[EntityId, Bounds] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cell_size <= 0:
            raise ValueError("cell_size must be positive")

    def insert(self, entity_id: EntityId, bounds: Bounds) -> None:
        self.remove(entity_id)
        self._bounds_by_id[entity_id] = bounds
        for cell in self._cells_for_bounds(bounds):
            self._cells[cell].add(entity_id)

    def move(self, entity_id: EntityId, bounds: Bounds) -> None:
        self.insert(entity_id, bounds)

    def remove(self, entity_id: EntityId) -> None:
        old_bounds = self._bounds_by_id.pop(entity_id, None)
        if old_bounds is None:
            return
        for cell in self._cells_for_bounds(old_bounds):
            occupants = self._cells.get(cell)
            if occupants is None:
                continue
            occupants.discard(entity_id)
            if not occupants:
                self._cells.pop(cell, None)

    def query(self, bounds: Bounds) -> set[EntityId]:
        found: set[EntityId] = set()
        for cell in self._cells_for_bounds(bounds):
            found.update(self._cells.get(cell, set()))
        return found

    def clear(self) -> None:
        self._cells.clear()
        self._bounds_by_id.clear()

    def _cells_for_bounds(self, bounds: Bounds) -> set[Cell]:
        left, top, width, height = bounds
        right = left + max(0, width)
        bottom = top + max(0, height)
        min_x = floor(left / self.cell_size)
        max_x = floor(right / self.cell_size)
        min_y = floor(top / self.cell_size)
        max_y = floor(bottom / self.cell_size)
        return {
            (cell_x, cell_y)
            for cell_x in range(min_x, max_x + 1)
            for cell_y in range(min_y, max_y + 1)
        }

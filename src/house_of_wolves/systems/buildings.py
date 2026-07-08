"""Building lifecycle helpers shared by combat, rendering, and runtime systems."""

from __future__ import annotations

from dataclasses import dataclass

from house_of_wolves.core.contracts import EntityId
from house_of_wolves.entities.building import Building
from house_of_wolves.world.world import WorldState

BUILDING_DESTRUCTION_MS = 1000


@dataclass(slots=True)
class BuildingLifecycleSystem:
    """Expires buildings that are already in their visual destruction state."""

    def update(self, world: WorldState, dt_ms: int) -> None:
        """Advance active building destruction timers."""
        for entity in list(world.entities.values()):
            if not isinstance(entity, Building) or entity.destruction_remaining_ms <= 0:
                continue
            entity.destruction_remaining_ms -= max(0, int(dt_ms))
            if entity.destruction_remaining_ms <= 0:
                world.remove_entity(entity.id)


def start_building_destruction(
    world: WorldState,
    building: Building,
    *,
    duration_ms: int = BUILDING_DESTRUCTION_MS,
) -> None:
    """Deactivate a building while keeping it briefly renderable as rubble."""
    if building.destruction_remaining_ms > 0:
        return

    building.hp = 0
    building.alive = False
    building.complete = False
    building.production_queue.clear()
    building.destruction_remaining_ms = max(1, int(duration_ms))
    world.command_queues.pop(building.id, None)
    world.hard_obstacle_ids.discard(building.id)
    _remove_builder_commands_targeting(world, building.id)
    world.recalculate_population()


def is_building_destroying(entity: object) -> bool:
    """Return whether a building is waiting on its destruction visual timer."""
    return isinstance(entity, Building) and entity.destruction_remaining_ms > 0


def _remove_builder_commands_targeting(world: WorldState, target_id: EntityId) -> None:
    """Drop construction/repair commands that still point at a destroyed building."""
    for queue in world.command_queues.values():
        queue.commands = [
            command
            for command in queue.commands
            if command.target_entity_id != target_id or command.type not in {"build", "repair"}
        ]

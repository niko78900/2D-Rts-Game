"""Authoritative local world state."""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import TYPE_CHECKING

from house_of_wolves.core.contracts import Command, CommandQueue, EntityId, WorldPosition
from house_of_wolves.core.performance import PerformanceStats
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.world.camera import Camera
from house_of_wolves.world.encounter_zones import DEFAULT_ENCOUNTER_ZONES, EncounterZone
from house_of_wolves.world.spatial_hash import SpatialHash
from house_of_wolves.world.terrain import DEFAULT_TERRAIN_BANDS, TerrainBand

if TYPE_CHECKING:
    from house_of_wolves.entities.base import Entity


@dataclass(slots=True)
class Notification:
    message: str
    remaining_ms: int = 2500


@dataclass(slots=True)
class WorldState:
    """Single authoritative simulation container for the desktop RTS."""

    settings: AppSettings = field(default_factory=AppSettings)
    rng_seed: int = 1337
    elapsed_ms: int = 0
    next_entity_id: int = 1
    entities: dict[EntityId, Entity] = field(default_factory=dict)
    command_queues: dict[EntityId, CommandQueue] = field(default_factory=dict)
    resources: dict[str, int] = field(
        default_factory=lambda: {"wood": 0, "food": 0, "stone": 0, "iron": 0, "gold": 0}
    )
    resource_nodes_by_type: dict[str, list[EntityId]] = field(
        default_factory=lambda: {
            "wood": [],
            "food": [],
            "stone": [],
            "iron": [],
            "ore": [],
            "gold": [],
        }
    )
    unit_ids: set[EntityId] = field(default_factory=set)
    hard_obstacle_ids: set[EntityId] = field(default_factory=set)
    completed_deposit_huts_by_owner: dict[str, list[EntityId]] = field(default_factory=dict)
    current_population: int = 0
    max_population: int = 0
    notifications: list[Notification] = field(default_factory=list)
    camera: Camera = field(default_factory=Camera)
    spatial_hash: SpatialHash = field(default_factory=SpatialHash)
    terrain_bands: tuple[TerrainBand, ...] = DEFAULT_TERRAIN_BANDS
    encounter_zones: tuple[EncounterZone, ...] = DEFAULT_ENCOUNTER_ZONES
    performance_stats: PerformanceStats = field(default_factory=PerformanceStats)
    rng: Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.rng = Random(self.rng_seed)

    def allocate_entity_id(self) -> EntityId:
        entity_id = EntityId(self.next_entity_id)
        self.next_entity_id += 1
        return entity_id

    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity
        self.command_queues.setdefault(entity.id, CommandQueue(entity.id))
        self.spatial_hash.insert(entity.id, entity.bounds)
        self._index_resource_node(entity)
        self._index_entity_tags(entity)
        self.recalculate_population()

    def update_entity_position(self, entity_id: EntityId, position: WorldPosition) -> None:
        entity = self.entities[entity_id]
        entity.position = position
        self.spatial_hash.move(entity_id, entity.bounds)

    def remove_entity(self, entity_id: EntityId) -> None:
        self.entities.pop(entity_id, None)
        self.command_queues.pop(entity_id, None)
        self.spatial_hash.remove(entity_id)
        self.unindex_resource_node(entity_id)
        self.unit_ids.discard(entity_id)
        self.hard_obstacle_ids.discard(entity_id)
        self.recalculate_population()

    def unindex_resource_node(self, entity_id: EntityId) -> None:
        self._remove_resource_node_index(entity_id)

    def _index_resource_node(self, entity: Entity) -> None:
        resource_type = _resource_type_for_index(entity)
        if resource_type is None:
            return
        for key in _resource_index_keys(resource_type):
            bucket = self.resource_nodes_by_type.setdefault(key, [])
            if entity.id not in bucket:
                bucket.append(entity.id)

    def _remove_resource_node_index(self, entity_id: EntityId) -> None:
        for bucket in self.resource_nodes_by_type.values():
            if entity_id in bucket:
                bucket.remove(entity_id)

    def _index_entity_tags(self, entity: Entity) -> None:
        tags = set(getattr(entity, "tags", ()))
        if "unit" in tags:
            self.unit_ids.add(entity.id)
        if bool(tags & {"building", "resource"}):
            self.hard_obstacle_ids.add(entity.id)

    def recalculate_population(self) -> None:
        self.completed_deposit_huts_by_owner.clear()
        self.current_population = sum(
            _population_cost(entity, self.settings.default_unit_pop_cost)
            for entity in self.entities.values()
        )
        self.max_population = sum(
            _population_cap_bonus(entity) for entity in self.entities.values()
        )
        for entity in self.entities.values():
            owner = _completed_deposit_hut_owner(entity)
            if owner is not None:
                self.completed_deposit_huts_by_owner.setdefault(owner, []).append(entity.id)

    def notify(self, message: str, *, duration_ms: int = 2500) -> None:
        self.notifications.append(Notification(message, duration_ms))

    def update_notifications(self, dt_ms: int) -> None:
        for notification in self.notifications:
            notification.remaining_ms -= max(0, int(dt_ms))
        self.notifications = [
            notification
            for notification in self.notifications
            if notification.remaining_ms > 0
        ]

    def enqueue_command(self, entity_id: EntityId, command: Command) -> None:
        queue = self.command_queues.setdefault(entity_id, CommandQueue(entity_id))
        if command.queued:
            queue.append(command)
        else:
            queue.replace(command)

    def to_json(self) -> dict[str, object]:
        return {
            "rng_seed": self.rng_seed,
            "elapsed_ms": self.elapsed_ms,
            "next_entity_id": self.next_entity_id,
            "resources": self.resources,
            "current_population": self.current_population,
            "max_population": self.max_population,
            "command_queues": [
                queue.to_json()
                for _, queue in sorted(
                    self.command_queues.items(),
                    key=lambda item: int(item[0]),
                )
            ],
        }

    @classmethod
    def from_json(cls, value: dict[str, object]) -> WorldState:
        world = cls(
            rng_seed=int(value.get("rng_seed", 1337)),
            elapsed_ms=int(value.get("elapsed_ms", 0)),
            next_entity_id=int(value.get("next_entity_id", 1)),
            resources=dict(value.get("resources", {})),
            current_population=int(value.get("current_population", 0)),
            max_population=int(value.get("max_population", 0)),
        )
        for queue_data in value.get("command_queues", []):
            queue = CommandQueue.from_json(queue_data)
            world.command_queues[queue.owner_id] = queue
        return world


def _population_cost(entity: object, default_cost: int) -> int:
    if (
        not getattr(entity, "alive", False)
        or getattr(entity, "owner", None) != "frontier"
        or "unit" not in getattr(entity, "tags", ())
    ):
        return 0
    return max(0, int(getattr(entity, "population_cost", default_cost)))


def _population_cap_bonus(entity: object) -> int:
    if (
        not getattr(entity, "alive", False)
        or getattr(entity, "owner", None) != "frontier"
        or "building" not in getattr(entity, "tags", ())
        or not bool(getattr(entity, "complete", True))
    ):
        return 0
    production_config = getattr(entity, "production_config", None)
    if production_config is None:
        return 0
    return max(0, int(production_config.population_cap_bonus))


def _completed_deposit_hut_owner(entity: object) -> str | None:
    if (
        not getattr(entity, "alive", False)
        or "building" not in getattr(entity, "tags", ())
        or not bool(getattr(entity, "complete", True))
    ):
        return None
    functions = getattr(entity, "functions", {})
    if not bool(functions.get("dropoff")):
        return None
    owner = getattr(entity, "owner", None)
    return str(owner) if owner is not None else None


def _resource_type_for_index(entity: object) -> str | None:
    tags = getattr(entity, "tags", ())
    if "resource" not in tags:
        return None
    resource_type = getattr(entity, "resource_type", None)
    if resource_type is None:
        return None
    return str(resource_type)


def _resource_index_keys(resource_type: str) -> tuple[str, ...]:
    if resource_type == "iron":
        return ("iron", "ore")
    if resource_type == "ore":
        return ("ore", "iron")
    return (resource_type,)

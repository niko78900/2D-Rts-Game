"""Selected-object panel view model and ability rules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from house_of_wolves.core.contracts import EntityId
from house_of_wolves.world.world import WorldState

ABILITY_ORDER = (
    "Move",
    "Attack",
    "Attack Move",
    "Stop",
    "Build",
    "Gather Wood",
    "Gather Gold",
    "Gather Ore",
    "Gather Stone",
    "Dropoff",
)


@dataclass(frozen=True, slots=True)
class SelectedPanel:
    """Text content for the selected object panel."""

    title: str
    subtitle: str
    health: str
    details: tuple[str, ...]
    abilities: tuple[str, ...]


def selected_panel_for(world: WorldState, selected_ids: Iterable[EntityId]) -> SelectedPanel:
    """Build selected unit/building/object UI text."""

    selected_entities = [
        world.entities[entity_id] for entity_id in selected_ids if entity_id in world.entities
    ]
    if not selected_entities:
        return SelectedPanel(
            title="No Selection",
            subtitle="Select a unit, building, or resource.",
            health="Health: -",
            details=("Left click or drag to select objects.",),
            abilities=(),
        )
    if len(selected_entities) > 1:
        return multi_selection_panel(selected_entities)

    entity = selected_entities[0]
    return SelectedPanel(
        title=entity_display_name(entity),
        subtitle=entity_subtitle(entity),
        health=entity_health_text(entity),
        details=entity_details(entity),
        abilities=entity_abilities(entity),
    )


def multi_selection_panel(entities: list[Any]) -> SelectedPanel:
    total_hp = sum(max(0, int(getattr(entity, "hp", 0))) for entity in entities)
    title = (
        "Multiple Units"
        if all(entity_is_unit(entity) for entity in entities)
        else "Multiple Selection"
    )
    return SelectedPanel(
        title=title,
        subtitle=f"{len(entities)} objects selected",
        health=f"Total Health: {total_hp}",
        details=(selection_breakdown(entities),),
        abilities=mutual_abilities(entities),
    )


def entity_display_name(entity: Any) -> str:
    names = {
        "settler": "Settler",
        "spearman": "Spearman",
        "archer": "Archer",
        "raider_swordsman": "Raider Swordsman",
        "hut": "Hut",
        "wood_tree": "Tree",
        "gold_mine": "Gold Mine",
        "stone_outcrop": "Stone Outcrop",
        "iron_deposit": "Ore Deposit",
    }
    for tag in getattr(entity, "tags", ()):
        if tag in names:
            return names[tag]
    return "Object"


def entity_subtitle(entity: Any) -> str:
    tags = set(getattr(entity, "tags", ()))
    owner = str(getattr(entity, "owner", "neutral")).title()
    if "unit" in tags:
        return f"{owner} Unit"
    if "building" in tags:
        return f"{owner} Building"
    if "resource" in tags:
        resource_type = str(getattr(entity, "resource_type", "resource")).title()
        return f"{resource_type} Resource"
    return f"{owner} Object"


def entity_health_text(entity: Any) -> str:
    tags = set(getattr(entity, "tags", ()))
    hp = max(0, int(getattr(entity, "hp", 0)))
    if "resource" in tags:
        amount = _resource_remaining(entity)
        resource_type = display_resource_type(str(getattr(entity, "resource_type", "resource")))
        return f"Health: {hp}    Remaining {resource_type}: {amount}"
    return f"Health: {hp}"


def entity_details(entity: Any) -> tuple[str, ...]:
    tags = set(getattr(entity, "tags", ()))
    if "unit" in tags:
        speed = round(float(getattr(entity, "speed", 0)))
        state = str(getattr(entity, "state", "idle")).title()
        return (f"Speed: {speed}", f"State: {state}")
    if "building" in tags:
        functions = getattr(entity, "functions", {})
        pop_bonus = functions.get("population_cap_bonus", 0)
        if not getattr(entity, "complete", False):
            return ("Status: Under Construction", f"Build Progress: {_build_progress(entity)}%")
        complete = "Complete"
        return (f"Status: {complete}", f"Population Bonus: {pop_bonus}")
    if "resource" in tags:
        slots = int(getattr(entity, "harvest_slots", 0))
        gather_time = int(getattr(entity, "gather_time_ms", 0))
        return (f"Harvest Slots: {slots}", f"Gather Time: {gather_time} ms")
    return ()


def entity_abilities(entity: Any) -> tuple[str, ...]:
    tags = set(getattr(entity, "tags", ()))
    owner = str(getattr(entity, "owner", "neutral"))
    if "unit" in tags and owner != "frontier":
        return ()
    abilities: list[str] = []
    if "movable" in tags:
        abilities.extend(["Move", "Attack Move", "Stop"])
    if "unit" in tags and int(getattr(entity, "damage", 0)) > 0:
        abilities.append("Attack")
    if "settler" in tags:
        abilities.extend(["Build", "Gather Wood", "Gather Gold", "Gather Ore", "Gather Stone"])
    if "building" in tags:
        functions = getattr(entity, "functions", {})
        if not bool(getattr(entity, "complete", True)):
            return ()
        if functions.get("dropoff"):
            abilities.append("Dropoff")
        for unit_id in functions.get("trainable_units", []):
            abilities.append(f"Produce {entity_display_from_id(str(unit_id))}")
    if "resource" in tags:
        resource_type = str(getattr(entity, "resource_type", "resource"))
        abilities.append(f"Gather {display_resource_type(resource_type)}")
    return ordered_abilities(abilities)


def mutual_abilities(entities: list[Any]) -> tuple[str, ...]:
    if not entities:
        return ()
    shared = set(entity_abilities(entities[0]))
    for entity in entities[1:]:
        shared &= set(entity_abilities(entity))
    return ordered_abilities(shared)


def ordered_abilities(abilities: Iterable[str]) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(abilities))
    order = {ability: index for index, ability in enumerate(ABILITY_ORDER)}
    return tuple(sorted(unique, key=lambda ability: (order.get(ability, len(order)), ability)))


def entity_is_unit(entity: Any) -> bool:
    return "unit" in getattr(entity, "tags", ())


def _build_progress(entity: Any) -> int:
    build_time = int(getattr(entity, "build_time_ms", 0) or 0)
    if build_time <= 0:
        return 100
    progress_ms = int(getattr(entity, "build_progress_ms", 0) or 0)
    return round(max(0.0, min(1.0, progress_ms / build_time)) * 100)


def entity_display_from_id(entity_id: str) -> str:
    return entity_id.replace("_", " ").title()


def display_resource_type(resource_type: str) -> str:
    if resource_type == "iron":
        return "Ore"
    return resource_type.title()


def _resource_remaining(entity: Any) -> int:
    amount = getattr(entity, "amount_remaining", None)
    if amount is not None:
        return max(0, int(amount))
    return max(0, int(getattr(entity, "hp", 0)))


def selection_breakdown(entities: list[Any]) -> str:
    counts: dict[str, int] = {}
    for entity in entities:
        tags = set(getattr(entity, "tags", ()))
        if "unit" in tags:
            key = "Units"
        elif "building" in tags:
            key = "Buildings"
        elif "resource" in tags:
            key = "Resources"
        else:
            key = "Objects"
        counts[key] = counts.get(key, 0) + 1
    return "  ".join(f"{key}: {value}" for key, value in counts.items())

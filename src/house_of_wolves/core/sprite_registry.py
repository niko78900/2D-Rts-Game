"""Processed sprite paths, lifecycle stage selection, and cached image loading."""

from __future__ import annotations

from pathlib import Path

import pygame

from house_of_wolves.systems.buildings import is_building_destroying
from house_of_wolves.systems.towers import (
    STONE_ARCHER_TOWER_ID,
    WIZARD_TOWER_ID,
    WOODEN_ARCHER_TOWER_ID,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

HUT_STAGE_SCAFFOLDING = "construction_0_50"
HUT_STAGE_PARTIAL = "construction_50_90"
HUT_STAGE_COMPLETE = "complete"

RESOURCE_SPRITE_ROOT = PROJECT_ROOT / "assets" / "art" / "resources" / "processed"
RESOURCE_STAGE_AMOUNT_100_75 = "amount_100_75"
RESOURCE_STAGE_AMOUNT_75_25 = "amount_75_25"
RESOURCE_STAGE_AMOUNT_25_0 = "amount_25_0"
RESOURCE_SPRITE_IDS = ("gold_mine", "iron_deposit", "stone_outcrop")
RESOURCE_SPRITE_STAGES = (
    RESOURCE_STAGE_AMOUNT_100_75,
    RESOURCE_STAGE_AMOUNT_75_25,
    RESOURCE_STAGE_AMOUNT_25_0,
)
RESOURCE_SPRITE_PATHS = {
    resource_id: {
        stage: RESOURCE_SPRITE_ROOT / resource_id / f"{stage}.png"
        for stage in RESOURCE_SPRITE_STAGES
    }
    for resource_id in RESOURCE_SPRITE_IDS
}
_RESOURCE_SPRITE_CACHE: dict[tuple[str, str, str, bool], pygame.Surface | None] = {}

BUILDING_SPRITE_ROOT = PROJECT_ROOT / "assets" / "art" / "buildings" / "processed"
BUILDING_STAGE_DAMAGE_75_50 = "damage_75_50"
BUILDING_STAGE_DAMAGE_50_25 = "damage_50_25"
BUILDING_STAGE_DAMAGE_25_10 = "damage_25_10"
BUILDING_STAGE_DESTROYED_10_0 = "destroyed_10_0"
BUILDING_SPRITE_BUILDING_IDS = (
    "hut",
    "barracks",
    "archery",
    "chicken_farm",
    "pig_farm",
    WOODEN_ARCHER_TOWER_ID,
    STONE_ARCHER_TOWER_ID,
    WIZARD_TOWER_ID,
)
BUILDING_SPRITE_STAGES = (
    HUT_STAGE_SCAFFOLDING,
    HUT_STAGE_PARTIAL,
    HUT_STAGE_COMPLETE,
    BUILDING_STAGE_DAMAGE_75_50,
    BUILDING_STAGE_DAMAGE_50_25,
    BUILDING_STAGE_DAMAGE_25_10,
    BUILDING_STAGE_DESTROYED_10_0,
)
BUILDING_SPRITE_PATHS = {
    building_id: {
        stage: BUILDING_SPRITE_ROOT / building_id / f"{stage}.png"
        for stage in BUILDING_SPRITE_STAGES
    }
    for building_id in BUILDING_SPRITE_BUILDING_IDS
}
BUILDING_SPRITE_PATHS[WIZARD_TOWER_ID] = BUILDING_SPRITE_PATHS[STONE_ARCHER_TOWER_ID]
_BUILDING_SPRITE_CACHE: dict[tuple[str, str, str, bool], pygame.Surface | None] = {}

HUT_CONSTRUCTION_SPRITES = {
    stage: str(BUILDING_SPRITE_PATHS["hut"][stage])
    for stage in (HUT_STAGE_SCAFFOLDING, HUT_STAGE_PARTIAL, HUT_STAGE_COMPLETE)
}


def resource_sprite_id_for(entity: object) -> str | None:
    """Return the normalized mine resource sprite id for an entity."""
    tags = set(getattr(entity, "tags", ()))
    for resource_id in RESOURCE_SPRITE_IDS:
        if resource_id in tags:
            return resource_id
    return None


def resource_sprite_stage_for(entity: object) -> str:
    """Return the resource sprite depletion stage for the current entity state."""
    if str(getattr(entity, "state", "active")) == "destroying":
        return RESOURCE_STAGE_AMOUNT_25_0
    max_hp = max(0, int(getattr(entity, "max_hp", 0) or getattr(entity, "hp", 0)))
    if max_hp <= 0:
        return RESOURCE_STAGE_AMOUNT_100_75
    hp_ratio = max(0.0, min(1.0, int(getattr(entity, "hp", 0)) / max_hp))
    if hp_ratio > 0.75:
        return RESOURCE_STAGE_AMOUNT_100_75
    if hp_ratio > 0.25:
        return RESOURCE_STAGE_AMOUNT_75_25
    return RESOURCE_STAGE_AMOUNT_25_0


def resource_sprite_reference_for(entity: object) -> str | None:
    """Return the processed sprite path expected for a mine resource entity."""
    resource_id = resource_sprite_id_for(entity)
    if resource_id is None:
        return None
    return str(RESOURCE_SPRITE_PATHS[resource_id][resource_sprite_stage_for(entity)])


def load_resource_sprite(resource_id: str, stage: str) -> pygame.Surface | None:
    """Load and cache one processed mine resource sprite."""
    path = RESOURCE_SPRITE_PATHS.get(resource_id, {}).get(stage)
    if path is None:
        return None
    return _load_sprite(path, (resource_id, stage), _RESOURCE_SPRITE_CACHE)


def building_sprite_id_for(entity: object) -> str | None:
    """Return the normalized building sprite id for an entity."""
    tags = set(getattr(entity, "tags", ()))
    if "hut" in tags:
        return "hut"
    if "barracks" in tags:
        return "barracks"
    if "archery" in tags or "archery_range" in tags:
        return "archery"
    if "chicken_farm" in tags:
        return "chicken_farm"
    if "pig_farm" in tags:
        return "pig_farm"
    if WOODEN_ARCHER_TOWER_ID in tags:
        return WOODEN_ARCHER_TOWER_ID
    if STONE_ARCHER_TOWER_ID in tags:
        return STONE_ARCHER_TOWER_ID
    if WIZARD_TOWER_ID in tags:
        return WIZARD_TOWER_ID
    return None


def building_sprite_stage_for(entity: object) -> str:
    """Return the building sprite lifecycle stage for the current entity state."""
    if is_building_destroying(entity):
        return BUILDING_STAGE_DESTROYED_10_0
    if not bool(getattr(entity, "complete", True)):
        progress = _building_progress_ratio(entity)
        if progress < 0.50:
            return HUT_STAGE_SCAFFOLDING
        if progress < 0.90:
            return HUT_STAGE_PARTIAL
        return HUT_STAGE_COMPLETE

    max_hp = max(0, int(getattr(entity, "max_hp", 0) or getattr(entity, "hp", 0)))
    if max_hp <= 0:
        return HUT_STAGE_COMPLETE
    hp_ratio = max(0.0, min(1.0, int(getattr(entity, "hp", 0)) / max_hp))
    if hp_ratio <= 0.10:
        return BUILDING_STAGE_DESTROYED_10_0
    if hp_ratio <= 0.25:
        return BUILDING_STAGE_DAMAGE_25_10
    if hp_ratio <= 0.50:
        return BUILDING_STAGE_DAMAGE_50_25
    if hp_ratio <= 0.75:
        return BUILDING_STAGE_DAMAGE_75_50
    return HUT_STAGE_COMPLETE


def building_sprite_reference_for(entity: object) -> str | None:
    """Return the processed sprite path expected for a building entity."""
    building_id = building_sprite_id_for(entity)
    if building_id is None:
        return None
    return str(BUILDING_SPRITE_PATHS[building_id][building_sprite_stage_for(entity)])


def load_building_sprite(building_id: str, stage: str) -> pygame.Surface | None:
    """Load and cache one processed building sprite."""
    path = BUILDING_SPRITE_PATHS.get(building_id, {}).get(stage)
    if path is None:
        return None
    return _load_sprite(path, (building_id, stage), _BUILDING_SPRITE_CACHE)


def hut_construction_stage_for(entity: object) -> str:
    """Return the Hut construction stage used by drawing and tests."""
    tags = set(getattr(entity, "tags", ()))
    if "hut" not in tags or bool(getattr(entity, "complete", True)):
        return HUT_STAGE_COMPLETE
    return building_sprite_stage_for(entity)


def hut_sprite_reference_for(entity: object) -> str:
    """Return the processed Hut sprite path for the current construction stage."""
    return str(BUILDING_SPRITE_PATHS["hut"][hut_construction_stage_for(entity)])


def _load_sprite(
    path: Path,
    cache_key_parts: tuple[str, str],
    cache: dict[tuple[str, str, str, bool], pygame.Surface | None],
) -> pygame.Surface | None:
    """Load one image with display-aware alpha conversion and cache misses."""
    can_convert = pygame.display.get_init() and pygame.display.get_surface() is not None
    cache_key = (*cache_key_parts, str(path), can_convert)
    if cache_key in cache:
        return cache[cache_key]
    if not path.exists():
        cache[cache_key] = None
        return None
    try:
        sprite = pygame.image.load(str(path))
        loaded = sprite.convert_alpha() if can_convert else sprite
    except pygame.error:
        loaded = None
    cache[cache_key] = loaded
    return loaded


def _building_progress_ratio(entity: object) -> float:
    """Return normalized construction progress for sprite-stage selection."""
    build_time = int(getattr(entity, "build_time_ms", 0) or 0)
    if build_time <= 0:
        return 1.0
    progress_ms = int(getattr(entity, "build_progress_ms", 0) or 0)
    return max(0.0, min(1.0, progress_ms / build_time))

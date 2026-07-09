"""Pygame renderer for the first playable slice."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from math import cos, hypot, sin
from pathlib import Path

import pygame

from house_of_wolves.core.contracts import Command, EntityId, Footprint, WorldPosition
from house_of_wolves.core.keybindings import (
    KEYBIND_ACTION_LABELS,
    KEYBIND_ACTION_ORDER,
    ability_display_label,
    formatted_key_name,
)
from house_of_wolves.core.performance import time_block
from house_of_wolves.core.settings import UI_PANEL_HEIGHT, AppSettings
from house_of_wolves.systems.buildings import is_building_destroying
from house_of_wolves.systems.combat import RANGED_ATTACK_WINDUP_MS
from house_of_wolves.systems.economy import (
    GATHER_SWING_MS,
    is_mine_resource,
    mine_harvest_area_bounds,
    mine_harvest_slot_candidates,
    tree_harvest_area_bounds,
    tree_harvest_slot_candidates,
)
from house_of_wolves.systems.farming import (
    animal_harvest_area_bounds,
    animal_harvest_slot_candidates,
)
from house_of_wolves.systems.selection import SelectionState
from house_of_wolves.ui.selected_panel import SelectedPanel, selected_panel_for
from house_of_wolves.world.collision import blocking_bounds_for_entity
from house_of_wolves.world.terrain import terrain_layout_for_height
from house_of_wolves.world.world import WorldState

ScreenRect = tuple[int, int, int, int]
PANEL_HEIGHT = UI_PANEL_HEIGHT
ABILITY_START_X = 520
ABILITY_START_Y_OFFSET = 18
ABILITY_ROW_HEIGHT = 30
ABILITY_CHIP_HEIGHT = 24
SETTINGS_BUTTON_WIDTH = 96
SETTINGS_BUTTON_HEIGHT = 28
SETTINGS_MENU_WIDTH = 320
SETTINGS_MENU_HEIGHT = 650
KEYBIND_ROW_HEIGHT = 24
KEYBIND_ROW_GAP = 3
KEYBIND_START_Y_OFFSET = 386
KEYBIND_ROWS_PER_COLUMN = 9
KEYBIND_COLUMN_GAP = 8
STATUS_BAR_HEIGHT = 6
SETTINGS_RESOURCE_GRANT_RESOURCES = (
    ("wood", "Wood"),
    ("food", "Food"),
    ("stone", "Stone"),
    ("iron", "Iron"),
    ("gold", "Gold"),
)
STATUS_BAR_TOP_MARGIN = 9
HEALTH_FILL = (54, 174, 86)
HEALTH_EMPTY = (139, 47, 43)
RESOURCE_FILL = (230, 193, 77)
RESOURCE_EMPTY = (118, 87, 35)
HUT_STAGE_SCAFFOLDING = "construction_0_50"
HUT_STAGE_PARTIAL = "construction_50_90"
HUT_STAGE_COMPLETE = "complete"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
BUILDING_SPRITE_BUILDING_IDS = ("hut", "barracks", "archery", "chicken_farm", "pig_farm")
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
_BUILDING_SPRITE_CACHE: dict[tuple[str, str, str, bool], pygame.Surface | None] = {}
HUT_CONSTRUCTION_SPRITES = {
    stage: str(BUILDING_SPRITE_PATHS["hut"][stage])
    for stage in (HUT_STAGE_SCAFFOLDING, HUT_STAGE_PARTIAL, HUT_STAGE_COMPLETE)
}
ANIMAL_SPRITE_PATHS = {
    "chicken": PROJECT_ROOT / "assets" / "art" / "resources" / "chicken.png",
    "pig": PROJECT_ROOT / "assets" / "art" / "resources" / "pig.png",
}


@dataclass(frozen=True, slots=True)
class AbilityButton:
    """Hit-test data for one selected-panel ability chip."""

    label: str
    rect: pygame.Rect
    display_label: str


@dataclass(frozen=True, slots=True)
class MoveTargetMarker:
    position: WorldPosition
    attack_move: bool = False


@dataclass(frozen=True, slots=True)
class StatusBarSpec:
    ratio: float
    fill_color: tuple[int, int, int]
    empty_color: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class UnitEquipmentVisual:
    """Derived placeholder equipment and normalized animation progress."""

    tool: str | None
    progress: float = 0.0


@dataclass(frozen=True, slots=True)
class BuildingPlacementPreview:
    building_id: str
    position: WorldPosition
    footprint: Footprint
    valid: bool

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Return the entity world-space bounds."""
        return self.footprint.bounds_at(self.position)


@dataclass(slots=True)
class GameRenderer:
    """Draws generated placeholder visuals for the demo world."""

    settings: AppSettings
    font: pygame.font.Font = field(init=False)
    small_font: pygame.font.Font = field(init=False)
    animal_sprites: dict[str, pygame.Surface] = field(init=False, repr=False)
    _scaled_sprite_cache: dict[tuple[str, tuple[int, int]], pygame.Surface] = field(
        init=False,
        repr=False,
    )
    _notification_surface_cache: dict[tuple[str, tuple[int, int, int]], pygame.Surface] = field(
        init=False,
        repr=False,
    )
    _damage_surface_cache: dict[tuple[int, tuple[int, int, int]], pygame.Surface] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Normalize derived state after dataclass initialization."""
        if not pygame.font.get_init():
            pygame.font.init()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)
        self.animal_sprites = _load_animal_sprites()
        self._scaled_sprite_cache = {}
        self._notification_surface_cache = {}
        self._damage_surface_cache = {}

    def render(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selection: SelectionState,
        fps: float,
        drag_rect: ScreenRect | None = None,
        active_ability: str | None = None,
        settings_open: bool = False,
        fullscreen: bool = False,
        ability_override: tuple[str, ...] | None = None,
        placement_preview: BuildingPlacementPreview | None = None,
        rebinding_action: str | None = None,
    ) -> None:
        """Render the current game frame or UI panel."""
        stats = world.performance_stats
        with time_block(stats, "render_background"):
            self._draw_background(surface, world)
        with time_block(stats, "render_entities"):
            self._draw_entities(surface, world, selection.selected_ids)
            self._draw_projectiles(surface, world)
            self._draw_combat_effects(surface, world)
            self._draw_attack_target_indicators(surface, world, selection.selected_ids)
        with time_block(stats, "render_waypoints"):
            self._draw_dropoff_markers(surface, world, selection.selected_ids)
            self._draw_destinations(surface, world, selection.selected_ids)
            if placement_preview is not None:
                self._draw_building_placement_preview(surface, world, placement_preview)
            if drag_rect is not None:
                self._draw_drag_rect(surface, drag_rect)
        with time_block(stats, "render_hud"):
            self._draw_hud(surface, world, selection, fps)
        with time_block(stats, "render_notifications"):
            self._draw_notifications(surface, world)
        with time_block(stats, "render_ui"):
            self._draw_selected_panel(surface, world, selection, active_ability, ability_override)
            self._draw_settings_button(surface)
            if self.settings.show_performance_overlay:
                self._draw_performance_overlay(surface, world, fps)
            if settings_open:
                self._draw_settings_menu(surface, fullscreen, rebinding_action)

    def _draw_background(self, surface: pygame.Surface, world: WorldState) -> None:
        """Draw background."""
        width, height = surface.get_size()
        layout = terrain_layout_for_height(height)
        sky_bottom = round(layout.sky_bottom_y)
        building_top = round(layout.building_lane_top_y)
        building_bottom = round(layout.building_lane_bottom_y)
        ground_top = round(layout.unit_walkable_top_y)
        ground_bottom = round(layout.unit_walkable_bottom_y)
        surface.fill((112, 168, 202))
        pygame.draw.rect(
            surface,
            (95, 151, 82),
            (0, building_top, width, building_bottom - building_top),
        )
        pygame.draw.rect(
            surface,
            (86, 147, 80),
            (0, ground_top, width, ground_bottom - ground_top),
        )
        pygame.draw.line(surface, (64, 112, 64), (0, ground_top), (width, ground_top), 2)
        pygame.draw.rect(
            surface,
            (72, 113, 65),
            (0, max(ground_top, ground_bottom - 46), width, 46),
        )
        pygame.draw.line(surface, (128, 114, 76), (0, ground_bottom), (width, ground_bottom), 2)

        camera_x = world.camera.x
        for base_x in range(-600, self.settings.world_width + 800, 520):
            screen_x = round(base_x - camera_x * 0.25)
            points = [
                (screen_x, sky_bottom),
                (screen_x + 180, round(sky_bottom * 0.64)),
                (screen_x + 390, sky_bottom),
            ]
            pygame.draw.polygon(surface, (90, 130, 118), points)

        for x in range(-200, self.settings.world_width + 400, 300):
            screen_x = round(x - camera_x)
            lane_y = round(ground_top + ((ground_bottom - ground_top) * 0.96))
            pygame.draw.line(
                surface,
                (65, 96, 55),
                (screen_x, lane_y),
                (screen_x + 170, lane_y),
                3,
            )

    def _draw_entities(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selected_ids: list[EntityId],
    ) -> None:
        """Draw entities."""
        selected = set(selected_ids)
        recent_hit_ids = {
            effect.target_entity_id
            for effect in world.combat_effects
            if effect.kind == "hit_flash" and effect.target_entity_id is not None
        }
        view_bounds = (
            world.camera.x - 160,
            -160,
            surface.get_width() + 320,
            max(1, surface.get_height() - PANEL_HEIGHT + 320),
        )
        visible_ids = world.spatial_hash.query(view_bounds)
        entities = sorted(
            (
                world.entities[entity_id]
                for entity_id in visible_ids
                if entity_id in world.entities and _renderable_entity(world.entities[entity_id])
            ),
            key=lambda entity: (entity.position.y, entity.position.x, int(entity.id)),
        )
        for entity in entities:
            rect = _screen_rect(world, entity.bounds)
            if not _rect_on_screen(surface, rect):
                continue
            tags = set(entity.tags)
            if "building" in tags:
                self._draw_building(surface, rect, entity)
                if self.settings.show_building_hitboxes:
                    self._draw_entity_hitbox(surface, rect, "building")
            elif "resource" in tags:
                self._draw_resource(surface, rect, entity)
                if self.settings.show_resource_hitboxes:
                    self._draw_resource_hitbox(surface, world, entity)
            else:
                self._draw_unit(surface, rect, entity, world)
                if self.settings.show_unit_hitboxes:
                    self._draw_entity_hitbox(surface, rect, "unit")
            if _status_bar_visible(entity, entity.id in selected, entity.id in recent_hit_ids):
                self._draw_status_bar(surface, rect, entity)
            if entity.id in selected:
                self._draw_selection(surface, rect, enemy=_is_enemy_entity(entity))

    def _draw_projectiles(self, surface: pygame.Surface, world: WorldState) -> None:
        """Draw lightweight arrows with a shaft and directional arrowhead."""
        for projectile in world.projectiles:
            screen = world.camera.world_to_screen(projectile.position)
            if not surface.get_rect().inflate(32, 32).collidepoint(screen):
                continue
            target_pos = projectile.target_pos or projectile.position
            direction_x = target_pos.x - projectile.position.x
            direction_y = target_pos.y - projectile.position.y
            length = hypot(direction_x, direction_y)
            if length <= 0.0001:
                direction_x, direction_y = 1.0, 0.0
            else:
                direction_x /= length
                direction_y /= length
            perpendicular = (-direction_y, direction_x)
            back = (
                screen[0] - direction_x * 9,
                screen[1] - direction_y * 9,
            )
            front = (
                screen[0] + direction_x * 9,
                screen[1] + direction_y * 9,
            )
            enemy = projectile.owner != "frontier"
            shaft = (205, 92, 82) if enemy else (226, 207, 113)
            outline = (75, 38, 42) if enemy else (77, 61, 35)
            pygame.draw.line(surface, outline, back, front, 4)
            pygame.draw.line(surface, shaft, back, front, 2)
            head_back = (
                front[0] - direction_x * 6,
                front[1] - direction_y * 6,
            )
            pygame.draw.polygon(
                surface,
                shaft,
                [
                    (front[0] + direction_x * 3, front[1] + direction_y * 3),
                    (
                        head_back[0] + perpendicular[0] * 4,
                        head_back[1] + perpendicular[1] * 4,
                    ),
                    (
                        head_back[0] - perpendicular[0] * 4,
                        head_back[1] - perpendicular[1] * 4,
                    ),
                ],
            )

    def _draw_combat_effects(self, surface: pygame.Surface, world: WorldState) -> None:
        """Draw bounded hit, strike, death, damage, and wave visuals."""
        for effect in world.combat_effects:
            duration = max(1, int(effect.duration_ms))
            progress = 1.0 - max(0.0, min(1.0, effect.remaining_ms / duration))
            position = effect.position
            target = (
                world.entities.get(effect.target_entity_id)
                if effect.target_entity_id is not None
                else None
            )
            if target is not None:
                position = _entity_visual_center(target)
            screen = world.camera.world_to_screen(position)
            if not surface.get_rect().inflate(100, 100).collidepoint(screen):
                continue

            if effect.kind == "hit_flash":
                if not self.settings.show_debug_hit_flashes:
                    continue
                if target is not None:
                    target_rect = _screen_rect(world, target.bounds).inflate(6, 6)
                    if "building" in getattr(target, "tags", ()):
                        pygame.draw.rect(
                            surface,
                            (255, 244, 209),
                            target_rect,
                            width=3,
                            border_radius=4,
                        )
                    else:
                        pygame.draw.ellipse(surface, (255, 244, 209), target_rect, width=3)
                else:
                    pygame.draw.circle(surface, (255, 244, 209), screen, 16, width=3)
                continue

            if effect.kind == "damage_number" and effect.value is not None:
                color = (246, 103, 92) if effect.owner != "frontier" else (247, 219, 108)
                key = (int(effect.value), color)
                text = self._damage_surface_cache.get(key)
                if text is None:
                    text = self.small_font.render(f"-{effect.value}", True, color)
                    if len(self._damage_surface_cache) > 48:
                        self._damage_surface_cache.clear()
                    self._damage_surface_cache[key] = text
                draw_pos = (
                    round(screen[0] - text.get_width() / 2),
                    round(screen[1] - 20 - progress * 24),
                )
                surface.blit(text, draw_pos)
                continue

            if effect.kind == "unit_fall":
                self._draw_unit_fall(surface, screen, effect, progress)
                continue

            if effect.kind == "melee_strike":
                reach = 18 + round(progress * 12)
                direction = (effect.direction_x, effect.direction_y)
                perpendicular = (-direction[1], direction[0])
                start = (
                    screen[0] + direction[0] * 5,
                    screen[1] + direction[1] * 5,
                )
                end = (
                    screen[0] + direction[0] * reach,
                    screen[1] + direction[1] * reach,
                )
                color = (235, 102, 91) if effect.owner != "frontier" else (244, 224, 143)
                pygame.draw.line(surface, color, start, end, 4)
                pygame.draw.line(
                    surface,
                    color,
                    (
                        end[0] - direction[0] * 5 + perpendicular[0] * 7,
                        end[1] - direction[1] * 5 + perpendicular[1] * 7,
                    ),
                    (
                        end[0] - direction[0] * 5 - perpendicular[0] * 7,
                        end[1] - direction[1] * 5 - perpendicular[1] * 7,
                    ),
                    2,
                )
                continue

            if effect.kind == "spawn_marker":
                radius = 34 + round(progress * 28)
                color = (184, 60, 64)
                pygame.draw.circle(surface, color, screen, radius, width=3)
                pygame.draw.line(
                    surface,
                    color,
                    (screen[0], screen[1] - radius - 18),
                    (screen[0], screen[1] - radius + 2),
                    4,
                )

    def _draw_unit_fall(
        self,
        surface: pygame.Surface,
        ground_position: tuple[int, int],
        effect: object,
        progress: float,
    ) -> None:
        """Draw a dead unit collapsing in the incoming hit direction."""
        fall_x = float(getattr(effect, "direction_x", 1.0))
        fall_y = float(getattr(effect, "direction_y", 0.0))
        direction_length = hypot(fall_x, fall_y)
        if direction_length <= 0.0001:
            fall_x, fall_y = 1.0, 0.0
        else:
            fall_x /= direction_length
            fall_y /= direction_length

        width = max(16.0, float(getattr(effect, "visual_width", 38.0)))
        height = max(20.0, float(getattr(effect, "visual_height", 58.0)))
        eased = min(1.0, max(0.0, progress))
        body_width = _lerp(max(10.0, width - 10.0), height * 0.72, eased)
        body_height = _lerp(max(14.0, height - 15.0), max(8.0, width * 0.30), eased)
        shift_x = fall_x * height * 0.34 * eased
        shift_y = abs(fall_y) * 6.0 * eased
        body_center_x = ground_position[0] + shift_x
        body_bottom = ground_position[1] + shift_y
        body_rect = pygame.Rect(
            round(body_center_x - body_width / 2),
            round(body_bottom - body_height),
            max(1, round(body_width)),
            max(1, round(body_height)),
        )
        tags = tuple(getattr(effect, "visual_tags", ()))
        enemy = getattr(effect, "owner", "neutral") not in {"frontier", "neutral"}
        color = _unit_body_color(tags, enemy)
        outline = (42, 27, 31) if enemy else (27, 38, 31)

        shadow = pygame.Rect(
            body_rect.left - 3,
            round(body_bottom - 6),
            body_rect.width + 6,
            10,
        )
        pygame.draw.ellipse(surface, (33, 42, 34), shadow)
        pygame.draw.ellipse(surface, color, body_rect)
        pygame.draw.ellipse(surface, outline, body_rect, width=2)

        head_radius = max(4, min(8, round(width / 5)))
        upright_head = (
            float(ground_position[0]),
            float(ground_position[1] - height + 12),
        )
        fallen_head = (
            float(ground_position[0] + fall_x * height * 0.62),
            float(ground_position[1] - head_radius + shift_y),
        )
        head_center = (
            round(_lerp(upright_head[0], fallen_head[0], eased)),
            round(_lerp(upright_head[1], fallen_head[1], eased)),
        )
        pygame.draw.circle(surface, _unit_head_color(enemy), head_center, head_radius)
        pygame.draw.circle(surface, outline, head_center, head_radius, width=1)

    def _draw_attack_target_indicators(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selected_ids: list[EntityId],
    ) -> None:
        """Mark targets currently attacked by selected player units."""
        for target_id in _selected_attack_target_ids(world, selected_ids):
            target = world.entities.get(target_id)
            if target is None or not getattr(target, "alive", False):
                continue
            rect = _screen_rect(world, target.bounds)
            marker = pygame.Rect(
                rect.left - 7,
                rect.bottom - 14,
                rect.width + 14,
                20,
            )
            pygame.draw.ellipse(surface, (225, 72, 67), marker, width=3)

    def _draw_unit(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        entity: object,
        world: WorldState,
    ) -> None:
        """Draw a readable primitive placeholder for one unit type."""
        tags = tuple(getattr(entity, "tags", ()))
        enemy = _is_enemy_entity(entity)
        color = _unit_body_color(tags, enemy)
        outline = (42, 27, 31) if enemy else (27, 38, 31)
        state = str(getattr(entity, "state", "idle"))
        if self.settings.show_debug_hit_flashes:
            if state == "attack_windup":
                outline = (246, 211, 105)
            elif state == "attacking":
                outline = (248, 238, 205)

        shadow = pygame.Rect(rect.left - 2, rect.bottom - 13, rect.width + 4, 13)
        pygame.draw.ellipse(surface, (33, 42, 34), shadow)
        body = pygame.Rect(
            rect.left + 5,
            rect.top + 13,
            max(8, rect.width - 10),
            max(12, rect.height - 15),
        )
        pygame.draw.rect(surface, color, body, border_radius=7)
        pygame.draw.rect(surface, outline, body, width=2, border_radius=7)
        head_radius = max(4, min(8, rect.width // 5))
        head_center = (rect.centerx, rect.top + 12)
        pygame.draw.circle(surface, _unit_head_color(enemy), head_center, head_radius)
        pygame.draw.circle(surface, outline, head_center, head_radius, width=1)

        facing_x = float(getattr(entity, "facing_x", 1.0))
        facing_y = float(getattr(entity, "facing_y", 0.0))
        facing_length = hypot(facing_x, facing_y)
        if facing_length <= 0.0001:
            facing_x, facing_y = 1.0, 0.0
        else:
            facing_x /= facing_length
            facing_y /= facing_length
        equipment = _unit_equipment_for(world, entity)
        self._draw_unit_equipment(
            surface,
            rect,
            tags,
            enemy,
            facing_x,
            facing_y,
            equipment,
        )
        self._draw_label(surface, _short_label(tags), body.center)

    def _draw_unit_equipment(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        tags: tuple[str, ...],
        enemy: bool,
        facing_x: float,
        facing_y: float,
        equipment: UnitEquipmentVisual,
    ) -> None:
        """Draw a tool, spear, sword, or bow in the unit's facing direction."""
        center = (float(rect.centerx), float(rect.centery + 3))
        perpendicular = (-facing_y, facing_x)
        weapon_color = (70, 48, 34) if not enemy else (55, 39, 46)
        metal_color = (213, 213, 194) if not enemy else (226, 176, 177)

        if equipment.tool == "bow":
            draw_progress = max(0.0, min(1.0, equipment.progress))
            grip = _offset_point(center, facing_x, facing_y, 9)
            bow_center = _offset_point(center, facing_x, facing_y, 17)
            upper = (
                bow_center[0] + perpendicular[0] * 11 - facing_x * 4,
                bow_center[1] + perpendicular[1] * 11 - facing_y * 4,
            )
            lower = (
                bow_center[0] - perpendicular[0] * 11 - facing_x * 4,
                bow_center[1] - perpendicular[1] * 11 - facing_y * 4,
            )
            pygame.draw.lines(surface, weapon_color, False, [upper, bow_center, lower], 3)
            nock = _offset_point(
                grip,
                facing_x,
                facing_y,
                -(2.0 + draw_progress * 8.0),
            )
            pygame.draw.lines(surface, (204, 194, 157), False, [upper, nock, lower], 1)
            if draw_progress > 0:
                arrow_front = _offset_point(bow_center, facing_x, facing_y, 8)
                pygame.draw.line(surface, metal_color, nock, arrow_front, 2)
            return

        if equipment.tool == "spear":
            start = _offset_point(center, facing_x, facing_y, -8)
            tip = _offset_point(center, facing_x, facing_y, 31)
            pygame.draw.line(surface, weapon_color, start, tip, 3)
            _draw_weapon_tip(surface, tip, facing_x, facing_y, metal_color)
            return

        if equipment.tool in {"axe", "pickaxe"}:
            tool_x, tool_y = _tool_swing_direction(
                facing_x,
                facing_y,
                equipment.progress,
            )
            tool_perpendicular = (-tool_y, tool_x)
            start = _offset_point(center, tool_x, tool_y, -3)
            tip = _offset_point(center, tool_x, tool_y, 22)
            pygame.draw.line(surface, weapon_color, start, tip, 3)
            if equipment.tool == "pickaxe":
                pick_left = (
                    tip[0] + tool_perpendicular[0] * 8,
                    tip[1] + tool_perpendicular[1] * 8,
                )
                pick_right = (
                    tip[0] - tool_perpendicular[0] * 8,
                    tip[1] - tool_perpendicular[1] * 8,
                )
                pygame.draw.line(surface, metal_color, pick_left, pick_right, 4)
            else:
                blade_outer = (
                    tip[0] + tool_perpendicular[0] * 8 - tool_x * 4,
                    tip[1] + tool_perpendicular[1] * 8 - tool_y * 4,
                )
                blade_inner = (
                    tip[0] + tool_perpendicular[0] * 3 - tool_x * 7,
                    tip[1] + tool_perpendicular[1] * 3 - tool_y * 7,
                )
                pygame.draw.polygon(surface, metal_color, [tip, blade_outer, blade_inner])
            return

        if equipment.tool is None:
            return

        start = _offset_point(center, facing_x, facing_y, -3)
        tip = _offset_point(center, facing_x, facing_y, 23)
        pygame.draw.line(surface, metal_color, start, tip, 4)
        guard_left = (
            start[0] + perpendicular[0] * 6,
            start[1] + perpendicular[1] * 6,
        )
        guard_right = (
            start[0] - perpendicular[0] * 6,
            start[1] - perpendicular[1] * 6,
        )
        pygame.draw.line(surface, weapon_color, guard_left, guard_right, 3)

    def _draw_resource(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        entity: object,
    ) -> None:
        """Draw resource."""
        tags = tuple(entity) if isinstance(entity, tuple) else tuple(getattr(entity, "tags", ()))
        if "chicken" in tags:
            if self._draw_animal_sprite(surface, rect, "chicken"):
                return
            pygame.draw.ellipse(surface, (246, 241, 212), rect)
            pygame.draw.circle(surface, (238, 195, 77), (rect.right - 4, rect.centery - 2), 4)
            pygame.draw.line(
                surface,
                (144, 96, 42),
                rect.midbottom,
                (rect.centerx - 4, rect.bottom + 4),
                2,
            )
            pygame.draw.line(
                surface,
                (144, 96, 42),
                rect.midbottom,
                (rect.centerx + 4, rect.bottom + 4),
                2,
            )
            return
        if "pig" in tags:
            if self._draw_animal_sprite(surface, rect, "pig"):
                return
            pygame.draw.ellipse(surface, (219, 130, 149), rect)
            pygame.draw.circle(surface, (236, 154, 169), (rect.right - 6, rect.centery), 6)
            pygame.draw.rect(surface, (83, 50, 55), rect, width=1, border_radius=5)
            return
        if "food_carcass" in tags:
            pygame.draw.ellipse(surface, (151, 91, 70), rect.inflate(4, -4))
            pygame.draw.line(surface, (224, 205, 158), rect.midleft, rect.midright, 2)
            return
        if "wood_tree" in tags:
            trunk = pygame.Rect(rect.centerx - 8, rect.bottom - 45, 16, 45)
            pygame.draw.rect(surface, (93, 61, 42), trunk)
            pygame.draw.circle(surface, (46, 117, 65), (rect.centerx, rect.top + 42), 42)
            pygame.draw.circle(surface, (58, 137, 72), (rect.centerx - 24, rect.top + 54), 28)
        else:
            if self._draw_resource_sprite(surface, rect, entity):
                return
            inner_color = (197, 168, 78)
            if "iron_deposit" in tags:
                inner_color = (24, 24, 24)
            elif "stone_outcrop" in tags:
                inner_color = (154, 154, 148)
            pygame.draw.ellipse(surface, (112, 102, 82), rect)
            pygame.draw.ellipse(surface, inner_color, rect.inflate(-30, -24))

    def _draw_animal_sprite(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        sprite_id: str,
    ) -> bool:
        """Draw animal sprite."""
        sprite = self.animal_sprites.get(sprite_id)
        if sprite is None:
            return False
        target_size = _sprite_target_size(sprite, rect)
        cache_key = (sprite_id, target_size)
        scaled = self._scaled_sprite_cache.get(cache_key)
        if scaled is None:
            scaled = pygame.transform.smoothscale(sprite, target_size)
            self._scaled_sprite_cache[cache_key] = scaled
        surface.blit(scaled, scaled.get_rect(center=rect.center))
        return True

    def _draw_resource_sprite(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        entity: object,
    ) -> bool:
        """Draw a processed resource sprite when one exists for the depletion stage."""
        resource_id = resource_sprite_id_for(entity)
        if resource_id is None:
            return False
        stage = resource_sprite_stage_for(entity)
        sprite = _load_resource_sprite(resource_id, stage)
        if sprite is None:
            return False
        target_size = _fit_sprite_inside_rect(sprite, rect)
        cache_key = (f"resource:{resource_id}:{stage}", target_size)
        scaled = self._scaled_sprite_cache.get(cache_key)
        if scaled is None:
            scaled = pygame.transform.smoothscale(sprite, target_size)
            self._scaled_sprite_cache[cache_key] = scaled
        surface.blit(scaled, scaled.get_rect(midbottom=rect.midbottom))
        return True

    def _draw_resource_hitbox(
        self,
        surface: pygame.Surface,
        world: WorldState,
        entity: object,
    ) -> None:
        """Draw resource hitbox."""
        rect = _screen_rect(world, blocking_bounds_for_entity(entity))
        pygame.draw.rect(surface, (238, 218, 111), rect, width=2, border_radius=8)
        if "farm_food" in getattr(entity, "tags", ()):
            harvest_rect = _screen_rect(world, animal_harvest_area_bounds(entity))
            pygame.draw.rect(surface, (238, 78, 78), harvest_rect, width=1)
            for slot in animal_harvest_slot_candidates(world, entity):
                pygame.draw.circle(surface, (238, 78, 78), world.camera.world_to_screen(slot), 3)
            return
        if is_mine_resource(entity):
            harvest_rect = _screen_rect(world, mine_harvest_area_bounds(entity))
            pygame.draw.rect(surface, (238, 78, 78), harvest_rect, width=1)
            for slot in mine_harvest_slot_candidates(world, entity):
                pygame.draw.circle(surface, (238, 78, 78), world.camera.world_to_screen(slot), 3)
            return
        if "wood_tree" not in getattr(entity, "tags", ()):
            return
        harvest_rect = _screen_rect(world, tree_harvest_area_bounds(entity))
        pygame.draw.rect(surface, (238, 78, 78), harvest_rect, width=1)
        for slot in tree_harvest_slot_candidates(world, entity):
            pygame.draw.circle(surface, (238, 78, 78), world.camera.world_to_screen(slot), 3)

    def _draw_entity_hitbox(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        kind: str,
    ) -> None:
        """Draw entity hitbox."""
        color = (87, 211, 239) if kind == "unit" else (238, 112, 222)
        pygame.draw.rect(surface, color, rect, width=2, border_radius=6)

    def _draw_building(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        entity: object,
    ) -> None:
        """Draw building."""
        if self._draw_building_sprite(surface, rect, entity):
            return
        tags = tuple(getattr(entity, "tags", ()))
        if "chicken_farm" in tags:
            self._draw_chicken_farm(surface, rect, complete=bool(getattr(entity, "complete", True)))
            self._draw_label(surface, _short_label(tags), rect.center)
            return
        if "pig_farm" in tags:
            self._draw_pig_farm(surface, rect, complete=bool(getattr(entity, "complete", True)))
            self._draw_label(surface, _short_label(tags), rect.center)
            return
        if "barracks" in tags:
            self._draw_barracks(surface, rect, complete=bool(getattr(entity, "complete", True)))
            self._draw_label(surface, _short_label(tags), rect.center)
            return
        if "archery" in tags or "archery_range" in tags:
            self._draw_archery(surface, rect, complete=bool(getattr(entity, "complete", True)))
            self._draw_label(surface, _short_label(tags), rect.center)
            return
        stage = hut_construction_stage_for(entity)
        if stage == HUT_STAGE_SCAFFOLDING:
            self._draw_hut_scaffolding(surface, rect)
        elif stage == HUT_STAGE_PARTIAL:
            self._draw_hut_partial(surface, rect)
        else:
            self._draw_hut_complete(surface, rect)
        self._draw_label(surface, _short_label(tags), rect.center)

    def _draw_building_sprite(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        entity: object,
    ) -> bool:
        """Draw a processed building sprite when one exists for the entity stage."""
        building_id = building_sprite_id_for(entity)
        if building_id is None:
            return False
        stage = building_sprite_stage_for(entity)
        sprite = _load_building_sprite(building_id, stage)
        if sprite is None:
            return False
        target_size = _fit_sprite_inside_rect(sprite, rect)
        cache_key = (f"building:{building_id}:{stage}", target_size)
        scaled = self._scaled_sprite_cache.get(cache_key)
        if scaled is None:
            scaled = pygame.transform.smoothscale(sprite, target_size)
            self._scaled_sprite_cache[cache_key] = scaled
        surface.blit(scaled, scaled.get_rect(midbottom=rect.midbottom))
        return True

    def _draw_hut_scaffolding(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """Draw hut scaffolding."""
        outline = (194, 183, 128)
        pygame.draw.rect(surface, (72, 76, 61), rect, width=3, border_radius=4)
        for x in (rect.left + 18, rect.centerx, rect.right - 18):
            pygame.draw.line(surface, outline, (x, rect.top + 6), (x, rect.bottom - 4), 3)
        for y in (rect.top + 18, rect.centery, rect.bottom - 18):
            pygame.draw.line(surface, outline, (rect.left + 8, y), (rect.right - 8, y), 3)
        pygame.draw.line(surface, outline, rect.bottomleft, rect.topright, 2)
        pygame.draw.line(surface, outline, rect.topleft, rect.bottomright, 2)

    def _draw_hut_partial(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """Draw hut partial."""
        pygame.draw.rect(surface, (102, 78, 55), rect, border_radius=4)
        pygame.draw.rect(surface, (194, 183, 128), rect, width=3, border_radius=4)
        pygame.draw.line(
            surface,
            (82, 58, 47),
            (rect.left + 14, rect.top + 28),
            (rect.right - 14, rect.top + 28),
            5,
        )

    def _draw_hut_complete(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """Draw hut complete."""
        pygame.draw.rect(surface, (115, 80, 54), rect, border_radius=4)
        roof = [
            (rect.left - 10, rect.top + 28),
            (rect.centerx, rect.top - 18),
            (rect.right + 10, rect.top + 28),
        ]
        pygame.draw.polygon(surface, (82, 58, 47), roof)
        pygame.draw.rect(surface, (49, 36, 32), rect, width=3, border_radius=4)

    def _draw_chicken_farm(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        complete: bool,
    ) -> None:
        """Draw chicken farm."""
        fill = (132, 93, 58) if complete else (88, 89, 72)
        pygame.draw.rect(surface, fill, rect, border_radius=4)
        roof = pygame.Rect(
            rect.left + 12,
            rect.top + 10,
            rect.width - 24,
            max(10, rect.height // 4),
        )
        pygame.draw.rect(surface, (86, 57, 44), roof, border_radius=3)
        door = pygame.Rect(rect.centerx - 12, rect.bottom - 28, 24, 22)
        pygame.draw.rect(surface, (42, 35, 30), door, border_radius=2)
        pygame.draw.rect(surface, (48, 36, 30), rect, width=3, border_radius=4)
        if not complete:
            pygame.draw.line(surface, (196, 181, 119), rect.topleft, rect.bottomright, 2)
            pygame.draw.line(surface, (196, 181, 119), rect.bottomleft, rect.topright, 2)

    def _draw_pig_farm(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        complete: bool,
    ) -> None:
        """Draw pig farm."""
        pen_color = (102, 76, 52) if complete else (88, 89, 72)
        pygame.draw.rect(surface, (83, 112, 67), rect, border_radius=4)
        for x in range(rect.left + 8, rect.right, 22):
            pygame.draw.line(surface, pen_color, (x, rect.top + 6), (x, rect.bottom - 6), 4)
        pygame.draw.rect(surface, pen_color, rect, width=4, border_radius=4)
        pygame.draw.ellipse(
            surface,
            (219, 130, 149),
            rect.inflate(-rect.width // 2, -rect.height // 2),
        )
        if not complete:
            pygame.draw.line(surface, (196, 181, 119), rect.topleft, rect.bottomright, 2)
            pygame.draw.line(surface, (196, 181, 119), rect.bottomleft, rect.topright, 2)

    def _draw_barracks(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        complete: bool,
    ) -> None:
        """Draw the placeholder Barracks building."""
        fill = (107, 82, 62) if complete else (80, 83, 68)
        roof = pygame.Rect(rect.left + 10, rect.top + 8, rect.width - 20, rect.height // 3)
        door = pygame.Rect(rect.centerx - 16, rect.bottom - 34, 32, 30)
        pygame.draw.rect(surface, fill, rect, border_radius=4)
        pygame.draw.rect(surface, (71, 52, 45), roof, border_radius=3)
        pygame.draw.rect(surface, (45, 38, 34), door, border_radius=2)
        for x in (rect.left + 22, rect.right - 22):
            pygame.draw.line(surface, (184, 166, 109), (x, rect.top + 18), (x, rect.bottom - 10), 3)
        pygame.draw.rect(surface, (39, 33, 30), rect, width=3, border_radius=4)
        if not complete:
            pygame.draw.line(surface, (196, 181, 119), rect.topleft, rect.bottomright, 2)
            pygame.draw.line(surface, (196, 181, 119), rect.bottomleft, rect.topright, 2)

    def _draw_archery(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        complete: bool,
    ) -> None:
        """Draw the placeholder Archery building."""
        fill = (105, 97, 65) if complete else (80, 83, 68)
        pygame.draw.rect(surface, fill, rect, border_radius=4)
        target = pygame.Rect(rect.centerx - 26, rect.top + 18, 52, 52)
        pygame.draw.ellipse(surface, (206, 190, 126), target)
        pygame.draw.ellipse(surface, (115, 68, 57), target.inflate(-14, -14), width=4)
        pygame.draw.line(
            surface,
            (58, 44, 33),
            (rect.left + 18, rect.bottom - 18),
            (rect.right - 18, rect.top + 18),
            4,
        )
        pygame.draw.line(
            surface,
            (58, 44, 33),
            (rect.left + 18, rect.top + 18),
            (rect.right - 18, rect.bottom - 18),
            2,
        )
        pygame.draw.rect(surface, (39, 33, 30), rect, width=3, border_radius=4)
        if not complete:
            pygame.draw.line(surface, (196, 181, 119), rect.topleft, rect.bottomright, 2)
            pygame.draw.line(surface, (196, 181, 119), rect.bottomleft, rect.topright, 2)

    def _draw_building_placement_preview(
        self,
        surface: pygame.Surface,
        world: WorldState,
        preview: BuildingPlacementPreview,
    ) -> None:
        """Draw building placement preview."""
        rect = _screen_rect(world, preview.bounds)
        if not _rect_on_screen(surface, rect):
            return
        color = (104, 190, 112) if preview.valid else (220, 82, 70)
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        overlay.fill((*color, 42))
        surface.blit(overlay, rect)
        pygame.draw.rect(surface, color, rect, width=3, border_radius=4)
        if preview.building_id == "hut":
            roof = [
                (rect.left - 10, rect.top + 28),
                (rect.centerx, rect.top - 18),
                (rect.right + 10, rect.top + 28),
            ]
            pygame.draw.polygon(surface, color, roof, width=2)
        elif preview.building_id in {"barracks", "archery"}:
            pygame.draw.rect(surface, color, rect.inflate(-18, -18), width=2, border_radius=4)
        elif preview.building_id == "pig_farm":
            pygame.draw.rect(surface, color, rect.inflate(-16, -16), width=2, border_radius=4)
        else:
            pygame.draw.line(
                surface,
                color,
                (rect.left + 12, rect.top + 18),
                (rect.right - 12, rect.top + 18),
                2,
            )
        self._draw_label(surface, preview.building_id[:3].upper(), rect.center)

    def _draw_selection(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        enemy: bool = False,
    ) -> None:
        """Draw selection."""
        marker = pygame.Rect(rect.left - 5, rect.bottom - 12, rect.width + 10, 18)
        color = (231, 84, 72) if enemy else (235, 220, 118)
        pygame.draw.ellipse(surface, color, marker, width=3)

    def _draw_status_bar(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        entity: object,
    ) -> None:
        """Draw status bar."""
        spec = status_bar_for_entity(entity)
        if spec is None:
            return
        width = max(32, rect.width)
        bar_rect = pygame.Rect(
            rect.centerx - (width // 2),
            rect.top - STATUS_BAR_TOP_MARGIN,
            width,
            STATUS_BAR_HEIGHT,
        )
        if not surface.get_rect().colliderect(bar_rect):
            return
        pygame.draw.rect(surface, spec.empty_color, bar_rect)
        fill_width = round(bar_rect.width * spec.ratio)
        if fill_width > 0:
            pygame.draw.rect(
                surface,
                spec.fill_color,
                (bar_rect.left, bar_rect.top, fill_width, bar_rect.height),
            )
        pygame.draw.rect(surface, (26, 29, 24), bar_rect, width=1)

    def _draw_destinations(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selected_ids: list[EntityId],
    ) -> None:
        """Draw destinations."""
        if self.settings.show_debug_waypoints:
            self._draw_debug_destinations(surface, world, selected_ids)
            return

        markers = gameplay_waypoint_markers(world, selected_ids)
        links = gameplay_waypoint_links(world, selected_ids)
        if not markers and not links:
            return
        for origin, move_targets in links:
            previous_screen = world.camera.world_to_screen(origin)
            for target in move_targets:
                current_screen = world.camera.world_to_screen(target.position)
                draw_dotted_line(
                    surface,
                    _gameplay_waypoint_link_color(target.attack_move),
                    previous_screen,
                    current_screen,
                )
                self._draw_gameplay_link_endpoint(
                    surface,
                    current_screen,
                    attack_move=target.attack_move,
                )
                previous_screen = current_screen

        for target in markers:
            current_screen = world.camera.world_to_screen(target.position)
            self._draw_gameplay_destination_marker(
                surface,
                current_screen,
                attack_move=target.attack_move,
            )

    def _draw_debug_destinations(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selected_ids: list[EntityId],
    ) -> None:
        """Draw debug destinations."""
        for entity_id, move_targets in queued_move_markers(world, selected_ids):
            entity = world.entities.get(entity_id)
            if entity is None:
                continue
            previous_screen = world.camera.world_to_screen(entity.position)
            for index, target in enumerate(move_targets, start=1):
                current_screen = world.camera.world_to_screen(target.position)
                draw_dotted_line(
                    surface,
                    _destination_line_color(target.attack_move),
                    previous_screen,
                    current_screen,
                )
                self._draw_debug_destination_marker(
                    surface,
                    current_screen,
                    index,
                    attack_move=target.attack_move,
                )
                previous_screen = current_screen

    def _draw_dropoff_markers(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selected_ids: list[EntityId],
    ) -> None:
        """Draw dropoff markers."""
        for entity_id in selected_ids:
            entity = world.entities.get(entity_id)
            dropoff_point = getattr(entity, "dropoff_point", None)
            if dropoff_point is None:
                continue
            self._draw_dropoff_flag(surface, world.camera.world_to_screen(dropoff_point))

    def _draw_dropoff_flag(self, surface: pygame.Surface, screen_pos: tuple[int, int]) -> None:
        """Draw dropoff flag."""
        x, y = screen_pos
        pygame.draw.line(surface, (18, 18, 18), (x, y), (x, y - 50), 4)
        pygame.draw.polygon(
            surface,
            (45, 112, 204),
            [(x + 2, y - 48), (x + 38, y - 36), (x + 2, y - 24)],
        )
        pygame.draw.polygon(
            surface,
            (15, 38, 74),
            [(x + 2, y - 48), (x + 38, y - 36), (x + 2, y - 24)],
            width=2,
        )
        pygame.draw.circle(surface, (18, 18, 18), (x, y), 5)

    def _draw_gameplay_destination_marker(
        self,
        surface: pygame.Surface,
        screen_pos: tuple[int, int],
        *,
        attack_move: bool = False,
    ) -> None:
        """Draw gameplay destination marker."""
        x, y = screen_pos
        color = _destination_marker_color(attack_move, 1)
        outline = (112, 54, 49) if attack_move else (123, 105, 47)
        pygame.draw.circle(surface, color, (x, y), 9, width=3)
        pygame.draw.circle(surface, outline, (x, y), 4)

    def _draw_gameplay_link_endpoint(
        self,
        surface: pygame.Surface,
        screen_pos: tuple[int, int],
        *,
        attack_move: bool = False,
    ) -> None:
        """Draw gameplay link endpoint."""
        color = _destination_marker_color(attack_move, 1)
        outline = (123, 105, 47) if not attack_move else (112, 54, 49)
        pygame.draw.circle(surface, outline, screen_pos, 5)
        pygame.draw.circle(surface, color, screen_pos, 3)

    def _draw_debug_destination_marker(
        self,
        surface: pygame.Surface,
        screen_pos: tuple[int, int],
        index: int,
        *,
        attack_move: bool = False,
    ) -> None:
        """Draw debug destination marker."""
        x, y = screen_pos
        radius = 10 if index == 1 else 8
        color = _destination_marker_color(attack_move, index)
        pygame.draw.circle(surface, color, (x, y), radius, width=2)
        pygame.draw.line(surface, color, (x - radius - 4, y), (x + radius + 4, y), 2)
        pygame.draw.line(surface, color, (x, y - radius - 4), (x, y + radius + 4), 2)

        label = self.small_font.render(str(index), True, (31, 29, 21))
        label_rect = label.get_rect(center=(x, y))
        pygame.draw.circle(surface, color, label_rect.center, 7)
        surface.blit(label, label_rect)

    def _draw_drag_rect(self, surface: pygame.Surface, drag_rect: ScreenRect) -> None:
        """Draw drag rect."""
        rect = pygame.Rect(drag_rect)
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        overlay.fill((235, 220, 118, 45))
        surface.blit(overlay, rect)
        pygame.draw.rect(surface, (235, 220, 118), rect, width=2)

    def _draw_hud(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selection: SelectionState,
        fps: float,
    ) -> None:
        """Draw hud."""
        pygame.draw.rect(surface, (25, 29, 31), (0, 0, surface.get_width(), 54))
        resources = "  ".join(
            f"{_resource_label(name)}: {world.resources.get(name, 0)}"
            for name in ("wood", "food", "stone", "iron", "gold")
        )
        self._draw_text(surface, resources, (16, 10), self.font)
        population = f"Population: {world.current_population} / {world.max_population}"
        self._draw_text(surface, population, (16, 34), self.small_font, color=(221, 204, 145))
        # Keep the wave timer in the right HUD cluster so it does not overlap resources.
        wave = self.small_font.render(wave_timer_text(world), True, (236, 178, 140))
        wave_rect = wave.get_rect(
            midright=(self.settings_button_rect(surface).left - 16, 18),
        )
        status = f"Selected: {len(selection.selected_ids)}   FPS: {fps:0.0f}"
        status_text = self.font.render(status, True, (240, 235, 214))
        status_rect = status_text.get_rect(midright=(wave_rect.left - 24, 18))
        surface.blit(status_text, status_rect)
        surface.blit(wave, wave_rect)
        hint = (
            "A/D or arrows pan | select, right click, shift queue | Ctrl+1-9 groups"
        )
        self._draw_text(surface, hint, (260, 34), self.small_font, color=(210, 214, 198))

    def _draw_notifications(self, surface: pygame.Surface, world: WorldState) -> None:
        """Draw notifications."""
        for index, notification in enumerate(world.notifications[-4:]):
            text = self._notification_surface(notification.message, (247, 229, 169))
            rect = text.get_rect(midtop=(surface.get_width() // 2, 62 + index * 24))
            background = rect.inflate(18, 8)
            pygame.draw.rect(surface, (36, 42, 38), background, border_radius=4)
            pygame.draw.rect(surface, (128, 114, 76), background, width=1, border_radius=4)
            surface.blit(text, rect)

    def _notification_surface(
        self,
        message: str,
        color: tuple[int, int, int],
    ) -> pygame.Surface:
        """Return a cached rendered surface for a notification."""
        key = (message, color)
        cached = self._notification_surface_cache.get(key)
        if cached is not None:
            return cached
        if len(self._notification_surface_cache) > 64:
            self._notification_surface_cache.clear()
        rendered = self.small_font.render(message, True, color)
        self._notification_surface_cache[key] = rendered
        return rendered

    def _draw_settings_button(self, surface: pygame.Surface) -> None:
        """Draw settings button."""
        rect = self.settings_button_rect(surface)
        pygame.draw.rect(surface, (52, 63, 58), rect, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), rect, width=1, border_radius=4)
        text = self.small_font.render("Settings", True, (244, 238, 213))
        surface.blit(text, text.get_rect(center=rect.center))

    def _draw_settings_menu(
        self,
        surface: pygame.Surface,
        fullscreen: bool,
        rebinding_action: str | None,
    ) -> None:
        """Draw settings menu."""
        rect = self.settings_menu_rect(surface)
        pygame.draw.rect(surface, (24, 29, 28), rect, border_radius=6)
        pygame.draw.rect(surface, (128, 114, 76), rect, width=2, border_radius=6)
        self._draw_text(surface, "Settings", (rect.left + 14, rect.top + 12), self.font)

        toggle = self.settings_display_toggle_rect(surface)
        label = "Display: Fullscreen" if fullscreen else "Display: Borderless"
        pygame.draw.rect(surface, (64, 75, 61), toggle, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), toggle, width=1, border_radius=4)
        text = self.small_font.render(label, True, (244, 238, 213))
        surface.blit(text, text.get_rect(center=toggle.center))

        hitboxes = self.settings_resource_hitboxes_toggle_rect(surface)
        hitbox_label = (
            "Resource Hitboxes: On"
            if self.settings.show_resource_hitboxes
            else "Resource Hitboxes: Off"
        )
        pygame.draw.rect(surface, (64, 75, 61), hitboxes, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), hitboxes, width=1, border_radius=4)
        hitbox_text = self.small_font.render(hitbox_label, True, (244, 238, 213))
        surface.blit(hitbox_text, hitbox_text.get_rect(center=hitboxes.center))

        unit_hitboxes = self.settings_unit_hitboxes_toggle_rect(surface)
        unit_hitbox_label = (
            "Unit Hitboxes: On"
            if self.settings.show_unit_hitboxes
            else "Unit Hitboxes: Off"
        )
        pygame.draw.rect(surface, (64, 75, 61), unit_hitboxes, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), unit_hitboxes, width=1, border_radius=4)
        unit_hitbox_text = self.small_font.render(unit_hitbox_label, True, (244, 238, 213))
        surface.blit(unit_hitbox_text, unit_hitbox_text.get_rect(center=unit_hitboxes.center))

        building_hitboxes = self.settings_building_hitboxes_toggle_rect(surface)
        building_hitbox_label = (
            "Building Hitboxes: On"
            if self.settings.show_building_hitboxes
            else "Building Hitboxes: Off"
        )
        pygame.draw.rect(surface, (64, 75, 61), building_hitboxes, border_radius=4)
        pygame.draw.rect(
            surface,
            (136, 152, 116),
            building_hitboxes,
            width=1,
            border_radius=4,
        )
        building_hitbox_text = self.small_font.render(
            building_hitbox_label,
            True,
            (244, 238, 213),
        )
        surface.blit(
            building_hitbox_text,
            building_hitbox_text.get_rect(center=building_hitboxes.center),
        )

        waypoints = self.settings_debug_waypoints_toggle_rect(surface)
        waypoint_label = (
            "Debug Waypoints: On"
            if self.settings.show_debug_waypoints
            else "Debug Waypoints: Off"
        )
        pygame.draw.rect(surface, (64, 75, 61), waypoints, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), waypoints, width=1, border_radius=4)
        waypoint_text = self.small_font.render(waypoint_label, True, (244, 238, 213))
        surface.blit(waypoint_text, waypoint_text.get_rect(center=waypoints.center))

        perf = self.settings_performance_overlay_toggle_rect(surface)
        perf_label = (
            "Performance: On"
            if self.settings.show_performance_overlay
            else "Performance: Off"
        )
        pygame.draw.rect(surface, (64, 75, 61), perf, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), perf, width=1, border_radius=4)
        perf_text = self.small_font.render(perf_label, True, (244, 238, 213))
        surface.blit(perf_text, perf_text.get_rect(center=perf.center))

        flashes = self.settings_hit_flashes_toggle_rect(surface)
        flashes_label = (
            "Hit Flashes: On"
            if self.settings.show_debug_hit_flashes
            else "Hit Flashes: Off"
        )
        pygame.draw.rect(surface, (64, 75, 61), flashes, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), flashes, width=1, border_radius=4)
        flashes_text = self.small_font.render(flashes_label, True, (244, 238, 213))
        surface.blit(flashes_text, flashes_text.get_rect(center=flashes.center))

        # Wave debug controls share one row so the existing keybind list remains visible.
        waves = self.settings_waves_toggle_rect(surface)
        waves_label = "Enemy Waves: On" if self.settings.waves_enabled else "Enemy Waves: Off"
        pygame.draw.rect(surface, (64, 75, 61), waves, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), waves, width=1, border_radius=4)
        waves_text = self.small_font.render(waves_label, True, (244, 238, 213))
        surface.blit(waves_text, waves_text.get_rect(center=waves.center))

        timer = self.settings_wave_timer_toggle_rect(surface)
        timer_label = "Timer: On" if self.settings.wave_timer_enabled else "Timer: Off"
        pygame.draw.rect(surface, (64, 75, 61), timer, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), timer, width=1, border_radius=4)
        timer_text = self.small_font.render(timer_label, True, (244, 238, 213))
        surface.blit(timer_text, timer_text.get_rect(center=timer.center))

        start_wave = self.settings_start_wave_rect(surface)
        pygame.draw.rect(surface, (86, 61, 58), start_wave, border_radius=4)
        pygame.draw.rect(surface, (184, 123, 95), start_wave, width=1, border_radius=4)
        start_wave_text = self.small_font.render("Start Enemy Wave Now", True, (244, 238, 213))
        surface.blit(start_wave_text, start_wave_text.get_rect(center=start_wave.center))

        # Debug economy buttons let us test production/build costs without waiting
        # for gather loops during balance passes.
        for resource_key, label in SETTINGS_RESOURCE_GRANT_RESOURCES:
            button = self.settings_resource_grant_rect(surface, resource_key)
            pygame.draw.rect(surface, (58, 74, 62), button, border_radius=4)
            pygame.draw.rect(surface, (125, 153, 108), button, width=1, border_radius=4)
            text = self.small_font.render(f"+10 {label}", True, (244, 238, 213))
            surface.blit(text, text.get_rect(center=button.center))

        self._draw_text(
            surface,
            "Keybinds",
            (rect.left + 14, rect.top + 364),
            self.small_font,
            color=(221, 204, 145),
        )
        for action in KEYBIND_ACTION_ORDER:
            row = self.settings_keybind_rect(surface, action)
            waiting = action == rebinding_action
            fill = (81, 104, 80) if waiting else (64, 75, 61)
            outline = (109, 176, 104) if waiting else (136, 152, 116)
            pygame.draw.rect(surface, fill, row, border_radius=4)
            pygame.draw.rect(surface, outline, row, width=1, border_radius=4)
            key_name = formatted_key_name(self.settings.keybindings.get(action))
            label = KEYBIND_ACTION_LABELS[action]
            text = f"{label}: press key" if waiting else f"{label}: {key_name}"
            rendered = self.small_font.render(text, True, (244, 238, 213))
            surface.blit(rendered, rendered.get_rect(midleft=(row.left + 10, row.centery)))

    def settings_button_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the settings button rectangle."""
        return pygame.Rect(
            surface.get_width() - SETTINGS_BUTTON_WIDTH - 16,
            12,
            SETTINGS_BUTTON_WIDTH,
            SETTINGS_BUTTON_HEIGHT,
        )

    def settings_menu_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the settings menu rectangle."""
        return pygame.Rect(
            surface.get_width() - SETTINGS_MENU_WIDTH - 16,
            52,
            SETTINGS_MENU_WIDTH,
            SETTINGS_MENU_HEIGHT,
        )

    def settings_display_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the display-mode toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 48, menu.width - 28, 30)

    def settings_resource_hitboxes_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the resource-hitbox toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 84, menu.width - 28, 30)

    def settings_unit_hitboxes_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the unit-hitbox toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 120, menu.width - 28, 30)

    def settings_building_hitboxes_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the building-hitbox toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 156, menu.width - 28, 30)

    def settings_debug_waypoints_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the waypoint-debug toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 192, menu.width - 28, 30)

    def settings_performance_overlay_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the profiler overlay toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 228, (menu.width - 36) // 2, 30)

    def settings_hit_flashes_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the debug hit-flash toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        left = menu.left + 22 + ((menu.width - 36) // 2)
        return pygame.Rect(left, menu.top + 228, (menu.width - 36) // 2, 30)

    def settings_waves_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the enemy-wave toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 264, (menu.width - 36) // 2, 30)

    def settings_wave_timer_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the wave-timer toggle rectangle."""
        menu = self.settings_menu_rect(surface)
        left = menu.left + 22 + ((menu.width - 36) // 2)
        return pygame.Rect(left, menu.top + 264, (menu.width - 36) // 2, 30)

    def settings_start_wave_rect(self, surface: pygame.Surface) -> pygame.Rect:
        """Return the start-wave debug button rectangle."""
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 300, menu.width - 28, 30)

    def settings_resource_grant_rect(
        self,
        surface: pygame.Surface,
        resource_key: str,
    ) -> pygame.Rect:
        """Return the debug resource-grant button rectangle."""
        menu = self.settings_menu_rect(surface)
        resource_keys = [key for key, _label in SETTINGS_RESOURCE_GRANT_RESOURCES]
        index = resource_keys.index(resource_key)
        gap = 1
        usable_width = menu.width - 28
        button_width = (usable_width - (gap * (len(resource_keys) - 1))) // len(resource_keys)
        return pygame.Rect(
            menu.left + 14 + index * (button_width + gap),
            menu.top + 332,
            button_width,
            24,
        )

    def settings_keybind_rect(self, surface: pygame.Surface, action: str) -> pygame.Rect:
        """Return the keybinding row rectangle for an action."""
        menu = self.settings_menu_rect(surface)
        index = KEYBIND_ACTION_ORDER.index(action)
        column = index // KEYBIND_ROWS_PER_COLUMN
        row = index % KEYBIND_ROWS_PER_COLUMN
        usable_width = menu.width - 28
        column_width = (usable_width - KEYBIND_COLUMN_GAP) // 2
        return pygame.Rect(
            menu.left + 14 + column * (column_width + KEYBIND_COLUMN_GAP),
            menu.top + KEYBIND_START_Y_OFFSET + row * (KEYBIND_ROW_HEIGHT + KEYBIND_ROW_GAP),
            column_width,
            KEYBIND_ROW_HEIGHT,
        )

    def settings_keybind_action_at(
        self,
        surface: pygame.Surface,
        screen_pos: tuple[int, int],
    ) -> str | None:
        """Return the keybinding action under a point."""
        for action in KEYBIND_ACTION_ORDER:
            if self.settings_keybind_rect(surface, action).collidepoint(screen_pos):
                return action
        return None

    def settings_resource_grant_at(
        self,
        surface: pygame.Surface,
        screen_pos: tuple[int, int],
    ) -> str | None:
        """Return the resource key for a clicked debug resource-grant button."""
        for resource_key, _label in SETTINGS_RESOURCE_GRANT_RESOURCES:
            if self.settings_resource_grant_rect(surface, resource_key).collidepoint(screen_pos):
                return resource_key
        return None

    def settings_menu_contains(self, surface: pygame.Surface, screen_pos: tuple[int, int]) -> bool:
        """Return whether a point is inside the settings menu."""
        return self.settings_menu_rect(surface).collidepoint(screen_pos)

    def _draw_selected_panel(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selection: SelectionState,
        active_ability: str | None,
        ability_override: tuple[str, ...] | None,
    ) -> None:
        """Draw selected panel."""
        panel = selected_panel_for(world, selection.selected_ids)
        panel_rect = pygame.Rect(
            0,
            surface.get_height() - PANEL_HEIGHT,
            surface.get_width(),
            PANEL_HEIGHT,
        )
        pygame.draw.rect(surface, (26, 31, 29), panel_rect)
        pygame.draw.line(surface, (128, 114, 76), panel_rect.topleft, panel_rect.topright, 2)

        self._draw_text(surface, panel.title, (18, panel_rect.top + 14), self.font)
        self._draw_text(
            surface,
            panel.subtitle,
            (18, panel_rect.top + 40),
            self.small_font,
            color=(195, 199, 182),
        )
        self._draw_text(
            surface,
            panel.health,
            (18, panel_rect.top + 64),
            self.small_font,
            color=(221, 204, 145),
        )

        detail_x = 290
        for row, detail in enumerate(panel.details[:3]):
            self._draw_text(
                surface,
                detail,
                (detail_x, panel_rect.top + 18 + row * 24),
                self.small_font,
                color=(217, 220, 202),
            )

        for button in self.ability_buttons_for_panel(surface, panel, ability_override):
            text = self.small_font.render(button.display_label, True, (244, 238, 213))
            fill = (81, 104, 80) if button.label == active_ability else (64, 75, 61)
            outline = (109, 176, 104) if button.label == active_ability else (136, 152, 116)
            border_width = 2 if button.label == active_ability else 1
            pygame.draw.rect(surface, fill, button.rect, border_radius=4)
            pygame.draw.rect(surface, outline, button.rect, width=border_width, border_radius=4)
            surface.blit(text, text.get_rect(center=button.rect.center))

    def panel_contains(self, surface: pygame.Surface, screen_pos: tuple[int, int]) -> bool:
        """Return whether a screen position is inside the command panel."""
        panel_rect = pygame.Rect(
            0,
            surface.get_height() - PANEL_HEIGHT,
            surface.get_width(),
            PANEL_HEIGHT,
        )
        return panel_rect.collidepoint(screen_pos)

    def ability_at(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selection: SelectionState,
        screen_pos: tuple[int, int],
        ability_override: tuple[str, ...] | None = None,
    ) -> str | None:
        """Return the ability button under a screen position."""
        panel = selected_panel_for(world, selection.selected_ids)
        for button in self.ability_buttons_for_panel(surface, panel, ability_override):
            if button.rect.collidepoint(screen_pos):
                return button.label
        return None

    def ability_buttons_for_panel(
        self,
        surface: pygame.Surface,
        panel: SelectedPanel,
        ability_override: tuple[str, ...] | None = None,
    ) -> list[AbilityButton]:
        """Create clickable ability buttons for the selected panel."""
        panel_top = surface.get_height() - PANEL_HEIGHT
        ability_x = ABILITY_START_X
        ability_y = panel_top + ABILITY_START_Y_OFFSET
        buttons: list[AbilityButton] = []
        abilities = ability_override if ability_override is not None else panel.abilities
        for index, ability in enumerate(abilities):
            display_label = ability_display_label(
                ability,
                self.settings.keybindings,
                slot_index=index,
            )
            text = self.small_font.render(display_label, True, (244, 238, 213))
            chip = text.get_rect()
            chip.width += 18
            chip.height = ABILITY_CHIP_HEIGHT
            if ability_x + chip.width > surface.get_width() - 16:
                ability_x = ABILITY_START_X
                ability_y += ABILITY_ROW_HEIGHT
            chip.topleft = (ability_x, ability_y)
            buttons.append(AbilityButton(ability, chip, display_label))
            ability_x += chip.width + 8
        return buttons

    def _draw_text(
        self,
        surface: pygame.Surface,
        text: str,
        position: tuple[int, int],
        font: pygame.font.Font,
        *,
        color: tuple[int, int, int] = (240, 235, 214),
    ) -> None:
        """Draw text."""
        surface.blit(font.render(text, True, color), position)

    def _draw_label(self, surface: pygame.Surface, label: str, center: tuple[int, int]) -> None:
        """Draw label."""
        text = self.small_font.render(label, True, (245, 238, 210))
        surface.blit(text, text.get_rect(center=center))

    def _draw_performance_overlay(
        self,
        surface: pygame.Surface,
        world: WorldState,
        fps: float,
    ) -> None:
        """Draw performance overlay."""
        stats = world.performance_stats
        timings = stats.timings_ms
        counters = stats.counters
        lines = [
            f"FPS {fps:0.0f}",
            (
                f"Entities {stats.entity_count}  Units {stats.unit_count}  "
                f"Resources {stats.resource_count}  Buildings {stats.building_count}"
            ),
            f"Input {timings.get('input', 0.0):0.2f} ms",
            (
                f"Update {timings.get('update', 0.0):0.2f} ms  "
                f"Render {timings.get('render', 0.0):0.2f} ms"
            ),
            (
                f"Move {timings.get('movement', 0.0):0.2f}  "
                f"Combat {timings.get('combat', 0.0):0.2f}  "
                f"Economy {timings.get('economy', 0.0):0.2f}  "
                f"Farm {timings.get('farming', 0.0):0.2f}"
            ),
            (
                f"Render entities {timings.get('render_entities', 0.0):0.2f}  "
                f"HUD/UI {timings.get('render_hud', 0.0) + timings.get('render_ui', 0.0):0.2f}"
            ),
            (
                f"Notifications {counters.notifications_active}  "
                f"new {counters.notifications_created}  "
                f"suppressed {counters.notifications_suppressed}  "
                f"render {timings.get('render_notifications', 0.0):0.2f}"
            ),
            (
                f"Path jobs {counters.path_jobs_processed}  "
                f"Path calcs {counters.full_path_calculations}  "
                f"Resource searches {counters.resource_searches}"
            ),
            (
                f"Candidates {counters.resource_candidates_checked}  "
                f"Collision checks {counters.collision_checks}"
            ),
            (
                f"Projectiles {counters.active_projectiles}  "
                f"Effects {counters.active_combat_effects}  "
                f"Attacks {counters.attacks_started}  "
                f"Hits {counters.projectile_hits}"
            ),
        ]
        width = 390
        height = 18 + len(lines) * 19
        rect = pygame.Rect(surface.get_width() - width - 16, 52, width, height)
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        overlay.fill((22, 26, 24, 220))
        surface.blit(overlay, rect)
        pygame.draw.rect(surface, (128, 114, 76), rect, width=1, border_radius=4)
        for index, line in enumerate(lines):
            self._draw_text(
                surface,
                line,
                (rect.left + 10, rect.top + 8 + index * 19),
                self.small_font,
                color=(244, 238, 213),
            )


def settler_equipment_for(
    world: WorldState,
    settler: object,
) -> UnitEquipmentVisual:
    """Derive a settler's visible tool from current work or combat state."""
    if "settler" not in getattr(settler, "tags", ()):
        return UnitEquipmentVisual(None)
    state = str(getattr(settler, "state", "idle"))
    if state in {"attack_windup", "attacking", "attack_cooldown"}:
        return UnitEquipmentVisual("bow", _bow_draw_progress(settler))
    if state != "gathering":
        return UnitEquipmentVisual(None)

    queue = world.command_queues.get(settler.id)
    command = queue.peek() if queue is not None else None
    if command is None or command.type != "gather":
        return UnitEquipmentVisual(None)
    resource_type = str(command.payload.get("resource_type", ""))
    if resource_type == "wood":
        tool = "axe"
    elif resource_type in {"stone", "iron", "ore", "gold"}:
        tool = "pickaxe"
    else:
        return UnitEquipmentVisual(None)
    elapsed_ms = max(0, int(command.payload.get("swing_elapsed_ms", 0) or 0))
    return UnitEquipmentVisual(tool, min(1.0, elapsed_ms / max(1, GATHER_SWING_MS)))


def _unit_equipment_for(
    world: WorldState,
    entity: object,
) -> UnitEquipmentVisual:
    """Return placeholder equipment for the current unit role and state."""
    tags = tuple(getattr(entity, "tags", ()))
    if "settler" in tags:
        return settler_equipment_for(world, entity)
    if _tags_include_role(tags, "archer"):
        return UnitEquipmentVisual("bow", _bow_draw_progress(entity))
    if "spearman" in tags:
        return UnitEquipmentVisual("spear")
    return UnitEquipmentVisual("sword")


def _bow_draw_progress(entity: object) -> float:
    """Return normalized bow-string draw for an active ranged wind-up."""
    if getattr(entity, "state", None) != "attack_windup":
        return 0.0
    remaining_ms = max(0, int(getattr(entity, "attack_windup_remaining_ms", 0)))
    return max(
        0.0,
        min(1.0, 1.0 - remaining_ms / max(1, RANGED_ATTACK_WINDUP_MS)),
    )


def _tool_swing_direction(
    facing_x: float,
    facing_y: float,
    progress: float,
) -> tuple[float, float]:
    """Rotate a gathering tool through raise, strike, and recovery phases."""
    phase = max(0.0, min(1.0, progress))
    if phase <= 0.65:
        sweep = phase / 0.65
        angle = -0.9 + sweep * 1.8
    else:
        recovery = (phase - 0.65) / 0.35
        angle = 0.9 - recovery * 1.8
    cosine = cos(angle)
    sine = sin(angle)
    return (
        facing_x * cosine - facing_y * sine,
        facing_x * sine + facing_y * cosine,
    )


def _unit_body_color(tags: tuple[str, ...], enemy: bool) -> tuple[int, int, int]:
    """Return a distinct placeholder body color for each current unit role."""
    if enemy:
        if _tags_include_role(tags, "archer"):
            return (125, 67, 119)
        return (151, 61, 67)
    if "spearman" in tags:
        return (80, 120, 174)
    if _tags_include_role(tags, "archer"):
        return (177, 127, 62)
    return (78, 145, 87)


def _unit_head_color(enemy: bool) -> tuple[int, int, int]:
    """Return the simple head color shared by placeholder combat units."""
    return (180, 112, 108) if enemy else (206, 176, 132)


def _tags_include_role(tags: tuple[str, ...], role: str) -> bool:
    """Return whether plain or owner-prefixed tags identify a unit role."""
    return any(tag == role or tag.endswith(f"_{role}") for tag in tags)


def _offset_point(
    origin: tuple[float, float],
    direction_x: float,
    direction_y: float,
    distance: float,
) -> tuple[float, float]:
    """Offset a screen point along a normalized direction."""
    return (
        origin[0] + direction_x * distance,
        origin[1] + direction_y * distance,
    )


def _lerp(start: float, end: float, progress: float) -> float:
    """Interpolate between two scalar values."""
    return start + (end - start) * progress


def _draw_weapon_tip(
    surface: pygame.Surface,
    tip: tuple[float, float],
    direction_x: float,
    direction_y: float,
    color: tuple[int, int, int],
) -> None:
    """Draw a small triangular spearhead at a weapon endpoint."""
    perpendicular = (-direction_y, direction_x)
    base = (
        tip[0] - direction_x * 7,
        tip[1] - direction_y * 7,
    )
    pygame.draw.polygon(
        surface,
        color,
        [
            (tip[0] + direction_x * 4, tip[1] + direction_y * 4),
            (base[0] + perpendicular[0] * 4, base[1] + perpendicular[1] * 4),
            (base[0] - perpendicular[0] * 4, base[1] - perpendicular[1] * 4),
        ],
    )


def _entity_visual_center(entity: object) -> WorldPosition:
    """Return the visual center of an anchored entity footprint."""
    left, top, width, height = entity.bounds
    return WorldPosition(left + width / 2, top + height / 2)


def _selected_attack_target_ids(
    world: WorldState,
    selected_ids: list[EntityId],
) -> set[EntityId]:
    """Return live target IDs referenced by selected units' combat state."""
    target_ids: set[EntityId] = set()
    for entity_id in selected_ids:
        entity = world.entities.get(entity_id)
        if entity is None or getattr(entity, "owner", None) != "frontier":
            continue
        pending = getattr(entity, "pending_attack_target_id", None)
        if pending is not None:
            target_ids.add(pending)
        queue = world.command_queues.get(entity_id)
        command = queue.peek() if queue is not None else None
        if command is None:
            continue
        if command.target_entity_id is not None and command.type == "attack":
            target_ids.add(command.target_entity_id)
        for key in ("attack_move_target_id", "attack_move_chase_target_id"):
            value = command.payload.get(key)
            if value is not None:
                target_ids.add(EntityId(int(value)))
    return target_ids


def _status_bar_visible(entity: object, selected: bool, recently_hit: bool) -> bool:
    """Return whether combat readability currently requires an entity bar."""
    tags = set(getattr(entity, "tags", ()))
    if "resource" in tags:
        return True
    if selected or recently_hit:
        return True
    if "building" in tags:
        max_hp = max(0, int(getattr(entity, "max_hp", 0) or 0))
        return max_hp > 0 and int(getattr(entity, "hp", 0)) < max_hp
    return str(getattr(entity, "state", "idle")) in {
        "attack_windup",
        "attacking",
        "attack_cooldown",
    }


def _screen_rect(world: WorldState, bounds: tuple[float, float, float, float]) -> pygame.Rect:
    """Return the bounds used for screen rect."""
    left, top, width, height = bounds
    screen_pos = world.camera.world_to_screen(WorldPosition(left, top))
    return pygame.Rect(screen_pos[0], screen_pos[1], round(width), round(height))


def _rect_on_screen(surface: pygame.Surface, rect: pygame.Rect) -> bool:
    """Return the bounds used for rect on screen."""
    return rect.colliderect(surface.get_rect().inflate(120, 120))


def _short_label(tags: tuple[str, ...]) -> str:
    """Return display text for short label."""
    for tag in tags:
        if tag not in {
            "unit",
            "resource",
            "building",
            "selectable",
            "movable",
            "farm_food",
            "food_animal",
            "food_carcass",
        }:
            return tag[:3].upper()
    return "?"


def _is_enemy_entity(entity: object) -> bool:
    """Return whether enemy entity."""
    return getattr(entity, "owner", "neutral") not in {"frontier", "neutral"}


def _renderable_entity(entity: object) -> bool:
    """Return whether an entity should be drawn this frame."""
    return getattr(entity, "alive", False) or is_building_destroying(entity)


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


def _load_resource_sprite(resource_id: str, stage: str) -> pygame.Surface | None:
    """Load and cache one processed mine resource sprite."""
    path = RESOURCE_SPRITE_PATHS.get(resource_id, {}).get(stage)
    if path is None:
        return None
    can_convert = pygame.display.get_init() and pygame.display.get_surface() is not None
    cache_key = (resource_id, stage, str(path), can_convert)
    if cache_key in _RESOURCE_SPRITE_CACHE:
        return _RESOURCE_SPRITE_CACHE[cache_key]
    if not path.exists():
        _RESOURCE_SPRITE_CACHE[cache_key] = None
        return None
    try:
        sprite = pygame.image.load(str(path))
        loaded = sprite.convert_alpha() if can_convert else sprite
    except pygame.error:
        loaded = None
    _RESOURCE_SPRITE_CACHE[cache_key] = loaded
    return loaded


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


def _load_building_sprite(building_id: str, stage: str) -> pygame.Surface | None:
    """Load and cache one processed building sprite."""
    path = BUILDING_SPRITE_PATHS.get(building_id, {}).get(stage)
    if path is None:
        return None
    can_convert = pygame.display.get_init() and pygame.display.get_surface() is not None
    cache_key = (building_id, stage, str(path), can_convert)
    if cache_key in _BUILDING_SPRITE_CACHE:
        return _BUILDING_SPRITE_CACHE[cache_key]
    if not path.exists():
        _BUILDING_SPRITE_CACHE[cache_key] = None
        return None
    try:
        sprite = pygame.image.load(str(path))
        loaded = sprite.convert_alpha() if can_convert else sprite
    except pygame.error:
        loaded = None
    _BUILDING_SPRITE_CACHE[cache_key] = loaded
    return loaded


def _load_animal_sprites() -> dict[str, pygame.Surface]:
    """Load animal sprites."""
    sprites: dict[str, pygame.Surface] = {}
    for sprite_id, path in ANIMAL_SPRITE_PATHS.items():
        if not path.exists():
            continue
        try:
            sprite = pygame.image.load(str(path))
            sprites[sprite_id] = (
                sprite.convert_alpha()
                if pygame.display.get_init() and pygame.display.get_surface() is not None
                else sprite
            )
        except pygame.error:
            continue
    return sprites


def _sprite_target_size(sprite: pygame.Surface, rect: pygame.Rect) -> tuple[int, int]:
    """Return the position used for sprite target size."""
    box_width = max(1, rect.width * 2)
    box_height = max(1, rect.height * 2)
    return _fit_sprite_size(sprite, box_width, box_height, fallback=rect.size)


def _fit_sprite_inside_rect(sprite: pygame.Surface, rect: pygame.Rect) -> tuple[int, int]:
    """Return a size that fits a sprite inside a building footprint rectangle."""
    return _fit_sprite_size(
        sprite,
        max(1, rect.width),
        max(1, rect.height),
        fallback=rect.size,
    )


def _fit_sprite_size(
    sprite: pygame.Surface,
    box_width: int,
    box_height: int,
    *,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    """Scale a sprite into a box while preserving its source aspect ratio."""
    width, height = sprite.get_size()
    if width <= 0 or height <= 0:
        return (max(1, fallback[0]), max(1, fallback[1]))
    aspect = width / height
    if box_width / box_height > aspect:
        target_height = box_height
        target_width = round(target_height * aspect)
    else:
        target_width = box_width
        target_height = round(target_width / aspect)
    return (max(1, target_width), max(1, target_height))


def hut_construction_stage_for(entity: object) -> str:
    """Return the Hut construction stage used by both drawing and future sprites."""

    tags = set(getattr(entity, "tags", ()))
    if "hut" not in tags or bool(getattr(entity, "complete", True)):
        return HUT_STAGE_COMPLETE
    return building_sprite_stage_for(entity)


def hut_sprite_reference_for(entity: object) -> str:
    """Return the expected future sprite path for the current Hut stage."""

    return str(BUILDING_SPRITE_PATHS["hut"][hut_construction_stage_for(entity)])


def status_bar_for_entity(entity: object) -> StatusBarSpec | None:
    """Return the status bar values for an entity."""
    tags = set(getattr(entity, "tags", ()))
    if "food_animal" in tags:
        hp = max(0, int(getattr(entity, "hp", 0)))
        max_hp = int(getattr(entity, "max_hp", 0) or hp)
        if max_hp <= 0:
            return None
        return StatusBarSpec(
            _ratio(hp, max_hp),
            HEALTH_FILL,
            HEALTH_EMPTY,
        )
    if "resource" in tags:
        amount = max(0, int(getattr(entity, "amount_remaining", 0)))
        max_amount = int(getattr(entity, "max_amount_remaining", 0) or amount)
        if max_amount <= 0:
            return None
        return StatusBarSpec(
            _ratio(amount, max_amount),
            RESOURCE_FILL,
            RESOURCE_EMPTY,
        )
    if "unit" in tags or "building" in tags:
        hp = max(0, int(getattr(entity, "hp", 0)))
        max_hp = int(getattr(entity, "max_hp", 0) or hp)
        if max_hp <= 0:
            return None
        return StatusBarSpec(
            _ratio(hp, max_hp),
            HEALTH_FILL,
            HEALTH_EMPTY,
        )
    return None


def _ratio(current: int, maximum: int) -> float:
    """Clamp a current/max value into a status-bar ratio."""
    if maximum <= 0:
        return 0.0
    return max(0.0, min(1.0, current / maximum))


def _building_progress_ratio(entity: object) -> float:
    """Return construction progress used by building bars."""
    build_time = int(getattr(entity, "build_time_ms", 0) or 0)
    if build_time <= 0:
        return 1.0
    progress_ms = int(getattr(entity, "build_progress_ms", 0) or 0)
    return max(0.0, min(1.0, progress_ms / build_time))


def queued_move_targets(
    world: WorldState,
    selected_ids: Iterable[EntityId],
) -> list[tuple[EntityId, list[WorldPosition]]]:
    """Return visible queued move destinations for selected entities only."""

    return [
        (entity_id, [marker.position for marker in markers])
        for entity_id, markers in queued_move_markers(world, selected_ids)
    ]


def queued_move_markers(
    world: WorldState,
    selected_ids: Iterable[EntityId],
) -> list[tuple[EntityId, list[MoveTargetMarker]]]:
    """Return visible queued move marker metadata for selected entities only."""

    visible_markers: list[tuple[EntityId, list[MoveTargetMarker]]] = []
    for entity_id in selected_ids:
        queue = world.command_queues.get(entity_id)
        if queue is None:
            continue
        markers = [_command_marker(command) for command in queue.commands]
        move_markers = [marker for marker in markers if marker is not None]
        if move_markers:
            visible_markers.append((entity_id, move_markers))
    return visible_markers


def gameplay_waypoint_markers(
    world: WorldState,
    selected_ids: Iterable[EntityId],
) -> list[MoveTargetMarker]:
    """Collapse per-unit formation slots into one readable marker per waypoint step."""

    markers_by_step: dict[int, list[MoveTargetMarker]] = {}
    for _entity_id, markers in queued_move_markers(world, selected_ids):
        for index, marker in enumerate(markers):
            markers_by_step.setdefault(index, []).append(marker)

    return [
        _average_marker(markers_by_step[index])
        for index in sorted(markers_by_step)
        if markers_by_step[index]
    ]


def gameplay_waypoint_links(
    world: WorldState,
    selected_ids: Iterable[EntityId],
) -> list[tuple[WorldPosition, list[MoveTargetMarker]]]:
    """Return each selected unit's simple route links for gameplay waypoint drawing."""

    links: list[tuple[WorldPosition, list[MoveTargetMarker]]] = []
    for entity_id, markers in queued_move_markers(world, selected_ids):
        entity = world.entities.get(entity_id)
        if entity is None:
            continue
        links.append((entity.position, markers))
    return links


def _average_marker(markers: list[MoveTargetMarker]) -> MoveTargetMarker:
    """Return the average queued marker position for a group."""
    x = sum(marker.position.x for marker in markers) / len(markers)
    y = sum(marker.position.y for marker in markers) / len(markers)
    return MoveTargetMarker(
        WorldPosition(x, y),
        attack_move=any(marker.attack_move for marker in markers),
    )


def _command_target(command: Command) -> WorldPosition | None:
    """Return the position used for command target."""
    if command.type != "move":
        return None
    return command.target_pos


def _command_marker(command: Command) -> MoveTargetMarker | None:
    """Return the visible marker position for a command."""
    target = _command_target(command)
    if target is None:
        return None
    return MoveTargetMarker(target, attack_move=command.payload.get("attack_move") is True)


def _destination_line_color(attack_move: bool) -> tuple[int, int, int]:
    """Return the waypoint line color for a command."""
    return (176, 70, 58) if attack_move else (162, 144, 74)


def dotted_line_points(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    spacing: int = 12,
) -> list[tuple[int, int]]:
    """Return evenly spaced dot centers along a screen-space segment."""

    distance = hypot(end[0] - start[0], end[1] - start[1])
    if distance <= 0:
        return [start]
    count = max(2, int(distance // max(1, spacing)) + 1)
    return [
        (
            round(start[0] + ((end[0] - start[0]) * index / (count - 1))),
            round(start[1] + ((end[1] - start[1]) * index / (count - 1))),
        )
        for index in range(count)
    ]


def draw_dotted_line(
    surface: pygame.Surface,
    color: tuple[int, int, int],
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    spacing: int = 12,
    radius: int = 2,
) -> None:
    """Draw a dotted waypoint link between two screen points."""
    for point in dotted_line_points(start, end, spacing=spacing):
        pygame.draw.circle(surface, color, point, radius)


def _gameplay_waypoint_link_color(attack_move: bool) -> tuple[int, int, int]:
    """Return the gameplay waypoint link color."""
    return (176, 83, 75) if attack_move else (178, 158, 86)


def _destination_marker_color(attack_move: bool, index: int) -> tuple[int, int, int]:
    """Return the waypoint marker color for a command."""
    if attack_move:
        return (231, 84, 72) if index == 1 else (194, 66, 58)
    return (238, 218, 111) if index == 1 else (226, 183, 86)


def _resource_label(resource_type: str) -> str:
    """Return display text for resource label."""
    if resource_type == "iron":
        return "Iron"
    return resource_type.title()


def wave_timer_text(world: WorldState) -> str:
    """Return the HUD text for enemy wave pressure."""
    if not world.settings.waves_enabled:
        return "Waves Off"
    remaining_ms = max(0, world.next_wave_due_ms - world.elapsed_ms)
    if world.next_wave_due_ms <= 0:
        remaining_ms = max(0, world.settings.initial_wave_delay_seconds * 1000)
    total_seconds = remaining_ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"Next wave: {minutes:02d}:{seconds:02d}"

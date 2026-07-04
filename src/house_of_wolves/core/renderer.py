"""Pygame renderer for the first playable slice."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import pygame

from house_of_wolves.core.contracts import Command, EntityId, WorldPosition
from house_of_wolves.core.settings import UI_PANEL_HEIGHT, AppSettings
from house_of_wolves.systems.selection import SelectionState
from house_of_wolves.ui.selected_panel import SelectedPanel, selected_panel_for
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
SETTINGS_MENU_WIDTH = 260
SETTINGS_MENU_HEIGHT = 96


@dataclass(frozen=True, slots=True)
class AbilityButton:
    """Hit-test data for one selected-panel ability chip."""

    label: str
    rect: pygame.Rect


@dataclass(slots=True)
class GameRenderer:
    """Draws generated placeholder visuals for the demo world."""

    settings: AppSettings
    font: pygame.font.Font = field(init=False)
    small_font: pygame.font.Font = field(init=False)

    def __post_init__(self) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

    def render(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selection: SelectionState,
        fps: float,
        drag_rect: ScreenRect | None = None,
        active_ability: str | None = None,
        settings_open: bool = False,
        fullscreen: bool = True,
    ) -> None:
        self._draw_background(surface, world)
        self._draw_entities(surface, world, selection.selected_ids)
        self._draw_dropoff_markers(surface, world, selection.selected_ids)
        self._draw_destinations(surface, world, selection.selected_ids)
        if drag_rect is not None:
            self._draw_drag_rect(surface, drag_rect)
        self._draw_hud(surface, world, selection, fps)
        self._draw_selected_panel(surface, world, selection, active_ability)
        self._draw_settings_button(surface)
        if settings_open:
            self._draw_settings_menu(surface, fullscreen)

    def _draw_background(self, surface: pygame.Surface, world: WorldState) -> None:
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
        selected = set(selected_ids)
        entities = sorted(
            (entity for entity in world.entities.values() if entity.alive),
            key=lambda entity: (entity.position.y, entity.position.x, int(entity.id)),
        )
        for entity in entities:
            rect = _screen_rect(world, entity.bounds)
            if not _rect_on_screen(surface, rect):
                continue
            tags = set(entity.tags)
            if "building" in tags:
                self._draw_building(surface, rect, entity.tags)
            elif "resource" in tags:
                self._draw_resource(surface, rect, entity.tags)
            else:
                self._draw_unit(surface, rect, entity.tags)
            if entity.id in selected:
                self._draw_selection(surface, rect)

    def _draw_unit(self, surface: pygame.Surface, rect: pygame.Rect, tags: tuple[str, ...]) -> None:
        color = (86, 145, 92)
        if "spearman" in tags:
            color = (92, 123, 171)
        elif "archer" in tags:
            color = (171, 123, 68)
        pygame.draw.ellipse(surface, (33, 42, 34), rect.move(0, 6).inflate(8, -18))
        pygame.draw.ellipse(surface, color, rect)
        pygame.draw.rect(surface, (28, 34, 30), rect, width=2, border_radius=6)
        self._draw_label(surface, _short_label(tags), rect.center)

    def _draw_resource(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        tags: tuple[str, ...],
    ) -> None:
        if "wood_tree" in tags:
            trunk = pygame.Rect(rect.centerx - 8, rect.bottom - 45, 16, 45)
            pygame.draw.rect(surface, (93, 61, 42), trunk)
            pygame.draw.circle(surface, (46, 117, 65), (rect.centerx, rect.top + 42), 42)
            pygame.draw.circle(surface, (58, 137, 72), (rect.centerx - 24, rect.top + 54), 28)
        else:
            pygame.draw.ellipse(surface, (112, 102, 82), rect)
            pygame.draw.ellipse(surface, (197, 168, 78), rect.inflate(-30, -24))
        pygame.draw.rect(surface, (49, 55, 45), rect, width=2, border_radius=8)

    def _draw_building(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        tags: tuple[str, ...],
    ) -> None:
        pygame.draw.rect(surface, (115, 80, 54), rect, border_radius=4)
        roof = [
            (rect.left - 10, rect.top + 28),
            (rect.centerx, rect.top - 18),
            (rect.right + 10, rect.top + 28),
        ]
        pygame.draw.polygon(surface, (82, 58, 47), roof)
        pygame.draw.rect(surface, (49, 36, 32), rect, width=3, border_radius=4)
        self._draw_label(surface, _short_label(tags), rect.center)

    def _draw_selection(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        marker = pygame.Rect(rect.left - 5, rect.bottom - 12, rect.width + 10, 18)
        pygame.draw.ellipse(surface, (235, 220, 118), marker, width=3)

    def _draw_destinations(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selected_ids: list[EntityId],
    ) -> None:
        for entity_id, move_targets in queued_move_targets(world, selected_ids):
            entity = world.entities.get(entity_id)
            if entity is None:
                continue
            previous_screen = world.camera.world_to_screen(entity.position)
            for index, target in enumerate(move_targets, start=1):
                current_screen = world.camera.world_to_screen(target)
                pygame.draw.line(surface, (162, 144, 74), previous_screen, current_screen, 1)
                self._draw_destination_marker(surface, current_screen, index)
                previous_screen = current_screen

    def _draw_dropoff_markers(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selected_ids: list[EntityId],
    ) -> None:
        for entity_id in selected_ids:
            entity = world.entities.get(entity_id)
            dropoff_point = getattr(entity, "dropoff_point", None)
            if dropoff_point is None:
                continue
            self._draw_dropoff_flag(surface, world.camera.world_to_screen(dropoff_point))

    def _draw_dropoff_flag(self, surface: pygame.Surface, screen_pos: tuple[int, int]) -> None:
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

    def _draw_destination_marker(
        self,
        surface: pygame.Surface,
        screen_pos: tuple[int, int],
        index: int,
    ) -> None:
        x, y = screen_pos
        radius = 10 if index == 1 else 8
        color = (238, 218, 111) if index == 1 else (226, 183, 86)
        pygame.draw.circle(surface, color, (x, y), radius, width=2)
        pygame.draw.line(surface, color, (x - radius - 4, y), (x + radius + 4, y), 2)
        pygame.draw.line(surface, color, (x, y - radius - 4), (x, y + radius + 4), 2)

        label = self.small_font.render(str(index), True, (31, 29, 21))
        label_rect = label.get_rect(center=(x, y))
        pygame.draw.circle(surface, (238, 218, 111), label_rect.center, 7)
        surface.blit(label, label_rect)

    def _draw_drag_rect(self, surface: pygame.Surface, drag_rect: ScreenRect) -> None:
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
        pygame.draw.rect(surface, (25, 29, 31), (0, 0, surface.get_width(), 54))
        resources = "  ".join(
            f"{name.title()}: {world.resources.get(name, 0)}"
            for name in ("wood", "food", "stone", "iron", "gold")
        )
        self._draw_text(surface, resources, (16, 10), self.font)
        status = f"Selected: {len(selection.selected_ids)}   FPS: {fps:0.0f}"
        self._draw_text(surface, status, (surface.get_width() - 380, 10), self.font)
        hint = (
            "A/D or arrows pan | left click/drag select | right click move | "
            "Shift queues | Esc quits"
        )
        self._draw_text(surface, hint, (16, 34), self.small_font, color=(210, 214, 198))

    def _draw_settings_button(self, surface: pygame.Surface) -> None:
        rect = self.settings_button_rect(surface)
        pygame.draw.rect(surface, (52, 63, 58), rect, border_radius=4)
        pygame.draw.rect(surface, (136, 152, 116), rect, width=1, border_radius=4)
        text = self.small_font.render("Settings", True, (244, 238, 213))
        surface.blit(text, text.get_rect(center=rect.center))

    def _draw_settings_menu(self, surface: pygame.Surface, fullscreen: bool) -> None:
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

    def settings_button_rect(self, surface: pygame.Surface) -> pygame.Rect:
        return pygame.Rect(
            surface.get_width() - SETTINGS_BUTTON_WIDTH - 16,
            12,
            SETTINGS_BUTTON_WIDTH,
            SETTINGS_BUTTON_HEIGHT,
        )

    def settings_menu_rect(self, surface: pygame.Surface) -> pygame.Rect:
        return pygame.Rect(
            surface.get_width() - SETTINGS_MENU_WIDTH - 16,
            52,
            SETTINGS_MENU_WIDTH,
            SETTINGS_MENU_HEIGHT,
        )

    def settings_display_toggle_rect(self, surface: pygame.Surface) -> pygame.Rect:
        menu = self.settings_menu_rect(surface)
        return pygame.Rect(menu.left + 14, menu.top + 48, menu.width - 28, 30)

    def settings_menu_contains(self, surface: pygame.Surface, screen_pos: tuple[int, int]) -> bool:
        return self.settings_menu_rect(surface).collidepoint(screen_pos)

    def _draw_selected_panel(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selection: SelectionState,
        active_ability: str | None,
    ) -> None:
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
        for row, detail in enumerate(panel.details[:2]):
            self._draw_text(
                surface,
                detail,
                (detail_x, panel_rect.top + 18 + row * 24),
                self.small_font,
                color=(217, 220, 202),
            )

        for button in self.ability_buttons_for_panel(surface, panel):
            text = self.small_font.render(button.label, True, (244, 238, 213))
            fill = (81, 104, 80) if button.label == active_ability else (64, 75, 61)
            outline = (109, 176, 104) if button.label == active_ability else (136, 152, 116)
            border_width = 2 if button.label == active_ability else 1
            pygame.draw.rect(surface, fill, button.rect, border_radius=4)
            pygame.draw.rect(surface, outline, button.rect, width=border_width, border_radius=4)
            surface.blit(text, text.get_rect(center=button.rect.center))

    def panel_contains(self, surface: pygame.Surface, screen_pos: tuple[int, int]) -> bool:
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
    ) -> str | None:
        panel = selected_panel_for(world, selection.selected_ids)
        for button in self.ability_buttons_for_panel(surface, panel):
            if button.rect.collidepoint(screen_pos):
                return button.label
        return None

    def ability_buttons_for_panel(
        self,
        surface: pygame.Surface,
        panel: SelectedPanel,
    ) -> list[AbilityButton]:
        panel_top = surface.get_height() - PANEL_HEIGHT
        ability_x = ABILITY_START_X
        ability_y = panel_top + ABILITY_START_Y_OFFSET
        buttons: list[AbilityButton] = []
        for ability in panel.abilities[:8]:
            text = self.small_font.render(ability, True, (244, 238, 213))
            chip = text.get_rect()
            chip.width += 18
            chip.height = ABILITY_CHIP_HEIGHT
            if ability_x + chip.width > surface.get_width() - 16:
                ability_x = ABILITY_START_X
                ability_y += ABILITY_ROW_HEIGHT
            chip.topleft = (ability_x, ability_y)
            buttons.append(AbilityButton(ability, chip))
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
        surface.blit(font.render(text, True, color), position)

    def _draw_label(self, surface: pygame.Surface, label: str, center: tuple[int, int]) -> None:
        text = self.small_font.render(label, True, (245, 238, 210))
        surface.blit(text, text.get_rect(center=center))


def _screen_rect(world: WorldState, bounds: tuple[float, float, float, float]) -> pygame.Rect:
    left, top, width, height = bounds
    screen_pos = world.camera.world_to_screen(WorldPosition(left, top))
    return pygame.Rect(screen_pos[0], screen_pos[1], round(width), round(height))


def _rect_on_screen(surface: pygame.Surface, rect: pygame.Rect) -> bool:
    return rect.colliderect(surface.get_rect().inflate(120, 120))


def _short_label(tags: tuple[str, ...]) -> str:
    for tag in tags:
        if tag not in {"unit", "resource", "building", "selectable", "movable"}:
            return tag[:3].upper()
    return "?"


def queued_move_targets(
    world: WorldState,
    selected_ids: Iterable[EntityId],
) -> list[tuple[EntityId, list[WorldPosition]]]:
    """Return visible queued move destinations for selected entities only."""

    visible_targets: list[tuple[EntityId, list[WorldPosition]]] = []
    for entity_id in selected_ids:
        queue = world.command_queues.get(entity_id)
        if queue is None:
            continue
        targets = [_command_target(command) for command in queue.commands]
        move_targets = [target for target in targets if target is not None]
        if move_targets:
            visible_targets.append((entity_id, move_targets))
    return visible_targets


def _command_target(command: Command) -> WorldPosition | None:
    if command.type != "move":
        return None
    return command.target_pos

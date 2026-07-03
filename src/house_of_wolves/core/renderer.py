"""Pygame renderer for the first playable slice."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import pygame

from house_of_wolves.core.contracts import Command, EntityId, WorldPosition
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.systems.selection import SelectionState
from house_of_wolves.ui.selected_panel import selected_panel_for
from house_of_wolves.world.world import WorldState

ScreenRect = tuple[int, int, int, int]


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
    ) -> None:
        self._draw_background(surface, world)
        self._draw_entities(surface, world, selection.selected_ids)
        self._draw_destinations(surface, world, selection.selected_ids)
        if drag_rect is not None:
            self._draw_drag_rect(surface, drag_rect)
        self._draw_hud(surface, world, selection, fps)
        self._draw_selected_panel(surface, world, selection)

    def _draw_background(self, surface: pygame.Surface, world: WorldState) -> None:
        surface.fill((112, 168, 202))
        width, height = surface.get_size()
        horizon_y = 360
        pygame.draw.rect(surface, (86, 147, 80), (0, horizon_y, width, height - horizon_y))
        pygame.draw.rect(surface, (72, 113, 65), (0, 612, width, 46))
        pygame.draw.rect(surface, (55, 79, 49), (0, 650, width, 70))

        camera_x = world.camera.x
        for base_x in range(-600, self.settings.world_width + 800, 520):
            screen_x = round(base_x - camera_x * 0.25)
            points = [(screen_x, 360), (screen_x + 180, 230), (screen_x + 390, 360)]
            pygame.draw.polygon(surface, (90, 130, 118), points)

        for x in range(-200, self.settings.world_width + 400, 300):
            screen_x = round(x - camera_x)
            pygame.draw.line(surface, (65, 96, 55), (screen_x, 638), (screen_x + 170, 638), 3)

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
        self._draw_text(surface, status, (surface.get_width() - 250, 10), self.font)
        hint = (
            "A/D or arrows pan | left click/drag select | right click move | "
            "Shift queues | Esc quits"
        )
        self._draw_text(surface, hint, (16, 34), self.small_font, color=(210, 214, 198))

    def _draw_selected_panel(
        self,
        surface: pygame.Surface,
        world: WorldState,
        selection: SelectionState,
    ) -> None:
        panel = selected_panel_for(world, selection.selected_ids)
        panel_height = 112
        panel_rect = pygame.Rect(
            0,
            surface.get_height() - panel_height,
            surface.get_width(),
            panel_height,
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

        ability_x = 520
        ability_y = panel_rect.top + 18
        for ability in panel.abilities[:8]:
            text = self.small_font.render(ability, True, (244, 238, 213))
            chip = text.get_rect()
            chip.width += 18
            chip.height = 24
            if ability_x + chip.width > surface.get_width() - 16:
                ability_x = 520
                ability_y += 30
            chip.topleft = (ability_x, ability_y)
            pygame.draw.rect(surface, (64, 75, 61), chip, border_radius=4)
            pygame.draw.rect(surface, (136, 152, 116), chip, width=1, border_radius=4)
            surface.blit(text, text.get_rect(center=chip.center))
            ability_x += chip.width + 8

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

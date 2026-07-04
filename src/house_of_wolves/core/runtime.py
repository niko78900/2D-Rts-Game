"""Pygame runtime for the minimal playable slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

import pygame

from house_of_wolves.core.contracts import EntityId
from house_of_wolves.core.renderer import GameRenderer, ScreenRect
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.building import Building
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.systems.production import ProductionError, produce_unit
from house_of_wolves.systems.selection import SelectionSystem
from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.world import WorldState


@dataclass(slots=True)
class GameRuntime:
    """Owns Pygame init, input, update, render, and shutdown."""

    settings: AppSettings
    world: WorldState = field(default_factory=create_demo_world)
    selection_system: SelectionSystem = field(default_factory=SelectionSystem)
    movement_system: MovementSystem = field(default_factory=MovementSystem)
    running: bool = False
    screen: pygame.Surface | None = None
    clock: pygame.time.Clock | None = None
    renderer: GameRenderer | None = None
    drag_start_screen: tuple[int, int] | None = None
    drag_current_screen: tuple[int, int] | None = None
    active_dropoff_building_id: EntityId | None = None

    def __post_init__(self) -> None:
        if self.world.settings != self.settings:
            self.world = create_demo_world(self.settings)

    def initialize(self) -> None:
        pygame.init()
        pygame.display.set_caption(self.settings.window_title)
        self.screen = pygame.display.set_mode(self.settings.virtual_size)
        self.clock = pygame.time.Clock()
        self.renderer = GameRenderer(self.settings)
        self.running = True

    def shutdown(self) -> None:
        self.running = False
        pygame.quit()

    def run(self, max_frames: int | None = None) -> int:
        self.initialize()
        frame_count = 0
        try:
            while self.running:
                assert self.clock is not None
                dt_ms = self.clock.tick(self.settings.target_fps)
                self.process_events()
                self.update(dt_ms)
                self.render()
                pygame.display.flip()
                frame_count += 1
                if max_frames is not None and frame_count >= max_frames:
                    self.running = False
        finally:
            self.shutdown()
        return 0

    def process_events(self) -> None:
        for event in pygame.event.get():
            self.handle_event(event)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.running = False
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._handle_ability_click(event.pos):
                return
            if self._handle_dropoff_placement(event.pos):
                return
            self.drag_start_screen = event.pos
            self.drag_current_screen = event.pos
            return
        if event.type == pygame.MOUSEMOTION and self.drag_start_screen is not None:
            self.drag_current_screen = event.pos
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._finish_selection(event.pos, _shift_pressed())
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self._issue_move(event.pos, queued=_shift_pressed())

    def _handle_ability_click(self, screen_pos: tuple[int, int]) -> bool:
        if self.screen is None or self.renderer is None:
            return False
        ability = self.renderer.ability_at(
            self.screen,
            self.world,
            self.selection_system.state,
            screen_pos,
        )
        if ability is None:
            return False
        if ability == "Dropoff":
            self._toggle_dropoff_mode()
            return True
        if ability.startswith("Produce "):
            self.active_dropoff_building_id = None
            self._produce_from_selection(ability.removeprefix("Produce "))
        return True

    def _toggle_dropoff_mode(self) -> None:
        building = self._selected_dropoff_building()
        if building is None:
            self.active_dropoff_building_id = None
            return
        if self.active_dropoff_building_id == building.id:
            self.active_dropoff_building_id = None
        else:
            self.active_dropoff_building_id = building.id

    def _handle_dropoff_placement(self, screen_pos: tuple[int, int]) -> bool:
        if self.active_dropoff_building_id is None:
            return False
        if (
            self.screen is not None
            and self.renderer is not None
            and self.renderer.panel_contains(self.screen, screen_pos)
        ):
            return True
        building = self.world.entities.get(self.active_dropoff_building_id)
        if not isinstance(building, Building):
            self.active_dropoff_building_id = None
            return False
        building.dropoff_point = self.world.camera.screen_to_world(*screen_pos)
        self.active_dropoff_building_id = None
        return True

    def _selected_dropoff_building(self) -> Building | None:
        if len(self.selection_system.state.selected_ids) != 1:
            return None
        entity = self.world.entities.get(self.selection_system.state.selected_ids[0])
        if isinstance(entity, Building) and entity.dropoff_point is not None:
            return entity
        return None

    def _produce_from_selection(self, display_name: str) -> None:
        if len(self.selection_system.state.selected_ids) != 1:
            return
        producer_id = self.selection_system.state.selected_ids[0]
        unit_id = display_name.replace(" ", "_").lower()
        try:
            produce_unit(self.world, producer_id, unit_id)
        except ProductionError:
            return

    def update(self, dt_ms: int) -> None:
        self._update_camera(dt_ms)
        self.movement_system.update(self.world, dt_ms)

    def render(self) -> None:
        if self.screen is None or self.renderer is None:
            return
        fps = self.clock.get_fps() if self.clock is not None else 0
        self.renderer.render(
            self.screen,
            self.world,
            self.selection_system.state,
            fps,
            self._current_drag_rect(),
            self._active_ability_label(),
        )

    def _active_ability_label(self) -> str | None:
        if self.active_dropoff_building_id is not None:
            return "Dropoff"
        return None

    def _update_camera(self, dt_ms: int) -> None:
        direction = 0
        keys = pygame.key.get_pressed()
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            direction -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            direction += 1

        if pygame.mouse.get_focused() and self.screen is not None:
            mouse_x, _ = pygame.mouse.get_pos()
            width = self.screen.get_width()
            margin = self.settings.edge_scroll_margin
            if mouse_x <= margin:
                direction -= 1
            elif mouse_x >= width - margin:
                direction += 1

        if direction:
            seconds = dt_ms / 1000
            self.world.camera.move_by(direction * self.settings.camera_pan_speed * seconds)

    def _finish_selection(self, end_screen: tuple[int, int], add: bool) -> None:
        start = self.drag_start_screen
        self.drag_start_screen = None
        self.drag_current_screen = None
        if start is None:
            return
        drag_distance = hypot(end_screen[0] - start[0], end_screen[1] - start[1])
        if drag_distance < self.settings.selection_drag_threshold:
            world_pos = self.world.camera.screen_to_world(*end_screen)
            self.selection_system.select_at(self.world, world_pos, add=add)
            return
        world_bounds = self._screen_drag_to_world_bounds(start, end_screen)
        self.selection_system.box_select(self.world, world_bounds, add=add)

    def _issue_move(self, screen_pos: tuple[int, int], *, queued: bool) -> None:
        movable_ids = [
            entity_id
            for entity_id in self.selection_system.state.selected_ids
            if entity_id in self.world.entities
            and "movable" in self.world.entities[entity_id].tags
            and self.world.entities[entity_id].owner == "frontier"
        ]
        if not movable_ids:
            return
        target_pos = self.world.camera.screen_to_world(*screen_pos)
        command = make_command("move", movable_ids, target_pos=target_pos, queued=queued)
        for entity_id in movable_ids:
            self.world.enqueue_command(entity_id, command)

    def _current_drag_rect(self) -> ScreenRect | None:
        if self.drag_start_screen is None or self.drag_current_screen is None:
            return None
        if (
            hypot(
                self.drag_current_screen[0] - self.drag_start_screen[0],
                self.drag_current_screen[1] - self.drag_start_screen[1],
            )
            < self.settings.selection_drag_threshold
        ):
            return None
        return _normalize_screen_rect(self.drag_start_screen, self.drag_current_screen)

    def _screen_drag_to_world_bounds(
        self,
        start_screen: tuple[int, int],
        end_screen: tuple[int, int],
    ) -> tuple[float, float, float, float]:
        left, top, width, height = _normalize_screen_rect(start_screen, end_screen)
        world_top_left = self.world.camera.screen_to_world(left, top)
        return (world_top_left.x, world_top_left.y, width, height)


def _shift_pressed() -> bool:
    return bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)


def _normalize_screen_rect(
    start: tuple[int, int],
    end: tuple[int, int],
) -> ScreenRect:
    left = min(start[0], end[0])
    top = min(start[1], end[1])
    width = abs(end[0] - start[0])
    height = abs(end[1] - start[1])
    return (left, top, width, height)

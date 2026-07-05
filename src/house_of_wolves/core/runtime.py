"""Pygame runtime for the minimal playable slice."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from math import hypot

import pygame

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.core.keybindings import (
    KEYBIND_ACTION_ORDER,
    KEYBIND_ATTACK,
    KEYBIND_ATTACK_MOVE,
    KEYBIND_BUILD,
    KEYBIND_BUILD_HUT,
    KEYBIND_CANCEL_BUILD,
    KEYBIND_GATHER_GOLD,
    KEYBIND_GATHER_ORE,
    KEYBIND_GATHER_STONE,
    KEYBIND_GATHER_WOOD,
    KEYBIND_STOP,
    normalized_key_name,
)
from house_of_wolves.core.renderer import BuildingPlacementPreview, GameRenderer, ScreenRect
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.systems.combat import CombatSystem
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.construction import ConstructionSystem, starting_construction_hp
from house_of_wolves.systems.economy import (
    EconomySystem,
    assign_auto_gather_targets,
    completed_deposit_huts,
    resource_interaction_position,
)
from house_of_wolves.systems.group_movement import issue_group_move_command
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.systems.production import ProductionError, produce_unit
from house_of_wolves.systems.selection import SelectionSystem
from house_of_wolves.world.collision import blocking_bounds_for_entity, nearest_free_position
from house_of_wolves.world.demo import create_demo_world
from house_of_wolves.world.terrain import (
    clamp_unit_position_to_walkable_lane_for_height,
    terrain_bands_for_height,
    terrain_layout_for_height,
)
from house_of_wolves.world.world import WorldState

HUT_BUILDING_ID = "hut"
HUT_FOOTPRINT = Footprint(150, 116)
HUT_MAX_HP = 650
HUT_BUILD_TIME_MS = 12_000
BUILD_MENU_ABILITIES = ("Hut", "Back")
PLACEMENT_MENU_ABILITIES = ("Cancel",)
GATHER_RESOURCE_TYPES = {
    "Gather Wood": "wood",
    "Gather Gold": "gold",
    "Gather Ore": "iron",
    "Gather Stone": "stone",
}
KEYBIND_GATHER_ACTIONS = {
    KEYBIND_GATHER_WOOD: "Gather Wood",
    KEYBIND_GATHER_GOLD: "Gather Gold",
    KEYBIND_GATHER_ORE: "Gather Ore",
    KEYBIND_GATHER_STONE: "Gather Stone",
}


@dataclass(slots=True)
class GameRuntime:
    """Owns Pygame init, input, update, render, and shutdown."""

    settings: AppSettings
    world: WorldState = field(default_factory=create_demo_world)
    selection_system: SelectionSystem = field(default_factory=SelectionSystem)
    movement_system: MovementSystem = field(default_factory=MovementSystem)
    combat_system: CombatSystem = field(default_factory=CombatSystem)
    construction_system: ConstructionSystem = field(default_factory=ConstructionSystem)
    economy_system: EconomySystem = field(default_factory=EconomySystem)
    running: bool = False
    screen: pygame.Surface | None = None
    clock: pygame.time.Clock | None = None
    renderer: GameRenderer | None = None
    display_flags: int = 0
    drag_start_screen: tuple[int, int] | None = None
    drag_current_screen: tuple[int, int] | None = None
    mouse_screen_pos: tuple[int, int] = (0, 0)
    active_dropoff_building_id: EntityId | None = None
    active_command_ability: str | None = None
    build_menu_open: bool = False
    active_building_placement: str | None = None
    settings_menu_open: bool = False
    rebinding_action: str | None = None

    def __post_init__(self) -> None:
        if self.world.settings != self.settings:
            self.world = create_demo_world(self.settings)

    def initialize(self) -> None:
        _pin_window_to_primary_display()
        pygame.init()
        pygame.display.set_caption(self.settings.window_title)
        self._set_display_mode(rebuild_world=True)
        self.clock = pygame.time.Clock()
        self.running = True

    def shutdown(self) -> None:
        self.running = False
        pygame.quit()

    def _set_display_mode(self, *, rebuild_world: bool) -> None:
        flags = pygame.FULLSCREEN if self.settings.fullscreen else pygame.NOFRAME
        size = _desktop_size_for_display(self.settings.display_index, self.settings.virtual_size)
        self.display_flags = flags
        self.screen = pygame.display.set_mode(size, flags, display=self.settings.display_index)
        self._apply_display_size(self.screen.get_size(), rebuild_world=rebuild_world)
        self.renderer = GameRenderer(self.settings)

    def _apply_display_size(self, size: tuple[int, int], *, rebuild_world: bool) -> None:
        width, height = size
        if (
            width == self.settings.virtual_width
            and height == self.settings.virtual_height
            and height == self.settings.world_height
        ):
            return
        self.settings = replace(
            self.settings,
            virtual_width=width,
            virtual_height=height,
            world_height=height,
        )
        if rebuild_world:
            self.world = create_demo_world(self.settings)
            return
        self.world.settings = self.settings
        self.world.camera.viewport_width = width
        self.world.camera.viewport_height = height
        self.world.camera.world_height = height
        self.world.camera.clamp()
        self.world.terrain_bands = terrain_bands_for_height(height)

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
        if event.type == pygame.KEYDOWN and self._handle_key_rebind(event):
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.settings_menu_open:
                self.settings_menu_open = False
                self.rebinding_action = None
            elif self._cancel_active_mode():
                return
            else:
                self.running = False
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self._toggle_fullscreen()
            return
        if event.type == pygame.KEYDOWN and self._handle_hotkey(event.key):
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.mouse_screen_pos = event.pos
            if self._handle_settings_click(event.pos):
                return
            if self._handle_ability_click(event.pos):
                return
            if self._handle_building_placement(event.pos):
                return
            if self._handle_dropoff_placement(event.pos):
                return
            if self._handle_command_placement(event.pos):
                return
            self.drag_start_screen = event.pos
            self.drag_current_screen = event.pos
            return
        if event.type == pygame.MOUSEMOTION:
            self.mouse_screen_pos = event.pos
            if self.drag_start_screen is not None:
                self.drag_current_screen = event.pos
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.mouse_screen_pos = event.pos
            self._finish_selection(event.pos, _shift_pressed())
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self.mouse_screen_pos = event.pos
            if self._cancel_active_mode():
                return
            self.active_command_ability = None
            if self._handle_settler_context_right_click(event.pos, queued=_shift_pressed()):
                return
            self._issue_move(event.pos, queued=_shift_pressed())

    def _handle_ability_click(self, screen_pos: tuple[int, int]) -> bool:
        if self.screen is None or self.renderer is None:
            return False
        ability = self.renderer.ability_at(
            self.screen,
            self.world,
            self.selection_system.state,
            screen_pos,
            self._ability_override(),
        )
        if ability is None:
            return False
        if self.build_menu_open:
            return self._handle_build_menu_ability(ability)
        if self.active_building_placement is not None:
            return self._handle_build_placement_ability(ability)
        if ability in GATHER_RESOURCE_TYPES:
            self._issue_auto_gather(GATHER_RESOURCE_TYPES[ability])
            return True
        if ability in {"Move", "Attack", "Attack Move"}:
            return self._activate_command_ability(ability)
        if ability == "Stop":
            self.active_dropoff_building_id = None
            self.active_command_ability = None
            self.build_menu_open = False
            self.active_building_placement = None
            self._stop_selected_units()
            return True
        if ability == "Build":
            if not self._selected_builder_ids():
                return True
            self.active_dropoff_building_id = None
            self.active_command_ability = None
            self.active_building_placement = None
            self.build_menu_open = True
            return True
        if ability == "Dropoff":
            self.active_command_ability = None
            self.build_menu_open = False
            self.active_building_placement = None
            self._toggle_dropoff_mode()
            return True
        if ability.startswith("Produce "):
            self.active_dropoff_building_id = None
            self.active_command_ability = None
            self.build_menu_open = False
            self.active_building_placement = None
            self._produce_from_selection(ability.removeprefix("Produce "))
        return True

    def _handle_build_menu_ability(self, ability: str) -> bool:
        if ability == "Back":
            self.build_menu_open = False
            return True
        if ability == "Hut":
            self.build_menu_open = False
            self.active_building_placement = HUT_BUILDING_ID
            return True
        return True

    def _handle_build_placement_ability(self, ability: str) -> bool:
        if ability == "Cancel":
            self.active_building_placement = None
            return True
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
        building.dropoff_point = clamp_unit_position_to_walkable_lane_for_height(
            self.world.camera.screen_to_world(*screen_pos),
            self.world.settings.world_height,
        )
        self.active_dropoff_building_id = None
        return True

    def _handle_building_placement(self, screen_pos: tuple[int, int]) -> bool:
        if self.active_building_placement is None:
            return False
        if (
            self.screen is not None
            and self.renderer is not None
            and self.renderer.panel_contains(self.screen, screen_pos)
        ):
            return True
        if self.active_building_placement != HUT_BUILDING_ID:
            return True
        world_pos = self.world.camera.screen_to_world(*screen_pos)
        if not self._valid_hut_placement_at(world_pos):
            return True
        hut = self._create_hut_construction_site(world_pos)
        queued = _shift_pressed()
        self._order_selected_builders_to_site(hut, queued=queued)
        if not queued:
            self.active_building_placement = None
        return True

    def _handle_command_placement(self, screen_pos: tuple[int, int]) -> bool:
        if self.active_command_ability is None:
            return False
        if (
            self.screen is not None
            and self.renderer is not None
            and self.renderer.panel_contains(self.screen, screen_pos)
        ):
            return True
        attack_move = self.active_command_ability == "Attack Move"
        if self.active_command_ability == "Attack":
            self._issue_attack(screen_pos, queued=_shift_pressed())
            self.active_command_ability = None
            return True
        if self.active_command_ability in GATHER_RESOURCE_TYPES:
            self._issue_gather(
                screen_pos,
                GATHER_RESOURCE_TYPES[self.active_command_ability],
                queued=_shift_pressed(),
            )
            self.active_command_ability = None
            return True
        self._issue_move(screen_pos, queued=_shift_pressed(), attack_move=attack_move)
        self.active_command_ability = None
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

    def _handle_settler_context_right_click(
        self,
        screen_pos: tuple[int, int],
        *,
        queued: bool,
    ) -> bool:
        if not self._selected_builder_ids():
            return False
        world_pos = self.world.camera.screen_to_world(*screen_pos)
        entity_id = self.selection_system.pick_at(self.world, world_pos)
        if entity_id is None:
            return False
        entity = self.world.entities.get(entity_id)
        if isinstance(entity, Building):
            if entity.owner != "frontier":
                return False
            if not entity.complete:
                self._order_selected_builders_to_site(entity, queued=queued)
                return True
            if _needs_repair(entity):
                self._order_selected_repairers_to_site(entity, queued=queued)
                return True
            return False
        if isinstance(entity, ResourceNode):
            self._order_selected_gatherers_to_resource(entity, queued=queued)
            return True
        return False

    def _handle_key_rebind(self, event: pygame.event.Event) -> bool:
        if self.rebinding_action is None:
            return False
        if event.key == pygame.K_ESCAPE:
            self.rebinding_action = None
            return True
        key_name = normalized_key_name(pygame.key.name(event.key))
        keybindings = dict(self.settings.keybindings)
        for action, bound_key in list(keybindings.items()):
            if action != self.rebinding_action and bound_key == key_name:
                keybindings[action] = ""
        keybindings[self.rebinding_action] = key_name
        self.settings = replace(self.settings, keybindings=keybindings)
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)
        self.rebinding_action = None
        return True

    def _handle_hotkey(self, key: int) -> bool:
        if self.settings_menu_open:
            return False
        action = self._keybound_action_for_key(key)
        if action is None:
            return False
        if action == KEYBIND_CANCEL_BUILD:
            return self._cancel_active_mode()
        if action == KEYBIND_STOP:
            self._cancel_active_mode()
            self._stop_selected_units()
            return True
        if self.active_building_placement is not None:
            return False
        if self.build_menu_open:
            if action == KEYBIND_BUILD_HUT:
                return self._handle_build_menu_ability("Hut")
            return False
        if action == KEYBIND_BUILD:
            if not self._selected_builder_ids():
                return True
            self.active_dropoff_building_id = None
            self.active_command_ability = None
            self.active_building_placement = None
            self.build_menu_open = True
            return True
        if action == KEYBIND_ATTACK:
            return self._activate_command_ability("Attack")
        if action == KEYBIND_ATTACK_MOVE:
            return self._activate_command_ability("Attack Move")
        if action in KEYBIND_GATHER_ACTIONS:
            self._issue_auto_gather(GATHER_RESOURCE_TYPES[KEYBIND_GATHER_ACTIONS[action]])
            return True
        return False

    def _activate_command_ability(self, ability: str) -> bool:
        if ability == "Attack" and not self._selected_player_attack_unit_ids():
            return True
        if ability in {"Move", "Attack Move"} and not self._selected_player_movable_unit_ids():
            return True
        self.active_dropoff_building_id = None
        self.build_menu_open = False
        self.active_building_placement = None
        self.active_command_ability = None if self.active_command_ability == ability else ability
        return True

    def _keybound_action_for_key(self, key: int) -> str | None:
        key_name = normalized_key_name(pygame.key.name(key))
        for action in KEYBIND_ACTION_ORDER:
            if self.settings.keybindings.get(action) == key_name:
                return action
        return None

    def update(self, dt_ms: int) -> None:
        self._update_camera(dt_ms)
        self.combat_system.update(self.world, dt_ms)
        self.movement_system.update(self.world, dt_ms)
        self.construction_system.update(self.world, dt_ms)
        self.economy_system.update(self.world, dt_ms)
        self.world.update_notifications(dt_ms)

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
            self.settings_menu_open,
            self.settings.fullscreen,
            self._ability_override(),
            self._placement_preview(),
            self.rebinding_action,
        )

    def _active_ability_label(self) -> str | None:
        if self.active_command_ability is not None:
            return self.active_command_ability
        if self.active_dropoff_building_id is not None:
            return "Dropoff"
        return None

    def _ability_override(self) -> tuple[str, ...] | None:
        if self.active_building_placement is not None:
            return PLACEMENT_MENU_ABILITIES
        if self.build_menu_open:
            return BUILD_MENU_ABILITIES
        return None

    def _handle_settings_click(self, screen_pos: tuple[int, int]) -> bool:
        if self.screen is None or self.renderer is None:
            return False
        if self.renderer.settings_button_rect(self.screen).collidepoint(screen_pos):
            self.settings_menu_open = not self.settings_menu_open
            if not self.settings_menu_open:
                self.rebinding_action = None
            return True
        if not self.settings_menu_open:
            return False
        if self.renderer.settings_display_toggle_rect(self.screen).collidepoint(screen_pos):
            self._toggle_fullscreen()
            return True
        if self.renderer.settings_resource_hitboxes_toggle_rect(self.screen).collidepoint(
            screen_pos
        ):
            self._toggle_resource_hitboxes()
            return True
        if self.renderer.settings_unit_hitboxes_toggle_rect(self.screen).collidepoint(
            screen_pos
        ):
            self._toggle_unit_hitboxes()
            return True
        if self.renderer.settings_building_hitboxes_toggle_rect(self.screen).collidepoint(
            screen_pos
        ):
            self._toggle_building_hitboxes()
            return True
        if self.renderer.settings_debug_waypoints_toggle_rect(self.screen).collidepoint(
            screen_pos
        ):
            self._toggle_debug_waypoints()
            return True
        keybind_action = self.renderer.settings_keybind_action_at(self.screen, screen_pos)
        if keybind_action is not None:
            self.rebinding_action = keybind_action
            return True
        if self.renderer.settings_menu_contains(self.screen, screen_pos):
            return True
        self.settings_menu_open = False
        self.rebinding_action = None
        return True

    def _toggle_fullscreen(self) -> None:
        self.settings_menu_open = False
        self.settings = replace(self.settings, fullscreen=not self.settings.fullscreen)
        self._set_display_mode(rebuild_world=False)

    def _toggle_resource_hitboxes(self) -> None:
        self.settings = replace(
            self.settings,
            show_resource_hitboxes=not self.settings.show_resource_hitboxes,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_unit_hitboxes(self) -> None:
        self.settings = replace(
            self.settings,
            show_unit_hitboxes=not self.settings.show_unit_hitboxes,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_building_hitboxes(self) -> None:
        self.settings = replace(
            self.settings,
            show_building_hitboxes=not self.settings.show_building_hitboxes,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_debug_waypoints(self) -> None:
        self.settings = replace(
            self.settings,
            show_debug_waypoints=not self.settings.show_debug_waypoints,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

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

    def _issue_move(
        self,
        screen_pos: tuple[int, int],
        *,
        queued: bool,
        attack_move: bool = False,
    ) -> None:
        movable_ids = self._selected_player_movable_unit_ids()
        if not movable_ids:
            return
        target_pos = clamp_unit_position_to_walkable_lane_for_height(
            self.world.camera.screen_to_world(*screen_pos),
            self.world.settings.world_height,
        )
        issue_group_move_command(
            self.world,
            movable_ids,
            target_pos,
            queued=queued,
            attack_move=attack_move,
        )

    def _issue_attack(self, screen_pos: tuple[int, int], *, queued: bool) -> None:
        target_id = self.selection_system.pick_at(
            self.world,
            self.world.camera.screen_to_world(*screen_pos),
        )
        if target_id is None:
            return
        target = self.world.entities.get(target_id)
        if target is None or target.owner in {"frontier", "neutral"}:
            return
        for entity_id in self._selected_player_attack_unit_ids():
            self.world.enqueue_command(
                entity_id,
                make_command("attack", [entity_id], target_entity_id=target_id, queued=queued),
            )

    def _issue_gather(
        self,
        screen_pos: tuple[int, int],
        resource_type: str,
        *,
        queued: bool,
    ) -> None:
        target_id = self.selection_system.pick_at(
            self.world,
            self.world.camera.screen_to_world(*screen_pos),
        )
        if target_id is None:
            return
        target = self.world.entities.get(target_id)
        if not isinstance(target, ResourceNode):
            return
        if not _resource_matches(target, resource_type):
            return
        self._order_selected_gatherers_to_resource(target, queued=queued)

    def _issue_auto_gather(self, resource_type: str) -> None:
        gatherer_ids = self._selected_builder_ids()
        if not gatherer_ids:
            return
        self.active_dropoff_building_id = None
        self.active_command_ability = None
        self.build_menu_open = False
        self.active_building_placement = None
        assignments, message = assign_auto_gather_targets(
            self.world,
            gatherer_ids,
            resource_type,
            owner="frontier",
        )
        if message is not None:
            self.world.notify(message)
            return
        for gatherer_id, resource in assignments.items():
            self._order_gatherer_to_resource(
                resource,
                gatherer_id,
                queued=False,
                manual=False,
            )

    def _stop_selected_units(self) -> None:
        for entity_id in self._selected_player_movable_unit_ids():
            queue = self.world.command_queues.get(entity_id)
            if queue is not None:
                queue.clear()
            entity = self.world.entities.get(entity_id)
            if entity is not None and hasattr(entity, "state"):
                entity.state = "idle"

    def _selected_player_movable_unit_ids(self) -> list[EntityId]:
        return [
            entity_id
            for entity_id in self.selection_system.state.selected_ids
            if entity_id in self.world.entities
            and "unit" in self.world.entities[entity_id].tags
            and "movable" in self.world.entities[entity_id].tags
            and self.world.entities[entity_id].owner == "frontier"
        ]

    def _selected_player_attack_unit_ids(self) -> list[EntityId]:
        return [
            entity_id
            for entity_id in self.selection_system.state.selected_ids
            if entity_id in self.world.entities
            and "unit" in self.world.entities[entity_id].tags
            and self.world.entities[entity_id].owner == "frontier"
            and int(getattr(self.world.entities[entity_id], "damage", 0)) > 0
        ]

    def _selected_builder_ids(self) -> list[EntityId]:
        builder_ids: list[EntityId] = []
        for entity_id in self.selection_system.state.selected_ids:
            entity = self.world.entities.get(entity_id)
            if (
                entity is not None
                and entity.owner == "frontier"
                and "settler" in entity.tags
                and "movable" in entity.tags
            ):
                builder_ids.append(entity_id)
        return builder_ids

    def _placement_preview(self) -> BuildingPlacementPreview | None:
        if self.active_building_placement != HUT_BUILDING_ID:
            return None
        position = self.world.camera.screen_to_world(*self.mouse_screen_pos)
        snapped_position = self._snapped_hut_position(position)
        return BuildingPlacementPreview(
            building_id=HUT_BUILDING_ID,
            position=snapped_position,
            footprint=HUT_FOOTPRINT,
            valid=self._valid_hut_placement_at(position),
        )

    def _valid_hut_placement_at(self, position: WorldPosition) -> bool:
        snapped = self._snapped_hut_position(position)
        half_width = HUT_FOOTPRINT.width / 2
        if snapped.x < half_width or snapped.x > self.world.settings.world_width - half_width:
            return False
        return not self._building_overlaps_existing_building(snapped, HUT_FOOTPRINT)

    def _snapped_hut_position(self, position: WorldPosition) -> WorldPosition:
        layout = terrain_layout_for_height(self.world.settings.world_height)
        return WorldPosition(position.x, layout.building_lane_bottom_y)

    def _building_overlaps_existing_building(
        self,
        position: WorldPosition,
        footprint: Footprint,
    ) -> bool:
        bounds = footprint.bounds_at(position)
        for entity in self.world.entities.values():
            if "building" not in entity.tags or not entity.alive:
                continue
            if _bounds_intersect(bounds, entity.bounds):
                return True
        return False

    def _create_hut_construction_site(self, position: WorldPosition) -> Building:
        build_position = self._snapped_hut_position(position)
        hut = Building(
            id=self.world.allocate_entity_id(),
            owner="frontier",
            position=build_position,
            footprint=HUT_FOOTPRINT,
            hp=starting_construction_hp(HUT_MAX_HP),
            max_hp=HUT_MAX_HP,
            tags=("building", "hut", "selectable"),
            build_time_ms=HUT_BUILD_TIME_MS,
            complete=False,
            functions=Building.production_functions(
                dropoff=True,
                population_cap_bonus=5,
                trainable_units=("settler", "spearman"),
            ),
            dropoff_point=WorldPosition(
                build_position.x + 220,
                terrain_layout_for_height(self.world.settings.world_height).unit_walkable_top_y,
            ),
        )
        self.world.add_entity(hut)
        return hut

    def _order_selected_builders_to_site(self, hut: Building, *, queued: bool = False) -> None:
        builder_ids = self._selected_builder_ids()
        if not builder_ids:
            return
        for index, builder_id in enumerate(builder_ids):
            self._order_builder_to_site(
                hut,
                builder_id,
                index=index,
                total=len(builder_ids),
                queued=queued,
            )

    def _order_builder_to_site(
        self,
        hut: Building,
        builder_id: EntityId,
        *,
        index: int,
        total: int,
        queued: bool,
    ) -> None:
        interaction_point = self._builder_interaction_point(
            hut,
            builder_id,
            index=index,
            total=total,
        )
        self.world.enqueue_command(
            builder_id,
            make_command("move", [builder_id], target_pos=interaction_point, queued=queued),
        )
        self.world.enqueue_command(
            builder_id,
            make_command(
                "build",
                [builder_id],
                target_entity_id=hut.id,
                target_pos=interaction_point,
                queued=True,
                building_id=HUT_BUILDING_ID,
            ),
        )

    def _order_selected_repairers_to_site(
        self,
        building: Building,
        *,
        queued: bool = False,
    ) -> None:
        repairer_ids = self._selected_builder_ids()
        if not repairer_ids:
            return
        for index, repairer_id in enumerate(repairer_ids):
            interaction_point = self._builder_interaction_point(
                building,
                repairer_id,
                index=index,
                total=len(repairer_ids),
            )
            self.world.enqueue_command(
                repairer_id,
                make_command("move", [repairer_id], target_pos=interaction_point, queued=queued),
            )
            self.world.enqueue_command(
                repairer_id,
                make_command(
                    "repair",
                    [repairer_id],
                    target_entity_id=building.id,
                    target_pos=interaction_point,
                    queued=True,
                ),
            )

    def _order_selected_gatherers_to_resource(
        self,
        resource: ResourceNode,
        *,
        queued: bool = False,
    ) -> None:
        gatherer_ids = self._selected_builder_ids()
        if not gatherer_ids:
            return
        if not completed_deposit_huts(self.world, "frontier"):
            self.world.notify("Needs hut to deposit.")
            return
        for gatherer_id in gatherer_ids:
            self._order_gatherer_to_resource(
                resource,
                gatherer_id,
                queued=queued,
                manual=True,
            )

    def _order_gatherer_to_resource(
        self,
        resource: ResourceNode,
        gatherer_id: EntityId,
        *,
        queued: bool,
        manual: bool,
    ) -> None:
        interaction_point = resource_interaction_position(
            self.world,
            resource,
            gatherer_id,
        )
        self.world.enqueue_command(
            gatherer_id,
            make_command("move", [gatherer_id], target_pos=interaction_point, queued=queued),
        )
        self.world.enqueue_command(
            gatherer_id,
            make_command(
                "gather",
                [gatherer_id],
                target_entity_id=resource.id,
                target_pos=interaction_point,
                queued=True,
                resource_type=resource.resource_type,
                current_resource_id=resource.id.to_json(),
                manual=manual,
            ),
        )

    def _builder_interaction_point(
        self,
        hut: Building,
        builder_id: EntityId,
        *,
        index: int,
        total: int,
    ) -> WorldPosition:
        layout = terrain_layout_for_height(self.world.settings.world_height)
        columns = max(1, min(5, total))
        row = index // columns
        column = index % columns
        row_count = columns if row < (total // columns) else total - (row * columns)
        row_count = max(1, row_count)
        x_offset = (column - ((row_count - 1) / 2)) * 28
        y_offset = row * 30
        return nearest_free_position(
            self.world,
            WorldPosition(hut.position.x + x_offset, layout.unit_walkable_top_y + y_offset),
            ignore_id=builder_id,
        )

    def _resource_interaction_point(
        self,
        resource: ResourceNode,
        gatherer_id: EntityId,
        *,
        index: int,
        total: int,
    ) -> WorldPosition:
        left, top, width, height = blocking_bounds_for_entity(resource)
        right = left + width
        bottom = top + height
        center_x = left + (width / 2)
        center_y = top + (height / 2)
        columns = max(1, min(5, total))
        row = index // columns
        column = index % columns
        row_count = columns if row < (total // columns) else total - (row * columns)
        row_count = max(1, row_count)
        offset = (column - ((row_count - 1) / 2)) * 28
        row_offset = row * 24
        candidates = (
            WorldPosition(center_x + offset, bottom + 30 + row_offset),
            WorldPosition(center_x + offset, top - 18 - row_offset),
            WorldPosition(left - 28 - row_offset, center_y + offset),
            WorldPosition(right + 28 + row_offset, center_y + offset),
        )
        gatherer = self.world.entities.get(gatherer_id)
        origin = gatherer.position if gatherer is not None else resource.position
        ordered_candidates = sorted(candidates, key=lambda candidate: _distance(origin, candidate))
        for candidate in ordered_candidates:
            clamped = clamp_unit_position_to_walkable_lane_for_height(
                candidate,
                self.world.settings.world_height,
            )
            return nearest_free_position(self.world, clamped, ignore_id=gatherer_id)
        return nearest_free_position(self.world, resource.position, ignore_id=gatherer_id)

    def _cancel_active_mode(self) -> bool:
        if (
            self.active_command_ability is None
            and self.active_dropoff_building_id is None
            and self.active_building_placement is None
            and not self.build_menu_open
        ):
            return False
        self.active_command_ability = None
        self.active_dropoff_building_id = None
        self.active_building_placement = None
        self.build_menu_open = False
        return True

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


def _desktop_size_for_display(
    display_index: int,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    sizes = pygame.display.get_desktop_sizes()
    if 0 <= display_index < len(sizes):
        width, height = sizes[display_index]
        if width > 0 and height > 0:
            return (width, height)
    return fallback


def _pin_window_to_primary_display() -> None:
    os.environ.pop("SDL_VIDEO_CENTERED", None)
    os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"


def _normalize_screen_rect(
    start: tuple[int, int],
    end: tuple[int, int],
) -> ScreenRect:
    left = min(start[0], end[0])
    top = min(start[1], end[1])
    width = abs(end[0] - start[0])
    height = abs(end[1] - start[1])
    return (left, top, width, height)


def _bounds_intersect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    return not (
        first_left + first_width < second_left
        or second_left + second_width < first_left
        or first_top + first_height < second_top
        or second_top + second_height < first_top
    )


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def _needs_repair(building: Building) -> bool:
    max_hp = int(getattr(building, "max_hp", 0) or getattr(building, "hp", 0))
    return max_hp > 0 and building.hp < max_hp


def _resource_matches(resource: ResourceNode, resource_type: str) -> bool:
    return resource.resource_type == resource_type and resource.amount_remaining > 0

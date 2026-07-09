"""Pygame runtime for the minimal playable slice."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from math import hypot

import pygame

from house_of_wolves.core.contracts import EntityId, Footprint, WorldPosition
from house_of_wolves.core.keybindings import (
    COMMAND_PANEL_SLOT_ACTIONS,
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
    command_slot_index_for_key,
    normalized_key_name,
)
from house_of_wolves.core.performance import time_block
from house_of_wolves.core.renderer import BuildingPlacementPreview, GameRenderer, ScreenRect
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.building import Building
from house_of_wolves.entities.resource_node import ResourceNode
from house_of_wolves.systems.buildings import BuildingLifecycleSystem
from house_of_wolves.systems.combat import CombatSystem
from house_of_wolves.systems.commands import make_command
from house_of_wolves.systems.construction import ConstructionSystem, starting_construction_hp
from house_of_wolves.systems.economy import (
    EconomySystem,
    completed_deposit_huts,
    gather_slot_count_for_resource,
    issue_gather_command,
)
from house_of_wolves.systems.farming import (
    CHICKEN_FARM_ID,
    FARM_BUILDING_SPECS,
    PIG_FARM_ID,
    FarmSystem,
    is_farm_building,
)
from house_of_wolves.systems.group_movement import issue_group_move_command
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.systems.production import (
    PRODUCTION_BUILDING_SPECS,
    ProductionError,
    produce_unit,
)
from house_of_wolves.systems.selection import SelectionSystem
from house_of_wolves.systems.waves import WaveSystem
from house_of_wolves.ui.selected_panel import selected_panel_for
from house_of_wolves.world.collision import nearest_free_position, position_blocked_by_hard_obstacle
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
HUT_BUILD_COST = {"wood": 50}
BUILD_MENU_ABILITIES = ("Hut", "Barracks", "Archery", "Chicken Farm", "Pig Farm", "Back")
BUILDING_ID_BY_BUILD_ABILITY = {
    "Hut": HUT_BUILDING_ID,
    "Barracks": "barracks",
    "Archery": "archery",
    "Chicken Farm": CHICKEN_FARM_ID,
    "Pig Farm": PIG_FARM_ID,
}
PLACEMENT_MENU_ABILITIES = ("Cancel",)
GATHER_RESOURCE_TYPES = {
    "Gather Wood": "wood",
    "Gather Gold": "gold",
    "Gather Iron": "iron",
    "Gather Stone": "stone",
}
KEYBIND_GATHER_ACTIONS = {
    KEYBIND_GATHER_WOOD: "Gather Wood",
    KEYBIND_GATHER_GOLD: "Gather Gold",
    KEYBIND_GATHER_ORE: "Gather Iron",
    KEYBIND_GATHER_STONE: "Gather Stone",
}
DOUBLE_CLICK_MS = 350
COMMON_UNIT_TYPE_TAGS = {"unit", "selectable", "movable", "enemy"}


@dataclass(slots=True)
class GameRuntime:
    """Owns Pygame init, input, update, render, and shutdown."""

    settings: AppSettings
    world: WorldState = field(default_factory=create_demo_world)
    selection_system: SelectionSystem = field(default_factory=SelectionSystem)
    movement_system: MovementSystem = field(default_factory=MovementSystem)
    combat_system: CombatSystem = field(default_factory=CombatSystem)
    building_lifecycle_system: BuildingLifecycleSystem = field(
        default_factory=BuildingLifecycleSystem,
    )
    construction_system: ConstructionSystem = field(default_factory=ConstructionSystem)
    economy_system: EconomySystem = field(default_factory=EconomySystem)
    farm_system: FarmSystem = field(default_factory=FarmSystem)
    wave_system: WaveSystem = field(default_factory=WaveSystem)
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
    control_groups: dict[int, list[EntityId]] = field(default_factory=dict)
    last_click_entity_id: EntityId | None = None
    last_click_ms: int = -DOUBLE_CLICK_MS

    def __post_init__(self) -> None:
        """Normalize derived state after dataclass initialization."""
        if self.world.settings != self.settings:
            self.world = create_demo_world(self.settings)

    def initialize(self) -> None:
        """Initialize runtime resources before the game loop starts."""
        _pin_window_to_primary_display()
        pygame.init()
        pygame.display.set_caption(self.settings.window_title)
        self._set_display_mode(rebuild_world=True)
        self.clock = pygame.time.Clock()
        self.running = True

    def shutdown(self) -> None:
        """Release runtime resources and close Pygame."""
        self.running = False
        pygame.quit()

    def _set_display_mode(self, *, rebuild_world: bool) -> None:
        """Create the Pygame display using the configured mode."""
        flags = pygame.FULLSCREEN if self.settings.fullscreen else pygame.NOFRAME
        size = _desktop_size_for_display(self.settings.display_index, self.settings.virtual_size)
        self.display_flags = flags
        self.screen = pygame.display.set_mode(size, flags, display=self.settings.display_index)
        self._apply_display_size(self.screen.get_size(), rebuild_world=rebuild_world)
        self.renderer = GameRenderer(self.settings)

    def _apply_display_size(self, size: tuple[int, int], *, rebuild_world: bool) -> None:
        """Apply a display size change to settings, world, and camera."""
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
        """Run the app or runtime loop until it exits."""
        self.initialize()
        frame_count = 0
        try:
            while self.running:
                assert self.clock is not None
                dt_ms = self.clock.tick(self.settings.target_fps)
                stats = self.world.performance_stats
                stats.reset_frame()
                stats.fps = self.clock.get_fps()
                with time_block(stats, "input"):
                    self.process_events()
                with time_block(stats, "update"):
                    self.update(dt_ms)
                with time_block(stats, "render"):
                    self.render()
                with time_block(stats, "display"):
                    pygame.display.flip()
                frame_count += 1
                if max_frames is not None and frame_count >= max_frames:
                    self.running = False
        finally:
            self.shutdown()
        return 0

    def process_events(self) -> None:
        """Process pending Pygame input events."""
        for event in pygame.event.get():
            self.handle_event(event)

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle one Pygame event."""
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
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
            self._toggle_performance_overlay()
            return
        if event.type == pygame.KEYDOWN and self._handle_control_group_hotkey(event):
            return
        if event.type == pygame.KEYDOWN and self._handle_command_slot_hotkey(event.key):
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
            if self._handle_building_rally_right_click(event.pos):
                return
            if self._handle_settler_context_right_click(event.pos, queued=_shift_pressed()):
                return
            if self._handle_unit_context_right_click(event.pos, queued=_shift_pressed()):
                return
            self._issue_move(event.pos, queued=_shift_pressed())

    def _handle_ability_click(self, screen_pos: tuple[int, int]) -> bool:
        """Handle ability click input or UI flow."""
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
        return self._handle_ability(ability)

    def _handle_ability(self, ability: str) -> bool:
        """Handle ability input or UI flow."""
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
        if ability == "Unassign Worker":
            self._unassign_selected_farm_worker()
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
        if ability.startswith(("Produce ", "Train ")):
            self.active_dropoff_building_id = None
            self.active_command_ability = None
            self.build_menu_open = False
            self.active_building_placement = None
            self._produce_from_selection(
                ability.removeprefix("Produce ").removeprefix("Train ")
            )
        return True

    def _handle_build_menu_ability(self, ability: str) -> bool:
        """Handle build menu ability input or UI flow."""
        if ability == "Back":
            self.build_menu_open = False
            return True
        building_id = BUILDING_ID_BY_BUILD_ABILITY.get(ability)
        if building_id is not None:
            self.build_menu_open = False
            self.active_building_placement = building_id
            return True
        return True

    def _handle_build_placement_ability(self, ability: str) -> bool:
        """Handle build placement ability input or UI flow."""
        if ability == "Cancel":
            self.active_building_placement = None
            return True
        return True

    def _toggle_dropoff_mode(self) -> None:
        """Toggle dropoff mode."""
        building = self._selected_dropoff_building()
        if building is None:
            self.active_dropoff_building_id = None
            return
        if self.active_dropoff_building_id == building.id:
            self.active_dropoff_building_id = None
        else:
            self.active_dropoff_building_id = building.id

    def _handle_dropoff_placement(self, screen_pos: tuple[int, int]) -> bool:
        """Handle dropoff placement input or UI flow."""
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
        self._set_building_rally_point(
            building,
            self.world.camera.screen_to_world(*screen_pos),
        )
        self.active_dropoff_building_id = None
        return True

    def _handle_building_placement(self, screen_pos: tuple[int, int]) -> bool:
        """Handle building placement input or UI flow."""
        if self.active_building_placement is None:
            return False
        if (
            self.screen is not None
            and self.renderer is not None
            and self.renderer.panel_contains(self.screen, screen_pos)
        ):
            return True
        building_id = self.active_building_placement
        if building_id is None:
            return False
        world_pos = self.world.camera.screen_to_world(*screen_pos)
        if not self._valid_building_placement_at(building_id, world_pos):
            return True
        if not self._spend_building_cost(building_id):
            return True
        site = self._create_building_construction_site(building_id, world_pos)
        queued = _shift_pressed()
        self._order_selected_builders_to_site(site, queued=queued)
        if not queued:
            self.active_building_placement = None
        return True

    def _handle_command_placement(self, screen_pos: tuple[int, int]) -> bool:
        """Handle command placement input or UI flow."""
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
        self._issue_move(screen_pos, queued=_shift_pressed(), attack_move=attack_move)
        self.active_command_ability = None
        return True

    def _selected_dropoff_building(self) -> Building | None:
        """Return the selected building with a drop-off marker."""
        return self._selected_rally_building()

    def _selected_rally_building(self) -> Building | None:
        """Return the selected building that can accept a rally point."""
        if len(self.selection_system.state.selected_ids) != 1:
            return None
        entity = self.world.entities.get(self.selection_system.state.selected_ids[0])
        if (
            isinstance(entity, Building)
            and entity.owner == "frontier"
            and entity.complete
            and (
                entity.production_config.dropoff
                or len(entity.production_config.trainable_units) > 0
            )
        ):
            return entity
        return None

    def _produce_from_selection(self, display_name: str) -> None:
        """Produce from selection."""
        if len(self.selection_system.state.selected_ids) != 1:
            return
        producer_id = self.selection_system.state.selected_ids[0]
        unit_id = display_name.replace(" ", "_").lower()
        try:
            produce_unit(self.world, producer_id, unit_id)
        except ProductionError as error:
            self.world.notify(str(error))
            return

    def _handle_building_rally_right_click(
        self,
        screen_pos: tuple[int, int],
    ) -> bool:
        """Handle building rally right click input or UI flow."""
        building = self._selected_rally_building()
        if building is None:
            return False
        if (
            self.screen is not None
            and self.renderer is not None
            and self.renderer.panel_contains(self.screen, screen_pos)
        ):
            return True
        self._set_building_rally_point(
            building,
            self.world.camera.screen_to_world(*screen_pos),
        )
        return True

    def _set_building_rally_point(self, building: Building, world_pos: WorldPosition) -> bool:
        """Set building rally point."""
        target_pos = clamp_unit_position_to_walkable_lane_for_height(
            world_pos,
            self.world.settings.world_height,
        )
        if position_blocked_by_hard_obstacle(
            self.world,
            target_pos,
            ignore_id=building.id,
        ):
            self.world.notify("Invalid rally point.")
            return False
        building.dropoff_point = target_pos
        return True

    def _handle_settler_context_right_click(
        self,
        screen_pos: tuple[int, int],
        *,
        queued: bool,
    ) -> bool:
        """Handle settler context right click input or UI flow."""
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
            if is_farm_building(entity):
                self._assign_selected_worker_to_farm(entity)
                return True
            if _needs_repair(entity):
                self._order_selected_repairers_to_site(entity, queued=queued)
                return True
            return False
        if isinstance(entity, ResourceNode):
            self._order_selected_gatherers_to_resource(entity, queued=queued)
            return True
        return False

    def _handle_unit_context_right_click(
        self,
        screen_pos: tuple[int, int],
        *,
        queued: bool,
    ) -> bool:
        """Handle unit context right click input or UI flow."""
        if not self._selected_player_attack_unit_ids():
            return False
        target_id = self.selection_system.pick_at(
            self.world,
            self.world.camera.screen_to_world(*screen_pos),
        )
        if target_id is None:
            return False
        target = self.world.entities.get(target_id)
        if target is None or target.owner in {"frontier", "neutral"}:
            return False
        for entity_id in self._selected_player_attack_unit_ids():
            self.world.enqueue_command(
                entity_id,
                make_command("attack", [entity_id], target_entity_id=target_id, queued=queued),
            )
        return True

    def _handle_key_rebind(self, event: pygame.event.Event) -> bool:
        """Handle key rebind input or UI flow."""
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
        """Handle hotkey input or UI flow."""
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
            if not self._ability_available("Build"):
                return True
            self.active_dropoff_building_id = None
            self.active_command_ability = None
            self.active_building_placement = None
            self.build_menu_open = True
            return True
        if action == KEYBIND_ATTACK:
            if not self._ability_available("Attack"):
                return True
            return self._activate_command_ability("Attack")
        if action == KEYBIND_ATTACK_MOVE:
            if not self._ability_available("Attack Move"):
                return True
            return self._activate_command_ability("Attack Move")
        if action in KEYBIND_GATHER_ACTIONS:
            ability = KEYBIND_GATHER_ACTIONS[action]
            if not self._ability_available(ability):
                return True
            self._issue_auto_gather(GATHER_RESOURCE_TYPES[ability])
            return True
        return False

    def _handle_command_slot_hotkey(self, key: int) -> bool:
        """Handle command slot hotkey input or UI flow."""
        if self.settings_menu_open:
            return False
        slot_index = command_slot_index_for_key(
            pygame.key.name(key),
            self.settings.keybindings,
        )
        if slot_index is None:
            return False
        ability = self._ability_for_command_slot(slot_index)
        if ability is None:
            return False
        return self._handle_ability(ability)

    def _ability_for_command_slot(self, slot_index: int) -> str | None:
        """Return the ability assigned to a command-panel hotkey slot."""
        abilities = self._available_abilities()
        if slot_index < 0 or slot_index >= len(abilities):
            return None
        return abilities[slot_index]

    def _ability_available(self, ability: str) -> bool:
        """Return whether an ability is active in the current panel."""
        return ability in self._available_abilities()

    def _available_abilities(self) -> tuple[str, ...]:
        """Return available abilities."""
        abilities = self._ability_override()
        if abilities is not None:
            return abilities
        return selected_panel_for(
            self.world,
            self.selection_system.state.selected_ids,
        ).abilities

    def _handle_control_group_hotkey(self, event: pygame.event.Event) -> bool:
        """Handle control group hotkey input or UI flow."""
        if self.settings_menu_open:
            return False
        group_number = _number_key(event.key)
        if group_number is None:
            return False
        mods = int(getattr(event, "mod", pygame.key.get_mods()))
        if mods & pygame.KMOD_CTRL:
            self._assign_control_group(group_number)
        else:
            self._recall_control_group(group_number)
        return True

    def _assign_control_group(self, group_number: int) -> None:
        """Assign control group."""
        self.control_groups[group_number] = [
            entity_id
            for entity_id in self.selection_system.state.selected_ids
            if entity_id in self.world.entities
        ]

    def _recall_control_group(self, group_number: int) -> None:
        """Recall and select a stored control group."""
        entity_ids = [
            entity_id
            for entity_id in self.control_groups.get(group_number, [])
            if entity_id in self.world.entities
            and getattr(self.world.entities[entity_id], "alive", False)
        ]
        self.control_groups[group_number] = entity_ids
        self.selection_system.state.replace(entity_ids)

    def _activate_command_ability(self, ability: str) -> bool:
        """Enter targeting mode for a selected command ability."""
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
        """Return the configured action bound to a pressed key."""
        key_name = normalized_key_name(pygame.key.name(key))
        for action in KEYBIND_ACTION_ORDER:
            if action in COMMAND_PANEL_SLOT_ACTIONS:
                continue
            if self.settings.keybindings.get(action) == key_name:
                return action
        return None

    def update(self, dt_ms: int) -> None:
        """Advance this system for one simulation tick."""
        stats = self.world.performance_stats
        with time_block(stats, "camera"):
            self._update_camera(dt_ms)
        with time_block(stats, "combat"):
            self.combat_system.update(self.world, dt_ms)
        with time_block(stats, "buildings"):
            self.building_lifecycle_system.update(self.world, dt_ms)
        with time_block(stats, "movement"):
            self.movement_system.update(self.world, dt_ms)
        with time_block(stats, "construction"):
            self.construction_system.update(self.world, dt_ms)
        with time_block(stats, "economy"):
            self.economy_system.update(self.world, dt_ms)
        gather_stats = self.economy_system.last_frame_stats
        stats.counters.path_jobs_processed += gather_stats.path_jobs_processed
        stats.counters.resource_candidates_checked += gather_stats.resource_candidates_checked
        stats.counters.full_path_calculations += gather_stats.full_path_calculations
        stats.counters.resource_searches += gather_stats.resource_searches
        with time_block(stats, "farming"):
            self.farm_system.update(self.world, dt_ms)
        with time_block(stats, "waves"):
            self.wave_system.update(self.world, dt_ms)
        with time_block(stats, "notifications"):
            self.world.update_notifications(dt_ms)
        # Combat and waves can remove entities during the frame; keep selection
        # state pointing only at live world objects before the next render/input pass.
        self.selection_system.state.selected_ids = [
            entity_id
            for entity_id in self.selection_system.state.selected_ids
            if entity_id in self.world.entities
            and getattr(self.world.entities[entity_id], "alive", False)
        ]
        stats.snapshot_world_counts(self.world)

    def render(self) -> None:
        """Render the current game frame or UI panel."""
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
        """Return the active ability label."""
        if self.active_command_ability is not None:
            return self.active_command_ability
        if self.active_dropoff_building_id is not None:
            return "Dropoff"
        return None

    def _ability_override(self) -> tuple[str, ...] | None:
        """Return entity identifiers for ability override."""
        if self.active_building_placement is not None:
            return PLACEMENT_MENU_ABILITIES
        if self.build_menu_open:
            return BUILD_MENU_ABILITIES
        return None

    def _handle_settings_click(self, screen_pos: tuple[int, int]) -> bool:
        """Handle settings click input or UI flow."""
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
        if self.renderer.settings_performance_overlay_toggle_rect(self.screen).collidepoint(
            screen_pos
        ):
            self._toggle_performance_overlay()
            return True
        if self.renderer.settings_hit_flashes_toggle_rect(self.screen).collidepoint(
            screen_pos
        ):
            self._toggle_hit_flashes()
            return True
        if self.renderer.settings_waves_toggle_rect(self.screen).collidepoint(screen_pos):
            self._toggle_waves()
            return True
        if self.renderer.settings_wave_timer_toggle_rect(self.screen).collidepoint(screen_pos):
            self._toggle_wave_timer()
            return True
        if self.renderer.settings_start_wave_rect(self.screen).collidepoint(screen_pos):
            self.wave_system.start_wave_now(self.world)
            return True
        resource_key = self.renderer.settings_resource_grant_at(self.screen, screen_pos)
        if resource_key is not None:
            self._grant_debug_resource(resource_key)
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
        """Toggle fullscreen."""
        self.settings_menu_open = False
        self.settings = replace(self.settings, fullscreen=not self.settings.fullscreen)
        self._set_display_mode(rebuild_world=False)

    def _toggle_resource_hitboxes(self) -> None:
        """Toggle resource hitboxes."""
        self.settings = replace(
            self.settings,
            show_resource_hitboxes=not self.settings.show_resource_hitboxes,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_unit_hitboxes(self) -> None:
        """Toggle unit hitboxes."""
        self.settings = replace(
            self.settings,
            show_unit_hitboxes=not self.settings.show_unit_hitboxes,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_building_hitboxes(self) -> None:
        """Toggle building hitboxes."""
        self.settings = replace(
            self.settings,
            show_building_hitboxes=not self.settings.show_building_hitboxes,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_debug_waypoints(self) -> None:
        """Toggle debug waypoints."""
        self.settings = replace(
            self.settings,
            show_debug_waypoints=not self.settings.show_debug_waypoints,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_performance_overlay(self) -> None:
        """Toggle performance overlay."""
        self.settings = replace(
            self.settings,
            show_performance_overlay=not self.settings.show_performance_overlay,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_waves(self) -> None:
        """Toggle automatic enemy wave spawning."""
        self.settings = replace(self.settings, waves_enabled=not self.settings.waves_enabled)
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_wave_timer(self) -> None:
        """Toggle timer-driven enemy wave spawning."""
        self.settings = replace(
            self.settings,
            wave_timer_enabled=not self.settings.wave_timer_enabled,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _toggle_hit_flashes(self) -> None:
        """Toggle debug-only attacker and target outline flashes."""
        self.settings = replace(
            self.settings,
            show_debug_hit_flashes=not self.settings.show_debug_hit_flashes,
        )
        self.world.settings = self.settings
        self.renderer = GameRenderer(self.settings)

    def _grant_debug_resource(self, resource_key: str, amount: int = 10) -> None:
        """Add resources from the settings debug menu."""
        # Keep the cheat local to runtime state; it should behave like gathered
        # inventory and avoid touching resource-node depletion logic.
        self.world.resources[resource_key] = self.world.resources.get(resource_key, 0) + amount

    def _update_camera(self, dt_ms: int) -> None:
        """Advance camera for the current frame."""
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
        """Finish selection."""
        start = self.drag_start_screen
        self.drag_start_screen = None
        self.drag_current_screen = None
        if start is None:
            return
        drag_distance = hypot(end_screen[0] - start[0], end_screen[1] - start[1])
        if drag_distance < self.settings.selection_drag_threshold:
            self._finish_click_selection(end_screen, add=add)
            return
        world_bounds = self._screen_drag_to_world_bounds(start, end_screen)
        self.selection_system.box_select(self.world, world_bounds, add=add)

    def _finish_click_selection(self, screen_pos: tuple[int, int], *, add: bool) -> None:
        """Finish click selection."""
        world_pos = self.world.camera.screen_to_world(*screen_pos)
        picked_id = self.selection_system.pick_at(self.world, world_pos)
        now_ms = pygame.time.get_ticks()
        if (
            picked_id is not None
            and picked_id == self.last_click_entity_id
            and now_ms - self.last_click_ms <= DOUBLE_CLICK_MS
            and self._select_visible_same_type_units(picked_id, add=add)
        ):
            self.last_click_ms = now_ms
            return
        self.selection_system.select_at(self.world, world_pos, add=add)
        self.last_click_entity_id = picked_id
        self.last_click_ms = now_ms

    def _select_visible_same_type_units(self, entity_id: EntityId, *, add: bool) -> bool:
        """Select visible units matching the clicked unit type."""
        entity = self.world.entities.get(entity_id)
        if (
            entity is None
            or "unit" not in entity.tags
            or entity.owner != "frontier"
        ):
            return False
        unit_type = _unit_type_tag(entity)
        if unit_type is None:
            return False
        selected_ids = [
            other.id
            for other in self.world.entities.values()
            if other.owner == "frontier"
            and "unit" in other.tags
            and unit_type in other.tags
            and self._entity_is_visible_on_screen(other)
        ]
        selected_ids.sort(key=int)
        if add and self.selection_system._current_selection_is_player_units(self.world):
            for selected_id in selected_ids:
                self.selection_system.state.add(selected_id)
        else:
            self.selection_system.state.replace(selected_ids)
        return True

    def _entity_is_visible_on_screen(self, entity: object) -> bool:
        """Return whether an entity is inside the current viewport."""
        left, top, width, height = entity.bounds
        right = left + width
        bottom = top + height
        view_left = self.world.camera.x
        view_right = view_left + self.world.camera.viewport_width
        view_top = 0
        view_bottom = max(0, self.world.camera.viewport_height - self.settings.ui_panel_height)
        return not (
            right < view_left
            or left > view_right
            or bottom < view_top
            or top > view_bottom
        )

    def _issue_move(
        self,
        screen_pos: tuple[int, int],
        *,
        queued: bool,
        attack_move: bool = False,
    ) -> None:
        """Issue move commands."""
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
        """Issue attack commands."""
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

    def _issue_auto_gather(self, resource_type: str) -> None:
        """Issue auto gather commands."""
        gatherer_ids = self._selected_builder_ids()
        if not gatherer_ids:
            return
        self.active_dropoff_building_id = None
        self.active_command_ability = None
        self.build_menu_open = False
        self.active_building_placement = None
        message = self.economy_system.queue_auto_gather(
            self.world,
            gatherer_ids,
            resource_type,
            owner="frontier",
        )
        if message is not None:
            self.world.notify(message)
            return

    def _stop_selected_units(self) -> None:
        """Clear commands for selected controllable units."""
        for entity_id in self._selected_player_movable_unit_ids():
            queue = self.world.command_queues.get(entity_id)
            if queue is not None:
                queue.clear()
            entity = self.world.entities.get(entity_id)
            if entity is not None and hasattr(entity, "state"):
                entity.state = "idle"

    def _selected_player_movable_unit_ids(self) -> list[EntityId]:
        """Return entity identifiers for selected player movable unit ids."""
        return [
            entity_id
            for entity_id in self.selection_system.state.selected_ids
            if entity_id in self.world.entities
            and "unit" in self.world.entities[entity_id].tags
            and "movable" in self.world.entities[entity_id].tags
            and self.world.entities[entity_id].owner == "frontier"
        ]

    def _selected_player_attack_unit_ids(self) -> list[EntityId]:
        """Return entity identifiers for selected player attack unit ids."""
        return [
            entity_id
            for entity_id in self.selection_system.state.selected_ids
            if entity_id in self.world.entities
            and "unit" in self.world.entities[entity_id].tags
            and self.world.entities[entity_id].owner == "frontier"
            and int(getattr(self.world.entities[entity_id], "damage", 0)) > 0
        ]

    def _selected_builder_ids(self) -> list[EntityId]:
        """Return entity identifiers for selected builder ids."""
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
        """Build the current building placement preview."""
        building_id = self.active_building_placement
        if building_id is None:
            return None
        position = self.world.camera.screen_to_world(*self.mouse_screen_pos)
        footprint = self._building_footprint(building_id)
        snapped_position = self._snapped_building_position(position)
        return BuildingPlacementPreview(
            building_id=building_id,
            position=snapped_position,
            footprint=footprint,
            valid=self._valid_building_placement_at(building_id, position),
        )

    def _valid_hut_placement_at(self, position: WorldPosition) -> bool:
        """Return entity identifiers for valid hut placement at."""
        return self._valid_building_placement_at(HUT_BUILDING_ID, position)

    def _valid_building_placement_at(self, building_id: str, position: WorldPosition) -> bool:
        """Return entity identifiers for valid building placement at."""
        footprint = self._building_footprint(building_id)
        snapped = self._snapped_building_position(position)
        half_width = footprint.width / 2
        if snapped.x < half_width or snapped.x > self.world.settings.world_width - half_width:
            return False
        return not self._building_overlaps_existing_building(snapped, footprint)

    def _snapped_hut_position(self, position: WorldPosition) -> WorldPosition:
        """Return the position used for snapped hut position."""
        return self._snapped_building_position(position)

    def _snapped_building_position(self, position: WorldPosition) -> WorldPosition:
        """Return the position used for snapped building position."""
        layout = terrain_layout_for_height(self.world.settings.world_height)
        return WorldPosition(position.x, layout.building_lane_bottom_y)

    def _building_overlaps_existing_building(
        self,
        position: WorldPosition,
        footprint: Footprint,
    ) -> bool:
        """Return whether placement overlaps a building footprint."""
        bounds = footprint.bounds_at(position)
        for entity in self.world.entities.values():
            if "building" not in entity.tags or not entity.alive:
                continue
            if _bounds_intersect(bounds, entity.bounds):
                return True
        return False

    def _create_hut_construction_site(self, position: WorldPosition) -> Building:
        """Create hut construction site."""
        return self._create_building_construction_site(HUT_BUILDING_ID, position)

    def _create_building_construction_site(
        self,
        building_id: str,
        position: WorldPosition,
    ) -> Building:
        """Create building construction site."""
        build_position = self._snapped_building_position(position)
        if building_id == HUT_BUILDING_ID:
            building = Building(
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
                    population_cap_bonus=self.settings.hut_pop_cap_bonus,
                    trainable_units=("settler", "spearman"),
                ),
                dropoff_point=WorldPosition(
                    build_position.x + 220,
                    terrain_layout_for_height(
                        self.world.settings.world_height
                    ).unit_walkable_top_y,
                ),
            )
            self.world.add_entity(building)
            return building

        if building_id in PRODUCTION_BUILDING_SPECS:
            spec = PRODUCTION_BUILDING_SPECS[building_id]
            # Dedicated military buildings share the construction/rally path used
            # by huts, but their functions only expose trainable unit production.
            building = Building(
                id=self.world.allocate_entity_id(),
                owner="frontier",
                position=build_position,
                footprint=spec.footprint,
                hp=starting_construction_hp(spec.hp),
                max_hp=spec.hp,
                tags=("building", spec.building_id, "selectable"),
                build_time_ms=spec.build_time_ms,
                complete=False,
                functions=Building.production_functions(
                    trainable_units=spec.trainable_units,
                ),
                dropoff_point=WorldPosition(
                    build_position.x + 220,
                    terrain_layout_for_height(
                        self.world.settings.world_height
                    ).unit_walkable_top_y,
                ),
            )
            self.world.add_entity(building)
            return building

        spec = FARM_BUILDING_SPECS[building_id]
        farm = Building(
            id=self.world.allocate_entity_id(),
            owner="frontier",
            position=build_position,
            footprint=spec.footprint,
            hp=starting_construction_hp(spec.hp),
            max_hp=spec.hp,
            tags=("building", building_id, "selectable"),
            build_time_ms=spec.build_time_ms,
            complete=False,
            functions={
                "farm_type": spec.farm_type,
                "farm_state": "idle_no_worker",
                "food_output": spec.animal_food_yield,
            },
        )
        self.world.add_entity(farm)
        return farm

    def _building_footprint(self, building_id: str) -> Footprint:
        """Return the footprint for a buildable building type."""
        if building_id == HUT_BUILDING_ID:
            return HUT_FOOTPRINT
        if building_id in PRODUCTION_BUILDING_SPECS:
            return PRODUCTION_BUILDING_SPECS[building_id].footprint
        return FARM_BUILDING_SPECS[building_id].footprint

    def _building_cost(self, building_id: str) -> dict[str, int]:
        """Return the configured cost for building cost."""
        if building_id == HUT_BUILDING_ID:
            return HUT_BUILD_COST
        if building_id in PRODUCTION_BUILDING_SPECS:
            return PRODUCTION_BUILDING_SPECS[building_id].cost
        return FARM_BUILDING_SPECS[building_id].cost

    def _spend_building_cost(self, building_id: str) -> bool:
        """Spend building cost."""
        cost = self._building_cost(building_id)
        for resource, amount in cost.items():
            if self.world.resources.get(resource, 0) < amount:
                self.world.notify(f"Needs {resource}.")
                return False
        for resource, amount in cost.items():
            self.world.resources[resource] = self.world.resources.get(resource, 0) - amount
        return True

    def _order_selected_builders_to_site(self, hut: Building, *, queued: bool = False) -> None:
        """Issue orders for selected builders to site."""
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
        """Issue orders for builder to site."""
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
                building_id=_building_id_for_site(hut),
            ),
        )

    def _assign_selected_worker_to_farm(self, farm: Building) -> None:
        """Assign selected worker to farm."""
        builder_ids = self._selected_builder_ids()
        if not builder_ids:
            return
        message = self.farm_system.assign_worker(self.world, farm, builder_ids[0])
        if message is not None:
            self.world.notify(message)

    def _unassign_selected_farm_worker(self) -> None:
        """Unassign workers from selected farm buildings."""
        if len(self.selection_system.state.selected_ids) != 1:
            return
        entity = self.world.entities.get(self.selection_system.state.selected_ids[0])
        if not isinstance(entity, Building) or not is_farm_building(entity):
            return
        self.farm_system.unassign_farm(self.world, entity)

    def _order_selected_repairers_to_site(
        self,
        building: Building,
        *,
        queued: bool = False,
    ) -> None:
        """Issue orders for selected repairers to site."""
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
        """Issue orders for selected gatherers to resource."""
        gatherer_ids = self._selected_builder_ids()
        if not gatherer_ids:
            return
        if not completed_deposit_huts(self.world, "frontier"):
            self.world.notify("Needs hut to deposit.")
            return
        slot_count = gather_slot_count_for_resource(resource)
        for index, gatherer_id in enumerate(gatherer_ids):
            slot_index = index % slot_count if slot_count > 0 else 0
            self._order_gatherer_to_resource(
                resource,
                gatherer_id,
                queued=queued,
                manual=True,
                slot_index=slot_index,
            )

    def _order_gatherer_to_resource(
        self,
        resource: ResourceNode,
        gatherer_id: EntityId,
        *,
        queued: bool,
        manual: bool,
        slot_index: int = 0,
    ) -> None:
        """Issue orders for gatherer to resource."""
        issue_gather_command(
            self.world,
            resource,
            gatherer_id,
            queued=queued,
            manual=manual,
            slot_index=slot_index,
        )

    def _builder_interaction_point(
        self,
        hut: Building,
        builder_id: EntityId,
        *,
        index: int,
        total: int,
    ) -> WorldPosition:
        """Return a worker approach point for a building site."""
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

    def _cancel_active_mode(self) -> bool:
        """Cancel active mode."""
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
        """Return the bounds used for current drag rect."""
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
        """Return the bounds used for screen drag to world bounds."""
        left, top, width, height = _normalize_screen_rect(start_screen, end_screen)
        world_top_left = self.world.camera.screen_to_world(left, top)
        return (world_top_left.x, world_top_left.y, width, height)


def _shift_pressed() -> bool:
    """Return whether Shift is currently held."""
    return bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)


def _number_key(key: int) -> int | None:
    """Return the numeric control-group key for an event."""
    if pygame.K_1 <= key <= pygame.K_9:
        return (key - pygame.K_1) + 1
    if pygame.K_KP1 <= key <= pygame.K_KP9:
        return (key - pygame.K_KP1) + 1
    return None


def _unit_type_tag(entity: object) -> str | None:
    """Return the type tag used for same-type unit selection."""
    for tag in getattr(entity, "tags", ()):
        if tag not in COMMON_UNIT_TYPE_TAGS:
            return tag
    return None


def _desktop_size_for_display(
    display_index: int,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    """Return the desktop resolution for the requested display."""
    sizes = pygame.display.get_desktop_sizes()
    if 0 <= display_index < len(sizes):
        width, height = sizes[display_index]
        if width > 0 and height > 0:
            return (width, height)
    return fallback


def _pin_window_to_primary_display() -> None:
    """Ask SDL to create the window on the primary display."""
    os.environ.pop("SDL_VIDEO_CENTERED", None)
    os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"


def _normalize_screen_rect(
    start: tuple[int, int],
    end: tuple[int, int],
) -> ScreenRect:
    """Return the bounds used for normalize screen rect."""
    left = min(start[0], end[0])
    top = min(start[1], end[1])
    width = abs(end[0] - start[0])
    height = abs(end[1] - start[1])
    return (left, top, width, height)


def _bounds_intersect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    """Return the bounds used for bounds intersect."""
    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    return not (
        first_left + first_width < second_left
        or second_left + second_width < first_left
        or first_top + first_height < second_top
        or second_top + second_height < first_top
    )


def _needs_repair(building: Building) -> bool:
    """Return whether a building can be repaired by settlers."""
    max_hp = int(getattr(building, "max_hp", 0) or getattr(building, "hp", 0))
    return max_hp > 0 and building.hp < max_hp


def _building_id_for_site(building: Building) -> str:
    """Return entity identifiers for building id for site."""
    for building_id in (
        HUT_BUILDING_ID,
        "barracks",
        "archery",
        CHICKEN_FARM_ID,
        PIG_FARM_ID,
    ):
        if building_id in building.tags:
            return building_id
    return HUT_BUILDING_ID

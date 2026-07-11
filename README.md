# House of Wolves Remastered

House of Wolves Remastered is an independent, playable alpha-stage reimplementation
of the 2013 side-scrolling Flash RTS. It is written in Python 3.12 with Pygame and
focuses on rebuilding the original game's economy, production, combat, and wave
pressure in a maintainable local simulation.

This is an alpha/prototype, not a finished remaster. The current build is playable and
tested, but it still uses placeholder unit and tree visuals, has no complete campaign,
and is missing final audio, balance, progression, and save/load support.

## Contents

- [Current Playable Status](#current-playable-status)
- [Gameplay Features](#gameplay-features)
- [Setup](#setup)
- [Running The Game](#running-the-game)
- [Validation And Tests](#validation-and-tests)
- [Controls](#controls)
- [Settings And Debug Menu](#settings-and-debug-menu)
- [Architecture Overview](#architecture-overview)
- [Asset Pipeline](#asset-pipeline)
- [Performance Approach](#performance-approach)
- [Known Alpha Limitations](#known-alpha-limitations)
- [Roadmap](#roadmap)
- [Asset And Licensing Note](#asset-and-licensing-note)

## Current Playable Status

Running the game opens a borderless, monitor-sized RTS map by default. The current
build supports a complete sandbox loop:

1. Select and move units across a side-scrolling map.
2. Gather Wood, Food, Stone, Iron, and Gold.
3. Deposit gathered resources at completed Huts.
4. Construct economy and military buildings with one or more Settlers.
5. Train Settlers, Spearmen, and Archers while managing population.
6. Build defensive Wooden Archer, Stone Archer, and Wizard Towers.
7. Assign rally points and queue movement, attack, gather, and construction orders.
8. Defend buildings and units against timer-driven enemy waves.

The demo world starts with player units, a Hut, 40 Trees, and five nodes each for
Stone, Iron, and Gold. Enemy waves are enabled by default and enter from the right
side of the map.

## Gameplay Features

### Selection And Commands

- Single-click unit, building, resource, and enemy inspection.
- Drag-box selection for player units.
- Shift-click and Shift-drag additive selection.
- Double-click selection of visible player units of the same type.
- Multiple player units may be selected; buildings, resources, and enemy units are
  inspected one at a time.
- Mixed unit groups expose only actions shared by every selected unit type.
- Control groups support assignment and recall on number keys `1` through `9`.
- Right-click context commands for movement, attacks, gathering, repairs, farm work,
  construction assistance, and building rally points.
- Shift-right-click queues movement, attack, gathering, and applicable build orders.
- Move, Attack, Attack Move, and Stop command-panel actions.
- Queued waypoint links and endpoint dots for each selected unit.

### Movement And Pathing

- Loose formation slot assignment prevents groups from sharing one destination.
- Shift-queued groups preserve formation order across waypoints.
- Friendly units use soft separation, limited overlap, sliding, and short emergency
  same-team ghosting when genuinely stuck.
- Enemy units never ghost through player units.
- Buildings and resources remain hard blockers.
- Trees and mine resources expose dedicated harvest rectangles and up to eight stable
  gathering slots.
- Simple blocker detours route units around buildings and resource footprints without
  a full navigation grid.
- Units abandon only locally unreachable interaction points; ordinary long-distance
  movement is not cancelled because of incidental collisions.

### Economy And Resources

- Resources: Wood, Food, Stone, Iron, and Gold.
- Settlers gather five units per load after five successful swings.
- Wood uses animated Pygame-drawn axes; Stone, Iron, and Gold use animated pickaxes.
- Manual right-click gathering targets the selected node and intentionally ignores
  auto-gather safety checks.
- Gather action buttons search for nearby safe nodes and distribute multiple Settlers
  across candidates.
- Resource assignment uses cached node lists, cached safety checks, cheap distance
  filtering, and a frame-budgeted job queue.
- Settlers periodically re-evaluate the closest completed player Hut for deposits.
- Under-construction Huts never accept deposits.
- Trees have 150 HP. Stone, Iron, and Gold nodes have 500 HP.
- Depleted nodes enter a short destruction state before removal.
- Trees respawn after 60 seconds up to a separate cap of 40 active Trees.
- Stone, Iron, and Gold respawn after 60 seconds up to five active nodes per type.

### Construction And Buildings

Settlers can place buildings only on the dedicated building lane. Multiple Settlers
may work on one construction site, with the construction speed bonus capped at ten
workers. Active builders face the construction site and use a Pygame-drawn hammer
swing while work is progressing. Additional Settlers can join an existing site by
right-clicking it.

Current buildings:

| Building | Current role |
| --- | --- |
| Hut | Resource deposit, population provider, emergency/basic unit production |
| Barracks | Dedicated Spearman production |
| Archery | Dedicated Archer production |
| Chicken Farm | Lower-output farm loop with Chickens |
| Pig Farm | Higher-output farm loop with Pigs |
| Wooden Archer Tower | Early single-arrow defensive tower |
| Stone Archer Tower | Tougher fast-arrow defensive tower |
| Wizard Tower | Expensive splash-damage magic defensive tower |

Construction begins at 10% HP and gains HP with build progress. Processed building
sprites cover early construction, partial construction, completion, multiple damage
bands, and final destruction. Destroyed buildings become non-functional immediately
and retain a short visual destruction state before removal.

Settlers automatically repair a damaged completed player building when it is
right-clicked. There is no separate Repair button.

### Production And Population

- Every current player unit costs one population.
- Every completed player Hut provides ten population.
- Under-construction or destroyed Huts provide no population.
- Production checks building completion, available resources, trainable unit type,
  and population capacity.
- Huts, Barracks, and Archery buildings support individual rally points.
- Newly produced units spawn at a nearby valid position and walk to the rally point.

### Food Farms

- Completed Chicken and Pig Farms manage their animal lifecycle independently.
- Animals spawn and wander inside a bounded farm area even before a worker is assigned.
- One Settler may be assigned to each completed farm.
- The worker kills the animal, harvests its carcass in timed five-food loads, deposits
  at the nearest completed Hut, and repeats.
- Chicken carcasses contain 20 Food and take 120 seconds of active harvesting across
  four trips.
- Pig carcasses contain 20 Food and take 60 seconds of active harvesting across four
  trips.
- Farm animal and carcass interaction uses stable left/right worker slots.
- Farm workers pause when no completed deposit Hut is available.

### Combat And Enemy Waves

Current player units:

- Settler: worker and short-range bow attacker.
- Spearman: melee attacker.
- Archer: ranged attacker.

Current enemy wave units:

- Enemy Swordsman: melee pressure unit.
- Enemy Archer: ranged pressure unit.

Combat currently includes:

- Idle defensive target acquisition for player and enemy combat units.
- Completed defensive towers automatically acquire nearby enemy units.
- Wooden Archer Towers fire one arrow; Stone Archer Towers alternate two archers,
  firing harder-hitting fast arrows at roughly double the single-archer cadence.
- Wizard Towers fire slower, stronger Pygame-drawn magic bolts with a small
  footprint-overlap splash radius around impact.
- Direct attacks, Attack Move, local aggro, chase limits, and target cleanup.
- Building-edge melee distance so attackers do not chase unreachable building centers.
- Configurable attack wind-up and cooldown states.
- Lightweight arrow projectiles for Archers and Settlers; ranged damage applies on
  impact rather than when the shot starts.
- Pygame-drawn melee strike indicators.
- Floating damage numbers with cached text surfaces.
- Health bars for selected, damaged, or actively fighting units and buildings.
- Optional white hit/attacker flashes behind a default-off debug setting.
- Directional unit death effects: dead units leave gameplay immediately, then their
  placeholder body falls away from the incoming strike for roughly 800 ms.
- Wave-spawn notification and a short right-side spawn marker.

Projectile updates are linear in active projectile count and validate only their
assigned target. Projectiles safely continue to the last known position when their
target disappears.

## Setup

### Requirements

- Python 3.12 or newer.
- A Windows, Linux, or macOS environment supported by Pygame.
- Git and `pip`.

The project currently includes development and packaging dependencies in
`requirements.txt`, including Pygame, Pillow, NumPy, JSON Schema validation, pytest,
Ruff, coverage tooling, and PyInstaller.

### Windows PowerShell

Run these commands from the project folder, not from `C:\Windows\System32`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

If PowerShell blocks local activation scripts, allow them for the current process:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Linux Or macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Running The Game

Default borderless mode uses the primary monitor's desktop resolution:

```powershell
python -m house_of_wolves
```

Explicit display modes:

```powershell
python -m house_of_wolves --windowed
python -m house_of_wolves --fullscreen
```

On Windows, `launch_game.cmd` activates `.venv` and starts the default game mode:

```powershell
.\launch_game.cmd
```

The launcher expects `.venv` to exist in the project folder.

## Validation And Tests

Validate all JSON content definitions against their schemas without opening a window:

```powershell
python -m house_of_wolves --validate
```

Run the test suite:

```powershell
python -m pytest -q
```

Run static checks:

```powershell
python -m ruff check src tests tools
```

The test suite uses Pygame's dummy video driver where needed and covers data loading,
serialization contracts, spatial indexing, movement, group formations, gathering,
construction, production, farming, combat, waves, rendering, settings, and headless
runtime behavior.

## Controls

### Mouse And General Controls

| Input | Action |
| --- | --- |
| `A` / `D` or Left / Right arrows | Pan camera horizontally |
| Move cursor to screen edge | Edge-scroll camera |
| Left click | Select or inspect one entity |
| Left drag | Box-select player units |
| Shift + selection | Add player units to the current selection |
| Double left click unit | Select visible player units of the same type |
| Right click terrain | Move selected units |
| Shift + right click terrain | Queue movement waypoint |
| Right click enemy | Attack with selected combat-capable units |
| Shift + right click enemy | Queue attack |
| Right click resource | Gather it with selected Settlers |
| Shift + right click resource | Queue gathering |
| Right click incomplete building | Send selected Settlers to help construction |
| Right click damaged player building | Send selected Settlers to repair |
| Right click completed farm | Assign one selected Settler as farm worker |
| Right click terrain with production building selected | Set its rally point |
| Ctrl + `1`-`9` | Assign current selection to a control group |
| `1`-`9` | Recall control group |
| `F11` | Toggle fullscreen/borderless mode |
| `F3` | Toggle performance overlay |
| `Esc` | Cancel the active mode/menu; exit when no mode is active |

### Command Panel And Default Hotkeys

The command panel displays its active hotkey beside each button. Command-slot keys are
context-sensitive and activate the button currently occupying that slot:

```text
Q  W  E  R
Z  S  X  F
```

The Settler Build menu uses these slot keys for Hut, Barracks, Archery, Chicken Farm,
Pig Farm, Wooden Archer Tower, Stone Archer Tower, and Wizard Tower.

Default direct action bindings:

| Action | Default |
| --- | --- |
| Build menu | `B` |
| Build Hut | `H` |
| Cancel build/mode | `C` |
| Attack targeting | `T` |
| Attack Move targeting | `R` |
| Stop | `S` |
| Gather Wood | `W` |
| Gather Gold | `G` |
| Gather Iron | `O` |
| Gather Stone | `V` |

Command-slot bindings are processed before direct action bindings. All command-slot
and direct action keys can be changed from the Settings menu. Assigning a key already
used by another configurable action clears the older binding.

## Settings And Debug Menu

Open `Settings` from the top-right HUD. Available controls:

- Toggle borderless and fullscreen display modes.
- Toggle Resource, Unit, and Building hitbox outlines.
- Toggle numbered debug waypoint rendering.
- Toggle the performance overlay.
- Toggle white combat hit/attacker flashes. This is off by default.
- Enable or disable automatic enemy waves.
- Enable or disable the wave timer.
- Start the next enemy wave immediately.
- Add `+10` Wood, Food, Stone, Iron, or Gold for testing.
- Rebind command-panel slots and direct action keys.

Hitboxes and harvest areas remain active when their debug outlines are hidden. Turning
waves off prevents future automatic spawns but does not remove enemies already alive.
The Settings panel renders above HUD wave information.

## Architecture Overview

The project uses a `src/` package layout and one authoritative local `WorldState`.
Systems update that state in a timed Pygame loop; the renderer reads it without owning
gameplay behavior.

```text
src/house_of_wolves/
  core/       application shell, runtime loop, settings, renderer, data loading,
              typed game specs, sprite registry, keybindings, and performance tools
  entities/   units, buildings, resources, projectiles, and transient combat effects
  systems/    movement, commands, construction, economy, production, farming,
              combat, waves, and lifecycle logic
  ui/         selected panel and supporting UI modules
  world/      world state, terrain layout, camera, collision, and spatial hash
data/         JSON definitions and JSON schemas
assets/       source art, processed runtime sprites, and asset manifest
tests/        unit, integration, rendering, validation, and headless runtime tests
tools/        deterministic building and resource sprite processing scripts
```

### Runtime Data Flow

The runtime advances camera, combat, building lifecycle, movement, construction,
economy, farming, waves, and notifications each frame. Important shared contracts
include `EntityId`, `WorldPosition`, `Footprint`, `Command`, `CommandQueue`, resource
amounts, and production queue items.

`WorldState` owns:

- Entity storage and stable IDs.
- Per-entity command queues.
- Player resources and population.
- Resource-node indexes by type.
- Unit and hard-obstacle indexes.
- Completed deposit-Hut indexes.
- Camera, terrain, encounter zones, notifications, projectiles, and combat effects.
- A spatial hash used for local visibility, collision, and target queries.

JSON files under `data/` are schema-validated at startup and are the canonical source
for unit, production-building, defensive-tower, farm-building, and resource-node
runtime specs. `core.game_specs` converts those validated definitions into typed
runtime objects while preserving compatibility aliases such as legacy `ore` keybinds
for the Iron resource. Lower-level system timing, pathing thresholds, and visual-effect
durations still live as centralized Python constants.

### Implemented Systems

- **Selection:** selection constraints, additive selection, same-type double-click,
  control groups, and enemy inspection.
- **Commands:** validated move, attack, gather, build, repair, production, upgrade,
  rescue, and cancel command shapes.
- **Movement:** loose group slots, queued formations, soft unit separation, shoving,
  ghosting fallback, arrival tolerance, and blocker detours.
- **Construction:** lane-constrained placement, multiple builders, construction HP,
  completion, repairs, and destruction lifecycle.
- **Economy:** gather state machine, safe auto-assignment, manual gathering, deposits,
  resource depletion, caching, and respawns.
- **Production:** building-specific trainable units, costs, population checks, valid
  spawning, and rally points.
- **Farming:** autonomous animal lifecycle, wandering, worker assignment, killing,
  timed carcass harvesting, and food deposits.
- **Combat:** guard behavior, direct attacks, Attack Move, wind-up/cooldown, projectiles,
  melee effects, hit feedback, death effects, and cleanup.
- **Towers:** completed defensive buildings use local target scans, wind-up/cooldown
  timers, arrow or magic projectiles, and shared projectile damage resolution.
- **Waves:** timer-driven right-side enemy waves, basic scaling, HUD countdown, and
  debug controls.
- **Rendering:** terrain bands, HUD, settings, selected panel, waypoints, processed
  sprites, Pygame-drawn placeholders, health bars, notifications, and debug overlays.
- **Sprite registry:** processed building/resource sprite paths, lifecycle stage
  selection, and display-aware image caches live outside the main renderer.

## Asset Pipeline

Source building and mine art is kept unchanged. Processing scripts remove the supplied
backgrounds and write transparent, normalized runtime PNGs into `processed/` folders:

```powershell
python tools/process_building_sprites.py
python tools/process_resource_sprites.py
```

Current runtime assets:

- Hut, Barracks, Archery, Chicken Farm, Pig Farm, Wooden Archer Tower, and Stone
  Archer Tower construction/damage/destruction sprites under
  `assets/art/buildings/processed/`.
- Gold Mine, Iron Deposit, and Stone Outcrop depletion sprites under
  `assets/art/resources/processed/`.
- Transparent Chicken and Pig sprites under `assets/art/resources/`.

Building sprites are bottom-aligned to existing gameplay footprints so art changes do
not alter collision. Mine sprites are also visual-only; their smaller blocking
footprints remain independent from image bounds. Missing processed sprites fall back
to Pygame-drawn placeholders. Processed sprite path selection and cached image loading
are centralized in `src/house_of_wolves/core/sprite_registry.py`.

Unit sprites are not final. Units, Trees, weapons, arrows, melee strikes, damage
feedback, wave markers, and directional death animations currently use Pygame
primitives. Current placeholder equipment includes bows, spears, swords, axes,
pickaxes, and building hammers. Wooden and Stone Archer Towers use processed art with
Pygame-drawn archer overlays. Wizard Tower currently reuses the processed Stone
Archer Tower base with a Pygame-drawn wizard overlay, and Wizard Tower magic bolts
remain Pygame primitives. This keeps gameplay testable while final art is still in
development.

## Performance Approach

The alpha uses predictable main-thread budgets rather than threading:

- The Pygame clock targets 60 FPS, and simulation timers use elapsed milliseconds
  instead of frame counts.
- Spatial-hash queries limit rendering, collision, and combat acquisition to local
  candidates.
- Friendly units use bounded neighbor counts for separation and shoving.
- Resource nodes are indexed by type instead of scanning every entity.
- Auto-gather checks cheap distance first, path-checks at most five nearby candidates,
  and processes at most two expensive assignment jobs per frame.
- Resource safety results are cached for one second.
- Projectiles update in `O(active projectiles)` and inspect only their assigned target.
- Combat effects and notifications are bounded to prevent unbounded list growth.
- Notification and floating-damage text surfaces are cached.
- Processed sprites are loaded and scaled through renderer caches.

The optional performance overlay reports frame timings, entity counts, path jobs,
path calculations, resource searches, collision checks, notification activity,
projectile counts, effect counts, attacks, and projectile hits.

## Known Alpha Limitations

- Unit and Tree visuals are placeholders; final sprite animation is not implemented.
- There is no complete campaign, objective progression, victory/defeat flow, or story.
- AI is limited to local guard behavior and wave pressure rather than strategic base
  management.
- Pathing uses local obstacle detours instead of a full navigation mesh or A* grid.
- Crowded formations can still require soft separation or temporary friendly ghosting.
- Upgrade definitions exist, but there is no complete playable progression loop.
- Save/load is not implemented.
- Audio and final sound hooks are not implemented.
- Balance values and wave scaling are provisional.
- Tower balance is provisional; there are no tower upgrades, garrisoning, or manual
  tower targeting controls yet.
- The Wizard Tower is a defensive building only; there is no mobile Wizard unit yet.
- Settings and keybind changes are not persisted between launches.
- There is no multiplayer support.
- Licensing for project-provided visual assets still requires final confirmation before
  a public release.

## Roadmap

Near-term development priorities:

1. Replace placeholder Unit and Tree visuals with original, replaceable sprite sets.
2. Expand pathfinding for denser maps and more complex blocker layouts.
3. Add scenario objectives, victory/defeat conditions, and campaign progression.
4. Complete upgrades, broader unit/building balance, and wave tuning.
5. Add save/load and persistent settings/keybindings.
6. Add audio, accessibility options, and final combat/UI polish.
7. Finalize asset provenance and licensing before distribution.

## Asset And Licensing Note

The repository contains project-provided source images and transparent processed
runtime derivatives. Their entries are tracked in `assets/ASSET_MANIFEST.json`; the
current license field is `pending confirmation`. No license should be inferred from
the presence of a file in this repository.

Before publishing a release, confirm ownership or redistribution permission for every
asset, update the manifest with final license and attribution details, and replace any
asset that cannot be cleared. House of Wolves and related original game rights belong
to their respective owners; this repository is an independent technical/fan project
and does not claim official affiliation.

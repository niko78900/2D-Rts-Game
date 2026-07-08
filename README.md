# House of Wolves Remastered

Playable alpha-stage Pygame remaster of the 2013 side-scrolling RTS.

This repository contains the current RTS implementation: gameplay systems, data
definitions, validation, asset-processing tools, tests, and runtime assets.

## Setup

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
python -m pytest
```

## Validation Entry Point

```powershell
python -m house_of_wolves --validate
```

The validation mode loads and validates the JSON definitions, then prints a content summary.

## Playable Alpha

```powershell
python -m house_of_wolves
```

Borderless windowed mode on the primary display is the default play mode. It uses the
monitor's full desktop size, such as `1920x1080` on a 1080p display:

```powershell
python -m house_of_wolves
```

Use fullscreen explicitly when needed:

```powershell
python -m house_of_wolves --fullscreen
```

The in-game `Settings` button in the top-right HUD can toggle between borderless
windowed mode and fullscreen.

The same settings menu can toggle resource hitbox debug outlines. They are off by
default; resource nodes still block movement while the outlines are hidden. The settings
menu also includes debug resource grants and enemy-wave controls.

You can also double-click `launch_game.cmd` from the project folder.

This opens the current playable RTS slice: side-scrolling map, camera panning, unit
selection, loose group movement, combat, enemy waves, resource gathering, building
construction, production, food farms, population cap, rally points, and debug settings.

## Current Gameplay

- Select units with left click or drag-select. Shift adds to selection. Double-click selects visible units of the same type.
- Right-click terrain with units selected to move; Shift + right-click queues waypoints.
- Use Move, Attack, Attack Move, and Stop from the command panel or their configured hotkeys.
- Settlers can gather Wood, Food, Stone, Iron, and Gold. Iron is the in-game name for the former Ore label.
- Settlers can build Huts, Barracks, Archery, Chicken Farms, and Pig Farms on the building lane.
- Completed Huts accept deposits, train basic units, set rally/drop-off points, and increase population cap.
- Barracks train Spearmen and Archery buildings train Archers.
- Chicken and Pig farms spawn animals, support one assigned worker, and produce Food through carcass harvesting.
- Enemy waves are enabled by default and spawn enemy swordsmen/archers from the right side of the map.
- Buildings and mine resources use processed sprite stages for construction, damage, destruction, or depletion.

## Controls

- `A` / `D` or arrow keys: pan camera.
- Left click: select one object.
- Left drag: box-select units.
- Shift + select: add to current selection.
- Ctrl + `1`-`9`: assign control group.
- `1`-`9`: recall control group.
- Right click terrain: move units or set selected production-building rally point.
- Right click enemy: attack target.
- Right click resource with settler selected: gather that node.
- `Esc`: cancel build placement, targeting mode, sub-menu, or selection depending on current UI state.
- Command-panel hotkeys use slot keys `Q`, `W`, `E`, `R`, `Z`, `S`, `X`, `F`, plus configurable direct action hotkeys in Settings.

## Architecture

- `src/house_of_wolves/core`: settings, app shell, data loading, serialization, assets, profiler hooks.
- `src/house_of_wolves/world`: world state, camera, terrain bands, encounter zones, spatial hash.
- `src/house_of_wolves/entities`: base entity types for units, buildings, resources, projectiles, captives.
- `src/house_of_wolves/systems`: command, selection, economy, production, combat, upgrades, AI, waves, objectives.
- `src/house_of_wolves/ui`: HUD, command panel, tooltips, cursors, notifications.
- `data`: faithful-first starter content and JSON schemas.
- `assets`: source art, processed runtime sprites, placeholder-ready audio/font directories, and licensing manifest.

## Asset Pipeline

Source art stays untouched. Runtime sprites are generated into normalized `processed`
folders and loaded with placeholder fallback when a sprite is missing.

```powershell
python tools/process_building_sprites.py
python tools/process_resource_sprites.py
```

Building source sprites live under `assets/art/buildings/` and process into
`assets/art/buildings/processed/` for Hut, Barracks, Archery, Chicken Farm, and Pig Farm.

Mine resource source sprites live under `assets/art/resources/Ores/` and process into
`assets/art/resources/processed/` for Gold Mine, Iron Deposit, and Stone Outcrop.

Current runtime sprite stage rules:

- Buildings: construction progress selects construction stages; completed HP selects damage stages; destroyed buildings show rubble briefly before removal.
- Mine resources: HP ratio selects `amount_100_75`, `amount_75_25`, or `amount_25_0`.
- Trees still use generated placeholder art until tree sprites are added.

## Test Commands

```powershell
python -m ruff check src tests tools
python -m pytest -q
python -m house_of_wolves --validate
```

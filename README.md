# House of Wolves Remastered

Playable scaffold for a faithful-first Pygame remaster of the 2013 side-scrolling RTS.

This repository defines the package layout, data contracts, starter JSON content, schema
validation, placeholder asset generation, tests, and the current minimal playable slice.

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

## Playable Slice

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
default; resource nodes still block movement while the outlines are hidden.

You can also double-click `launch_game.cmd` from the project folder.

This opens the current minimal Pygame slice: placeholder map, camera panning, unit selection,
loose group movement, basic production, drop-off flags, shoving, and right-click movement. It
is not a full RTS prototype yet.

Select the hut and click `Produce Settler` or `Produce Spearman` to spawn a unit. New units
walk to the hut's blue drop-off flag.

Click `Dropoff`, then click the map to move the hut flag. Click `Dropoff` again to cancel
flag placement.

## Architecture

- `src/house_of_wolves/core`: settings, app shell, data loading, serialization, assets, profiler hooks.
- `src/house_of_wolves/world`: world state, camera, terrain bands, encounter zones, spatial hash.
- `src/house_of_wolves/entities`: base entity types for units, buildings, resources, projectiles, captives.
- `src/house_of_wolves/systems`: command, selection, economy, production, combat, upgrades, AI, waves, objectives.
- `src/house_of_wolves/ui`: HUD, command panel, tooltips, cursors, notifications.
- `data`: faithful-first starter content and JSON schemas.
- `assets`: placeholder-ready art/audio/font directories plus licensing manifest.
- `sources`: project reference documents, including the porting analysis PDF.

## Sources

The scaffold is based on `sources/House of Wolves 2013 Flash RTS Analytical Porting Report.pdf`.

## Next Implementation Steps

1. Fill in worker gather/deposit behavior using the resource definitions.
2. Add building placement validation and production queues.
3. Add combat resolution and defensive structure targeting.
4. Add waves, objectives, save/load, and richer UI feedback.

## Asset Policy

Use original assets wherever practical. If external assets are added later, prefer CC0 first,
then CC BY with attribution recorded in `assets/ASSET_MANIFEST.json`.

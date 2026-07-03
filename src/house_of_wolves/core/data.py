"""JSON definition loading and schema validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from house_of_wolves.core.settings import DATA_ROOT, SCHEMA_ROOT

DEFINITION_FILES = {
    "units": "units.json",
    "buildings": "buildings.json",
    "resources": "resources.json",
    "upgrades": "upgrades.json",
    "waves": "waves.json",
    "factions": "factions.json",
}


class DefinitionLoadError(RuntimeError):
    """Raised when JSON content cannot be loaded or validated."""


@dataclass(frozen=True, slots=True)
class DefinitionSet:
    """One validated JSON definition file."""

    name: str
    items: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class DataBundle:
    """Validated game definition bundle."""

    units: DefinitionSet
    buildings: DefinitionSet
    resources: DefinitionSet
    upgrades: DefinitionSet
    waves: DefinitionSet
    factions: DefinitionSet

    def summary(self) -> dict[str, int]:
        return {
            "units": len(self.units.items),
            "buildings": len(self.buildings.items),
            "resources": len(self.resources.items),
            "upgrades": len(self.upgrades.items),
            "waves": len(self.waves.items),
            "factions": len(self.factions.items),
        }


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except OSError as exc:
        raise DefinitionLoadError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DefinitionLoadError(f"Invalid JSON in {path}: {exc}") from exc


def validate_json(data: Any, schema: Any, source_name: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(data)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path)
        location = f" at {path}" if path else ""
        message = f"{source_name} failed schema validation{location}: {exc.message}"
        raise DefinitionLoadError(message) from exc


def load_definition_set(
    name: str,
    data_root: Path = DATA_ROOT,
    schema_root: Path = SCHEMA_ROOT,
) -> DefinitionSet:
    filename = DEFINITION_FILES[name]
    data_path = data_root / filename
    schema_path = schema_root / f"{data_path.stem}.schema.json"
    data = load_json(data_path)
    schema = load_json(schema_path)
    validate_json(data, schema, filename)
    return DefinitionSet(name=name, items=data)


def load_data_bundle(data_root: Path = DATA_ROOT, schema_root: Path = SCHEMA_ROOT) -> DataBundle:
    sets = {name: load_definition_set(name, data_root, schema_root) for name in DEFINITION_FILES}
    return DataBundle(**sets)

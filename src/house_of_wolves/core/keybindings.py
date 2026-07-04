"""Configurable action keybindings shared by runtime and UI."""

from __future__ import annotations

KEYBIND_BUILD = "build"
KEYBIND_ATTACK = "attack"
KEYBIND_ATTACK_MOVE = "attack_move"
KEYBIND_STOP = "stop"
KEYBIND_BUILD_HUT = "build_hut"
KEYBIND_CANCEL_BUILD = "cancel_build"
KEYBIND_GATHER_WOOD = "gather_wood"
KEYBIND_GATHER_GOLD = "gather_gold"
KEYBIND_GATHER_ORE = "gather_ore"
KEYBIND_GATHER_STONE = "gather_stone"

KEYBIND_ACTION_ORDER = (
    KEYBIND_BUILD,
    KEYBIND_BUILD_HUT,
    KEYBIND_CANCEL_BUILD,
    KEYBIND_ATTACK,
    KEYBIND_ATTACK_MOVE,
    KEYBIND_STOP,
    KEYBIND_GATHER_WOOD,
    KEYBIND_GATHER_GOLD,
    KEYBIND_GATHER_ORE,
    KEYBIND_GATHER_STONE,
)

KEYBIND_ACTION_LABELS = {
    KEYBIND_BUILD: "Build",
    KEYBIND_BUILD_HUT: "Build Hut",
    KEYBIND_CANCEL_BUILD: "Cancel Build",
    KEYBIND_ATTACK: "Attack",
    KEYBIND_ATTACK_MOVE: "Attack Move",
    KEYBIND_STOP: "Stop",
    KEYBIND_GATHER_WOOD: "Gather Wood",
    KEYBIND_GATHER_GOLD: "Gather Gold",
    KEYBIND_GATHER_ORE: "Gather Ore",
    KEYBIND_GATHER_STONE: "Gather Stone",
}

ABILITY_KEYBIND_ACTIONS = {
    "Build": KEYBIND_BUILD,
    "Hut": KEYBIND_BUILD_HUT,
    "Cancel": KEYBIND_CANCEL_BUILD,
    "Attack": KEYBIND_ATTACK,
    "Attack Move": KEYBIND_ATTACK_MOVE,
    "Stop": KEYBIND_STOP,
    "Gather Wood": KEYBIND_GATHER_WOOD,
    "Gather Gold": KEYBIND_GATHER_GOLD,
    "Gather Ore": KEYBIND_GATHER_ORE,
    "Gather Stone": KEYBIND_GATHER_STONE,
}

DEFAULT_KEYBINDINGS = {
    KEYBIND_BUILD: "b",
    KEYBIND_BUILD_HUT: "h",
    KEYBIND_CANCEL_BUILD: "c",
    KEYBIND_ATTACK: "t",
    KEYBIND_ATTACK_MOVE: "r",
    KEYBIND_STOP: "s",
    KEYBIND_GATHER_WOOD: "w",
    KEYBIND_GATHER_GOLD: "g",
    KEYBIND_GATHER_ORE: "o",
    KEYBIND_GATHER_STONE: "v",
}


def default_keybindings() -> dict[str, str]:
    return dict(DEFAULT_KEYBINDINGS)


def normalized_key_name(key_name: str) -> str:
    return key_name.strip().lower()


def formatted_key_name(key_name: str | None) -> str:
    if not key_name:
        return "-"
    normalized = normalized_key_name(key_name)
    if len(normalized) == 1:
        return normalized.upper()
    return normalized.replace("_", " ").title()


def keybinding_for_ability(
    ability: str,
    keybindings: dict[str, str],
) -> str | None:
    action = ABILITY_KEYBIND_ACTIONS.get(ability)
    if action is None:
        return None
    return keybindings.get(action)


def ability_display_label(ability: str, keybindings: dict[str, str]) -> str:
    key_name = keybinding_for_ability(ability, keybindings)
    if not key_name:
        return ability
    return f"{ability} [{formatted_key_name(key_name)}]"

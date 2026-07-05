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
KEYBIND_COMMAND_SLOT_1 = "command_slot_1"
KEYBIND_COMMAND_SLOT_2 = "command_slot_2"
KEYBIND_COMMAND_SLOT_3 = "command_slot_3"
KEYBIND_COMMAND_SLOT_4 = "command_slot_4"
KEYBIND_COMMAND_SLOT_5 = "command_slot_5"
KEYBIND_COMMAND_SLOT_6 = "command_slot_6"
KEYBIND_COMMAND_SLOT_7 = "command_slot_7"
KEYBIND_COMMAND_SLOT_8 = "command_slot_8"

COMMAND_PANEL_SLOT_ACTIONS = (
    KEYBIND_COMMAND_SLOT_1,
    KEYBIND_COMMAND_SLOT_2,
    KEYBIND_COMMAND_SLOT_3,
    KEYBIND_COMMAND_SLOT_4,
    KEYBIND_COMMAND_SLOT_5,
    KEYBIND_COMMAND_SLOT_6,
    KEYBIND_COMMAND_SLOT_7,
    KEYBIND_COMMAND_SLOT_8,
)

KEYBIND_ACTION_ORDER = (
    *COMMAND_PANEL_SLOT_ACTIONS,
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
    KEYBIND_COMMAND_SLOT_1: "Command Slot 1",
    KEYBIND_COMMAND_SLOT_2: "Command Slot 2",
    KEYBIND_COMMAND_SLOT_3: "Command Slot 3",
    KEYBIND_COMMAND_SLOT_4: "Command Slot 4",
    KEYBIND_COMMAND_SLOT_5: "Command Slot 5",
    KEYBIND_COMMAND_SLOT_6: "Command Slot 6",
    KEYBIND_COMMAND_SLOT_7: "Command Slot 7",
    KEYBIND_COMMAND_SLOT_8: "Command Slot 8",
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
    KEYBIND_COMMAND_SLOT_1: "q",
    KEYBIND_COMMAND_SLOT_2: "w",
    KEYBIND_COMMAND_SLOT_3: "e",
    KEYBIND_COMMAND_SLOT_4: "r",
    KEYBIND_COMMAND_SLOT_5: "z",
    KEYBIND_COMMAND_SLOT_6: "s",
    KEYBIND_COMMAND_SLOT_7: "x",
    KEYBIND_COMMAND_SLOT_8: "f",
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
    *,
    slot_index: int | None = None,
) -> str | None:
    if slot_index is not None and 0 <= slot_index < len(COMMAND_PANEL_SLOT_ACTIONS):
        return keybindings.get(COMMAND_PANEL_SLOT_ACTIONS[slot_index])
    action = ABILITY_KEYBIND_ACTIONS.get(ability)
    if action is None:
        return None
    return keybindings.get(action)


def ability_display_label(
    ability: str,
    keybindings: dict[str, str],
    *,
    slot_index: int | None = None,
) -> str:
    key_name = keybinding_for_ability(ability, keybindings, slot_index=slot_index)
    if not key_name:
        return ability
    return f"{ability} [{formatted_key_name(key_name)}]"


def command_slot_index_for_key(key_name: str, keybindings: dict[str, str]) -> int | None:
    normalized = normalized_key_name(key_name)
    for index, action in enumerate(COMMAND_PANEL_SLOT_ACTIONS):
        if keybindings.get(action) == normalized:
            return index
    return None

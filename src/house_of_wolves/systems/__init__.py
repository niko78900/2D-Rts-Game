"""Simulation system scaffolds."""

from house_of_wolves.systems.combat import CombatSystem
from house_of_wolves.systems.commands import CommandValidationError, make_command, validate_command
from house_of_wolves.systems.construction import (
    ConstructionSystem,
    construction_hp_for_progress,
    construction_progress,
    starting_construction_hp,
)
from house_of_wolves.systems.economy import EconomySystem, ResourceWallet
from house_of_wolves.systems.farming import FarmSystem
from house_of_wolves.systems.group_movement import (
    assign_units_to_slots,
    generate_loose_formation_slots,
    issue_group_move_command,
)
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.systems.production import ProductionError, produce_unit

__all__ = [
    "CommandValidationError",
    "CombatSystem",
    "ConstructionSystem",
    "EconomySystem",
    "FarmSystem",
    "MovementSystem",
    "ProductionError",
    "ResourceWallet",
    "assign_units_to_slots",
    "generate_loose_formation_slots",
    "issue_group_move_command",
    "make_command",
    "construction_hp_for_progress",
    "construction_progress",
    "produce_unit",
    "starting_construction_hp",
    "validate_command",
]

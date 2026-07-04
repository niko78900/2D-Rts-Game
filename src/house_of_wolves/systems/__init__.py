"""Simulation system scaffolds."""

from house_of_wolves.systems.commands import CommandValidationError, make_command, validate_command
from house_of_wolves.systems.group_movement import (
    assign_units_to_slots,
    generate_loose_formation_slots,
    issue_group_move_command,
)
from house_of_wolves.systems.movement import MovementSystem
from house_of_wolves.systems.production import ProductionError, produce_unit

__all__ = [
    "CommandValidationError",
    "MovementSystem",
    "ProductionError",
    "assign_units_to_slots",
    "generate_loose_formation_slots",
    "issue_group_move_command",
    "make_command",
    "produce_unit",
    "validate_command",
]

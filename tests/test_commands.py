from __future__ import annotations

import pytest

from house_of_wolves.core.contracts import EntityId
from house_of_wolves.systems.commands import CommandValidationError, make_command


def test_make_move_command_validates_target_position() -> None:
    command = make_command("move", [1, EntityId(2)], target_pos=(300, 420), queued=True)

    assert command.type == "move"
    assert command.target_pos is not None
    assert command.target_pos.to_tuple() == (300, 420)
    assert command.queued is True


def test_build_command_requires_building_id_payload() -> None:
    with pytest.raises(CommandValidationError, match="building_id"):
        make_command("build", [1], target_pos=(100, 400))


def test_invalid_command_type_is_rejected() -> None:
    with pytest.raises(CommandValidationError, match="Invalid command type"):
        make_command("dance", [1], target_pos=(100, 400))

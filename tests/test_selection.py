from __future__ import annotations

from house_of_wolves.core.contracts import WorldPosition
from house_of_wolves.systems.selection import SelectionSystem
from house_of_wolves.world.demo import create_demo_world


def test_selection_pick_click_add_and_clear() -> None:
    world = create_demo_world()
    units = [entity for entity in world.entities.values() if "unit" in entity.tags]
    selection = SelectionSystem()

    picked = selection.select_at(world, units[0].position)
    assert picked == units[0].id
    assert selection.state.selected_ids == [units[0].id]

    selection.select_at(world, units[1].position, add=True)
    assert selection.state.selected_ids == [units[0].id, units[1].id]

    selection.select_at(world, WorldPosition(7000, 100))
    assert selection.state.selected_ids == []


def test_box_select_replaces_or_adds_visible_units() -> None:
    world = create_demo_world()
    units = [entity for entity in world.entities.values() if "unit" in entity.tags]
    selection = SelectionSystem()

    selected = selection.box_select(world, _bounds_around(units))
    assert selected == [unit.id for unit in units]
    assert selection.state.selected_ids == selected

    selection.state.clear()
    selection.state.add(units[0].id)
    added = selection.box_select(world, _bounds_around(units[1:]), add=True)

    assert added == [units[1].id, units[2].id]
    assert selection.state.selected_ids == [units[0].id, units[1].id, units[2].id]


def test_selection_can_pick_buildings_and_resource_objects() -> None:
    world = create_demo_world()
    building = next(entity for entity in world.entities.values() if "building" in entity.tags)
    resource = next(entity for entity in world.entities.values() if "resource" in entity.tags)
    selection = SelectionSystem()

    assert selection.select_at(world, building.position) == building.id
    assert selection.state.selected_ids == [building.id]

    assert selection.select_at(world, resource.position) == resource.id
    assert selection.state.selected_ids == [resource.id]


def test_shift_clicking_building_or_resource_replaces_selection_instead_of_adding() -> None:
    world = create_demo_world()
    units = [entity for entity in world.entities.values() if "unit" in entity.tags]
    building = next(entity for entity in world.entities.values() if "building" in entity.tags)
    resource = next(entity for entity in world.entities.values() if "resource" in entity.tags)
    selection = SelectionSystem()

    selection.state.replace([units[0].id, units[1].id])

    selection.select_at(world, building.position, add=True)
    assert selection.state.selected_ids == [building.id]

    selection.select_at(world, resource.position, add=True)
    assert selection.state.selected_ids == [resource.id]


def test_shift_clicking_unit_replaces_existing_building_or_resource_selection() -> None:
    world = create_demo_world()
    unit = next(entity for entity in world.entities.values() if "unit" in entity.tags)
    building = next(entity for entity in world.entities.values() if "building" in entity.tags)
    selection = SelectionSystem()

    selection.state.replace([building.id])
    selection.select_at(world, unit.position, add=True)

    assert selection.state.selected_ids == [unit.id]


def test_box_select_only_selects_units_even_when_objects_overlap_bounds() -> None:
    world = create_demo_world()
    units = [entity for entity in world.entities.values() if "unit" in entity.tags]
    selection = SelectionSystem()

    selected = selection.box_select(world, _bounds_around(world.entities.values()))

    assert selected == [unit.id for unit in units]
    assert all(
        "unit" in world.entities[entity_id].tags
        for entity_id in selection.state.selected_ids
    )


def _bounds_around(entities: object) -> tuple[float, float, float, float]:
    bounds = [entity.bounds for entity in entities]
    left = min(bound[0] for bound in bounds)
    top = min(bound[1] for bound in bounds)
    right = max(bound[0] + bound[2] for bound in bounds)
    bottom = max(bound[1] + bound[3] for bound in bounds)
    return (left - 1, top - 1, (right - left) + 2, (bottom - top) + 2)

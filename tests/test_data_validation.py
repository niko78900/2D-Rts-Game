from __future__ import annotations

from house_of_wolves.core.data import load_data_bundle


def test_all_data_files_validate_against_schemas() -> None:
    """Verify that all data files validate against schemas."""
    bundle = load_data_bundle()

    assert bundle.summary() == {
        "units": 9,
        "buildings": 12,
        "resources": 6,
        "upgrades": 9,
        "waves": 4,
        "factions": 4,
    }


def test_faithful_first_resource_names_are_present() -> None:
    """Verify that faithful first resource names are present."""
    bundle = load_data_bundle()
    resource_types = {item["resource_type"] for item in bundle.resources.items.values()}

    assert resource_types == {"wood", "food", "stone", "iron", "gold"}

from __future__ import annotations

from house_of_wolves.core.game_specs import (
    building_spec_from_data,
    resource_spec_from_type,
    unit_spec_from_data,
)
from house_of_wolves.core.runtime import (
    HUT_BUILD_COST,
    HUT_BUILD_TIME_MS,
    HUT_FOOTPRINT,
    HUT_MAX_HP,
    HUT_SPEC,
)
from house_of_wolves.core.settings import AppSettings
from house_of_wolves.entities.resource_node import resource_hp_for_type
from house_of_wolves.systems.economy import RESOURCE_NODE_SPECS
from house_of_wolves.systems.farming import FARM_BUILDING_SPECS
from house_of_wolves.systems.production import (
    BUILDING_UNIT_COSTS,
    PRODUCTION_BUILDING_SPECS,
    UNIT_TEMPLATES,
    unit_cost,
)
from house_of_wolves.systems.towers import TOWER_SPECS


def test_runtime_unit_templates_are_built_from_unit_json() -> None:
    """Verify that trainable and wave unit stats stay aligned with unit JSON."""
    for unit_id, template in UNIT_TEMPLATES.items():
        spec = unit_spec_from_data(unit_id)

        assert template["hp"] == spec.hp
        assert template["speed"] == spec.speed
        assert template["damage"] == spec.damage
        assert template["attack_range"] == spec.attack_range
        assert template["attack_cooldown_ms"] == spec.attack_cooldown_ms
        assert template["cost"] == spec.cost
        assert template["population_cost"] == spec.population_cost


def test_building_production_specs_are_built_from_building_json() -> None:
    """Verify military production buildings use canonical building JSON."""
    for building_id, spec in PRODUCTION_BUILDING_SPECS.items():
        source_id = "archery" if building_id == "archery_range" else building_id
        source = building_spec_from_data(source_id)

        assert spec.display_name == source.display_name
        assert spec.footprint == source.footprint
        assert spec.hp == source.hp
        assert spec.build_time_ms == source.build_time_ms
        assert spec.cost == source.cost
        assert spec.trainable_units == tuple(source.functions["trainable_units"])


def test_building_specific_unit_costs_are_loaded_from_json() -> None:
    """Verify production price overrides come from building JSON."""
    source = building_spec_from_data("barracks")
    expected = source.functions["unit_cost_overrides"]["spearman"]

    assert BUILDING_UNIT_COSTS["barracks"]["spearman"] == {"wood": 30, "food": 15}
    assert BUILDING_UNIT_COSTS["barracks"]["spearman"] == {
        key: value for key, value in expected.items() if value > 0
    }
    assert unit_cost("spearman") == unit_spec_from_data("spearman").cost
    assert unit_cost("spearman") != BUILDING_UNIT_COSTS["barracks"]["spearman"]


def test_tower_specs_are_built_from_building_json() -> None:
    """Verify tower combat/building stats stay aligned with building JSON."""
    for tower_id, spec in TOWER_SPECS.items():
        source = building_spec_from_data(tower_id)
        functions = source.functions

        assert spec.display_name == source.display_name
        assert spec.footprint == source.footprint
        assert spec.hp == source.hp
        assert spec.build_time_ms == source.build_time_ms
        assert spec.cost == source.cost
        assert spec.attack_range == functions["attack_range"]
        assert spec.damage == functions["damage"]
        assert spec.attack_cooldown_ms == functions["attack_cooldown_ms"]
        assert spec.windup_ms == functions["windup_ms"]
        assert spec.projectile_kind == functions["projectile"]
        assert spec.projectile_speed == functions["projectile_speed"]


def test_farm_specs_are_built_from_building_json() -> None:
    """Verify food-farm building and animal stats come from building JSON."""
    for building_id, spec in FARM_BUILDING_SPECS.items():
        source = building_spec_from_data(building_id)
        functions = source.functions

        assert spec.display_name == source.display_name
        assert spec.footprint == source.footprint
        assert spec.hp == source.hp
        assert spec.build_time_ms == source.build_time_ms
        assert spec.cost == source.cost
        assert spec.farm_type == functions["farm_type"]
        assert spec.animal_hp == functions["animal_hp"]
        assert spec.animal_food_yield == functions["animal_food_yield"]
        assert spec.respawn_delay_ms == functions["respawn_delay_ms"]


def test_resource_specs_are_built_from_resource_json() -> None:
    """Verify resource nodes and respawns use canonical resource JSON."""
    for resource_type, spec in RESOURCE_NODE_SPECS.items():
        source = resource_spec_from_type(resource_type)

        assert spec.tags == source.tags
        assert spec.footprint == source.footprint
        assert spec.blocking_footprint == source.blocking_footprint
        assert spec.gather_time_ms == source.gather_time_ms
        assert spec.depleted_replacement == source.depleted_replacement
        assert resource_hp_for_type(resource_type) == source.amount


def test_hut_runtime_constants_are_built_from_building_json() -> None:
    """Verify hut placement and construction constants stay data-backed."""
    source = building_spec_from_data("hut")

    assert source == HUT_SPEC
    assert source.footprint == HUT_FOOTPRINT
    assert source.hp == HUT_MAX_HP
    assert source.build_time_ms == HUT_BUILD_TIME_MS
    assert source.cost == HUT_BUILD_COST
    assert AppSettings().hut_pop_cap_bonus == source.functions["population_cap_bonus"]

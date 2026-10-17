"""Acceptance tests for the pure content_v1 schema and loader layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from llm_rpg.content.loader_v2 import load_pack_v2
from llm_rpg.content.validator_v2 import validate_pack_v2
from llm_rpg.models.content_v2 import ContentPackV2, ContentV2Error


def _default_files() -> dict[str, Any]:
    return {
        "pack.yaml": {
            "schema_version": 2,
            "id": "demo_pack",
            "name": "Demo Pack",
            "version": "1.0.0",
        },
        "world.yaml": {
            "id": "misty_world",
            "name": "Misty World",
        },
        "locations.yaml": {
            "locations": [
                {"id": "town", "name": "Town"},
                {"id": "field", "name": "Field"},
            ],
            "routes": [],
        },
        "initial_state.yaml": {"player": {"location_id": "town"}},
    }


def _write_pack(tmp_path: Path, overrides: dict[str, Any] | None = None) -> Path:
    files = _default_files()
    if overrides:
        files.update(overrides)
    for filename, data in files.items():
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        elif isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return tmp_path


def _codes(pack: ContentPackV2) -> set[str]:
    return {issue.code for issue in validate_pack_v2(pack)}


def _load_error(path: Path, code: str) -> None:
    with pytest.raises(ContentV2Error) as caught:
        load_pack_v2(path)
    assert caught.value.code == code


def test_valid_pack_loads_and_validates(tmp_path: Path) -> None:
    pack = load_pack_v2(_write_pack(tmp_path))
    assert pack.manifest.id == "demo_pack"
    assert pack.world.id == "misty_world"
    assert [location.id for location in pack.locations] == ["town", "field"]
    assert validate_pack_v2(pack) == []


def test_on_time_trigger_defaults_to_environment_phase(tmp_path: Path) -> None:
    files = _default_files()
    files["rules.yaml"] = {
        "rules": [{
            "id": "phase_rule",
            "trigger": {"type": "on_time_crossed", "due_tick": 1},
            "effects": [{"type": "flag_set", "key": "ready", "value": True}],
            "fire_policy": {"mode": "once_per_instance"},
        }]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert pack.rules[0].trigger.root.phase.value == "environment"


def test_unknown_trigger_phase_is_unsupported(tmp_path: Path) -> None:
    files = _default_files()
    files["rules.yaml"] = {
        "rules": [{
            "id": "phase_rule",
            "trigger": {"type": "on_time_crossed", "due_tick": 1, "phase": "nope"},
            "effects": [{"type": "flag_set", "key": "ready", "value": True}],
            "fire_policy": {"mode": "once_per_instance"},
        }]
    }
    _load_error(_write_pack(tmp_path, files), "CONTENT_UNSUPPORTED_FEATURE")


def test_action_completed_trigger_rejects_phase(tmp_path: Path) -> None:
    files = _default_files()
    files["rules.yaml"] = {
        "rules": [{
            "id": "action_rule",
            "trigger": {
                "type": "on_action_completed",
                "action": "move",
                "actor": "player",
                "phase": "environment",
            },
            "effects": [{"type": "flag_set", "key": "ready", "value": True}],
            "fire_policy": {"mode": "once_per_instance"},
        }]
    }
    _load_error(_write_pack(tmp_path, files), "CONTENT_UNKNOWN_FIELD")


def test_unknown_field_is_rejected_with_content_unknown_field(tmp_path: Path) -> None:
    files = _default_files()
    files["world.yaml"]["surprise"] = True
    _load_error(_write_pack(tmp_path, files), "CONTENT_UNKNOWN_FIELD")


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["pack.yaml"] = "schema_version: 2\nid: demo_pack\nname: First\nname: Second\nversion: 1.0.0\n"
    _load_error(_write_pack(tmp_path, files), "CONTENT_DUPLICATE_KEY")


@pytest.mark.parametrize("schema_version", [3, "missing"])
def test_unsupported_or_missing_schema_version_is_rejected(tmp_path: Path, schema_version: Any) -> None:
    files = _default_files()
    if schema_version == "missing":
        del files["pack.yaml"]["schema_version"]
    else:
        files["pack.yaml"]["schema_version"] = schema_version
    _load_error(_write_pack(tmp_path, files), "CONTENT_PACK_SCHEMA_UNSUPPORTED")


def test_yaml_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}_outside.yaml"
    outside.write_text("value: external\n", encoding="utf-8")
    pack_dir = _write_pack(tmp_path)
    link = pack_dir / "external.yaml"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable in this environment: {exc}")
    _load_error(pack_dir, "CONTENT_PATH_ESCAPE")


def test_item_quantity_other_than_one_is_unsupported(tmp_path: Path) -> None:
    files = _default_files()
    files["items.yaml"] = {"items": [{"id": "lantern", "name": "Lantern", "item_type": "tool", "quantity": 2}]}
    _load_error(_write_pack(tmp_path, files), "CONTENT_UNSUPPORTED_FEATURE")


def test_dangling_reference_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["world.yaml"] = {"id": "misty_world", "name": "Misty World"}
    files["locations.yaml"]["locations"][0]["parent_id"] = "missing_place"
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_DANGLING_REF" in _codes(pack)


def test_duplicate_id_across_types_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["characters.yaml"] = {
        "characters": [{"id": "town", "name": "Guard", "initial_location_id": "town"}]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_DUPLICATE_ID" in _codes(pack)


def test_invalid_owner_syntax_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["items.yaml"] = {"items": [{"id": "lantern", "name": "Lantern", "item_type": "tool"}]}
    files["initial_state.yaml"] = {
        "player": {"location_id": "town"},
        "items": [{"id": "lantern", "owner": "somewhere"}],
    }
    _load_error(_write_pack(tmp_path, files), "CONTENT_INVALID_OWNER")


def test_duplicate_directed_route_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["locations.yaml"]["routes"] = [
        {"from": "town", "to": "field"},
        {"from": "town", "to": "field"},
    ]
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_DUPLICATE_ROUTE" in _codes(pack)


def test_undeclared_flag_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["rules.yaml"] = {
        "rules": [{
            "id": "flag_rule",
            "trigger": {"type": "on_time_crossed", "due_tick": 1},
            "condition": {"type": "flag_equals", "key": "unknown_flag", "value": True},
            "effects": [{"type": "flag_set", "key": "unknown_flag", "value": True}],
            "fire_policy": {"mode": "once_per_instance"},
        }]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_UNDECLARED_FLAG" in _codes(pack)


def test_condition_depth_over_eight_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    condition: dict[str, Any] = {"type": "flag_equals", "key": "ready", "value": True}
    for _ in range(8):
        condition = {"not": condition}
    files["initial_state.yaml"]["flags"] = {"ready": True}
    files["rules.yaml"] = {
        "rules": [{
            "id": "deep_rule",
            "trigger": {"type": "on_time_crossed", "due_tick": 1},
            "condition": condition,
            "effects": [{"type": "flag_set", "key": "ready", "value": True}],
            "fire_policy": {"mode": "once_per_instance"},
        }]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_CONDITION_TOO_DEEP" in _codes(pack)


def test_recipe_over_sixteen_steps_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["goals.yaml"] = {"recipes": [{"id": "long_plan", "steps": [{"action": "wait", "ticks": 1}] * 17}]}
    _load_error(_write_pack(tmp_path, files), "CONTENT_RECIPE_TOO_LONG")


def test_generated_schema_forbids_extra_fields_on_every_model_object() -> None:
    schema = ContentPackV2.model_json_schema()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node.get("additionalProperties") is False
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)


def test_reserved_id_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["locations.yaml"]["locations"][0]["id"] = "player"
    _load_error(_write_pack(tmp_path, files), "CONTENT_RESERVED_ID")


def test_plain_type_error_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["world.yaml"]["start_hour"] = "8"
    _load_error(_write_pack(tmp_path, files), "CONTENT_TYPE_ERROR")


def test_out_of_range_value_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["world.yaml"]["start_hour"] = 24
    _load_error(_write_pack(tmp_path, files), "CONTENT_VALUE_RANGE")


def test_non_finite_number_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["world.yaml"]["lore_summary"] = float("nan")
    _load_error(_write_pack(tmp_path, files), "CONTENT_NON_FINITE_NUMBER")


def test_reference_to_wrong_kind_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["items.yaml"] = {"items": [{"id": "lantern", "name": "Lantern", "item_type": "tool"}]}
    files["characters.yaml"] = {
        "characters": [{"id": "guard", "name": "Guard", "initial_location_id": "lantern"}]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_KIND_MISMATCH" in _codes(pack)


def test_cross_pack_reference_is_rejected(tmp_path: Path) -> None:
    files = _default_files()
    files["locations.yaml"]["locations"][0]["parent_id"] = "other_pack/town"
    _load_error(_write_pack(tmp_path, files), "CONTENT_CROSS_PACK_REF")


def test_unknown_knowledge_placeholder_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["knowledge.yaml"] = {
        "knowledge_rules": [{
            "id": "heard_rule",
            "source_event_types": ["move"],
            "observers": "actor",
            "memory_kind": "observation",
            "visibility": "npc_private",
            "template": "Unknown {npc}",
        }]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_UNKNOWN_PLACEHOLDER" in _codes(pack)


def test_condition_node_count_over_128_is_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["initial_state.yaml"]["flags"] = {"ready": True}
    files["rules.yaml"] = {
        "rules": [{
            "id": "large_rule",
            "trigger": {"type": "on_time_crossed", "due_tick": 1},
            "condition": {"all": [
                {"type": "flag_equals", "key": "ready", "value": True} for _ in range(128)
            ]},
            "effects": [{"type": "flag_set", "key": "ready", "value": True}],
            "fire_policy": {"mode": "once_per_instance"},
        }]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_CONDITION_TOO_LARGE" in _codes(pack)


def test_overlapping_schedule_windows_are_reported(tmp_path: Path) -> None:
    files = _default_files()
    files["characters.yaml"] = {
        "characters": [{"id": "guard", "name": "Guard", "initial_location_id": "town"}]
    }
    files["schedules.yaml"] = {
        "schedules": [
            {"id": "morning", "character_id": "guard", "activity": "patrol", "location_id": "town", "at_tick": 1, "window_ticks": 3},
            {"id": "midday", "character_id": "guard", "activity": "rest", "location_id": "field", "at_tick": 3, "window_ticks": 2},
        ]
    }
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_SCHEDULE_OVERLAP" in _codes(pack)


def test_duplicate_location_name_is_reported_as_ambiguous_alias(tmp_path: Path) -> None:
    files = _default_files()
    files["locations.yaml"]["locations"][1]["name"] = " town "
    pack = load_pack_v2(_write_pack(tmp_path, files))
    assert "CONTENT_AMBIGUOUS_ALIAS" in _codes(pack)


def test_missing_required_file_is_rejected(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path)
    (pack_dir / "world.yaml").unlink()
    _load_error(pack_dir, "CONTENT_DANGLING_REF")


def test_recursive_yaml_alias_is_unsupported(tmp_path: Path) -> None:
    files = _default_files()
    files["prompts.yaml"] = "prompt: &loop [*loop]\n"
    _load_error(_write_pack(tmp_path, files), "CONTENT_UNSUPPORTED_FEATURE")

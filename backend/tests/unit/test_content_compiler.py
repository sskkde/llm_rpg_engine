"""Determinism and purity tests for content_v1 RuntimeBundle compilation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

import yaml

from llm_rpg.content.compiler import compile_pack_v2
from llm_rpg.content.loader_v2 import load_pack_v2
from llm_rpg.models.content_v2 import ContentPackV2


def _files(
    *,
    version: str = "1.0.0",
    reverse: bool = False,
    explicit_defaults: bool = False,
    reverse_steps: bool = False,
) -> dict[str, Any]:
    locations = [
        {"id": "north", "name": "North"},
        {"id": "south", "name": "South"},
    ]
    characters = [
        {"id": "guard", "name": "Guard", "initial_location_id": "north"},
        {"id": "herbalist", "name": "Herbalist", "initial_location_id": "south"},
    ]
    rules = [
        {
            "id": "bell_rule",
            "trigger": {"type": "on_time_crossed", "due_tick": 3},
            "effects": [{"type": "flag_set", "key": "bell", "value": True}],
            "fire_policy": {"mode": "once_per_instance"},
        },
        {
            "id": "gate_rule",
            "trigger": {"type": "on_time_crossed", "due_tick": 5},
            "effects": [{"type": "flag_set", "key": "bell", "value": False}],
            "fire_policy": {"mode": "once_per_source_event"},
        },
    ]
    steps = [{"action": "wait", "ticks": 1}, {"action": "wait", "ticks": 2}]
    if reverse:
        locations.reverse()
        characters.reverse()
        rules.reverse()
    if reverse_steps:
        steps.reverse()

    world: dict[str, Any] = {"id": "fog_world", "name": "Fog World"}
    locs = locations
    routes = [{"from": "north", "to": "south"}]
    if explicit_defaults:
        world.update({
            "description": "",
            "tags": [],
            "enabled": True,
            "genre": "",
            "theme": "",
            "lore_summary": "",
            "status": "active",
            "start_hour": 8,
            "start_minute": 0,
            "start_tick": 0,
        })
        locs = [
            {
                **location,
                "description": "",
                "tags": [],
                "enabled": True,
                "parent_id": None,
                "access_rules": {"always_accessible": True},
            }
            for location in locations
        ]
        routes = [{"from": "north", "to": "south", "open": True, "travel_ticks": 1, "bidirectional": False}]
        characters = [
            {
                **character,
                "description": "",
                "tags": [],
                "enabled": True,
                "public_identity": "",
                "personality": "",
                "alive": True,
            }
            for character in characters
        ]
        rules = [
            {
                **rule,
                "name": "",
                "description": "",
                "tags": [],
                "enabled": True,
                "condition": None,
                "priority": 0,
            }
            for rule in rules
        ]
        player = {"location_id": "north", "alive": True}
        initial_state = {
            "player": player,
            "characters": [],
            "items": [],
            "routes": [],
            "flags": {"bell": False},
            "schedules": [],
        }
    else:
        initial_state = {"player": {"location_id": "north"}, "flags": {"bell": False}}

    return {
        "pack.yaml": {"schema_version": 2, "id": "fog_pack", "name": "Fog Pack", "version": version},
        "world.yaml": world,
        "locations.yaml": {"locations": locs, "routes": routes},
        "characters.yaml": {"characters": characters},
        "initial_state.yaml": initial_state,
        "rules.yaml": {"rules": rules},
        "goals.yaml": {"recipes": [{"id": "small_plan", "steps": steps}]},
    }


def _write_pack(root: Path, files: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for filename, data in files.items():
        (root / filename).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return root


def _load_compile(root: Path, files: dict[str, Any] | None = None, **compile_kwargs: Any):
    if files is not None:
        _write_pack(root, files)
    return compile_pack_v2(load_pack_v2(root), **compile_kwargs)


def test_same_pack_compiled_twice_has_identical_runtime_hash(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path / "pack", _files())
    pack = load_pack_v2(pack_dir)
    first = compile_pack_v2(pack)
    second = compile_pack_v2(pack)
    assert first.runtime_hash == second.runtime_hash
    assert first.runtime_bundle == second.runtime_bundle


def test_unordered_yaml_list_order_does_not_change_runtime_hash(tmp_path: Path) -> None:
    first = _load_compile(tmp_path / "first", _files())
    second = _load_compile(tmp_path / "second", _files(reverse=True))
    assert first.runtime_hash == second.runtime_hash
    assert first.runtime_bundle == second.runtime_bundle


def test_explicit_documented_defaults_match_omitted_defaults(tmp_path: Path) -> None:
    omitted = _load_compile(tmp_path / "omitted", _files())
    explicit = _load_compile(tmp_path / "explicit", _files(explicit_defaults=True))
    assert omitted.runtime_hash == explicit.runtime_hash
    assert omitted.runtime_bundle == explicit.runtime_bundle


def test_explicit_default_trigger_phase_matches_omitted_phase(tmp_path: Path) -> None:
    omitted_files = _files()
    explicit_files = _files()
    for rule in explicit_files["rules.yaml"]["rules"]:
        rule["trigger"]["phase"] = "environment"
    omitted = _load_compile(tmp_path / "omitted_phase", omitted_files)
    explicit = _load_compile(tmp_path / "explicit_phase", explicit_files)
    assert omitted.runtime_hash == explicit.runtime_hash


def test_plan_recipe_step_order_is_hash_significant(tmp_path: Path) -> None:
    ordered = _load_compile(tmp_path / "ordered", _files())
    reversed_steps = _load_compile(tmp_path / "reversed", _files(reverse_steps=True))
    assert ordered.runtime_hash != reversed_steps.runtime_hash


def test_ref_map_is_deterministic_and_version_scoped(tmp_path: Path) -> None:
    first = _load_compile(tmp_path / "first", _files(version="1.0.0"))
    repeat = _load_compile(tmp_path / "repeat", _files(version="1.0.0"))
    next_version = _load_compile(tmp_path / "next", _files(version="1.0.1"))
    stable_ref = "fog_pack/fog_world"
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, f"content_v1:fog_pack:1.0.0:{stable_ref}"))
    assert first.ref_map == repeat.ref_map
    assert first.ref_map[stable_ref] == expected
    assert first.ref_map[stable_ref] != next_version.ref_map[stable_ref]


def test_compiler_does_not_mutate_input_pack(tmp_path: Path) -> None:
    pack = load_pack_v2(_write_pack(tmp_path / "pack", _files(reverse=True)))
    before = pack.model_dump(mode="json", by_alias=True)
    compile_pack_v2(pack)
    assert pack.model_dump(mode="json", by_alias=True) == before


def test_source_hash_is_recorded_but_does_not_change_runtime_hash(tmp_path: Path) -> None:
    pack = load_pack_v2(_write_pack(tmp_path / "pack", _files()))
    first = compile_pack_v2(pack, source_hash="source-a")
    second = compile_pack_v2(pack, source_hash="source-b")
    assert first.runtime_bundle["_source"]["source_hash"] == "source-a"
    assert second.runtime_bundle["_source"]["source_hash"] == "source-b"
    assert first.runtime_hash == second.runtime_hash

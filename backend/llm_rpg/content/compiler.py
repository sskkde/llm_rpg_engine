"""Canonical compilation of strict content pack models into RuntimeBundle."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from llm_rpg.models.content_v2 import (
    BUNDLE_SCHEMA_VERSION,
    ENGINE_RULES_VERSION,
    ContentPackV2,
)
from llm_rpg.content.validator_v2 import validate_pack_v2


@dataclass(frozen=True)
class CompiledBundle:
    runtime_bundle: dict
    runtime_hash: str
    bundle_schema_version: int
    engine_rules_version: int
    ref_map: dict[str, str]


def canonical_json(value: Any) -> str:
    """Serialize JSON data with deterministic key order and no whitespace."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _runtime_hash_input(runtime_bundle: dict) -> dict:
    # _source is provenance only. It is kept beside the runtime configuration
    # in the returned artifact but deliberately excluded from semantic hashing.
    return {key: value for key, value in runtime_bundle.items() if key != "_source"}


def compute_runtime_hash(runtime_bundle: dict) -> str:
    payload = {
        "bundle": _runtime_hash_input(runtime_bundle),
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "engine_rules_version": ENGINE_RULES_VERSION,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _canonicalize_values(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value):
            child = value[key]
            if key == "tags" and isinstance(child, list):
                normalized[key] = sorted(set(child))
            else:
                normalized[key] = _canonicalize_values(child)
        return normalized
    if isinstance(value, list):
        return [_canonicalize_values(child) for child in value]
    return value


def _sort_by_id(values: list[dict]) -> list[dict]:
    return sorted(values, key=lambda item: item["id"])


def _canonical_routes(routes: list[dict]) -> list[dict]:
    directed: list[dict] = []
    for route in routes:
        current = dict(route)
        bidirectional = current.get("bidirectional", False)
        current["bidirectional"] = False
        directed.append(current)
        if bidirectional and current["from"] != current["to"]:
            reverse = dict(current)
            reverse["from"], reverse["to"] = current["to"], current["from"]
            directed.append(reverse)
    return sorted(directed, key=lambda route: (route["from"], route["to"]))


def _sorted_initial_state(initial_state: dict) -> dict:
    result = dict(initial_state)
    result["characters"] = sorted(result.get("characters", []), key=lambda item: item["id"])
    result["items"] = sorted(result.get("items", []), key=lambda item: item["id"])
    result["routes"] = sorted(result.get("routes", []), key=lambda item: (item["from"], item["to"]))
    result["schedules"] = sorted(
        result.get("schedules", []),
        key=lambda item: (item["character_id"], item.get("start_tick", 0), item["activity"], item["location_id"]),
    )
    return result


def _sort_nested_faction_collections(factions: list[dict]) -> list[dict]:
    result = []
    for faction in factions:
        current = dict(faction)
        current["goals"] = sorted(current.get("goals", []), key=lambda goal: goal["goal_id"])
        current["relationships"] = sorted(
            current.get("relationships", []),
            key=lambda relationship: relationship["target_faction_id"],
        )
        result.append(current)
    return result


def _ref_map(pack: ContentPackV2) -> dict[str, str]:
    package_id = pack.manifest.id
    object_ids = [pack.world.id]
    for section in (
        pack.locations,
        pack.characters,
        pack.items,
        pack.rules,
        pack.schedules,
        pack.goals,
        pack.recipes,
        pack.knowledge_rules,
        pack.quests,
        pack.plot_beats,
        pack.factions,
    ):
        object_ids.extend(item.id for item in section)
    refs: dict[str, str] = {}
    for object_id in sorted(object_ids):
        stable_ref = f"{package_id}/{object_id}"
        scoped = f"{package_id}:{pack.manifest.version}:{stable_ref}"
        refs[stable_ref] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"content_v1:{scoped}"))
    return refs


def compile_pack_v2(pack: ContentPackV2, *, source_hash: str = "") -> CompiledBundle:
    """Compile a valid pack to its deterministic, JSON-serialisable bundle."""
    issues = validate_pack_v2(pack)
    if issues:
        raise issues[0]

    dumped = pack.model_dump(mode="json", by_alias=True)
    runtime_bundle: dict[str, Any] = {
        "world": dumped["world"],
        "locations": _sort_by_id(dumped["locations"]),
        "routes": _canonical_routes(dumped["routes"]),
        "characters": _sort_by_id(dumped["characters"]),
        "items": _sort_by_id(dumped["items"]),
        "initial_state": _sorted_initial_state(dumped["initial_state"]),
        "rules": _sort_by_id(dumped["rules"]),
        "schedules": _sort_by_id(dumped["schedules"]),
        "goals": _sort_by_id(dumped["goals"]),
        "recipes": _sort_by_id(dumped["recipes"]),
        "knowledge_rules": _sort_by_id(dumped["knowledge_rules"]),
        "quests": _sort_by_id(dumped["quests"]),
        "plot_beats": _sort_by_id(dumped["plot_beats"]),
        "factions": _sort_nested_faction_collections(_sort_by_id(dumped["factions"])),
        "_source": {"source_hash": source_hash},
    }
    runtime_bundle = _canonicalize_values(runtime_bundle)
    runtime_hash = compute_runtime_hash(runtime_bundle)
    return CompiledBundle(
        runtime_bundle=runtime_bundle,
        runtime_hash=runtime_hash,
        bundle_schema_version=BUNDLE_SCHEMA_VERSION,
        engine_rules_version=ENGINE_RULES_VERSION,
        ref_map=_ref_map(pack),
    )

"""Persistence adapter for the content_v1 pure advancement kernel.

The adapter maps a frozen published bundle and the existing session carrier
columns to/from the kernel's WorkingState. It deliberately never owns the DB
transaction: all writes remain in the caller's unit of work.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

from ..content.compiler import compute_runtime_hash
from ..content.runtime_models import CurrentPlanState, ItemInstanceState, PlanStatus
from ..models.content_v2 import CONTENT_NAMESPACE, CONTENT_PROFILE_ID
from ..storage.models import (
    ItemTemplateModel,
    LocationModel,
    NPCTemplateModel,
    PlaythroughInstanceModel,
    ScheduledEventModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    StoryPackageVersionModel,
    WorldModel,
    generate_uuid,
)
from .content_publish_service import ContentPublishError, load_published_bundle
from .content_rules import CompiledContentRules
from .time_simulation import (
    ScheduledStep,
    StepKind,
    StepStatus,
    WorkingState,
)
from .turn_unit_of_work import is_managed


CONTENT_RUN_STATE_SCHEMA_VERSION = 1


class ContentRuntimeError(Exception):
    """A fail-closed content_v1 persistence or codec error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ContentRuntimeBinding:
    session_id: str
    version_id: str
    world_id: str
    runtime_hash: str
    bundle_schema_version: int
    engine_rules_version: int


@dataclass(frozen=True)
class ContentRunState:
    schema_version: int
    profile_id: str
    binding_hash: str
    engine_rules_version: int
    logical_tick: int
    next_event_seq: int
    rules_fired: Mapping[str, str]
    flags: Mapping[str, Any]
    route_overrides: Mapping[str, bool]
    pending_steps: tuple[str, ...]


@dataclass(frozen=True)
class ContentRuntimeContext:
    binding: ContentRuntimeBinding
    rules: Any
    state: Any
    pending_steps: tuple
    consumed_step_keys: frozenset[str]
    start_event_seq: int
    run_state: ContentRunState


def _fail(code: str, message: str) -> ContentRuntimeError:
    return ContentRuntimeError(code, message)


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"{label} must be an integer >= {minimum}")
    return value


def _json_copy(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"{label} is not JSON serializable: {exc}") from exc


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"{label} must be an object")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"{label} keys must be strings")
    return result


def _validate_run_state_fields(state: ContentRunState) -> dict[str, Any]:
    if (
        isinstance(state.schema_version, bool)
        or not isinstance(state.schema_version, int)
        or state.schema_version != CONTENT_RUN_STATE_SCHEMA_VERSION
    ):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "unsupported content run-state schema_version")
    if state.profile_id != CONTENT_PROFILE_ID:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "foreign content run-state profile_id")
    if not isinstance(state.binding_hash, str) or len(state.binding_hash) != 64:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "binding_hash must be a 64-character string")
    engine_version = _strict_int(state.engine_rules_version, "engine_rules_version", minimum=1)
    logical_tick = _strict_int(state.logical_tick, "logical_tick")
    next_event_seq = _strict_int(state.next_event_seq, "next_event_seq")

    rules_fired = _mapping(state.rules_fired, "rules_fired")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in rules_fired.items()):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "rules_fired must map strings to strings")
    flags = _mapping(state.flags, "flags")
    route_overrides = _mapping(state.route_overrides, "route_overrides")
    if any(type(value) is not bool for value in route_overrides.values()):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "route_overrides values must be booleans")
    pending_steps = tuple(state.pending_steps)
    if any(not isinstance(key, str) or not key for key in pending_steps):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "pending_steps must contain non-empty strings")

    body = {
        "schema_version": CONTENT_RUN_STATE_SCHEMA_VERSION,
        "profile_id": CONTENT_PROFILE_ID,
        "binding_hash": state.binding_hash,
        "engine_rules_version": engine_version,
        "logical_tick": logical_tick,
        "next_event_seq": next_event_seq,
        "rules_fired": rules_fired,
        "flags": flags,
        "route_overrides": route_overrides,
        "pending_steps": list(pending_steps),
    }
    return _json_copy(body, "content run state")


def encode_content_run_state(state: ContentRunState) -> dict:
    """Encode exactly the frozen §7.3 run-state keys."""
    if not isinstance(state, ContentRunState):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "state must be ContentRunState")
    return _validate_run_state_fields(state)


def decode_content_run_state(raw: Any, *, expected_binding_hash: str) -> ContentRunState:
    """Strictly decode a namespaced content_v1 run-state body."""
    expected = {
        "schema_version",
        "profile_id",
        "binding_hash",
        "engine_rules_version",
        "logical_tick",
        "next_event_seq",
        "rules_fired",
        "flags",
        "route_overrides",
        "pending_steps",
    }
    if not isinstance(raw, Mapping):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content run state is not an object")
    body = dict(raw)
    missing = expected - set(body)
    unknown = set(body) - expected
    if missing:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"content run state is missing keys: {sorted(missing)}")
    if unknown:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"content run state has unknown keys: {sorted(unknown)}")
    if (
        isinstance(body["schema_version"], bool)
        or not isinstance(body["schema_version"], int)
        or body["schema_version"] != CONTENT_RUN_STATE_SCHEMA_VERSION
    ):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "unsupported content run-state schema_version")
    if body["profile_id"] != CONTENT_PROFILE_ID:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "foreign content run-state profile_id")
    if not isinstance(body["binding_hash"], str):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "binding_hash must be text")
    if body["binding_hash"] != expected_binding_hash:
        raise _fail("CONTENT_HASH_MISMATCH", "content run-state binding_hash differs from the published runtime hash")
    engine_version = _strict_int(body["engine_rules_version"], "engine_rules_version", minimum=1)
    logical_tick = _strict_int(body["logical_tick"], "logical_tick")
    next_event_seq = _strict_int(body["next_event_seq"], "next_event_seq")
    rules_fired = _mapping(body["rules_fired"], "rules_fired")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in rules_fired.items()):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "rules_fired must map strings to strings")
    flags = _mapping(body["flags"], "flags")
    route_overrides = _mapping(body["route_overrides"], "route_overrides")
    if any(type(value) is not bool for value in route_overrides.values()):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "route_overrides values must be booleans")
    pending = body["pending_steps"]
    if not isinstance(pending, list) or any(not isinstance(key, str) or not key for key in pending):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "pending_steps must be an array of non-empty strings")
    if len(set(pending)) != len(pending):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "pending_steps contains duplicate step keys")
    # Validate that all arbitrary JSON subtrees are safe to hand to the kernel.
    _json_copy(flags, "flags")
    return ContentRunState(
        schema_version=CONTENT_RUN_STATE_SCHEMA_VERSION,
        profile_id=CONTENT_PROFILE_ID,
        binding_hash=expected_binding_hash,
        engine_rules_version=engine_version,
        logical_tick=logical_tick,
        next_event_seq=next_event_seq,
        rules_fired=dict(rules_fired),
        flags=copy.deepcopy(flags),
        route_overrides=dict(route_overrides),
        pending_steps=tuple(pending),
    )


def read_content_run_state(
    global_flags: Any, *, expected_binding_hash: str
) -> ContentRunState | None:
    """Read only the content namespace; phase-3 and ordinary flags are opaque."""
    if global_flags is None:
        return None
    if not isinstance(global_flags, Mapping):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "global_flags_json is not an object")
    if CONTENT_NAMESPACE not in global_flags:
        return None
    return decode_content_run_state(
        global_flags[CONTENT_NAMESPACE], expected_binding_hash=expected_binding_hash
    )


def merge_content_run_state(global_flags: Any, state: ContentRunState) -> dict:
    """Return a new carrier object while preserving all non-content entries."""
    if global_flags is None:
        merged: dict[str, Any] = {}
    elif isinstance(global_flags, Mapping):
        merged = dict(global_flags)
    else:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "global_flags_json is not an object")
    merged[CONTENT_NAMESPACE] = encode_content_run_state(state)
    return merged


def is_content_conditions(conditions: Any) -> bool:
    return isinstance(conditions, Mapping) and CONTENT_NAMESPACE in conditions


def encode_content_step_conditions(step: Any) -> dict:
    """Encode a ScheduledStep using the isolated content namespace."""
    body = {
        "schema_version": CONTENT_RUN_STATE_SCHEMA_VERSION,
        "profile_id": CONTENT_PROFILE_ID,
        "step_key": getattr(step, "step_key", None),
        "tick": getattr(step, "tick", None),
        "phase": getattr(step, "phase", None),
        "actor_code": getattr(step, "actor_code", None),
        "kind": getattr(step, "kind", None),
        "payload": getattr(step, "payload", None),
    }
    # Reuse ScheduledStep's closed vocabulary and range checks before serialization.
    decoded = _decode_content_step_body(body)
    normalized = {
        "schema_version": CONTENT_RUN_STATE_SCHEMA_VERSION,
        "profile_id": CONTENT_PROFILE_ID,
        "step_key": decoded.step_key,
        "tick": decoded.tick,
        "phase": int(decoded.phase),
        "actor_code": decoded.actor_code,
        "kind": decoded.kind,
        "payload": _json_copy(decoded.payload, "scheduled-step payload"),
    }
    return {CONTENT_NAMESPACE: normalized}


def _decode_content_step_body(body: Any) -> ScheduledStep:
    expected = {
        "schema_version",
        "profile_id",
        "step_key",
        "tick",
        "phase",
        "actor_code",
        "kind",
        "payload",
    }
    if not isinstance(body, Mapping):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content scheduled-step payload is not an object")
    data = dict(body)
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"content scheduled step is missing keys: {sorted(missing)}")
    if unknown:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"content scheduled step has unknown keys: {sorted(unknown)}")
    if (
        isinstance(data["schema_version"], bool)
        or not isinstance(data["schema_version"], int)
        or data["schema_version"] != CONTENT_RUN_STATE_SCHEMA_VERSION
    ):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "unsupported content step schema_version")
    if data["profile_id"] != CONTENT_PROFILE_ID:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "foreign content step profile_id")
    if isinstance(data["tick"], bool) or not isinstance(data["tick"], int) or data["tick"] < 0:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content step tick must be a non-negative integer")
    if isinstance(data["phase"], bool) or not isinstance(data["phase"], int):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content step phase must be an integer")
    payload = _mapping(data["payload"], "scheduled-step payload")
    try:
        return ScheduledStep(
            step_key=data["step_key"],
            tick=data["tick"],
            phase=data["phase"],
            actor_code=data["actor_code"],
            kind=data["kind"],
            payload=payload,
        )
    except Exception as exc:
        if isinstance(exc, ContentRuntimeError):
            raise
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"invalid content scheduled step: {exc}") from exc


def decode_content_step_conditions(conditions: Any) -> ScheduledStep:
    """Strictly decode only a step under CONTENT_NAMESPACE."""
    if not is_content_conditions(conditions):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "scheduled step is not in the content namespace")
    return _decode_content_step_body(conditions[CONTENT_NAMESPACE])


def encode_content_npc_plan(plan: Any, *, binding_hash: str) -> str:
    """Encode the strict §8.2 CurrentPlanState representation."""
    if not isinstance(plan, CurrentPlanState):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "plan must be CurrentPlanState")
    body = {
        "schema_version": CONTENT_RUN_STATE_SCHEMA_VERSION,
        "profile_id": CONTENT_PROFILE_ID,
        "binding_hash": binding_hash,
        "goal_id": plan.goal_id,
        "source": plan.source,
        "generation": plan.generation,
        "recipe_step": plan.recipe_step,
        "action": plan.action,
        "target": plan.target,
        "start_tick": plan.start_tick,
        "expected_end_tick": plan.expected_end_tick,
        "status": plan.status,
        "failure_code": plan.failure_code,
    }
    _validate_plan_body(body, expected_binding_hash=binding_hash)
    return json.dumps({CONTENT_NAMESPACE: body}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate_plan_body(body: Any, *, expected_binding_hash: str) -> CurrentPlanState:
    expected = {
        "schema_version",
        "profile_id",
        "binding_hash",
        "goal_id",
        "source",
        "generation",
        "recipe_step",
        "action",
        "target",
        "start_tick",
        "expected_end_tick",
        "status",
        "failure_code",
    }
    if not isinstance(body, Mapping):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan is not an object")
    data = dict(body)
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"content NPC plan is missing keys: {sorted(missing)}")
    if unknown:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"content NPC plan has unknown keys: {sorted(unknown)}")
    if (
        isinstance(data["schema_version"], bool)
        or not isinstance(data["schema_version"], int)
        or data["schema_version"] != CONTENT_RUN_STATE_SCHEMA_VERSION
    ):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "unsupported content NPC plan schema_version")
    if data["profile_id"] != CONTENT_PROFILE_ID:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "foreign content NPC plan profile_id")
    if not isinstance(data["binding_hash"], str) or len(data["binding_hash"]) != 64:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan binding_hash must be a 64-character string")
    if data["binding_hash"] != expected_binding_hash:
        raise _fail("CONTENT_HASH_MISMATCH", "content NPC plan binding_hash differs from the published runtime hash")
    if not isinstance(data["goal_id"], str) or not data["goal_id"]:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan goal_id is invalid")
    if not isinstance(data["source"], str) or data["source"] not in {"goal", "schedule"}:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan source is invalid")
    generation = _strict_int(data["generation"], "plan generation")
    recipe_step = _strict_int(data["recipe_step"], "plan recipe_step")
    start_tick = _strict_int(data["start_tick"], "plan start_tick")
    expected_end_tick = _strict_int(data["expected_end_tick"], "plan expected_end_tick")
    if expected_end_tick < start_tick:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan ends before it starts")
    if not isinstance(data["action"], str) or data["action"] not in {"move", "wait", "take", "use", "transfer"}:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan action is invalid")
    if data["target"] is not None and not isinstance(data["target"], str):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan target must be text or null")
    allowed_statuses = {status.value for status in PlanStatus}
    if not isinstance(data["status"], str) or data["status"] not in allowed_statuses:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan status is invalid")
    if data["failure_code"] is not None and not isinstance(data["failure_code"], str):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content NPC plan failure_code must be text or null")
    return CurrentPlanState(
        goal_id=data["goal_id"],
        source=data["source"],
        generation=generation,
        recipe_step=recipe_step,
        action=data["action"],
        target=data["target"],
        start_tick=start_tick,
        expected_end_tick=expected_end_tick,
        status=data["status"],
        failure_code=data["failure_code"],
    )


def decode_content_npc_plan(raw: Any, *, expected_binding_hash: str) -> Any:
    """Decode a content plan, leaving other subsystem/phase-3 plan text opaque."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "hidden_plan_state is not text")
    text = raw.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"hidden_plan_state JSON is invalid: {exc}") from exc
    if not isinstance(parsed, Mapping) or CONTENT_NAMESPACE not in parsed:
        return None
    return _validate_plan_body(parsed[CONTENT_NAMESPACE], expected_binding_hash=expected_binding_hash)


def read_content_binding(db: Session, *, session_id: str) -> ContentRuntimeBinding:
    """Resolve and cross-check the permanent Session → Instance → World → SPV binding."""
    session = db.get(SessionModel, session_id)
    if session is None:
        raise _fail("CONTENT_BUNDLE_MISSING", f"session {session_id!r} does not exist")
    if not session.story_package_version_id or not session.playthrough_instance_id or not session.world_id:
        raise _fail("CONTENT_BUNDLE_MISSING", f"session {session_id!r} is missing its content binding")

    instance = db.get(PlaythroughInstanceModel, session.playthrough_instance_id)
    if (
        instance is None
        or instance.story_package_version_id != session.story_package_version_id
        or instance.world_id != session.world_id
    ):
        raise _fail("CONTENT_BINDING_MISMATCH", "session and playthrough instance bindings differ")
    world = db.get(WorldModel, session.world_id)
    if world is None or world.story_package_version_id != session.story_package_version_id:
        raise _fail("CONTENT_BINDING_MISMATCH", "session and world version bindings differ")
    version = db.get(StoryPackageVersionModel, session.story_package_version_id)
    if version is None:
        raise _fail("CONTENT_BUNDLE_MISSING", f"story package version {session.story_package_version_id!r} is missing")
    if version.status != "published":
        raise _fail("CONTENT_VERSION_NOT_PUBLISHED", f"content version {version.id!r} is not published")
    if (
        version.runtime_bundle_json is None
        or not isinstance(version.runtime_hash, str)
        or len(version.runtime_hash) != 64
    ):
        raise _fail("CONTENT_BUNDLE_MISSING", f"published version {version.id!r} has no complete runtime bundle/hash")
    if version.world_id != world.id:
        raise _fail("CONTENT_BINDING_MISMATCH", "published version and world bindings differ")

    ruleset = world.ruleset_json
    if not isinstance(ruleset, Mapping):
        raise _fail("CONTENT_BINDING_MISMATCH", "world ruleset_json is not an object")
    has_content = "content_profile" in ruleset
    has_phase3 = "phase3_profile" in ruleset
    if has_content and has_phase3:
        raise _fail("CONTENT_BINDING_CONFLICT", "world carries both content_v1 and phase-3 profiles")
    profile = ruleset.get("content_profile")
    if not has_content or has_phase3 or not isinstance(profile, Mapping) or profile.get("id") != CONTENT_PROFILE_ID:
        raise _fail("CONTENT_BINDING_MISMATCH", "world does not carry the content_v1 profile")
    if profile.get("runtime_hash") != version.runtime_hash:
        raise _fail("CONTENT_BINDING_MISMATCH", "world profile runtime hash differs from the published version")
    bundle_schema_version = profile.get("schema_version")
    engine_rules_version = profile.get("engine_rules_version")
    if (
        isinstance(bundle_schema_version, bool)
        or not isinstance(bundle_schema_version, int)
        or bundle_schema_version != version.runtime_schema_version
        or isinstance(engine_rules_version, bool)
        or not isinstance(engine_rules_version, int)
        or engine_rules_version < 1
    ):
        raise _fail("CONTENT_BINDING_MISMATCH", "world profile schema/rules version is incomplete or inconsistent")

    expected_instance_binding = {
        "version_id": version.id,
        "runtime_hash": version.runtime_hash,
        "bundle_schema_version": bundle_schema_version,
        "engine_rules_version": engine_rules_version,
    }
    config = instance.config_json if isinstance(instance.config_json, Mapping) else {}
    content_binding = config.get("__content_binding")
    if (
        not isinstance(content_binding, Mapping)
        or set(content_binding) != set(expected_instance_binding)
        or any(content_binding.get(key) != value for key, value in expected_instance_binding.items())
    ):
        raise _fail(
            "CONTENT_BINDING_MISMATCH",
            "playthrough instance content binding differs from the published version/world profile",
        )
    return ContentRuntimeBinding(
        session_id=session.id,
        version_id=version.id,
        world_id=world.id,
        runtime_hash=version.runtime_hash,
        bundle_schema_version=bundle_schema_version,
        engine_rules_version=engine_rules_version,
    )


def _world_maps(db: Session, binding: ContentRuntimeBinding, rules: Any):
    location_rows = db.query(LocationModel).filter(LocationModel.world_id == binding.world_id).all()
    locations = {row.code: row for row in location_rows}
    expected_locations = set(rules.data.locations)
    if len(locations) != len(location_rows) or set(locations) != expected_locations:
        raise _fail("CONTENT_BINDING_MISMATCH", "materialized locations differ from the published bundle")
    location_codes_by_id = {row.id: code for code, row in locations.items()}

    npc_rows = db.query(NPCTemplateModel).filter(NPCTemplateModel.world_id == binding.world_id).all()
    npcs = {row.code: row for row in npc_rows}
    if len(npcs) != len(npc_rows) or set(npcs) != set(rules.data.characters):
        raise _fail("CONTENT_BINDING_MISMATCH", "materialized characters differ from the published bundle")

    item_rows = db.query(ItemTemplateModel).filter(ItemTemplateModel.world_id == binding.world_id).all()
    items = {row.code: row for row in item_rows}
    if len(items) != len(item_rows) or set(items) != set(rules.data.items):
        raise _fail("CONTENT_BINDING_MISMATCH", "materialized items differ from the published bundle")
    return locations, location_codes_by_id, npcs, items


def _owner_from_row(
    row: SessionInventoryItemModel,
    *,
    location_codes_by_id: Mapping[str, str],
    npc_codes_by_state_id: Mapping[str, str],
) -> tuple[str, str]:
    if row.owner_type == "player":
        if row.owner_ref_id not in (None, "player"):
            raise _fail("CONTENT_RUN_STATE_CORRUPT", "player-owned item has a foreign owner reference")
        return "player", "player"
    if row.owner_type == "location":
        code = location_codes_by_id.get(row.owner_ref_id or "")
        if code is None:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", "item owner is not a location in this world")
        return "location", code
    if row.owner_type == "character":
        code = npc_codes_by_state_id.get(row.owner_ref_id or "")
        if code is None:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", "item owner is not an NPC state in this session")
        return "character", code
    raise _fail("CONTENT_RUN_STATE_CORRUPT", f"unsupported content item owner_type {row.owner_type!r}")


def _restore_one_shot(rules: Any, run_state: ContentRunState) -> tuple[dict[str, bool], set[str]]:
    rules_by_id = {rule.id: rule for rule in rules.data.rules}
    one_shot: dict[str, bool] = {}
    consumed: set[str] = set()
    for stored_key, stored_tick in run_state.rules_fired.items():
        if stored_key.startswith("__kernel__|"):
            one_shot[stored_key.split("|", 1)[1]] = True
            continue
        if "|" not in stored_key:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"invalid rules_fired key {stored_key!r}")
        rule_id, occurrence = stored_key.split("|", 1)
        rule = rules_by_id.get(rule_id)
        if rule is None or not occurrence:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"rules_fired references unknown rule {rule_id!r}")
        try:
            tick = int(stored_tick)
        except (TypeError, ValueError) as exc:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"rules_fired tick is invalid for {stored_key!r}") from exc
        if tick < 0 or str(tick) != stored_tick:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"rules_fired tick is invalid for {stored_key!r}")
        if rule.fire_mode == "once_per_instance":
            one_shot[f"content_rule:{rule_id}"] = True
        else:
            one_shot[f"content_rule:{rule_id}:{occurrence}"] = True
        consumed.add(f"rule:{rule_id}@{tick}")
    return one_shot, consumed


def _scheduled_content_rows(db: Session, session_id: str) -> list[ScheduledEventModel]:
    return db.query(ScheduledEventModel).filter(ScheduledEventModel.session_id == session_id).all()


def load_content_runtime_context(db: Session, *, session_id: str) -> ContentRuntimeContext:
    """Build an isolated WorkingState from the persisted carriers or fresh defaults."""
    binding = read_content_binding(db, session_id=session_id)
    try:
        bundle, runtime_hash = load_published_bundle(db, version_id=binding.version_id)
    except ContentPublishError as exc:
        raise _fail(exc.code, exc.message) from exc
    try:
        recomputed_hash = compute_runtime_hash(bundle)
    except (TypeError, ValueError) as exc:
        raise _fail("CONTENT_HASH_MISMATCH", f"published runtime bundle cannot be hashed: {exc}") from exc
    if runtime_hash != binding.runtime_hash or recomputed_hash != runtime_hash:
        raise _fail("CONTENT_HASH_MISMATCH", "published runtime bundle hash differs from its binding")
    if binding.bundle_schema_version != 1 or binding.engine_rules_version != 1:
        raise _fail("CONTENT_SCHEMA_UNSUPPORTED", "content bundle or engine rules schema is unsupported")

    from ..content.runtime_models import build_compiled_rules

    try:
        rules = CompiledContentRules(build_compiled_rules(bundle, binding_hash=runtime_hash))
    except Exception as exc:
        code = getattr(exc, "code", "CONTENT_SCHEMA_UNSUPPORTED")
        raise _fail(code, f"published content rules could not be compiled: {exc}") from exc
    locations, location_codes_by_id, npc_templates, item_templates = _world_maps(db, binding, rules)
    session_state = db.query(SessionStateModel).filter(SessionStateModel.session_id == session_id).one_or_none()
    run_state = read_content_run_state(
        session_state.global_flags_json if session_state is not None else None,
        expected_binding_hash=runtime_hash,
    )

    if run_state is None:
        # A fresh session is a pure overlay: reading twice inserts no rows and
        # always reconstructs the same defaults and finite initial schedule.
        state = rules.initial_state()
        pending_steps = tuple(rules.initial_steps())
        consumed_step_keys = frozenset()
        run_state = ContentRunState(
            schema_version=CONTENT_RUN_STATE_SCHEMA_VERSION,
            profile_id=CONTENT_PROFILE_ID,
            binding_hash=runtime_hash,
            engine_rules_version=binding.engine_rules_version,
            logical_tick=state.logical_tick,
            next_event_seq=0,
            rules_fired={},
            flags=copy.deepcopy(dict(state.flags)),
            route_overrides=dict(state.route_overrides),
            pending_steps=tuple(step.step_key for step in pending_steps),
        )
        return ContentRuntimeContext(
            binding=binding,
            rules=rules,
            state=state,
            pending_steps=pending_steps,
            consumed_step_keys=consumed_step_keys,
            start_event_seq=0,
            run_state=run_state,
        )

    if run_state.engine_rules_version != binding.engine_rules_version:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "run-state engine_rules_version differs from its binding")
    if session_state is None:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "content run state has no session_states carrier")
    state = rules.initial_state()
    state.logical_tick = run_state.logical_tick
    state.flags = copy.deepcopy(dict(run_state.flags))
    if not session_state.current_location_id or session_state.current_location_id not in location_codes_by_id:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "player location is not a materialized location in this world")
    state.player_location_code = location_codes_by_id[session_state.current_location_id]

    npc_states = db.query(SessionNPCStateModel).filter(SessionNPCStateModel.session_id == session_id).all()
    npc_states_by_template: dict[str, SessionNPCStateModel] = {}
    for row in npc_states:
        if row.npc_template_id in npc_states_by_template:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", "duplicate session NPC state for a materialized character")
        npc_states_by_template[row.npc_template_id] = row
    if set(npc_states_by_template) - {template.id for template in npc_templates.values()}:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "session contains an NPC state outside the published world")
    npc_codes_by_state_id: dict[str, str] = {}
    for code, template in npc_templates.items():
        row = npc_states_by_template.get(template.id)
        if row is None:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"session NPC state is missing for {code!r}")
        if not row.current_location_id or row.current_location_id not in location_codes_by_id:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"NPC {code!r} is not at a materialized location")
        npc_codes_by_state_id[row.id] = code
        state.npc_positions[code] = location_codes_by_id[row.current_location_id]
        if row.status_flags is not None and not isinstance(row.status_flags, Mapping):
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"NPC {code!r} status_flags is not an object")
        status_flags = row.status_flags or {}
        alive = status_flags.get("alive", state.npc_alive.get(code, True))
        if type(alive) is not bool:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"NPC {code!r} alive status is not boolean")
        state.npc_alive[code] = alive
        plan = decode_content_npc_plan(row.hidden_plan_state, expected_binding_hash=runtime_hash)
        state.npc_current_plans[code] = plan
        if plan is not None:
            state.npc_goals[code] = plan.goal_id

    inventory_rows = db.query(SessionInventoryItemModel).filter(
        SessionInventoryItemModel.session_id == session_id
    ).all()
    rows_by_key: dict[str, SessionInventoryItemModel] = {}
    for row in inventory_rows:
        if row.instance_key is None:
            continue
        if row.instance_key in rows_by_key:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"duplicate inventory instance_key {row.instance_key!r}")
        rows_by_key[row.instance_key] = row
    if set(rows_by_key) != set(rules.data.items):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "session inventory instance keys differ from the published items")
    for code, definition in rules.data.items.items():
        row = rows_by_key[code]
        if row.item_template_id != item_templates[code].id or row.quantity != 1:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"inventory instance {code!r} has invalid template/quantity")
        owner_type, owner_ref = _owner_from_row(
            row,
            location_codes_by_id=location_codes_by_id,
            npc_codes_by_state_id=npc_codes_by_state_id,
        )
        state.item_instances[code] = ItemInstanceState(
            code=code,
            quantity=row.quantity,
            owner_type=owner_type,
            owner_ref=owner_ref,
        )

    route_keys = set(state.routes_open)
    if set(run_state.route_overrides) - route_keys:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "route_overrides references a route outside the published bundle")
    # Defaults come from the immutable bundle; the session carrier is applied last.
    route_overrides = dict(state.route_overrides)
    route_overrides.update(run_state.route_overrides)
    state.route_overrides = route_overrides
    state.one_shot, rule_consumed_keys = _restore_one_shot(rules, run_state)

    pending_steps: list[ScheduledStep] = []
    consumed_keys = set(rule_consumed_keys)
    seen_step_keys: set[str] = set()
    for row in _scheduled_content_rows(db, session_id):
        conditions = row.trigger_conditions_json
        if not is_content_conditions(conditions):
            continue
        step = decode_content_step_conditions(conditions)
        if step.step_key in seen_step_keys:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"duplicate scheduled step {step.step_key!r}")
        seen_step_keys.add(step.step_key)
        if row.status == "pending":
            pending_steps.append(step)
        else:
            consumed_keys.add(step.step_key)
    pending_steps.sort(key=lambda step: step.order_key)
    if set(run_state.pending_steps) != {step.step_key for step in pending_steps}:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "run-state pending_steps differ from persisted scheduled events")
    return ContentRuntimeContext(
        binding=binding,
        rules=rules,
        state=state,
        pending_steps=tuple(pending_steps),
        consumed_step_keys=frozenset(consumed_keys),
        start_event_seq=run_state.next_event_seq,
        run_state=run_state,
    )


def _location_maps_for_apply(db: Session, binding: ContentRuntimeBinding, rules: Any):
    locations, location_codes_by_id, npc_templates, item_templates = _world_maps(db, binding, rules)
    return locations, location_codes_by_id, npc_templates, item_templates


def _rules_fired_after_advance(context: ContentRuntimeContext, result: Any) -> dict[str, str]:
    fired = dict(context.run_state.rules_fired)
    for step in getattr(result, "consumed_step_specs", ()) or ():
        if step.kind != StepKind.CONTENT_RULE_FIRE:
            continue
        rule_id = step.payload.get("rule")
        occurrence = step.payload.get("occurrence")
        if isinstance(rule_id, str) and isinstance(occurrence, str):
            fired[f"{rule_id}|{occurrence}"] = str(step.tick)
    for key, value in getattr(result.final_state, "one_shot", {}).items():
        if value is not True:
            continue
        if key.startswith("content_rule:"):
            # Rule firings are represented by stable rule-id/occurrence keys above.
            continue
        if key.startswith("content_plan_reeval:"):
            # The planner's re-evaluation budget is per-advance; past markers are
            # outside every later (start_tick, end_tick] interval.
            continue
        fired[f"__kernel__|{key}"] = str(result.actual_end_tick)
    return fired


def _persist_npc_states(
    db: Session,
    *,
    session_id: str,
    binding: ContentRuntimeBinding,
    rules: Any,
    final_state: WorkingState,
    locations: Mapping[str, LocationModel],
    npc_templates: Mapping[str, NPCTemplateModel],
) -> dict[str, SessionNPCStateModel]:
    existing_rows = db.query(SessionNPCStateModel).filter(
        SessionNPCStateModel.session_id == session_id
    ).all()
    by_template = {row.npc_template_id: row for row in existing_rows}
    if len(by_template) != len(existing_rows):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "duplicate session NPC state rows")
    expected_template_ids = {template.id for template in npc_templates.values()}
    if set(by_template) - expected_template_ids:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "session contains an NPC state outside the published world")
    by_code: dict[str, SessionNPCStateModel] = {}
    for code, template in npc_templates.items():
        position = final_state.npc_positions.get(code)
        if position not in locations:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"final NPC position for {code!r} is not in the published bundle")
        row = by_template.get(template.id)
        if row is None:
            row = SessionNPCStateModel(
                id=generate_uuid(),
                session_id=session_id,
                npc_template_id=template.id,
                current_location_id=locations[position].id,
                trust_score=50,
                suspicion_score=0,
                status_flags={},
            )
            db.add(row)
            by_template[template.id] = row
        row.current_location_id = locations[position].id
        if row.status_flags is not None and not isinstance(row.status_flags, Mapping):
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"NPC {code!r} status_flags is not an object")
        status_flags = dict(row.status_flags or {})
        alive = final_state.npc_alive.get(code, True)
        if type(alive) is not bool:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"final NPC alive value for {code!r} is not boolean")
        status_flags["alive"] = alive
        row.status_flags = status_flags
        plan = final_state.npc_current_plans.get(code)
        if plan is not None:
            row.hidden_plan_state = encode_content_npc_plan(plan, binding_hash=binding.runtime_hash)
        else:
            # Never clear another subsystem's free text or a phase-3 plan.
            prior = decode_content_npc_plan(row.hidden_plan_state, expected_binding_hash=binding.runtime_hash)
            if row.hidden_plan_state is None or prior is not None:
                row.hidden_plan_state = None
        by_code[code] = row
    return by_code


def _persist_inventory(
    db: Session,
    *,
    session_id: str,
    final_state: WorkingState,
    locations: Mapping[str, LocationModel],
    npc_states: Mapping[str, SessionNPCStateModel],
    item_templates: Mapping[str, ItemTemplateModel],
) -> None:
    rows = db.query(SessionInventoryItemModel).filter(
        SessionInventoryItemModel.session_id == session_id
    ).all()
    by_key: dict[str, SessionInventoryItemModel] = {}
    for row in rows:
        if row.instance_key is None:
            continue
        if row.instance_key in by_key:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"duplicate inventory instance_key {row.instance_key!r}")
        by_key[row.instance_key] = row
    instances = final_state.item_instances
    if set(by_key) - set(item_templates):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "session inventory contains an instance outside the published bundle")
    if set(instances) != set(item_templates):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "final item instances differ from the published bundle")
    npc_state_ids = {code: row.id for code, row in npc_states.items()}
    for code, item in instances.items():
        if item.code != code or type(item.quantity) is not int or item.quantity != 1:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"item instance {code!r} violates unique quantity invariants")
        row = by_key.get(code)
        if row is None:
            row = SessionInventoryItemModel(
                id=generate_uuid(),
                session_id=session_id,
                item_template_id=item_templates[code].id,
                owner_type=item.owner_type,
                owner_ref_id=None,
                quantity=item.quantity,
                bound_flag=False,
                instance_key=code,
            )
            db.add(row)
            by_key[code] = row
        if row.item_template_id != item_templates[code].id:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"inventory instance {code!r} has a foreign item template")
        if item.owner_type == "player":
            owner_ref_id = "player"
        elif item.owner_type == "location":
            if item.owner_ref not in locations:
                raise _fail("CONTENT_RUN_STATE_CORRUPT", f"item {code!r} has an unknown location owner")
            owner_ref_id = locations[item.owner_ref].id
        elif item.owner_type == "character":
            if item.owner_ref not in npc_state_ids:
                raise _fail("CONTENT_RUN_STATE_CORRUPT", f"item {code!r} has an unknown character owner")
            owner_ref_id = npc_state_ids[item.owner_ref]
        else:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"item {code!r} has unsupported owner_type {item.owner_type!r}")
        row.owner_type = item.owner_type
        row.owner_ref_id = owner_ref_id
        row.quantity = item.quantity
        row.instance_key = code


def _persist_scheduled_steps(db: Session, *, session_id: str, result: Any) -> None:
    rows_by_key: dict[str, ScheduledEventModel] = {}
    for row in _scheduled_content_rows(db, session_id):
        if not is_content_conditions(row.trigger_conditions_json):
            continue
        step = decode_content_step_conditions(row.trigger_conditions_json)
        if step.step_key in rows_by_key:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"duplicate scheduled step {step.step_key!r}")
        rows_by_key[step.step_key] = row
    specs = {step.step_key: step for step in (getattr(result, "consumed_step_specs", ()) or ())}
    consumed_outcomes = {item.step_key: item for item in (getattr(result, "consumed_steps", ()) or ())}
    terminal_status = {
        StepStatus.APPLIED: "triggered",
        StepStatus.BLOCKED: "cancelled",
        StepStatus.CANCELLED: "cancelled",
    }
    for outcome in consumed_outcomes.values():
        status = terminal_status.get(outcome.status)
        if status is None:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"unknown consumed-step status {outcome.status!r}")
        row = rows_by_key.get(outcome.step_key)
        if row is not None:
            row.status = status
            continue
        if outcome.kind == StepKind.PLAYER_CONTINUOUS_COMPLETE:
            continue
        step = specs.get(outcome.step_key)
        if step is None:
            raise _fail("CONTENT_RUN_STATE_CORRUPT", f"consumed step {outcome.step_key!r} has no persisted spec")
        row = ScheduledEventModel(
            id=generate_uuid(),
            session_id=session_id,
            event_template_id=None,
            trigger_time=None,
            trigger_conditions_json=encode_content_step_conditions(step),
            status=status,
        )
        db.add(row)
        rows_by_key[outcome.step_key] = row
    for step in getattr(result, "pending_steps", ()) or ():
        if step.step_key in rows_by_key:
            continue
        row = ScheduledEventModel(
            id=generate_uuid(),
            session_id=session_id,
            event_template_id=None,
            trigger_time=None,
            trigger_conditions_json=encode_content_step_conditions(step),
            status="pending",
        )
        db.add(row)
        rows_by_key[step.step_key] = row


def _write_content_cognition(
    db: Session,
    *,
    context: ContentRuntimeContext,
    advance_result: Any,
) -> None:
    try:
        from . import content_cognition
    except ModuleNotFoundError as exc:
        if exc.name not in {"llm_rpg.core.content_cognition", "content_cognition"}:
            raise
        raise _fail(
            "CONTENT_COGNITION_UNAVAILABLE",
            "write_cognition=True requires llm_rpg.core.content_cognition.write_content_cognition",
        ) from exc
    event_ids = getattr(advance_result, "event_ids", None) or db.info.get("content_event_ids", {})
    tick_positions = getattr(advance_result, "tick_positions", None) or db.info.get("content_tick_positions", {})
    entries, player_entries = content_cognition.build_cognition_plan(
        advance_result=advance_result,
        knowledge_rules=context.rules.data.knowledge_rules,
        binding_hash=context.binding.runtime_hash,
        version_id=context.binding.version_id,
        tick_positions=tick_positions,
        event_ids=event_ids,
    )
    content_cognition.write_content_cognition(
        db,
        session_id=context.binding.session_id,
        version_id=context.binding.version_id,
        binding_hash=context.binding.runtime_hash,
        entries=entries,
        player_entries=player_entries,
    )


def apply_content_advance(
    db: Session,
    *,
    session_id: str,
    context: ContentRuntimeContext,
    advance_result: Any,
    write_cognition: bool = False,
) -> None:
    """Persist one kernel result without taking ownership of the caller's UoW."""
    if not is_managed(db):
        raise _fail("CONTENT_RUNTIME_UOW_REQUIRED", "apply_content_advance requires a caller-managed unit of work")
    if context.binding.session_id != session_id:
        raise _fail("CONTENT_BINDING_MISMATCH", "runtime context belongs to a different session")
    current_binding = read_content_binding(db, session_id=session_id)
    if current_binding != context.binding:
        raise _fail("CONTENT_BINDING_MISMATCH", "content binding changed after context loading")
    if getattr(advance_result, "profile_id", None) != CONTENT_PROFILE_ID:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "advance result does not belong to content_v1")
    if advance_result.start_tick != context.run_state.logical_tick:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "advance result start tick differs from the loaded cursor")
    if advance_result.actual_end_tick < advance_result.start_tick:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "advance result ends before it starts")
    if advance_result.next_event_seq < context.start_event_seq:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "advance result event cursor moved backwards")
    if advance_result.final_state.logical_tick != advance_result.actual_end_tick:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "final working-state tick differs from the advance result")
    if set(advance_result.final_state.route_overrides) - set(context.state.routes_open):
        raise _fail("CONTENT_RUN_STATE_CORRUPT", "advance result contains a route outside the published bundle")

    locations, location_codes_by_id, npc_templates, item_templates = _location_maps_for_apply(
        db, current_binding, context.rules
    )
    session_state = db.query(SessionStateModel).filter(
        SessionStateModel.session_id == session_id
    ).one_or_none()
    player_code = advance_result.final_state.player_location_code
    if player_code not in locations:
        raise _fail("CONTENT_RUN_STATE_CORRUPT", f"final player location {player_code!r} is not in the published bundle")
    run_state = ContentRunState(
        schema_version=CONTENT_RUN_STATE_SCHEMA_VERSION,
        profile_id=CONTENT_PROFILE_ID,
        binding_hash=current_binding.runtime_hash,
        engine_rules_version=current_binding.engine_rules_version,
        logical_tick=advance_result.actual_end_tick,
        next_event_seq=advance_result.next_event_seq,
        rules_fired=_rules_fired_after_advance(context, advance_result),
        flags=copy.deepcopy(dict(advance_result.final_state.flags)),
        route_overrides=copy.deepcopy(dict(advance_result.final_state.route_overrides)),
        pending_steps=tuple(step.step_key for step in (advance_result.pending_steps or ())),
    )
    old_flags = session_state.global_flags_json if session_state is not None else {}
    merged_flags = merge_content_run_state(old_flags, run_state)
    if session_state is None:
        session_state = SessionStateModel(
            id=generate_uuid(),
            session_id=session_id,
            current_time=f"tick:{advance_result.actual_end_tick}",
            time_phase=CONTENT_PROFILE_ID,
            current_location_id=locations[player_code].id,
            active_mode="exploration",
            global_flags_json=merged_flags,
        )
        db.add(session_state)
    else:
        session_state.global_flags_json = merged_flags
        session_state.current_location_id = locations[player_code].id

    npc_states = _persist_npc_states(
        db,
        session_id=session_id,
        binding=current_binding,
        rules=context.rules,
        final_state=advance_result.final_state,
        locations=locations,
        npc_templates=npc_templates,
    )
    _persist_inventory(
        db,
        session_id=session_id,
        final_state=advance_result.final_state,
        locations=locations,
        npc_states=npc_states,
        item_templates=item_templates,
    )
    _persist_scheduled_steps(db, session_id=session_id, result=advance_result)
    # Flush is not a commit; it makes the carrier rows visible to cognition in the
    # same transaction and lets FK/unique failures abort the caller's whole UoW.
    db.flush()
    if write_cognition:
        _write_content_cognition(db, context=context, advance_result=advance_result)


__all__ = [
    "CONTENT_RUN_STATE_SCHEMA_VERSION",
    "ContentRuntimeError",
    "ContentRuntimeBinding",
    "ContentRunState",
    "ContentRuntimeContext",
    "read_content_binding",
    "encode_content_run_state",
    "decode_content_run_state",
    "read_content_run_state",
    "merge_content_run_state",
    "is_content_conditions",
    "encode_content_step_conditions",
    "decode_content_step_conditions",
    "encode_content_npc_plan",
    "decode_content_npc_plan",
    "load_content_runtime_context",
    "apply_content_advance",
]

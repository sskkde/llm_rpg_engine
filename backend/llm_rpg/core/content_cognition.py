"""Event-derived cognition planning and persistence for ``content_v1``.

This module is the DB boundary for cognition. Plans are derived from the
advancer's decided events and event-time position snapshots; it never infers
observer positions from the returned final state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from string import Formatter
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy.orm import Session as DBSession

from ..storage.models import (
    GameEventModel,
    LocationModel,
    MemoryFactModel,
    NPCPrivateMemoryModel,
    NPCTemplateModel,
    SessionModel,
    SessionNPCStateModel,
    StoryPackageVersionModel,
    WorldModel,
    generate_uuid,
)


class ContentCognitionError(Exception):
    """A fail-closed error while planning or writing content cognition."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class CognitionEntry:
    subject_type: str
    subject_ref: str
    source_event_id: str
    source_event_type: str
    rule_id: str
    memory_kind: str
    visibility: str
    content: str
    tick: int
    location_ref: str | None


@dataclass(frozen=True)
class PlayerKnowledgeEntry:
    subject_ref: str
    fact_type: str
    fact_key: str
    fact_value: Any
    source_game_event_id: str
    derivation_key: str


# CONTENT_COGNITION_* codes below are internal diagnostics, not members of the
# frozen phase-4 specification's §10 error-code list.
_ALLOWED_PLACEHOLDERS = frozenset({"actor", "target", "item", "location"})
_ALLOWED_MEMORY_KINDS = frozenset({"action", "observation"})
_ALLOWED_VISIBILITIES = frozenset({"npc_private", "npc_shared"})


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _state_map(state_at_event: Any, name: str) -> Mapping[str, Any]:
    value = _value(state_at_event, name)
    if isinstance(value, Mapping):
        return value
    # ``resolve_observers`` also accepts a position-only mapping as its snapshot.
    if name == "npc_positions" and isinstance(state_at_event, Mapping):
        return state_at_event
    return {}


def _is_alive(npc_ref: str, positions: Mapping[str, Any], alive: Mapping[str, Any]) -> bool:
    if npc_ref in alive:
        return alive[npc_ref] is True
    # Position snapshots without an aliveness map mean the listed NPCs were alive.
    return npc_ref in positions


def resolve_observers(
    *,
    event_type: str,
    event_location: str | None,
    actor_ref: str | None,
    knowledge_rules: Sequence[Mapping[str, Any]],
    state_at_event: Any,
) -> tuple[str, ...]:
    """Resolve the union of configured observers from an event-time snapshot."""
    positions = _state_map(state_at_event, "npc_positions")
    alive = _state_map(state_at_event, "npc_alive")
    known_npcs = set(positions) | set(alive)
    observers: set[str] = set()

    for rule in knowledge_rules:
        source_types = rule.get("source_event_types", ())
        if event_type not in source_types:
            continue
        scope = rule.get("observers")
        if scope == "actor":
            if (
                isinstance(actor_ref, str)
                and actor_ref
                and actor_ref not in {"player", "world"}
                and (not known_npcs or actor_ref in known_npcs)
            ):
                # Actor scope is identity-based; position does not gate the actor.
                observers.add(actor_ref)
        elif scope == "at_location":
            if event_location is None:
                continue
            observers.update(
                npc_ref
                for npc_ref, location_ref in positions.items()
                if location_ref == event_location and _is_alive(npc_ref, positions, alive)
            )
        elif scope == "all_alive":
            candidates = set(alive) if alive else set(positions)
            observers.update(
                npc_ref
                for npc_ref in candidates
                if _is_alive(npc_ref, positions, alive)
            )
        else:
            raise ContentCognitionError(
                "CONTENT_COGNITION_UNKNOWN_OBSERVER_SCOPE",
                f"knowledge rule {rule.get('id')!r} has unsupported observers {scope!r}",
            )

    return tuple(sorted(observers))


def _event_payload(event: Any) -> dict[str, Any]:
    for name in ("public_payload", "private_payload"):
        payload = _value(event, name)
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _event_actor(event: Any, payload: Mapping[str, Any]) -> str | None:
    actor = payload.get("npc_id") or payload.get("actor") or _value(event, "actor_code")
    return actor if isinstance(actor, str) and actor else None


def _event_location(
    event_type: str,
    payload: Mapping[str, Any],
    actor_ref: str | None,
    positions_at_tick: Mapping[str, str],
) -> str | None:
    # These event locations are frozen in §7.5: routes and travel starts use the
    # event's `from`, arrivals use `to`; other location events use their payload
    # or the event-time actor position.
    if event_type in {"route_changed", "npc_travel_started", "npc_travel_failed"}:
        value = payload.get("from")
    elif event_type == "npc_arrived":
        value = payload.get("to")
    elif event_type in {"npc_wait_started", "npc_wait_completed"}:
        value = payload.get("location")
    else:
        value = payload.get("location")
        if value is None and actor_ref is not None:
            value = positions_at_tick.get(actor_ref)
    return value if isinstance(value, str) and value else None


def _render_template(template: Any, values: Mapping[str, str], rule_id: str) -> str:
    if not isinstance(template, str):
        raise ContentCognitionError(
            "CONTENT_COGNITION_INVALID_TEMPLATE",
            f"knowledge rule {rule_id!r} has a non-string template",
        )
    try:
        parsed = tuple(Formatter().parse(template))
    except ValueError as exc:
        raise ContentCognitionError(
            "CONTENT_COGNITION_INVALID_TEMPLATE",
            f"knowledge rule {rule_id!r} has malformed template braces: {exc}",
        ) from exc

    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if (
            field_name not in _ALLOWED_PLACEHOLDERS
            or format_spec
            or conversion is not None
        ):
            raise ContentCognitionError(
                "CONTENT_COGNITION_UNKNOWN_PLACEHOLDER",
                f"knowledge rule {rule_id!r} uses unsupported placeholder {field_name!r}",
            )
    try:
        return template.format_map(dict(values))
    except (KeyError, ValueError, IndexError) as exc:
        raise ContentCognitionError(
            "CONTENT_COGNITION_INVALID_TEMPLATE",
            f"knowledge rule {rule_id!r} could not be rendered: {exc}",
        ) from exc


def _event_ids_for_plan(event_seq: Any, event_ids: Mapping[int, str]) -> str:
    event_id = event_ids.get(event_seq)
    if not isinstance(event_id, str) or not event_id:
        raise ContentCognitionError(
            "CONTENT_COGNITION_EVENT_ID_MISSING",
            f"no preallocated/persisted GameEvent id for engine event seq {event_seq!r}",
        )
    return event_id


def _derivation_key(version_id: str, source_event_id: str, subject_ref: str, rule_id: str) -> str:
    return f"{version_id}:{source_event_id}:{subject_ref}:{rule_id}"


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(child) for child in value]
    return value


def build_cognition_plan(
    *,
    advance_result: Any,
    knowledge_rules: Sequence[Mapping[str, Any]],
    binding_hash: str,
    version_id: str,
    tick_positions: Mapping[int, Mapping[str, str]],
    event_ids: Mapping[int, str],
) -> tuple[tuple[CognitionEntry, ...], tuple[PlayerKnowledgeEntry, ...]]:
    """Build standard NPC memories and player facts from decided engine events.

    CognitionSpec.event_seq is the explicit causal link back to the SimulationEvent
    sequence. We validate that link and its step/tick, then resolve observers from
    `tick_positions`; a missing durable/preallocated GameEvent ID is an error, not
    an invitation to generate a substitute ID.
    """
    if not isinstance(version_id, str) or not version_id:
        raise ContentCognitionError("CONTENT_COGNITION_VERSION_MISSING", "version_id is required")
    if not isinstance(binding_hash, str) or not binding_hash:
        raise ContentCognitionError("CONTENT_COGNITION_BINDING_MISSING", "binding_hash is required")

    events = tuple(_value(advance_result, "events", ()) or ())
    event_by_seq: dict[int, Any] = {}
    for event in events:
        seq = _value(event, "seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0 or seq in event_by_seq:
            raise ContentCognitionError(
                "CONTENT_COGNITION_EVENT_SEQUENCE_INVALID",
                f"invalid or duplicate SimulationEvent sequence {seq!r}",
            )
        event_by_seq[seq] = event

    # Consume and validate the advancer's explicit cognition-to-event causal map.
    cognition_by_event_seq: dict[int, list[Any]] = {}
    for spec in tuple(_value(advance_result, "cognition", ()) or ()):
        event_seq = _value(spec, "event_seq")
        event = event_by_seq.get(event_seq)
        if event is None:
            raise ContentCognitionError(
                "CONTENT_COGNITION_CAUSAL_EVENT_MISSING",
                f"CognitionSpec refers to missing event seq {event_seq!r}",
            )
        if (
            _value(spec, "source_step_code") != _value(event, "step_code")
            or _value(spec, "tick") != _value(event, "tick")
        ):
            raise ContentCognitionError(
                "CONTENT_COGNITION_CAUSAL_EVENT_MISMATCH",
                f"CognitionSpec does not match event seq {event_seq!r} step/tick",
            )
        cognition_by_event_seq.setdefault(event_seq, []).append(spec)

    npc_entries: list[CognitionEntry] = []
    player_entries: list[PlayerKnowledgeEntry] = []
    final_state = _value(advance_result, "final_state")
    final_alive = _state_map(final_state, "npc_alive")

    for event in events:
        event_seq = _value(event, "seq")
        event_type = _value(event, "event_type")
        tick = _value(event, "tick")
        step_code = _value(event, "step_code")
        if not isinstance(event_type, str) or not event_type:
            raise ContentCognitionError(
                "CONTENT_COGNITION_EVENT_TYPE_INVALID",
                f"event seq {event_seq!r} has no event_type",
            )
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
            raise ContentCognitionError(
                "CONTENT_COGNITION_EVENT_TICK_INVALID",
                f"event seq {event_seq!r} has invalid tick {tick!r}",
            )

        payload = _event_payload(event)
        actor_ref = _event_actor(event, payload)
        raw_snapshot = tick_positions.get(tick)
        snapshot_alive: Optional[Mapping[str, Any]] = None
        if isinstance(raw_snapshot, Mapping):
            # The turn service stores an event-time snapshot containing both maps.
            # Keep compatibility with direct callers/tests that supply just the
            # original {npc_code: location_code} map for each tick.
            snapshot_positions = raw_snapshot.get("npc_positions")
            if isinstance(snapshot_positions, Mapping):
                positions_at_tick: Mapping[str, str] = snapshot_positions
                raw_alive = raw_snapshot.get("npc_alive")
                if isinstance(raw_alive, Mapping):
                    snapshot_alive = raw_alive
            else:
                positions_at_tick = raw_snapshot
        else:
            positions_at_tick = {}
        location_ref = _event_location(event_type, payload, actor_ref, positions_at_tick)
        event_cognition = cognition_by_event_seq.get(event_seq, ())
        # Keep the validated causal specs associated with their event. The rule
        # plan below is authored from frozen config and event-time positions rather
        # than trusting any end-of-advance observer list or draft text.
        _ = event_cognition

        matching_rules = [
            rule for rule in knowledge_rules
            if event_type in rule.get("source_event_types", ())
        ]
        for rule in matching_rules:
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id:
                raise ContentCognitionError(
                    "CONTENT_COGNITION_RULE_ID_INVALID",
                    f"event type {event_type!r} matched a rule without a valid id",
                )
            memory_kind = rule.get("memory_kind")
            visibility = rule.get("visibility")
            if memory_kind not in _ALLOWED_MEMORY_KINDS:
                raise ContentCognitionError(
                    "CONTENT_COGNITION_MEMORY_KIND_INVALID",
                    f"knowledge rule {rule_id!r} has unsupported memory_kind {memory_kind!r}",
                )
            if visibility not in _ALLOWED_VISIBILITIES:
                raise ContentCognitionError(
                    "CONTENT_COGNITION_VISIBILITY_INVALID",
                    f"knowledge rule {rule_id!r} has unsupported visibility {visibility!r}",
                )
            scope = rule.get("observers")
            if scope == "at_location" and tick not in tick_positions:
                raise ContentCognitionError(
                    "CONTENT_COGNITION_EVENT_SNAPSHOT_MISSING",
                    f"event-time NPC positions are missing for tick {tick}",
                )
            if scope == "at_location" and location_ref is None:
                raise ContentCognitionError(
                    "CONTENT_COGNITION_EVENT_LOCATION_MISSING",
                    f"event {event_type!r} has no event-time location",
                )

            values = {
                "actor": actor_ref or "",
                "target": str(payload.get("target", payload.get("to", ""))),
                "item": str(payload.get("item", "")),
                "location": location_ref or "",
            }
            rendered = _render_template(rule.get("template", ""), values, rule_id)
            # Content-v1's supported effects do not change NPC aliveness. Where a
            # future event snapshot supplies its own aliveness map, prefer it; for
            # the current vocabulary final_state's unchanged map is equivalent.
            tick_alive = _value(advance_result, "tick_alive", {})
            if isinstance(tick_alive, Mapping) and isinstance(tick_alive.get(tick), Mapping):
                alive_at_tick = tick_alive[tick]
            elif snapshot_alive is not None:
                alive_at_tick = snapshot_alive
            else:
                alive_at_tick = final_alive
            state_at_event = {
                "npc_positions": positions_at_tick,
                "npc_alive": alive_at_tick,
            }
            observers = resolve_observers(
                event_type=event_type,
                event_location=location_ref,
                actor_ref=actor_ref,
                knowledge_rules=(rule,),
                state_at_event=state_at_event,
            )
            if not observers:
                continue
            source_event_id = _event_ids_for_plan(event_seq, event_ids)
            for subject_ref in observers:
                npc_entries.append(
                    CognitionEntry(
                        subject_type="npc",
                        subject_ref=subject_ref,
                        source_event_id=source_event_id,
                        source_event_type=event_type,
                        rule_id=rule_id,
                        memory_kind=memory_kind,
                        visibility=visibility,
                        content=rendered,
                        tick=tick,
                        location_ref=location_ref,
                    )
                )

        if _value(event, "visibility_scope") == "player_visible":
            source_event_id = _event_ids_for_plan(event_seq, event_ids)
            fact_value = {
                "event_type": event_type,
                "tick": tick,
                "actor": actor_ref,
                "payload": _plain_json(_value(event, "public_payload")),
            }
            player_entries.append(
                PlayerKnowledgeEntry(
                    subject_ref="player",
                    fact_type="player_knowledge",
                    fact_key=f"event:{event_type}:{event_seq}",
                    fact_value=fact_value,
                    source_game_event_id=source_event_id,
                    derivation_key=_derivation_key(
                        version_id, source_event_id, "player", "player_knowledge"
                    ),
                )
            )

    return tuple(npc_entries), tuple(player_entries)


def _require_bound_content_session(
    db: DBSession, *, session_id: str, version_id: str, binding_hash: str
) -> tuple[SessionModel, WorldModel]:
    session = db.query(SessionModel).filter(SessionModel.id == session_id).one_or_none()
    if session is None:
        raise ContentCognitionError(
            "CONTENT_COGNITION_SESSION_MISSING", f"session {session_id!r} does not exist"
        )
    version = db.query(StoryPackageVersionModel).filter(
        StoryPackageVersionModel.id == version_id
    ).one_or_none()
    world = db.query(WorldModel).filter(WorldModel.id == session.world_id).one_or_none()
    if version is None or world is None:
        raise ContentCognitionError(
            "CONTENT_COGNITION_BINDING_MISMATCH",
            f"session {session_id!r} is missing its bound content version or world",
        )
    profile = world.ruleset_json if isinstance(world.ruleset_json, Mapping) else {}
    content_profile = profile.get("content_profile")
    if (
        session.story_package_version_id != version_id
        or version.world_id != session.world_id
        or world.story_package_version_id != version_id
        or version.runtime_hash != binding_hash
        or not isinstance(content_profile, Mapping)
        or content_profile.get("id") != "content_v1"
        or content_profile.get("runtime_hash") != binding_hash
    ):
        raise ContentCognitionError(
            "CONTENT_COGNITION_BINDING_MISMATCH",
            f"session {session_id!r} does not match version/hash {version_id!r}/{binding_hash!r}",
        )
    return session, world


def _source_events(
    db: DBSession, *, session_id: str, source_event_ids: set[str]
) -> dict[str, GameEventModel]:
    if not source_event_ids:
        return {}
    rows = db.query(GameEventModel).filter(
        GameEventModel.session_id == session_id,
        GameEventModel.id.in_(source_event_ids),
    ).all()
    by_id = {row.id: row for row in rows}
    missing = sorted(source_event_ids - set(by_id))
    if missing:
        raise ContentCognitionError(
            "CONTENT_COGNITION_SOURCE_EVENT_NOT_PERSISTED",
            "source GameEvent rows must be flushed in the same unit of work before cognition; "
            f"missing/foreign ids: {missing}",
        )
    return by_id


def _fact_value_text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(_plain_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ContentCognitionError(
            "CONTENT_COGNITION_FACT_VALUE_INVALID",
            f"player knowledge fact_value is not JSON serializable: {exc}",
        ) from exc


def write_content_cognition(
    db: Any,
    *,
    session_id: str,
    version_id: str,
    binding_hash: str,
    entries: Sequence[CognitionEntry],
    player_entries: Sequence[PlayerKnowledgeEntry] = (),
) -> int:
    """Write event-derived memories/facts in the caller's transaction.

    GameEvent ids are resolved by ``build_cognition_plan`` from the advancer's
    event ``seq`` through the caller's preallocated ``plan_engine_event_ids`` map.
    The writer refuses an id whose GameEvent row has not yet been flushed; it
    never creates a substitute source event or commits the caller's transaction.
    """
    session, world = _require_bound_content_session(
        db, session_id=session_id, version_id=version_id, binding_hash=binding_hash
    )
    entry_list = tuple(entries)
    player_list = tuple(player_entries)
    written = 0
    seen_npc_keys: set[str] = set()
    seen_player_keys: set[str] = set()
    pending_npc_entries: list[tuple[CognitionEntry, str]] = []
    pending_player_entries: list[tuple[PlayerKnowledgeEntry, str]] = []

    # Check derivation identities before source-row lookup or staging writes.
    for entry in entry_list:
        if entry.subject_type != "npc":
            raise ContentCognitionError(
                "CONTENT_COGNITION_SUBJECT_TYPE_INVALID",
                f"content cognition subject_type must be 'npc', got {entry.subject_type!r}",
            )
        if entry.memory_kind not in _ALLOWED_MEMORY_KINDS or entry.visibility not in _ALLOWED_VISIBILITIES:
            raise ContentCognitionError(
                "CONTENT_COGNITION_ENTRY_INVALID",
                f"invalid memory kind/visibility for rule {entry.rule_id!r}",
            )
        derivation_key = _derivation_key(
            version_id, entry.source_event_id, entry.subject_ref, entry.rule_id
        )
        if derivation_key in seen_npc_keys:
            continue
        seen_npc_keys.add(derivation_key)
        existing = db.query(NPCPrivateMemoryModel.id).filter(
            NPCPrivateMemoryModel.session_id == session_id,
            NPCPrivateMemoryModel.derivation_key == derivation_key,
        ).first()
        if existing is None:
            pending_npc_entries.append((entry, derivation_key))

    for entry in player_list:
        if entry.subject_ref != "player" or entry.fact_type != "player_knowledge":
            raise ContentCognitionError(
                "CONTENT_COGNITION_PLAYER_FACT_INVALID",
                "player entries must use subject_ref='player' and fact_type='player_knowledge'",
            )
        expected_key = _derivation_key(
            version_id, entry.source_game_event_id, "player", "player_knowledge"
        )
        if entry.derivation_key != expected_key:
            raise ContentCognitionError(
                "CONTENT_COGNITION_DERIVATION_KEY_INVALID",
                f"player fact derivation key does not match {expected_key!r}",
            )
        if entry.derivation_key in seen_player_keys:
            continue
        seen_player_keys.add(entry.derivation_key)
        existing = db.query(MemoryFactModel.id).filter(
            MemoryFactModel.session_id == session_id,
            MemoryFactModel.subject_ref == "player",
            MemoryFactModel.derivation_key == entry.derivation_key,
        ).first()
        if existing is None:
            pending_player_entries.append((entry, expected_key))

    source_ids = {entry.source_event_id for entry, _ in pending_npc_entries}
    source_ids.update(entry.source_game_event_id for entry, _ in pending_player_entries)
    source_events = _source_events(db, session_id=session_id, source_event_ids=source_ids)

    for entry, derivation_key in pending_npc_entries:
        template_rows = db.query(NPCTemplateModel).filter(
            NPCTemplateModel.world_id == world.id,
            NPCTemplateModel.code == entry.subject_ref,
        ).all()
        if len(template_rows) != 1:
            raise ContentCognitionError(
                "CONTENT_COGNITION_NPC_TEMPLATE_MISSING",
                f"stable character id {entry.subject_ref!r} resolves to {len(template_rows)} templates",
            )
        template = template_rows[0]
        npc_state = db.query(SessionNPCStateModel).filter(
            SessionNPCStateModel.session_id == session_id,
            SessionNPCStateModel.npc_template_id == template.id,
        ).one_or_none()
        if npc_state is None:
            raise ContentCognitionError(
                "CONTENT_COGNITION_NPC_STATE_MISSING",
                f"NPC {entry.subject_ref!r} has no state in session {session_id!r}",
            )

        event = source_events[entry.source_event_id]
        if event.event_type != entry.source_event_type:
            raise ContentCognitionError(
                "CONTENT_COGNITION_SOURCE_EVENT_MISMATCH",
                f"entry event type {entry.source_event_type!r} differs from GameEvent {event.id!r} "
                f"type {event.event_type!r}",
            )
        location_id: Optional[str] = None
        if entry.location_ref is not None:
            location_rows = db.query(LocationModel.id).filter(
                LocationModel.world_id == world.id,
                LocationModel.code == entry.location_ref,
            ).all()
            if len(location_rows) != 1:
                raise ContentCognitionError(
                    "CONTENT_COGNITION_LOCATION_MISSING",
                    f"event location {entry.location_ref!r} resolves to {len(location_rows)} locations",
                )
            location_id = location_rows[0][0]

        db.add(
            NPCPrivateMemoryModel(
                id=generate_uuid(),
                session_id=session_id,
                npc_id=npc_state.id,
                npc_template_id=template.id,
                memory_type="episodic",
                memory_kind=entry.memory_kind,
                visibility=entry.visibility,
                content=entry.content,
                memory_text=entry.content,
                source_event_ids_json=[entry.source_event_id],
                derivation_key=derivation_key,
                source_turn_no=event.turn_no,
                source_id=entry.source_event_id,
                source_ref=derivation_key,
                knowledge_source="engine",
                location_id=location_id,
                importance=0.5,
                confidence=1.0,
                current_strength=1.0,
                created_turn=event.turn_no,
                last_accessed_turn=event.turn_no,
                recall_count=0,
                status="active",
            )
        )
        written += 1

    for entry, _unused_derivation_key in pending_player_entries:
        event = source_events[entry.source_game_event_id]
        db.add(
            MemoryFactModel(
                id=generate_uuid(),
                session_id=session_id,
                fact_type="player_knowledge",
                subject_ref="player",
                fact_key=entry.fact_key,
                fact_value=_fact_value_text(entry.fact_value),
                source_game_event_id=entry.source_game_event_id,
                derivation_key=entry.derivation_key,
                source_event_id=None,
            )
        )
        written += 1

    # Necessary cognition participates in the caller's UoW; no commit here.
    db.flush()
    return written

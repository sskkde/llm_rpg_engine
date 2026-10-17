"""Phase-3 persistence adapter: read, validate, plan-init, apply and project.

The adapter is the only place that knows how the phase-3 slice maps onto the
existing tables. It owns:

* the strict *read* of the slice's run state (cursor, NPC positions/plans, the
  unique token's owner, the pending steps) including the deferred baseline
  overlay of the first turn,
* the *baseline plan* for a fresh slice session (initial state, inventory row,
  scheduled steps) which ``core.session_initialization`` defers into the final
  transaction,
* the *apply* of one :class:`~llm_rpg.core.time_simulation.AdvanceResult` inside
  the turn's single authoritative transaction,
* the *public projection* of the adjudicated time summary.

Invariants this module enforces (plan sections 4.2, 5.3, 7.1, 7.2)
------------------------------------------------------------------
* Codes and storage ids are mapped explicitly, and every row is checked for
  world/session ownership before it is trusted.
* A session with business state but no run marker is refused, never "repaired".
* A pending scheduled row that is not part of the current profile's closed step
  vocabulary is refused, never silently dropped.
* The unique token is one inventory row whose owner is *updated*; the row is
  never deleted, recreated or duplicated for a loser.
* Every write happens through the caller's managed unit of work, so a failure
  rolls the whole turn back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..storage.models import (
    GameEventModel,
    LocationModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    ScheduledEventModel,
    StateDeltaModel,
    generate_uuid,
)
from ..storage.repositories import (
    EventLogRepository,
    GameEventRepository,
    LocationRepository,
    SessionInventoryItemRepository,
    SessionNPCStateRepository,
    SessionRepository,
    SessionStateRepository,
    StateDeltaRepository,
    WorldRepository,
)
from .time_simulation import (
    ACTION_INTERRUPTED,
    PHASE3_NAMESPACE,
    PlanStatus,
    PlayerActionKind,
    PlayerActionSpec,
    PlayerActionStatus,
    Phase3Profile,
    SimulationDelta,
    SimulationEvent,
    SimulationRunState,
    StepKind,
    StepStatus,
    TimeSimulationProfileError,
    TimeSimulationStateError,
    WorkingState,
    decode_npc_plan,
    decode_step_conditions,
    decode_run_state,
    encode_npc_plan,
    encode_run_state,
    encode_step_conditions,
    is_phase3_conditions,
    merge_run_state,
    read_run_state,
    resolve_phase3_profile,
)
from .time_simulation_rules import (
    ITEM_SPEC,
    LOCATION_SPECS,
    NPC_ALIVE_FLAG_KEY,
    NPC_SPECS,
    ROUTE_EDGES,
    ROUTE_OPEN_RULE_KEY,
    START_HOUR,
    START_MINUTE,
    TrialRules,
    get_trial_rules,
)

#: Every phase-3 delta path is namespaced so it can never be confused with a
#: canonical ``CanonicalState`` path by an existing reader.
DELTA_PATH_PREFIX = "phase3"

#: ``scheduled_events.status`` values used for a consumed step.
_SCHEDULED_TERMINAL_STATUS: Dict[str, str] = {
    StepStatus.APPLIED: "triggered",
    StepStatus.BLOCKED: "cancelled",
    StepStatus.CANCELLED: "cancelled",
}

#: ``result_json["action_type"]`` value that marks a zero-time clarification turn.
_CLARIFICATION_ACTION_TYPE = "clarification"


# ---------------------------------------------------------------------------
# Context DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingStepRow:
    """One durable pending step: its row id plus the decoded step."""

    row_id: str
    step: Any  # ScheduledStep (kept loose to avoid an import cycle in typing)


@dataclass
class SimulationContext:
    """Everything the turn path needs to advance one slice session."""

    profile: Phase3Profile
    session_id: str
    world_id: str
    rules: TrialRules
    run_state: SimulationRunState
    state: WorkingState
    is_fresh: bool
    pending_steps: List[PendingStepRow] = field(default_factory=list)
    consumed_step_keys: FrozenSet[str] = frozenset()
    location_ids: Dict[str, str] = field(default_factory=dict)
    location_codes_by_id: Dict[str, str] = field(default_factory=dict)
    npc_state_ids: Dict[str, str] = field(default_factory=dict)
    npc_template_ids: Dict[str, str] = field(default_factory=dict)
    item_template_id: str = ""
    inventory_row_id: Optional[str] = None
    session_state_row_id: Optional[str] = None
    #: True when the baseline rows only exist in the deferred init plan.
    baseline_planned: bool = False

    @property
    def start_tick(self) -> int:
        return self.run_state.logical_tick

    def location_id_for(self, code: str) -> str:
        try:
            return self.location_ids[code]
        except KeyError as exc:  # pragma: no cover - defensive
            raise TimeSimulationStateError(f"unknown phase-3 location code: {code!r}") from exc

    def location_code_for(self, location_id: Optional[str]) -> Optional[str]:
        if location_id is None:
            return None
        return self.location_codes_by_id.get(location_id)


@dataclass
class Phase3BaselinePlan:
    """Baseline rows the first slice turn must create inside its final commit."""

    session_state: Optional[Dict[str, Any]] = None
    npc_states: List[Dict[str, Any]] = field(default_factory=list)
    inventory_items: List[Dict[str, Any]] = field(default_factory=list)
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SimulationWriteResult:
    """What the apply step wrote, for the caller's result projection."""

    global_flags_json: Dict[str, Any]
    session_location_id: Optional[str]
    player_location_code: str
    event_ids: List[str] = field(default_factory=list)
    delta_ids: List[str] = field(default_factory=list)
    cognition_rows: int = 0
    step_rows_updated: int = 0
    step_rows_created: int = 0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now()


def format_start_display_time() -> str:
    """The slice's fixed starting display time (08:00 on day 1 of spring)."""
    return f"修仙历 春 第1日 辰时 {START_HOUR:02d}:{START_MINUTE:02d}"


def resolve_simulation_profile(db: Session, session: SessionModel) -> Optional[Phase3Profile]:
    """Resolve the session world's phase-3 profile (``None`` means legacy path)."""
    world = WorldRepository(db).get_by_id(session.world_id)
    if world is None:
        raise TimeSimulationStateError(
            f"world not found for session {session.id}: world_id={session.world_id}"
        )
    return resolve_phase3_profile(world)


def session_is_fresh(db: Session, session_id: str) -> bool:
    """True when the session has no business state yet.

    A session that only holds zero-time clarification turns is still fresh: the
    clarification path writes a single ``player_turn`` row and deliberately no
    state, so initializing the slice afterwards is not a guess.

    Every *business* row group is checked, not just ``session_states``: orphan NPC
    rows, an inventory row, scheduled steps or engine facts with no run marker mean
    the session already ran, and inventing a tick-0 cursor for it would replay
    consumed world time. Such a session is refused by the read adapter instead.
    """
    if SessionStateRepository(db).get_by_session(session_id) is not None:
        return False
    if SessionNPCStateRepository(db).get_by_session(session_id):
        return False
    if SessionInventoryItemRepository(db).get_by_session(session_id):
        return False
    if _scheduled_rows(db, session_id):
        return False
    if (
        db.query(GameEventModel.id)
        .filter(GameEventModel.session_id == session_id)
        .first()
        is not None
    ):
        return False
    for event in EventLogRepository(db).get_by_session_ordered(session_id):
        result = event.result_json if isinstance(event.result_json, dict) else {}
        if result.get("action_type") != _CLARIFICATION_ACTION_TYPE:
            return False
    return True


def _require_owned_location(
    location: Optional[LocationModel],
    *,
    world_id: str,
    code: str,
) -> LocationModel:
    if location is None:
        raise TimeSimulationStateError(f"phase-3 location {code!r} is missing")
    if location.world_id != world_id:
        raise TimeSimulationStateError(
            f"phase-3 location {code!r} belongs to another world"
        )
    return location


def _route_open(location: LocationModel, code: str) -> bool:
    rules = location.access_rules if isinstance(location.access_rules, dict) else {}
    value = rules.get(ROUTE_OPEN_RULE_KEY, True)
    if not isinstance(value, bool):
        raise TimeSimulationStateError(
            f"location {code!r} has a non-boolean {ROUTE_OPEN_RULE_KEY}: {value!r}"
        )
    return value


def _status_flags(row: Any) -> Dict[str, Any]:
    flags = getattr(row, "status_flags", None)
    return flags if isinstance(flags, dict) else {}


def _npc_is_alive(row: Any) -> bool:
    flags = _status_flags(row)
    value = flags.get(NPC_ALIVE_FLAG_KEY, True)
    if not isinstance(value, bool):
        raise TimeSimulationStateError(
            f"NPC aliveness flag {NPC_ALIVE_FLAG_KEY} is not a boolean: {value!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Baseline plan (first turn, deferred into the final transaction)
# ---------------------------------------------------------------------------


def plan_phase3_baseline(
    db: Session,
    session_id: str,
    world_id: str,
    *,
    rules: Optional[TrialRules] = None,
) -> Optional[Phase3BaselinePlan]:
    """Plan the slice's missing baseline rows; ``None`` for a legacy world.

    Only *missing* rows are planned. An existing row is left exactly as it is, so
    re-running a turn never resets an evolved position, plan or owner.
    """
    session = SessionRepository(db).get_by_id(session_id)
    if session is None:
        raise TimeSimulationStateError(f"session not found: {session_id}")
    world = WorldRepository(db).get_by_id(world_id)
    profile = resolve_phase3_profile(world) if world is not None else None
    if profile is None:
        return None

    rules = rules or get_trial_rules()
    location_repo = LocationRepository(db)
    plan = Phase3BaselinePlan()

    # Baseline rows are only legitimate for a session that has no business state
    # yet (a session that only holds zero-time clarification turns still counts).
    # For a session that already ran, every baseline row must exist: a missing one
    # is refused by the read adapter below, never silently re-issued here -- the
    # slice must not "补发" a lost unique item or replay a consumed step.
    if not session_is_fresh(db, session_id):
        return plan

    locations: Dict[str, LocationModel] = {}
    for spec in LOCATION_SPECS:
        location = location_repo.get_by_code(world_id, spec.code)
        locations[spec.code] = _require_owned_location(
            location, world_id=world_id, code=spec.code
        )

    player_start = locations[rules.initial_state().player_location_code]

    if SessionStateRepository(db).get_by_session(session_id) is None:
        plan.session_state = {
            "id": generate_uuid(),
            "session_id": session_id,
            "current_time": format_start_display_time(),
            "time_phase": "辰时",
            "current_location_id": player_start.id,
            "active_mode": "exploration",
            "global_flags_json": merge_run_state(
                {}, SimulationRunState(logical_tick=0, next_event_seq=0)
            ),
        }

    npc_repo = SessionNPCStateRepository(db)
    for spec in NPC_SPECS:
        template = _npc_template_for(db, world_id, spec.code)
        if npc_repo.get_by_session_and_npc(session_id, template.id) is not None:
            continue
        plan.npc_states.append(
            {
                "id": generate_uuid(),
                "session_id": session_id,
                "npc_template_id": template.id,
                "current_location_id": locations[spec.initial_location_code].id,
                "trust_score": 50,
                "suspicion_score": 0,
                "status_flags": {NPC_ALIVE_FLAG_KEY: True},
                "short_memory_summary": None,
                "hidden_plan_state": None,
            }
        )

    item_template = _item_template_for(db, world_id, ITEM_SPEC.code)
    if _token_rows(db, session_id, item_template.id) == []:
        plan.inventory_items.append(
            {
                "id": generate_uuid(),
                "session_id": session_id,
                "item_template_id": item_template.id,
                "owner_type": ITEM_SPEC.initial_owner_type,
                "owner_ref_id": locations[ITEM_SPEC.initial_owner_ref].id,
                "quantity": 1,
                "durability": None,
                "bound_flag": False,
            }
        )

    existing_keys = _existing_step_keys(db, session_id)
    for step in rules.initial_steps():
        if step.step_key in existing_keys:
            continue
        plan.scheduled_events.append(
            {
                "id": generate_uuid(),
                "session_id": session_id,
                "event_template_id": None,
                "trigger_time": None,
                "trigger_conditions_json": encode_step_conditions(step),
                "status": "pending",
            }
        )

    return plan


def _npc_template_for(db: Session, world_id: str, code: str) -> Any:
    from ..storage.repositories import NPCTemplateRepository

    template = NPCTemplateRepository(db).get_by_code(world_id, code)
    if template is None:
        raise TimeSimulationStateError(f"phase-3 NPC template {code!r} is missing")
    return template


def _item_template_for(db: Session, world_id: str, code: str) -> Any:
    from ..storage.repositories import ItemTemplateRepository

    for template in ItemTemplateRepository(db).get_by_world(world_id):
        if template.code == code:
            return template
    raise TimeSimulationStateError(f"phase-3 item template {code!r} is missing")


def _token_rows(db: Session, session_id: str, item_template_id: str) -> List[Any]:
    return [
        row
        for row in SessionInventoryItemRepository(db).get_by_session(session_id)
        if row.item_template_id == item_template_id
    ]


def _existing_step_keys(db: Session, session_id: str) -> FrozenSet[str]:
    keys = set()
    for row in _scheduled_rows(db, session_id):
        conditions = row.trigger_conditions_json
        if not is_phase3_conditions(conditions):
            continue
        keys.add(decode_step_conditions(conditions).step_key)
    return frozenset(keys)


def _scheduled_rows(db: Session, session_id: str) -> List[ScheduledEventModel]:
    return (
        db.query(ScheduledEventModel)
        .filter(ScheduledEventModel.session_id == session_id)
        .all()
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def load_simulation_context(
    db: Session,
    session_id: str,
    *,
    plan: Optional[Any] = None,
    rules: Optional[TrialRules] = None,
) -> SimulationContext:
    """Strictly read the slice's authoritative state for one turn.

    ``plan`` is the turn's deferred baseline plan (``SessionStoryStatePlan``). Its
    rows are used **only** where the durable row is absent, so a first turn sees
    the same state a later turn would read back.
    """
    session = SessionRepository(db).get_by_id(session_id)
    if session is None:
        raise TimeSimulationStateError(f"session not found: {session_id}")
    world = WorldRepository(db).get_by_id(session.world_id)
    if world is None:
        raise TimeSimulationStateError(f"world not found for session {session_id}")
    profile = resolve_phase3_profile(world)
    if profile is None:
        raise TimeSimulationProfileError(
            f"session {session_id} has no phase-3 profile"
        )

    rules = rules or get_trial_rules()
    world_id = session.world_id
    fresh = session_is_fresh(db, session_id)

    # -- locations (code <-> id), validated for ownership ---------------------
    location_repo = LocationRepository(db)
    location_ids: Dict[str, str] = {}
    location_codes_by_id: Dict[str, str] = {}
    location_rows: Dict[str, LocationModel] = {}
    for spec in LOCATION_SPECS:
        row = _require_owned_location(
            location_repo.get_by_code(world_id, spec.code), world_id=world_id, code=spec.code
        )
        location_ids[spec.code] = row.id
        location_codes_by_id[row.id] = spec.code
        location_rows[spec.code] = row

    # -- run state (durable row, else the deferred baseline plan) -------------
    session_state = SessionStateRepository(db).get_by_session(session_id)
    planned_session_state = _planned_session_state(plan, session_id)
    if session_state is not None:
        run_state = read_run_state(session_state.global_flags_json)
        session_state_row_id: Optional[str] = session_state.id
        current_location_id = session_state.current_location_id
        baseline_planned = False
    else:
        if planned_session_state is not None:
            run_state = read_run_state(planned_session_state.global_flags_json)
            current_location_id = planned_session_state.current_location_id
        else:
            run_state = None
            current_location_id = None
        session_state_row_id = None
        baseline_planned = True

    if run_state is None:
        if not fresh:
            raise TimeSimulationStateError(
                f"session {session_id} has business state but no phase-3 run marker; "
                "refusing to guess a cursor"
            )
        run_state = SimulationRunState(logical_tick=0, next_event_seq=0)
    else:
        _validate_event_cursor(db, session_id, run_state)

    player_code = location_codes_by_id.get(current_location_id) if current_location_id else None
    if player_code is None:
        raise TimeSimulationStateError(
            f"session {session_id} is not standing on a phase-3 location: "
            f"{current_location_id!r}"
        )

    # -- NPCs -----------------------------------------------------------------
    npc_state_ids: Dict[str, str] = {}
    npc_template_ids: Dict[str, str] = {}
    npc_positions: Dict[str, str] = {}
    npc_alive: Dict[str, bool] = {}
    npc_plans: Dict[str, Any] = {}
    npc_rows = {row.id: row for row in SessionNPCStateRepository(db).get_by_session(session_id)}
    planned_npc_rows = _planned_npc_rows(plan, session_id)
    for spec in NPC_SPECS:
        template = _npc_template_for(db, world_id, spec.code)
        row = next(
            (r for r in npc_rows.values() if r.npc_template_id == template.id), None
        )
        if row is None:
            row = next(
                (r for r in planned_npc_rows if r.npc_template_id == template.id), None
            )
        if row is None:
            if fresh:
                npc_positions[spec.code] = spec.initial_location_code
                npc_alive[spec.code] = True
                npc_plans[spec.code] = None
                continue
            raise TimeSimulationStateError(
                f"phase-3 NPC state for {spec.code!r} is missing in session {session_id}"
            )
        npc_template_ids[spec.code] = template.id
        npc_state_ids[spec.code] = row.id
        position_code = location_codes_by_id.get(row.current_location_id)
        if position_code is None:
            raise TimeSimulationStateError(
                f"NPC {spec.code!r} stands on a non phase-3 location: "
                f"{row.current_location_id!r}"
            )
        npc_positions[spec.code] = position_code
        npc_alive[spec.code] = _npc_is_alive(row)
        npc_plans[spec.code] = decode_npc_plan(row.hidden_plan_state)

    # -- the unique token -----------------------------------------------------
    item_template = _item_template_for(db, world_id, ITEM_SPEC.code)
    durable_token_rows = _token_rows(db, session_id, item_template.id)
    planned_token_rows = [
        row
        for row in _planned_inventory_rows(plan, session_id)
        if row.item_template_id == item_template.id
    ]
    token_rows = durable_token_rows or planned_token_rows
    if len(token_rows) == 0:
        if not fresh:
            raise TimeSimulationStateError(
                f"session {session_id} is missing the unique token row"
            )
        owner_type = ITEM_SPEC.initial_owner_type
        owner_ref_id: Optional[str] = location_ids[ITEM_SPEC.initial_owner_ref]
        inventory_row_id: Optional[str] = None
        quantity = 1
    elif len(token_rows) > 1:
        raise TimeSimulationStateError(
            f"session {session_id} holds {len(token_rows)} rows for the unique token; "
            "refusing to pick one"
        )
    else:
        row = token_rows[0]
        # A planned row's pre-allocated id *is* the id the deferred baseline insert
        # will use, so the owner update targets the same entity either way.
        inventory_row_id = row.id
        quantity = row.quantity
        owner_type = row.owner_type
        owner_ref_id = row.owner_ref_id

    if quantity != 1:
        raise TimeSimulationStateError(
            f"the unique token invariant is broken: quantity={quantity!r}"
        )

    owner_type, owner_ref_code = _resolve_item_owner(
        owner_type=owner_type,
        owner_ref_id=owner_ref_id,
        session_id=session_id,
        location_codes_by_id=location_codes_by_id,
        npc_state_ids=npc_state_ids,
    )

    # -- pending / consumed steps --------------------------------------------
    pending_steps: List[PendingStepRow] = []
    consumed_keys = set()
    durable_step_rows = _scheduled_rows(db, session_id)
    planned_step_rows = _planned_scheduled_rows(plan, session_id)
    step_rows = list(durable_step_rows)
    if planned_step_rows:
        step_rows.extend(planned_step_rows)
    for row in step_rows:
        conditions = row.trigger_conditions_json
        if not is_phase3_conditions(conditions):
            raise TimeSimulationStateError(
                f"session {session_id} has a scheduled event outside the phase-3 "
                f"namespace: {conditions!r}"
            )
        step = decode_step_conditions(conditions)
        if row.status == "pending":
            pending_steps.append(PendingStepRow(row_id=row.id, step=step))
        else:
            consumed_keys.add(step.step_key)

    state = WorkingState(
        logical_tick=run_state.logical_tick,
        player_location_code=player_code,
        player_alive=True,
        npc_positions=npc_positions,
        npc_alive=npc_alive,
        npc_plans=npc_plans,
        item_code=ITEM_SPEC.code,
        item_quantity=quantity,
        item_owner_type=owner_type,
        item_owner_ref=owner_ref_code,
        routes_open={
            f"{origin}->{destination}": _route_open(
                location_rows[destination], destination
            )
            for first, second in ROUTE_EDGES
            for origin, destination in ((first, second), (second, first))
        },
        one_shot=dict(run_state.one_shot),
    )

    return SimulationContext(
        profile=profile,
        session_id=session_id,
        world_id=world_id,
        rules=rules,
        run_state=run_state,
        state=state,
        is_fresh=fresh,
        pending_steps=pending_steps,
        consumed_step_keys=frozenset(consumed_keys),
        location_ids=location_ids,
        location_codes_by_id=location_codes_by_id,
        npc_state_ids=npc_state_ids,
        npc_template_ids=npc_template_ids,
        item_template_id=item_template.id,
        inventory_row_id=inventory_row_id,
        session_state_row_id=session_state_row_id,
        baseline_planned=baseline_planned,
    )


def _validate_event_cursor(
    db: Session,
    session_id: str,
    run_state: SimulationRunState,
) -> None:
    """The stored event cursor must match the durable engine timeline.

    Every committed advance writes its facts and the advanced cursor in the same
    transaction, and every fact carries the sequence it was given, so the durable
    timeline is exactly ``0..next_event_seq-1`` with no gaps. A cursor that does not
    match means the run state was damaged or restored out of band; continuing would
    hand out sequence numbers that already exist, so the turn is refused instead.
    """
    rows = (
        db.query(GameEventModel.result_json)
        .filter(GameEventModel.session_id == session_id)
        .all()
    )
    highest = -1
    seen = 0
    for (payload,) in rows:
        body = payload.get(PHASE3_NAMESPACE) if isinstance(payload, dict) else None
        if not isinstance(body, dict):
            continue
        sequence = body.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise TimeSimulationStateError(
                f"engine event of session {session_id} has a damaged sequence"
            )
        highest = max(highest, sequence)
        seen += 1
    if seen != run_state.next_event_seq or highest + 1 != run_state.next_event_seq:
        raise TimeSimulationStateError(
            f"phase-3 event cursor is inconsistent with the durable timeline: "
            f"cursor={run_state.next_event_seq}, events={seen}, highest={highest}"
        )


def _resolve_item_owner(
    *,
    owner_type: Optional[str],
    owner_ref_id: Optional[str],
    session_id: str,
    location_codes_by_id: Dict[str, str],
    npc_state_ids: Dict[str, str],
) -> Tuple[Optional[str], Optional[str]]:
    """Map a stored owner onto the slice's stable code, checking membership.

    Every namespace is checked *explicitly* and a reference that does not belong to
    this session is refused: an owner is either one of this session's own NPC state
    rows, one of the slice's locations, or the player. A template id, a foreign
    session's row id or a made-up player reference is damage, not a value to
    normalise -- silently "cleaning" it would hand the unique item to the wrong
    holder.
    """
    if owner_type is None:
        raise TimeSimulationStateError("the unique token has no owner_type")
    if owner_type == "location":
        code = location_codes_by_id.get(owner_ref_id) if owner_ref_id else None
        if code is None:
            raise TimeSimulationStateError(
                f"the unique token is owned by a non phase-3 location: {owner_ref_id!r}"
            )
        return "location", code
    if owner_type == "npc":
        # The stored owner must be this session's NPC state row id -- never a
        # template id and never another session's row.
        for code, state_id in npc_state_ids.items():
            if state_id == owner_ref_id:
                return "npc", code
        raise TimeSimulationStateError(
            f"the unique token is owned by a reference that is not one of this "
            f"session's NPC state rows: {owner_ref_id!r}"
        )
    if owner_type == "player":
        # The legacy player-owned convention is ``owner_type='player'`` with either a
        # NULL reference or the literal ``"player"``. Anything else is damage.
        if owner_ref_id not in (None, "player"):
            raise TimeSimulationStateError(
                f"player-owned item carries a foreign owner_ref_id: {owner_ref_id!r}"
            )
        return "player", "player"
    raise TimeSimulationStateError(f"unsupported token owner_type: {owner_type!r}")


def _planned_session_state(plan: Optional[Any], session_id: str) -> Optional[SessionStateModel]:
    if plan is None or getattr(plan, "session_id", None) != session_id:
        return None
    return plan.session_state_overlay()


def _planned_npc_rows(plan: Optional[Any], session_id: str) -> List[SessionNPCStateModel]:
    if plan is None or getattr(plan, "session_id", None) != session_id:
        return []
    return plan.npc_state_overlays()


def _planned_inventory_rows(plan: Optional[Any], session_id: str) -> List[SessionInventoryItemModel]:
    if plan is None or getattr(plan, "session_id", None) != session_id:
        return []
    return plan.inventory_item_overlays()


def _planned_scheduled_rows(plan: Optional[Any], session_id: str) -> List[ScheduledEventModel]:
    if plan is None or getattr(plan, "session_id", None) != session_id:
        return []
    return plan.scheduled_event_overlays()


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_simulation_advance(
    db: Session,
    ctx: SimulationContext,
    result: Any,
    *,
    transaction_id: str,
    turn_no: int,
    write_events: bool = True,
    write_cognition: bool = False,
    planned_event_ids: Optional[Dict[int, str]] = None,
) -> SimulationWriteResult:
    """Apply one advance inside the caller's managed transaction.

    Called from the turn's final write section, after the lock and the state
    revalidation and before the single authoritative commit. Every write is a
    necessary write: a failure propagates and rolls the whole turn back.
    """
    session_state_repo = SessionStateRepository(db)
    session_state_row = session_state_repo.get_by_session(ctx.session_id)
    if session_state_row is None:
        raise TimeSimulationStateError(
            f"session {ctx.session_id} has no session_states row to advance"
        )
    merged_flags = merge_run_state(
        session_state_row.global_flags_json,
        SimulationRunState(
            logical_tick=result.actual_end_tick,
            next_event_seq=result.next_event_seq,
            one_shot=dict(result.final_state.one_shot),
        ),
    )

    session_state_repo.update(
        session_state_row.id,
        {
            "global_flags_json": merged_flags,
            "current_location_id": ctx.location_ids[result.final_state.player_location_code],
        },
    )

    _apply_npc_writes(db, ctx, result)
    _apply_inventory_writes(db, ctx, result)
    step_rows_updated, step_rows_created = _apply_step_writes(db, ctx, result)

    event_ids: List[str] = []
    delta_ids: List[str] = []
    if write_events:
        event_ids, delta_ids = _write_engine_events(
            db,
            ctx,
            result,
            transaction_id=transaction_id,
            turn_no=turn_no,
            planned_event_ids=planned_event_ids,
        )

    cognition_rows = 0
    if write_cognition:
        cognition_rows = _write_cognition(
            db, ctx, result, transaction_id=transaction_id, turn_no=turn_no
        )

    return SimulationWriteResult(
        global_flags_json=merged_flags,
        session_location_id=ctx.location_ids[result.final_state.player_location_code],
        player_location_code=result.final_state.player_location_code,
        event_ids=event_ids,
        delta_ids=delta_ids,
        cognition_rows=cognition_rows,
        step_rows_updated=step_rows_updated,
        step_rows_created=step_rows_created,
    )


def _apply_npc_writes(db: Session, ctx: SimulationContext, result: Any) -> None:
    repo = SessionNPCStateRepository(db)
    for code, state_id in ctx.npc_state_ids.items():
        plan = result.final_state.npc_plans.get(code)
        update: Dict[str, Any] = {
            "current_location_id": ctx.location_ids[result.final_state.npc_positions[code]],
            "status_flags": {
                NPC_ALIVE_FLAG_KEY: bool(result.final_state.npc_alive.get(code, True))
            },
        }
        if plan is not None:
            update["hidden_plan_state"] = encode_npc_plan(plan)
        else:
            # The column is shared with other subsystems' free text. Only clear it
            # when the stored value is this slice's own (or empty); another
            # subsystem's text is left exactly as it is.
            row = repo.get_by_id(state_id)
            stored = row.hidden_plan_state if row is not None else None
            if stored is None or _is_phase3_plan_text(stored):
                update["hidden_plan_state"] = None
        repo.update(state_id, update)


def _is_phase3_plan_text(value: Any) -> bool:
    """True when the stored plan text is this slice's namespaced JSON."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text.startswith("{"):
        return False
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and PHASE3_NAMESPACE in parsed


def _apply_inventory_writes(db: Session, ctx: SimulationContext, result: Any) -> None:
    if ctx.inventory_row_id is None:
        return
    owner_type = result.final_state.item_owner_type
    owner_ref = result.final_state.item_owner_ref
    if owner_type == "location":
        owner_ref_id = ctx.location_ids[owner_ref]
    elif owner_type == "npc":
        owner_ref_id = ctx.npc_state_ids[owner_ref]
    elif owner_type == "player":
        owner_ref_id = "player"
    else:  # pragma: no cover - the kernel never produces another value
        raise TimeSimulationStateError(f"unsupported token owner_type: {owner_type!r}")
    SessionInventoryItemRepository(db).update(
        ctx.inventory_row_id,
        {"owner_type": owner_type, "owner_ref_id": owner_ref_id, "quantity": 1},
    )


def _apply_step_writes(db: Session, ctx: SimulationContext, result: Any) -> Tuple[int, int]:
    """Mark consumed step rows terminal and insert newly derived pending rows."""
    rows_by_key: Dict[str, ScheduledEventModel] = {}
    for row in _scheduled_rows(db, ctx.session_id):
        conditions = row.trigger_conditions_json
        if not is_phase3_conditions(conditions):
            raise TimeSimulationStateError(
                f"session {ctx.session_id} has a scheduled event outside the "
                "phase-3 namespace"
            )
        rows_by_key[decode_step_conditions(conditions).step_key] = row

    specs_by_key = {spec.step_key: spec for spec in getattr(result, "consumed_step_specs", [])}

    updated = 0
    created = 0
    for outcome in result.consumed_steps:
        terminal = _SCHEDULED_TERMINAL_STATUS.get(outcome.status)
        if terminal is None:  # pragma: no cover - defensive
            raise TimeSimulationStateError(f"unknown step status: {outcome.status!r}")
        row = rows_by_key.get(outcome.step_key)
        if row is not None:
            row.status = terminal
            updated += 1
            continue
        if outcome.kind == StepKind.PLAYER_CONTINUOUS_COMPLETE:
            # The player's completion step is per-turn: it never had a row and must
            # not get one.
            continue
        spec = specs_by_key.get(outcome.step_key)
        if spec is None:
            raise TimeSimulationStateError(
                f"consumed step {outcome.step_key!r} has neither a durable row nor a spec"
            )
        # A step that was derived *and* consumed inside this same advance: record it
        # with its terminal status so the durable timeline has no hole.
        db.add(
            ScheduledEventModel(
                id=generate_uuid(),
                session_id=ctx.session_id,
                event_template_id=None,
                trigger_time=None,
                trigger_conditions_json=encode_step_conditions(spec),
                status=terminal,
            )
        )
        created += 1

    for step in result.pending_steps:
        if step.step_key in rows_by_key:
            continue
        db.add(
            ScheduledEventModel(
                id=generate_uuid(),
                session_id=ctx.session_id,
                event_template_id=None,
                trigger_time=None,
                trigger_conditions_json=encode_step_conditions(step),
                status="pending",
            )
        )
        created += 1
    if created:
        db.flush()
    return updated, created


def plan_engine_event_ids(result: Any) -> Dict[int, str]:
    """Pre-allocate the durable id of every engine fact this turn will write.

    The ids are allocated *before* the model stages run so a world/scene stage can
    only reference events the engine has already decided -- including the slice's
    own steps of this turn. ``_write_engine_events`` then reuses exactly these ids,
    so the id a stage saw is the id the row carries.
    """
    return {event.seq: generate_uuid() for event in result.events}


def _write_engine_events(
    db: Session,
    ctx: SimulationContext,
    result: Any,
    *,
    transaction_id: str,
    turn_no: int,
    planned_event_ids: Optional[Dict[int, str]] = None,
) -> Tuple[List[str], List[str]]:
    """Persist this turn's engine facts and their deltas, in processing order.

    A delta's causal source is the engine event **of its own step**: events and
    deltas carry independent sequence numbers, so the two counters are never
    conflated -- doing so would silently attach a state change to an unrelated
    fact.
    """
    game_event_repo = GameEventRepository(db)
    delta_repo = StateDeltaRepository(db)
    event_ids: List[str] = []
    delta_ids: List[str] = []
    event_id_by_seq: Dict[int, str] = {}
    event_id_by_step: Dict[str, str] = {}

    for event in result.events:
        event_id = (planned_event_ids or {}).get(event.seq) or generate_uuid()
        event_id_by_seq[event.seq] = event_id
        event_id_by_step.setdefault(event.step_code, event_id)
        game_event_repo.create(
            {
                "id": event_id,
                "transaction_id": transaction_id,
                "session_id": ctx.session_id,
                "turn_no": turn_no,
                "event_type": event.event_type,
                "actor_id": event.actor_code,
                "target_ids_json": list(event.target_ids) or None,
                "visibility_scope": event.visibility_scope,
                "public_payload_json": event.public_payload,
                "private_payload_json": event.private_payload,
                "result_json": _event_result_json(event),
                "occurred_at": _now(),
            }
        )
        event_ids.append(event_id)

    for delta in result.deltas:
        source_event_id = event_id_by_step.get(delta.step_code)
        if source_event_id is None:
            raise TimeSimulationStateError(
                f"delta for step {delta.step_code!r} has no engine event to point at"
            )
        delta_id = generate_uuid()
        delta_repo.create(
            {
                "id": delta_id,
                "transaction_id": transaction_id,
                "source_event_id": source_event_id,
                "session_id": ctx.session_id,
                "turn_no": turn_no,
                "path": f"{DELTA_PATH_PREFIX}.{delta.path}",
                "operation": delta.operation,
                "old_value_json": delta.old_value,
                "new_value_json": delta.new_value,
                "visibility_scope": delta.visibility_scope,
                "validation_status": "valid",
                "created_at": _now(),
            }
        )
        delta_ids.append(delta_id)

    return event_ids, delta_ids


def _event_result_json(event: SimulationEvent) -> Dict[str, Any]:
    """Attach the engine's own step/tick/sequence identity to the fact row."""
    payload = dict(event.result_json or {})
    payload[PHASE3_NAMESPACE] = {
        "step_key": event.step_code,
        "logical_tick": event.tick,
        "phase": int(event.phase),
        "sequence": event.seq,
    }
    return payload


def _write_cognition(
    db: Session,
    ctx: SimulationContext,
    result: Any,
    *,
    transaction_id: str,
    turn_no: int,
) -> int:
    """Persist the advance's necessary private cognition (NPC memories only).

    Only perceiving *subjects* get a row: a fact an NPC could not perceive is
    never written, and a player-visible fact is left to the turn's own public
    projection instead of being copied into a global summary.
    """
    from ..storage.repositories import NPCPrivateMemoryRepository

    if not result.cognition:
        return 0
    repo = NPCPrivateMemoryRepository(db)
    written = 0
    for spec in result.cognition:
        if spec.subject_type != "npc":
            continue
        npc_state_id = ctx.npc_state_ids.get(spec.subject_ref)
        if npc_state_id is None:
            raise TimeSimulationStateError(
                f"cognition subject {spec.subject_ref!r} is not a phase-3 NPC"
            )
        repo.create(
            {
                "id": generate_uuid(),
                "session_id": ctx.session_id,
                "npc_id": npc_state_id,
                "npc_template_id": ctx.npc_template_ids.get(spec.subject_ref),
                "memory_type": spec.memory_kind,
                "memory_kind": spec.memory_kind,
                "memory_text": spec.content,
                "content": spec.content,
                "importance": 0.5,
                "confidence": 1.0,
                "visibility": spec.visibility,
                "status": "active",
                "created_turn": turn_no,
                "last_accessed_turn": turn_no,
                "world_time_text": None,
                "knowledge_source": "engine",
                "source_ref": spec.source_step_code,
                "source_turn_no": turn_no,
            }
        )
        written += 1
    return written


# ---------------------------------------------------------------------------
# Projections for the turn path
# ---------------------------------------------------------------------------


def build_player_action_spec(
    ctx: SimulationContext,
    *,
    action_type: str,
    duration_minutes: int,
    target_location_code: Optional[str] = None,
    target_actor_code: Optional[str] = None,
    refused: bool = False,
    detail_code: Optional[str] = None,
    detail_message: Optional[str] = None,
) -> PlayerActionSpec:
    """Build the kernel's player action from the engine's adjudication."""
    return PlayerActionSpec(
        kind=ctx.rules.classify_player_action(action_type),
        action_type=action_type,
        start_tick=ctx.run_state.logical_tick,
        duration_minutes=duration_minutes,
        target_location_code=target_location_code,
        target_actor_code=target_actor_code,
        refused=refused,
        detail_code=detail_code,
        detail_message=detail_message,
    )


def npc_overlay_for_turn(ctx: SimulationContext, result: Any) -> Dict[str, Any]:
    """The in-turn NPC projection: the advance's *final* state, not stale rows.

    Readers that build the model context must see the world the player will be in
    when the turn commits, so the overlay explicitly *overrides* the durable row
    values instead of only filling gaps.
    """
    by_state_id: Dict[str, Dict[str, Any]] = {}
    for code, state_id in ctx.npc_state_ids.items():
        plan = result.final_state.npc_plans.get(code)
        by_state_id[state_id] = {
            "current_location_id": ctx.location_ids[result.final_state.npc_positions[code]],
            "hidden_plan_state": encode_npc_plan(plan) if plan is not None else None,
            "status_flags": {
                NPC_ALIVE_FLAG_KEY: bool(result.final_state.npc_alive.get(code, True))
            },
        }
    return {
        "session_id": ctx.session_id,
        "by_npc_state_id": by_state_id,
    }


def project_time_summary(
    result: Any,
    *,
    planned_elapsed_minutes: int,
    original_elapsed_minutes: int,
    adjusted: bool,
    reason: str,
    category: str,
    new_world_time: Dict[str, Any],
) -> Dict[str, Any]:
    """The public ``time_advance_result`` of a simulated turn.

    ``accepted_elapsed_minutes`` and ``new_world_time`` carry the **actual**
    outcome: the cursor, the events, the deltas and the response all describe the
    same real endpoint, and an interrupted action is never reported as completed.
    """
    actual = result.actual_elapsed_minutes
    summary: Dict[str, Any] = {
        "accepted_elapsed_minutes": actual,
        "original_elapsed_minutes": original_elapsed_minutes,
        "planned_elapsed_minutes": planned_elapsed_minutes,
        "actual_elapsed_minutes": actual,
        "adjusted": adjusted or actual != planned_elapsed_minutes,
        "reason": reason,
        "category": category,
        "new_world_time": new_world_time,
        "interrupted": bool(result.interrupted),
        "player_action_status": result.player_result.status,
    }
    if result.player_result.arrival_task_code:
        summary["arrival_task_code"] = result.player_result.arrival_task_code
    if result.player_result.status == PlayerActionStatus.INTERRUPTED:
        summary["interrupt_reason"] = "perceivable_world_event"
    return summary


def player_action_kind(ctx: SimulationContext, action_type: str) -> str:
    return ctx.rules.classify_player_action(action_type)


def is_continuous_action(ctx: SimulationContext, action_type: str) -> bool:
    return player_action_kind(ctx, action_type) in (
        PlayerActionKind.IDLE,
        PlayerActionKind.MOVE,
    )


__all__ = [
    "DELTA_PATH_PREFIX",
    "PendingStepRow",
    "SimulationContext",
    "Phase3BaselinePlan",
    "SimulationWriteResult",
    "format_start_display_time",
    "resolve_simulation_profile",
    "session_is_fresh",
    "plan_phase3_baseline",
    "load_simulation_context",
    "apply_simulation_advance",
    "build_player_action_spec",
    "npc_overlay_for_turn",
    "project_time_summary",
    "player_action_kind",
    "is_continuous_action",
    "ACTION_INTERRUPTED",
]

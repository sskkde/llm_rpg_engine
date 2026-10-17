"""Phase-3 minimal time simulation: strict internal contracts.

Scope of this module (plan section 4)
-------------------------------------
This is the *internal* contract layer for the phase-3 vertical slice
(``.omo/plans/phase3-time-simulation.md``). It holds:

* profile resolution from ``World.ruleset_json``,
* the closed step vocabulary and phase ordering,
* the in-memory ``WorkingState`` / ``AdvanceResult`` DTOs,
* strict codecs for the two persisted run-state carriers
  (``SessionState.global_flags_json[PHASE3_NAMESPACE]`` and
  ``ScheduledEvent.trigger_conditions_json[PHASE3_NAMESPACE]``).

It deliberately has **no** DB session, no model call and no wall clock. The
persistence adapter (``time_simulation_persistence``) and the turn service own
every read and write; the kernel (``world_advancer``) owns only pure state
transition.

Fail-closed policy
------------------
Every codec rejects structure it does not fully understand instead of guessing:
an unknown key, a wrong type, a foreign profile id or an out-of-range integer is
an error, never a silent default. That is what keeps a damaged or foreign run
state from being reinterpreted as "no simulation" (which would replay the old
scheduler) or as a valid cursor (which would skip world time).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Namespace and profile constants
# ---------------------------------------------------------------------------

#: Key inside ``World.ruleset_json`` that marks a world as phase-3 enabled.
PROFILE_RULESET_KEY = "phase3_profile"

#: The single closed rule set this slice implements.
PROFILE_ID = "trial_micro_v1"

#: Structure version of the profile marker, the run state and the step payload.
PROFILE_SCHEMA_VERSION = 1

#: Namespace used for both the run-state flag and the scheduled-step conditions.
#: Both live inside caller-owned JSON columns, so the namespace is what keeps
#: them apart from ordinary flags and from the legacy scheduler's conditions.
PHASE3_NAMESPACE = "__phase3_simulation"

#: Hard budget for one advance (plan section 5.1). Exceeding it fails the whole
#: turn rather than committing a prefix.
MAX_STEPS_PER_ADVANCE = 256

#: Internal detail code for a player continuous action cut short by an interrupt.
ACTION_INTERRUPTED = "action_interrupted"


class TimeSimulationError(Exception):
    """Base class for phase-3 time-simulation failures."""

    code = "time_simulation_error"


class TimeSimulationProfileError(TimeSimulationError):
    """The world's profile marker is present but not usable."""

    code = "phase3_profile_invalid"


class TimeSimulationStateError(TimeSimulationError):
    """Persisted run state / plan / step payload is missing or damaged."""

    code = "phase3_state_invalid"


class TimeSimulationBudgetError(TimeSimulationError):
    """One advance produced more steps than the per-turn budget allows."""

    code = "phase3_step_budget_exceeded"


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase3Profile:
    """A validated phase-3 profile marker."""

    id: str
    schema_version: int


def resolve_phase3_profile(world: Any) -> Optional[Phase3Profile]:
    """Return the world's phase-3 profile, or ``None`` when it has none.

    ``None`` (no marker at all) is the *only* value that means "legacy path".
    A marker that exists but is unknown, incomplete or of another structure
    version raises :class:`TimeSimulationProfileError`: the caller must refuse
    the turn rather than silently fall back to the legacy scheduler.
    """
    ruleset = getattr(world, "ruleset_json", None)
    if ruleset is None:
        return None
    if not isinstance(ruleset, dict):
        raise TimeSimulationProfileError(
            "world ruleset_json is not an object; cannot decide whether a "
            "phase-3 profile is present"
        )
    if PROFILE_RULESET_KEY not in ruleset:
        return None

    raw = ruleset[PROFILE_RULESET_KEY]
    if not isinstance(raw, dict):
        raise TimeSimulationProfileError("phase3_profile is not an object")

    profile_id = raw.get("id")
    schema_version = raw.get("schema_version")
    if not isinstance(profile_id, str) or not profile_id:
        raise TimeSimulationProfileError("phase3_profile.id is missing or not a string")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise TimeSimulationProfileError(
            "phase3_profile.schema_version is missing or not an integer"
        )
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise TimeSimulationProfileError(
            f"unsupported phase3_profile.schema_version: {schema_version}"
        )
    if profile_id != PROFILE_ID:
        raise TimeSimulationProfileError(f"unknown phase3_profile.id: {profile_id}")

    unknown = set(raw) - {"id", "schema_version"}
    if unknown:
        raise TimeSimulationProfileError(
            f"phase3_profile has unknown keys: {sorted(unknown)}"
        )
    return Phase3Profile(id=profile_id, schema_version=schema_version)


# ---------------------------------------------------------------------------
# Ordering vocabulary
# ---------------------------------------------------------------------------


class SimulationPhase(IntEnum):
    """Phase inside one tick. Ascending; a step may only derive later phases."""

    ENVIRONMENT = 1
    NPC_MOVE = 2
    ITEM = 3
    PLAYER_CONTINUOUS = 4


class StepKind:
    """Closed vocabulary of step kinds the fixed rule set may schedule."""

    NPC_TRAVEL_START = "npc_travel_start"
    NPC_TRAVEL_ARRIVE = "npc_travel_arrive"
    NPC_TAKE_ITEM = "npc_take_item"
    NPC_USE_ITEM = "npc_use_item"
    ENVIRONMENT_INTERRUPT = "environment_interrupt"
    PLAYER_CONTINUOUS_COMPLETE = "player_continuous_complete"

    ALL = frozenset(
        {
            NPC_TRAVEL_START,
            NPC_TRAVEL_ARRIVE,
            NPC_TAKE_ITEM,
            NPC_USE_ITEM,
            ENVIRONMENT_INTERRUPT,
            PLAYER_CONTINUOUS_COMPLETE,
        }
    )


class StepStatus:
    """Terminal / transient states of one processed step."""

    APPLIED = "applied"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class PlayerActionKind:
    """Player action shapes this slice understands."""

    IDLE = "idle"
    MOVE = "move"
    INSTANT = "instant"

    ALL = frozenset({IDLE, MOVE, INSTANT})


class PlayerActionStatus:
    """Final player result of one advance."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    REFUSED = "refused"
    NOT_STARTED = "not_started"


class PlanStatus:
    """Lifecycle of one NPC travel plan."""

    IDLE = "idle"
    TRAVELING = "traveling"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def travel_step_key(actor_code: str, kind: str, tick: int) -> str:
    """Deterministic step key for the fixed rule set.

    Determinism matters beyond tidiness: the key is the dedupe identity that
    stops an already-consumed step from being scheduled (or fired) twice when a
    later turn re-derives the same itinerary.
    """
    return f"{actor_code}.{kind}@{tick}"


@dataclass(frozen=True)
class ScheduledStep:
    """One world/NPC/player step at an absolute logical tick."""

    step_key: str
    tick: int
    phase: int
    actor_code: str
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.step_key, str) or not self.step_key:
            raise TimeSimulationStateError("step_key must be a non-empty string")
        if isinstance(self.tick, bool) or not isinstance(self.tick, int) or self.tick < 0:
            raise TimeSimulationStateError(f"invalid step tick: {self.tick!r}")
        if int(self.phase) not in {int(p) for p in SimulationPhase}:
            raise TimeSimulationStateError(f"invalid step phase: {self.phase!r}")
        if not isinstance(self.actor_code, str) or not self.actor_code:
            raise TimeSimulationStateError("actor_code must be a non-empty string")
        if self.kind not in StepKind.ALL:
            raise TimeSimulationStateError(f"unknown step kind: {self.kind!r}")
        if not isinstance(self.payload, dict):
            raise TimeSimulationStateError("step payload must be an object")

    @property
    def order_key(self) -> Tuple[int, int, str, str]:
        """The authoritative queue key (plan section 5.1)."""
        return (self.tick, int(self.phase), self.actor_code, self.step_key)


def encode_step_conditions(step: ScheduledStep) -> Dict[str, Any]:
    """Namespaced ``trigger_conditions_json`` for one scheduled step."""
    body = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "step_key": step.step_key,
        "tick": step.tick,
        "phase": int(step.phase),
        "actor_code": step.actor_code,
        "kind": step.kind,
        "payload": step.payload,
    }
    try:
        json.dumps(body, sort_keys=True)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise TimeSimulationStateError(f"step payload is not JSON-serialisable: {exc}") from exc
    return {PHASE3_NAMESPACE: body}


def is_phase3_conditions(conditions: Any) -> bool:
    """True when a scheduled-event conditions blob belongs to this namespace."""
    return isinstance(conditions, dict) and PHASE3_NAMESPACE in conditions


def decode_step_conditions(conditions: Any) -> ScheduledStep:
    """Strictly decode one namespaced scheduled step."""
    if not is_phase3_conditions(conditions):
        raise TimeSimulationStateError("scheduled step is not in the phase-3 namespace")
    body = conditions[PHASE3_NAMESPACE]
    if not isinstance(body, dict):
        raise TimeSimulationStateError("phase-3 scheduled step payload is not an object")
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
    missing = expected - set(body)
    if missing:
        raise TimeSimulationStateError(
            f"phase-3 scheduled step is missing keys: {sorted(missing)}"
        )
    unknown = set(body) - expected
    if unknown:
        raise TimeSimulationStateError(
            f"phase-3 scheduled step has unknown keys: {sorted(unknown)}"
        )
    if body["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise TimeSimulationStateError(
            f"unsupported scheduled step schema_version: {body['schema_version']!r}"
        )
    if body["profile_id"] != PROFILE_ID:
        raise TimeSimulationStateError(
            f"foreign scheduled step profile_id: {body['profile_id']!r}"
        )
    return ScheduledStep(
        step_key=body["step_key"],
        tick=body["tick"],
        phase=body["phase"],
        actor_code=body["actor_code"],
        kind=body["kind"],
        payload=body["payload"],
    )


# ---------------------------------------------------------------------------
# Persisted run state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationRunState:
    """The bounded per-session simulation cursor kept in ``global_flags_json``.

    No event history is stored here: the durable timeline lives in
    ``game_events``/``state_deltas``. Only the cursor, the event sequence
    allocator and the finite one-shot switches are run state.
    """

    logical_tick: int
    next_event_seq: int
    profile_id: str = PROFILE_ID
    schema_version: int = PROFILE_SCHEMA_VERSION
    one_shot: Dict[str, bool] = field(default_factory=dict)

    def with_cursor(self, logical_tick: int, next_event_seq: int,
                    one_shot: Optional[Dict[str, bool]] = None) -> "SimulationRunState":
        return replace(
            self,
            logical_tick=logical_tick,
            next_event_seq=next_event_seq,
            one_shot=dict(self.one_shot if one_shot is None else one_shot),
        )


def _require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimeSimulationStateError(f"{label} is not an integer: {value!r}")
    if value < minimum:
        raise TimeSimulationStateError(f"{label} is below {minimum}: {value!r}")
    return value


def decode_run_state(raw: Any) -> Optional[SimulationRunState]:
    """Decode the run-state blob. ``None`` means "no run state at all"."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TimeSimulationStateError("phase-3 run state is not an object")
    expected = {"schema_version", "profile_id", "logical_tick", "next_event_seq", "one_shot"}
    missing = expected - set(raw)
    if missing:
        raise TimeSimulationStateError(f"phase-3 run state is missing keys: {sorted(missing)}")
    unknown = set(raw) - expected
    if unknown:
        raise TimeSimulationStateError(f"phase-3 run state has unknown keys: {sorted(unknown)}")
    if raw["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise TimeSimulationStateError(
            f"unsupported run-state schema_version: {raw['schema_version']!r}"
        )
    if raw["profile_id"] != PROFILE_ID:
        raise TimeSimulationStateError(f"foreign run-state profile_id: {raw['profile_id']!r}")
    one_shot = raw["one_shot"]
    if not isinstance(one_shot, dict):
        raise TimeSimulationStateError("run-state one_shot is not an object")
    for key, value in one_shot.items():
        if not isinstance(key, str) or not isinstance(value, bool):
            raise TimeSimulationStateError(f"invalid one_shot entry: {key!r}={value!r}")
    return SimulationRunState(
        logical_tick=_require_int(raw["logical_tick"], "run-state logical_tick"),
        next_event_seq=_require_int(raw["next_event_seq"], "run-state next_event_seq"),
        one_shot=dict(one_shot),
    )


def encode_run_state(state: SimulationRunState) -> Dict[str, Any]:
    """Encode the run state for ``global_flags_json``."""
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "logical_tick": _require_int(state.logical_tick, "run-state logical_tick"),
        "next_event_seq": _require_int(state.next_event_seq, "run-state next_event_seq"),
        "one_shot": {str(k): bool(v) for k, v in state.one_shot.items()},
    }


def read_run_state(global_flags: Any) -> Optional[SimulationRunState]:
    """Read the run state out of a session's ``global_flags_json``."""
    if global_flags is None:
        return None
    if not isinstance(global_flags, dict):
        raise TimeSimulationStateError("global_flags_json is not an object")
    return decode_run_state(global_flags.get(PHASE3_NAMESPACE))


def merge_run_state(global_flags: Any, state: SimulationRunState) -> Dict[str, Any]:
    """Return ``global_flags_json`` with the run state replaced, others kept."""
    if global_flags is None:
        merged: Dict[str, Any] = {}
    elif isinstance(global_flags, dict):
        merged = dict(global_flags)
    else:
        raise TimeSimulationStateError("global_flags_json is not an object")
    merged[PHASE3_NAMESPACE] = encode_run_state(state)
    return merged


# ---------------------------------------------------------------------------
# NPC travel plan (persisted in ``SessionNPCState.hidden_plan_state``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NPCTravelPlan:
    """The small itinerary record this slice stores per NPC.

    The column is shared with legacy free text, so a phase-3 plan is stored as a
    JSON object under the namespace key and a non-namespaced string is left
    untouched (never overwritten, never interpreted).
    """

    from_code: str
    to_code: str
    start_tick: int
    expected_end_tick: int
    step_key: str
    status: str

    def __post_init__(self) -> None:
        if self.status not in {
            PlanStatus.TRAVELING,
            PlanStatus.ARRIVED,
            PlanStatus.CANCELLED,
            PlanStatus.BLOCKED,
        }:
            raise TimeSimulationStateError(f"invalid NPC plan status: {self.status!r}")
        if self.expected_end_tick < self.start_tick:
            raise TimeSimulationStateError("NPC plan ends before it starts")


def encode_npc_plan(plan: NPCTravelPlan) -> str:
    """Encode one plan as the strict JSON string stored in the column."""
    return json.dumps(
        {
            PHASE3_NAMESPACE: {
                "schema_version": PROFILE_SCHEMA_VERSION,
                "profile_id": PROFILE_ID,
                "from": plan.from_code,
                "to": plan.to_code,
                "start": plan.start_tick,
                "expected_end": plan.expected_end_tick,
                "step_key": plan.step_key,
                "status": plan.status,
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_npc_plan(raw: Any) -> Optional[NPCTravelPlan]:
    """Decode a phase-3 plan, or ``None`` for absent/legacy content.

    Legacy text (anything that is not a namespaced phase-3 JSON object) is
    reported as ``None`` and left alone: this slice must not reinterpret, and
    must not overwrite, another subsystem's plan text.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TimeSimulationStateError("hidden_plan_state is not text")
    text = raw.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or PHASE3_NAMESPACE not in parsed:
        return None
    body = parsed[PHASE3_NAMESPACE]
    if not isinstance(body, dict):
        raise TimeSimulationStateError("phase-3 NPC plan is not an object")
    expected = {
        "schema_version",
        "profile_id",
        "from",
        "to",
        "start",
        "expected_end",
        "step_key",
        "status",
    }
    missing = expected - set(body)
    if missing:
        raise TimeSimulationStateError(f"phase-3 NPC plan is missing keys: {sorted(missing)}")
    unknown = set(body) - expected
    if unknown:
        raise TimeSimulationStateError(f"phase-3 NPC plan has unknown keys: {sorted(unknown)}")
    if body["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise TimeSimulationStateError(
            f"unsupported NPC plan schema_version: {body['schema_version']!r}"
        )
    if body["profile_id"] != PROFILE_ID:
        raise TimeSimulationStateError(f"foreign NPC plan profile_id: {body['profile_id']!r}")
    return NPCTravelPlan(
        from_code=body["from"],
        to_code=body["to"],
        start_tick=_require_int(body["start"], "NPC plan start"),
        expected_end_tick=_require_int(body["expected_end"], "NPC plan expected_end"),
        step_key=body["step_key"],
        status=body["status"],
    )


# ---------------------------------------------------------------------------
# Working state (the single evolving copy)
# ---------------------------------------------------------------------------


@dataclass
class WorkingState:
    """The one mutable state the advance runs on.

    Every later step reads this object after earlier steps have already applied
    their effects; there is no second copy of position/ownership truth.
    """

    logical_tick: int = 0
    player_location_code: str = ""
    player_alive: bool = True
    player_action_status: str = PlayerActionStatus.NOT_STARTED
    player_arrival_task_code: Optional[str] = None
    npc_positions: Dict[str, str] = field(default_factory=dict)
    npc_alive: Dict[str, bool] = field(default_factory=dict)
    npc_plans: Dict[str, Optional[NPCTravelPlan]] = field(default_factory=dict)
    item_code: str = ""
    item_quantity: int = 0
    item_owner_type: Optional[str] = None
    item_owner_ref: Optional[str] = None
    routes_open: Dict[str, bool] = field(default_factory=dict)
    one_shot: Dict[str, bool] = field(default_factory=dict)

    def copy(self) -> "WorkingState":
        """Deep-enough copy: the advance must never mutate its input."""
        return WorkingState(
            logical_tick=self.logical_tick,
            player_location_code=self.player_location_code,
            player_alive=self.player_alive,
            player_action_status=self.player_action_status,
            player_arrival_task_code=self.player_arrival_task_code,
            npc_positions=dict(self.npc_positions),
            npc_alive=dict(self.npc_alive),
            npc_plans=dict(self.npc_plans),
            item_code=self.item_code,
            item_quantity=self.item_quantity,
            item_owner_type=self.item_owner_type,
            item_owner_ref=self.item_owner_ref,
            routes_open=dict(self.routes_open),
            one_shot=dict(self.one_shot),
        )

    def route_key(self, from_code: str, to_code: str) -> str:
        return f"{from_code}->{to_code}"

    def route_is_open(self, from_code: str, to_code: str) -> bool:
        return bool(self.routes_open.get(self.route_key(from_code, to_code), False))

    def npc_is_alive(self, actor_code: str) -> bool:
        return bool(self.npc_alive.get(actor_code, True))


# ---------------------------------------------------------------------------
# Player action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerActionSpec:
    """The engine-adjudicated player action for one advance.

    ``refused`` marks an action the engine already rejected (unauthorized,
    unavailable, handlerless). It keeps the action class's existing time cost --
    the world still moves on -- but has no completion effect of its own.
    """

    kind: str
    action_type: str
    start_tick: int
    duration_minutes: int
    target_location_code: Optional[str] = None
    target_actor_code: Optional[str] = None
    refused: bool = False
    detail_code: Optional[str] = None
    detail_message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in PlayerActionKind.ALL:
            raise TimeSimulationStateError(f"invalid player action kind: {self.kind!r}")
        _require_int(self.start_tick, "player action start_tick")
        _require_int(self.duration_minutes, "player action duration_minutes")

    @property
    def end_tick(self) -> int:
        return self.start_tick + self.duration_minutes


@dataclass(frozen=True)
class PlayerActionResult:
    """Final player-facing outcome of one advance."""

    status: str
    action_type: str
    location_code: str
    elapsed_minutes: int
    detail_code: Optional[str] = None
    detail_message: Optional[str] = None
    arrival_task_code: Optional[str] = None


# ---------------------------------------------------------------------------
# Engine events / deltas / cognition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationEvent:
    """One engine-decided fact produced by a step, in processing order."""

    seq: int
    tick: int
    phase: int
    actor_code: str
    step_code: str
    event_type: str
    visibility_scope: str
    target_ids: Tuple[str, ...] = ()
    public_payload: Optional[Dict[str, Any]] = None
    private_payload: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SimulationDelta:
    """One state change, pointing at the step that caused it."""

    seq: int
    tick: int
    step_code: str
    path: str
    operation: str
    old_value: Any
    new_value: Any
    visibility_scope: str = "hidden"


@dataclass(frozen=True)
class CognitionSpec:
    """A fact one perceiving subject must remember because of this advance."""

    seq: int
    subject_type: str
    subject_ref: str
    tick: int
    content: str
    visibility: str
    memory_kind: str
    source_step_code: str
    event_seq: int


@dataclass(frozen=True)
class StepOutcome:
    """Terminal result of one processed step."""

    step_key: str
    tick: int
    phase: int
    actor_code: str
    kind: str
    status: str
    detail_code: Optional[str] = None
    detail_message: Optional[str] = None


@dataclass
class AdvanceResult:
    """Everything one advance decided, ready for the persistence adapter."""

    profile_id: str
    start_tick: int
    target_tick: int
    actual_end_tick: int
    interrupted: bool
    player_result: PlayerActionResult
    final_state: WorkingState
    events: List[SimulationEvent] = field(default_factory=list)
    deltas: List[SimulationDelta] = field(default_factory=list)
    cognition: List[CognitionSpec] = field(default_factory=list)
    consumed_steps: List[StepOutcome] = field(default_factory=list)
    #: The specs of every consumed step, in processing order. The persistence
    #: adapter needs them because a step that was *derived and consumed inside the
    #: same advance* has no durable row yet: it still has to be recorded with its
    #: terminal status so the durable timeline is complete.
    consumed_step_specs: List[ScheduledStep] = field(default_factory=list)
    pending_steps: List[ScheduledStep] = field(default_factory=list)
    next_event_seq: int = 0
    steps_processed: int = 0

    @property
    def actual_elapsed_minutes(self) -> int:
        return self.actual_end_tick - self.start_tick

    @property
    def player_action_status(self) -> str:
        return self.player_result.status


__all__ = [
    "PROFILE_RULESET_KEY",
    "PROFILE_ID",
    "PROFILE_SCHEMA_VERSION",
    "PHASE3_NAMESPACE",
    "MAX_STEPS_PER_ADVANCE",
    "ACTION_INTERRUPTED",
    "TimeSimulationError",
    "TimeSimulationProfileError",
    "TimeSimulationStateError",
    "TimeSimulationBudgetError",
    "Phase3Profile",
    "resolve_phase3_profile",
    "SimulationPhase",
    "StepKind",
    "StepStatus",
    "PlayerActionKind",
    "PlayerActionStatus",
    "PlanStatus",
    "ScheduledStep",
    "travel_step_key",
    "encode_step_conditions",
    "is_phase3_conditions",
    "decode_step_conditions",
    "SimulationRunState",
    "decode_run_state",
    "encode_run_state",
    "read_run_state",
    "merge_run_state",
    "NPCTravelPlan",
    "encode_npc_plan",
    "decode_npc_plan",
    "WorkingState",
    "PlayerActionSpec",
    "PlayerActionResult",
    "SimulationEvent",
    "SimulationDelta",
    "CognitionSpec",
    "StepOutcome",
    "AdvanceResult",
]

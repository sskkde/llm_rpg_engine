"""Phase-3 fixed micro scenario and its closed step handlers.

This module is the *domain* half of the phase-3 vertical slice: the fixed
"trial peak" scene (three locations, two NPCs, one unique token) plus the six
step handlers the slice supports. It is pure: no DB, no model, no clock, no
random. ``world_advancer`` owns queue mechanics; this module owns what a step
means and what it derives.

Fixed scenario (plan section 6)
-------------------------------
World clock starts at 08:00 with ``logical_tick == 0``. The player stands at the
mountain gate, NPC A at the plaza, NPC B and the token at the trial peak.

======================  ==========================================
Tick                    Deterministic step
======================  ==========================================
``+2``                  A departs the plaza for the trial peak
``+5``                  A arrives, then A and B contest the token
``+6``                  B tries to *use* the token (owner is already A)
``+7``                  Perceivable trial bell / formation disturbance
``+8`` / ``+9``         B departs the trial peak, then arrives at the gate
======================  ==========================================

The ``+5`` contest is the shared-state proof: the arrival step (phase
``NPC_MOVE``) applies first, then the two ``ITEM`` steps run against the *same*
``WorkingState`` in stable actor order, so A wins and B's attempt is an explicit
failure rather than a second copy of the token.

Interrupt switch
----------------
``build_trial_rules(interrupt_enabled=False)`` is the fixed *test* variant from
plan section 6 ("关闭中断的固定测试变体"). It is a code-level seam only: no
request field, profile value or model output can reach it, and the production
singleton ``get_trial_rules()`` always has the interrupt enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .time_simulation import (
    PHASE3_NAMESPACE,
    PROFILE_ID,
    PROFILE_RULESET_KEY,
    PROFILE_SCHEMA_VERSION,
    PlanStatus,
    PlayerActionKind,
    PlayerActionSpec,
    ScheduledStep,
    SimulationPhase,
    StepKind,
    StepStatus,
    TimeSimulationStateError,
    WorkingState,
    NPCTravelPlan,
    travel_step_key,
)

# ---------------------------------------------------------------------------
# Stable codes (shared by the seed script, the runtime and the tests)
# ---------------------------------------------------------------------------

MICRO_WORLD_CODE = "phase3_trial_micro"
MICRO_WORLD_NAME = "试炼峰时间纵切片"

LOCATION_MOUNTAIN_GATE = "mountain_gate"
LOCATION_PLAZA = "plaza"
LOCATION_TRIAL_PEAK = "trial_peak"

NPC_A_CODE = "npc_a"
NPC_B_CODE = "npc_b"

TOKEN_ITEM_CODE = "trial_token"

ROUTE_GATE_TO_PLAZA = "mountain_gate->plaza"
ROUTE_PLAZA_TO_PEAK = "plaza->trial_peak"

#: The slice's walkable directed edges. The three locations sit on one path
#: (gate - plaza - peak), so both directions of each edge are walkable: NPC B's
#: follow-up itinerary (+8 depart the peak, +9 arrive at the gate) uses the
#: reverse direction of the same physical path.
ROUTES: Tuple[str, ...] = (
    ROUTE_GATE_TO_PLAZA,
    ROUTE_PLAZA_TO_PEAK,
    "plaza->mountain_gate",
    "trial_peak->plaza",
)

#: Undirected parent -> child edges, used to derive per-direction route openness
#: from the destination location's ``access_rules``.
ROUTE_EDGES: Tuple[Tuple[str, str], ...] = (
    (LOCATION_MOUNTAIN_GATE, LOCATION_PLAZA),
    (LOCATION_PLAZA, LOCATION_TRIAL_PEAK),
)

START_HOUR = 8
START_MINUTE = 0
START_TICK = 0

#: Player action durations are *adjudicated* by the existing validator; these are
#: the values the acceptance trajectories use (idle/unknown 10, inspect 3,
#: nearby movement 15).
IDLE_DURATION_MINUTES = 10
INSPECT_DURATION_MINUTES = 3
MOVE_DURATION_MINUTES = 15

TICK_NPC_A_DEPART = 2
TICK_NPC_A_ARRIVE = 5
TICK_ITEM_CONTEST = 5
TICK_NPC_B_USE = 6
TICK_INTERRUPT = 7
TICK_NPC_B_DEPART = 8
TICK_NPC_B_ARRIVE = 9

#: Finite one-shot switch for the single perceivable world interrupt.
INTERRUPT_ONE_SHOT_KEY = "trial_interrupt"

#: Key inside ``Location.access_rules`` that marks a route as open. A missing key
#: means open; the value must be a bool.
ROUTE_OPEN_RULE_KEY = "phase3_route_open"

#: Session-flag key that records an NPC's phase-3 aliveness.
NPC_ALIVE_FLAG_KEY = "phase3_alive"

ARRIVAL_TASK_BY_LOCATION: Dict[str, str] = {
    LOCATION_PLAZA: "task_arrive_plaza",
    LOCATION_TRIAL_PEAK: "task_arrive_trial_peak",
}

#: The engine action types that this slice treats as *continuous* (interruptible)
#: actions. Everything else keeps the existing instant-at-start behaviour.
_CONTINUOUS_ACTION_KINDS: Dict[str, str] = {
    "move": PlayerActionKind.MOVE,
    "follow": PlayerActionKind.MOVE,
    "wait": PlayerActionKind.IDLE,
    # The authorized "idle" class: a long, unspecific action whose only
    # completion effect is that it ended.
    "idle": PlayerActionKind.IDLE,
    # The deterministic parser's generic bucket ("action") carries the 10-minute
    # "unknown" category, which is this slice's idle: a long, unspecific action
    # with no completion effect of its own.
    "action": PlayerActionKind.IDLE,
}


# ---------------------------------------------------------------------------
# Scenario data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocationSpec:
    code: str
    name: str
    description: str
    parent_code: Optional[str]
    tags: Tuple[str, ...]


@dataclass(frozen=True)
class NPCSpec:
    code: str
    name: str
    public_identity: str
    personality: str
    initial_location_code: str


@dataclass(frozen=True)
class ItemSpec:
    code: str
    name: str
    item_type: str
    description: str
    initial_owner_type: str
    initial_owner_ref: str


WORLD_SPEC: Dict[str, Any] = {
    "code": MICRO_WORLD_CODE,
    "name": MICRO_WORLD_NAME,
    "genre": "xianxia",
    "lore_summary": "试炼峰前的一小段真实时间：山门、广场与试炼峰之间，只有一枚令牌。",
    "status": "active",
}

LOCATION_SPECS: Tuple[LocationSpec, ...] = (
    LocationSpec(
        code=LOCATION_MOUNTAIN_GATE,
        name="山门",
        description="宗门外门入口，石阶向上通往广场。",
        parent_code=None,
        tags=("safe",),
    ),
    LocationSpec(
        code=LOCATION_PLAZA,
        name="广场",
        description="外门弟子聚集的广场，可远望试炼峰。",
        parent_code=LOCATION_MOUNTAIN_GATE,
        tags=("safe",),
    ),
    LocationSpec(
        code=LOCATION_TRIAL_PEAK,
        name="试炼峰",
        description="峰顶设有试炼阵法，令牌原本置于此处。",
        parent_code=LOCATION_PLAZA,
        tags=("safe",),
    ),
)

NPC_SPECS: Tuple[NPCSpec, ...] = (
    NPCSpec(
        code=NPC_A_CODE,
        name="甲师兄",
        public_identity="外门执事弟子",
        personality="行动果断，先取为快。",
        initial_location_code=LOCATION_PLAZA,
    ),
    NPCSpec(
        code=NPC_B_CODE,
        name="乙师弟",
        public_identity="外门新入弟子",
        personality="谨慎，但总慢人一步。",
        initial_location_code=LOCATION_TRIAL_PEAK,
    ),
)

ITEM_SPEC = ItemSpec(
    code=TOKEN_ITEM_CODE,
    name="试炼令牌",
    item_type="quest",
    description="试炼峰阵法中唯一的令牌，先到先得。",
    initial_owner_type="location",
    initial_owner_ref=LOCATION_TRIAL_PEAK,
)

#: The initial schedule. Arrival steps are *derived* by ``npc_travel_start``; the
#: rest are pre-scheduled so that the tick table is a fixed contract.
SCHEDULED_STEP_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "tick": TICK_NPC_A_DEPART,
        "phase": SimulationPhase.NPC_MOVE,
        "actor": NPC_A_CODE,
        "kind": StepKind.NPC_TRAVEL_START,
        "payload": {
            "from": LOCATION_PLAZA,
            "to": LOCATION_TRIAL_PEAK,
            "expected_end": TICK_NPC_A_ARRIVE,
        },
    },
    {
        "tick": TICK_ITEM_CONTEST,
        "phase": SimulationPhase.ITEM,
        "actor": NPC_A_CODE,
        "kind": StepKind.NPC_TAKE_ITEM,
        "payload": {"item": TOKEN_ITEM_CODE},
    },
    {
        "tick": TICK_ITEM_CONTEST,
        "phase": SimulationPhase.ITEM,
        "actor": NPC_B_CODE,
        "kind": StepKind.NPC_TAKE_ITEM,
        "payload": {"item": TOKEN_ITEM_CODE},
    },
    {
        "tick": TICK_NPC_B_USE,
        "phase": SimulationPhase.ITEM,
        "actor": NPC_B_CODE,
        "kind": StepKind.NPC_USE_ITEM,
        "payload": {"item": TOKEN_ITEM_CODE},
    },
    {
        "tick": TICK_INTERRUPT,
        "phase": SimulationPhase.ENVIRONMENT,
        "actor": "world",
        "kind": StepKind.ENVIRONMENT_INTERRUPT,
        "payload": {"one_shot_key": INTERRUPT_ONE_SHOT_KEY},
    },
    {
        "tick": TICK_NPC_B_DEPART,
        "phase": SimulationPhase.NPC_MOVE,
        "actor": NPC_B_CODE,
        "kind": StepKind.NPC_TRAVEL_START,
        "payload": {
            # B walks back down the peak-plaza path: one hop, so the fixed tick
            # table stays a single-leg itinerary per NPC step.
            "from": LOCATION_TRIAL_PEAK,
            "to": LOCATION_PLAZA,
            "expected_end": TICK_NPC_B_ARRIVE,
        },
    },
)


def profile_marker() -> Dict[str, Any]:
    """The ``World.ruleset_json`` fragment that enables this slice."""
    return {
        PROFILE_RULESET_KEY: {
            "id": PROFILE_ID,
            "schema_version": PROFILE_SCHEMA_VERSION,
        }
    }


def is_interrupt_step(step: ScheduledStep) -> bool:
    return step.kind == StepKind.ENVIRONMENT_INTERRUPT


# ---------------------------------------------------------------------------
# Effect drafts (the advancer assigns sequence numbers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CognitionDraft:
    """One perceiving subject that must remember this event."""

    subject_type: str
    subject_ref: str
    content: str
    visibility: str = "private"
    memory_kind: str = "action"


@dataclass(frozen=True)
class SimulationEventDraft:
    """An engine fact, before the advancer gives it a sequence number."""

    event_type: str
    visibility_scope: str
    target_ids: Tuple[str, ...] = ()
    public_payload: Optional[Dict[str, Any]] = None
    private_payload: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    cognition: Tuple[CognitionDraft, ...] = ()


@dataclass(frozen=True)
class SimulationDeltaDraft:
    """A state change, before the advancer gives it a sequence number."""

    path: str
    operation: str
    old_value: Any
    new_value: Any
    visibility_scope: str = "hidden"


@dataclass(frozen=True)
class StepEffect:
    """What one step did, and what it derived."""

    status: str
    events: Tuple[SimulationEventDraft, ...] = ()
    deltas: Tuple[SimulationDeltaDraft, ...] = ()
    derived_steps: Tuple[ScheduledStep, ...] = ()
    interrupts_player: bool = False
    detail_code: Optional[str] = None
    detail_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class TrialRules:
    """The closed rule set of the fixed micro scenario."""

    def __init__(self, *, interrupt_enabled: bool = True) -> None:
        self.interrupt_enabled = bool(interrupt_enabled)

    # -- initial state / schedule -------------------------------------------------

    def initial_state(self) -> WorkingState:
        """The deterministic starting state of a fresh slice session."""
        return WorkingState(
            logical_tick=START_TICK,
            player_location_code=LOCATION_MOUNTAIN_GATE,
            player_alive=True,
            npc_positions={
                NPC_A_CODE: LOCATION_PLAZA,
                NPC_B_CODE: LOCATION_TRIAL_PEAK,
            },
            npc_alive={NPC_A_CODE: True, NPC_B_CODE: True},
            npc_plans={NPC_A_CODE: None, NPC_B_CODE: None},
            item_code=TOKEN_ITEM_CODE,
            item_quantity=1,
            item_owner_type=ITEM_SPEC.initial_owner_type,
            item_owner_ref=ITEM_SPEC.initial_owner_ref,
            routes_open={route: True for route in ROUTES},
            one_shot={},
        )

    def initial_steps(self) -> List[ScheduledStep]:
        """The fixed pre-scheduled steps of a fresh slice session."""
        steps: List[ScheduledStep] = []
        for spec in SCHEDULED_STEP_SPECS:
            if spec["kind"] == StepKind.ENVIRONMENT_INTERRUPT and not self.interrupt_enabled:
                continue
            actor = spec["actor"]
            steps.append(
                ScheduledStep(
                    step_key=travel_step_key(actor, spec["kind"], spec["tick"]),
                    tick=spec["tick"],
                    phase=int(spec["phase"]),
                    actor_code=actor,
                    kind=spec["kind"],
                    payload=dict(spec["payload"]),
                )
            )
        return steps

    # -- player action ------------------------------------------------------------

    def classify_player_action(self, action_type: Optional[str]) -> str:
        """Map an engine action type onto this slice's action shape."""
        return _CONTINUOUS_ACTION_KINDS.get(
            (action_type or "").strip().lower(), PlayerActionKind.INSTANT
        )

    def player_completion_step(
        self, player_action: PlayerActionSpec
    ) -> Optional[ScheduledStep]:
        """The step that completes a continuous player action, if any."""
        if player_action.kind not in (PlayerActionKind.IDLE, PlayerActionKind.MOVE):
            return None
        return ScheduledStep(
            step_key=travel_step_key(
                "player", StepKind.PLAYER_CONTINUOUS_COMPLETE, player_action.end_tick
            ),
            tick=player_action.end_tick,
            phase=int(SimulationPhase.PLAYER_CONTINUOUS),
            actor_code="player",
            kind=StepKind.PLAYER_CONTINUOUS_COMPLETE,
            payload={
                "action_kind": player_action.kind,
                "action_type": player_action.action_type,
                "target_location_code": player_action.target_location_code,
            },
        )

    def arrival_task_for(self, location_code: str) -> Optional[str]:
        return ARRIVAL_TASK_BY_LOCATION.get(location_code)

    # -- step dispatch ------------------------------------------------------------

    def apply_step(
        self,
        *,
        state: WorkingState,
        step: ScheduledStep,
        player_action: PlayerActionSpec,
    ) -> StepEffect:
        """Apply one step to ``state`` and report what it did.

        Handlers mutate ``state`` in place; the advancer owns the copy, so the
        caller's input state is never touched. Preconditions are evaluated against
        the *current* state, which is what makes a same-tick competition see the
        earlier winner's effect.
        """
        handler = _HANDLERS.get(step.kind)
        if handler is None:
            raise TimeSimulationStateError(f"no handler for step kind {step.kind!r}")
        return handler(self, state, step, player_action)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _player_sees(state: WorkingState, location_code: Optional[str]) -> bool:
    return bool(
        state.player_alive
        and location_code is not None
        and state.player_location_code == location_code
    )


def _blocked(step: ScheduledStep, code: str, message: str) -> StepEffect:
    """A terminal blocked step: explicit, auditable, never retried."""
    return StepEffect(
        status=StepStatus.BLOCKED,
        events=(
            SimulationEventDraft(
                event_type="phase3_step_blocked",
                visibility_scope="hidden",
                private_payload={
                    "step_key": step.step_key,
                    "kind": step.kind,
                    "actor_id": step.actor_code,
                    "tick": step.tick,
                    "detail_code": code,
                },
                result_json={"status": StepStatus.BLOCKED, "detail_code": code},
            ),
        ),
        detail_code=code,
        detail_message=message,
    )


def _handle_npc_travel_start(
    rules: TrialRules,
    state: WorkingState,
    step: ScheduledStep,
    player_action: PlayerActionSpec,
) -> StepEffect:
    actor = step.actor_code
    from_code = step.payload.get("from")
    to_code = step.payload.get("to")
    expected_end = step.payload.get("expected_end")

    if not state.npc_is_alive(actor):
        return _blocked(step, "npc_not_alive", f"{actor} is not alive")
    if not isinstance(from_code, str) or not isinstance(to_code, str):
        raise TimeSimulationStateError("npc_travel_start requires 'from' and 'to'")
    if isinstance(expected_end, bool) or not isinstance(expected_end, int):
        raise TimeSimulationStateError("npc_travel_start requires an integer 'expected_end'")
    if expected_end <= step.tick:
        raise TimeSimulationStateError("npc_travel_start must end after it starts")
    if state.npc_positions.get(actor) != from_code:
        return _blocked(step, "actor_not_at_origin", f"{actor} is not at {from_code}")
    if not state.route_is_open(from_code, to_code):
        return _blocked(step, "route_closed", f"route {from_code}->{to_code} is closed")

    previous_plan = state.npc_plans.get(actor)
    if previous_plan is not None and previous_plan.status == PlanStatus.TRAVELING:
        return _blocked(step, "already_traveling", f"{actor} is already traveling")

    plan = NPCTravelPlan(
        from_code=from_code,
        to_code=to_code,
        start_tick=step.tick,
        expected_end_tick=expected_end,
        step_key=step.step_key,
        status=PlanStatus.TRAVELING,
    )
    state.npc_plans[actor] = plan

    arrive_step = ScheduledStep(
        step_key=travel_step_key(actor, StepKind.NPC_TRAVEL_ARRIVE, expected_end),
        tick=expected_end,
        phase=int(SimulationPhase.NPC_MOVE),
        actor_code=actor,
        kind=StepKind.NPC_TRAVEL_ARRIVE,
        payload={"from": from_code, "to": to_code, "plan_step_key": step.step_key},
    )

    visible = _player_sees(state, from_code)
    return StepEffect(
        status=StepStatus.APPLIED,
        derived_steps=(arrive_step,),
        events=(
            SimulationEventDraft(
                event_type="npc_travel_started",
                visibility_scope="player_visible" if visible else "hidden",
                target_ids=(to_code,),
                public_payload=(
                    {
                        "npc_id": actor,
                        "from": from_code,
                        "to": to_code,
                        "expected_end_tick": expected_end,
                    }
                    if visible
                    else None
                ),
                private_payload=(
                    None
                    if visible
                    else {
                        "npc_id": actor,
                        "from": from_code,
                        "to": to_code,
                        "expected_end_tick": expected_end,
                    }
                ),
                result_json={"status": StepStatus.APPLIED},
                cognition=(
                    CognitionDraft(
                        subject_type="npc",
                        subject_ref=actor,
                        content=f"我从{from_code}出发前往{to_code}。",
                        memory_kind="action",
                    ),
                ),
            ),
        ),
        deltas=(
            SimulationDeltaDraft(
                path=f"npcs.{actor}.plan",
                operation="set",
                old_value=None,
                new_value={
                    "from": from_code,
                    "to": to_code,
                    "start": step.tick,
                    "expected_end": expected_end,
                    "status": PlanStatus.TRAVELING,
                },
                visibility_scope="hidden",
            ),
        ),
    )


def _handle_npc_travel_arrive(
    rules: TrialRules,
    state: WorkingState,
    step: ScheduledStep,
    player_action: PlayerActionSpec,
) -> StepEffect:
    actor = step.actor_code
    from_code = step.payload.get("from")
    to_code = step.payload.get("to")
    plan_step_key = step.payload.get("plan_step_key")

    plan = state.npc_plans.get(actor)
    if plan is None or plan.step_key != plan_step_key:
        return _blocked(step, "plan_missing", f"{actor} has no matching travel plan")

    # A dead NPC or a route that closed mid-journey is never teleported to the
    # destination: the position stays at the origin and the plan becomes terminal.
    if not state.npc_is_alive(actor):
        state.npc_plans[actor] = NPCTravelPlan(
            from_code=plan.from_code,
            to_code=plan.to_code,
            start_tick=plan.start_tick,
            expected_end_tick=plan.expected_end_tick,
            step_key=plan.step_key,
            status=PlanStatus.CANCELLED,
        )
        return _blocked(step, "npc_died_in_transit", f"{actor} died before arriving")
    if state.npc_positions.get(actor) != plan.from_code:
        state.npc_plans[actor] = NPCTravelPlan(
            from_code=plan.from_code,
            to_code=plan.to_code,
            start_tick=plan.start_tick,
            expected_end_tick=plan.expected_end_tick,
            step_key=plan.step_key,
            status=PlanStatus.BLOCKED,
        )
        return _blocked(step, "actor_moved_away", f"{actor} left {plan.from_code}")
    if not state.route_is_open(plan.from_code, plan.to_code):
        state.npc_plans[actor] = NPCTravelPlan(
            from_code=plan.from_code,
            to_code=plan.to_code,
            start_tick=plan.start_tick,
            expected_end_tick=plan.expected_end_tick,
            step_key=plan.step_key,
            status=PlanStatus.CANCELLED,
        )
        return _blocked(step, "route_closed", "the route closed during the journey")

    state.npc_positions[actor] = plan.to_code
    state.npc_plans[actor] = NPCTravelPlan(
        from_code=plan.from_code,
        to_code=plan.to_code,
        start_tick=plan.start_tick,
        expected_end_tick=plan.expected_end_tick,
        step_key=plan.step_key,
        status=PlanStatus.ARRIVED,
    )

    visible = _player_sees(state, plan.to_code)
    payload = {"npc_id": actor, "from": plan.from_code, "to": plan.to_code}
    return StepEffect(
        status=StepStatus.APPLIED,
        events=(
            SimulationEventDraft(
                event_type="npc_arrived",
                visibility_scope="player_visible" if visible else "hidden",
                target_ids=(plan.to_code,),
                public_payload=payload if visible else None,
                private_payload=None if visible else payload,
                result_json={"status": StepStatus.APPLIED},
                cognition=(
                    CognitionDraft(
                        subject_type="npc",
                        subject_ref=actor,
                        content=f"我抵达了{plan.to_code}。",
                        memory_kind="action",
                    ),
                ),
            ),
        ),
        deltas=(
            SimulationDeltaDraft(
                path=f"npcs.{actor}.location",
                operation="set",
                old_value=plan.from_code,
                new_value=plan.to_code,
                visibility_scope="player_visible" if visible else "hidden",
            ),
        ),
    )


def _handle_npc_take_item(
    rules: TrialRules,
    state: WorkingState,
    step: ScheduledStep,
    player_action: PlayerActionSpec,
) -> StepEffect:
    actor = step.actor_code
    item_code = step.payload.get("item")
    if item_code != state.item_code:
        return _blocked(step, "item_unknown", f"unknown item {item_code!r}")
    if not state.npc_is_alive(actor):
        return _blocked(step, "npc_not_alive", f"{actor} is not alive")
    if state.item_quantity != 1:
        raise TimeSimulationStateError(
            f"the unique item invariant is broken: quantity={state.item_quantity}"
        )

    actor_location = state.npc_positions.get(actor)
    if state.item_owner_type != "location":
        # Someone already holds it. This is the explicit, effect-free failure the
        # competition contract requires -- never a second copy for the loser.
        visible = _player_sees(state, actor_location)
        return StepEffect(
            status=StepStatus.BLOCKED,
            events=(
                SimulationEventDraft(
                    event_type="item_take_failed",
                    visibility_scope="player_visible" if visible else "hidden",
                    target_ids=(item_code,),
                    public_payload=(
                        {"npc_id": actor, "item": item_code, "reason": "already_taken"}
                        if visible
                        else None
                    ),
                    private_payload=(
                        None
                        if visible
                        else {"npc_id": actor, "item": item_code, "reason": "already_taken"}
                    ),
                    result_json={
                        "status": StepStatus.BLOCKED,
                        "owner_type": state.item_owner_type,
                        "owner_ref": state.item_owner_ref,
                    },
                    cognition=(
                        CognitionDraft(
                            subject_type="npc",
                            subject_ref=actor,
                            content=f"{item_code} 已经被 {state.item_owner_ref} 取走，我晚了一步。",
                            memory_kind="observation",
                        ),
                    ),
                ),
            ),
            detail_code="item_already_owned",
            detail_message=f"{item_code} is already owned by {state.item_owner_ref}",
        )

    if actor_location != state.item_owner_ref:
        return _blocked(step, "actor_not_at_item", f"{actor} is not at the item")

    previous_owner = state.item_owner_ref
    state.item_owner_type = "npc"
    state.item_owner_ref = actor

    visible = _player_sees(state, actor_location)
    payload = {"npc_id": actor, "item": item_code, "from": previous_owner, "to": actor}
    return StepEffect(
        status=StepStatus.APPLIED,
        events=(
            SimulationEventDraft(
                event_type="item_acquired",
                visibility_scope="player_visible" if visible else "hidden",
                target_ids=(item_code,),
                public_payload=payload if visible else None,
                private_payload=None if visible else payload,
                result_json={"status": StepStatus.APPLIED, "owner_ref": actor},
                cognition=(
                    CognitionDraft(
                        subject_type="npc",
                        subject_ref=actor,
                        content=f"我取得了{item_code}。",
                        memory_kind="action",
                    ),
                ),
            ),
        ),
        deltas=(
            SimulationDeltaDraft(
                path=f"inventory.{item_code}.owner",
                operation="set",
                old_value={"owner_type": "location", "owner_ref": previous_owner},
                new_value={"owner_type": "npc", "owner_ref": actor},
                visibility_scope="hidden",
            ),
        ),
    )


def _handle_npc_use_item(
    rules: TrialRules,
    state: WorkingState,
    step: ScheduledStep,
    player_action: PlayerActionSpec,
) -> StepEffect:
    actor = step.actor_code
    item_code = step.payload.get("item")
    if item_code != state.item_code:
        return _blocked(step, "item_unknown", f"unknown item {item_code!r}")
    if not state.npc_is_alive(actor):
        return _blocked(step, "npc_not_alive", f"{actor} is not alive")

    owns = state.item_owner_type == "npc" and state.item_owner_ref == actor
    if not owns:
        # Reads the *latest* owner, so an earlier same-session transfer is visible.
        visible = _player_sees(state, state.npc_positions.get(actor))
        return StepEffect(
            status=StepStatus.BLOCKED,
            events=(
                SimulationEventDraft(
                    event_type="item_use_failed",
                    visibility_scope="player_visible" if visible else "hidden",
                    target_ids=(item_code,),
                    public_payload=(
                        {"npc_id": actor, "item": item_code, "reason": "not_owner"}
                        if visible
                        else None
                    ),
                    private_payload=(
                        None
                        if visible
                        else {"npc_id": actor, "item": item_code, "reason": "not_owner"}
                    ),
                    result_json={
                        "status": StepStatus.BLOCKED,
                        "owner_type": state.item_owner_type,
                        "owner_ref": state.item_owner_ref,
                    },
                    cognition=(
                        CognitionDraft(
                            subject_type="npc",
                            subject_ref=actor,
                            content=(
                                f"我想使用{item_code}，但它属于 "
                                f"{state.item_owner_ref}，我无法动用。"
                            ),
                            memory_kind="observation",
                        ),
                    ),
                ),
            ),
            detail_code="item_not_owned",
            detail_message=f"{actor} does not own {item_code}",
        )

    one_shot_key = f"item_used:{actor}"
    if state.one_shot.get(one_shot_key):
        return StepEffect(
            status=StepStatus.CANCELLED,
            detail_code="already_used",
            detail_message=f"{actor} already used {item_code}",
        )
    state.one_shot[one_shot_key] = True

    visible = _player_sees(state, state.npc_positions.get(actor))
    payload = {"npc_id": actor, "item": item_code, "effect": "token_attuned"}
    return StepEffect(
        status=StepStatus.APPLIED,
        events=(
            SimulationEventDraft(
                event_type="item_used",
                visibility_scope="player_visible" if visible else "hidden",
                target_ids=(item_code,),
                public_payload=payload if visible else None,
                private_payload=None if visible else payload,
                result_json={"status": StepStatus.APPLIED},
                cognition=(
                    CognitionDraft(
                        subject_type="npc",
                        subject_ref=actor,
                        content=f"我使用了{item_code}。",
                        memory_kind="action",
                    ),
                ),
            ),
        ),
        deltas=(
            SimulationDeltaDraft(
                path=f"inventory.{item_code}.used_by",
                operation="set",
                old_value=None,
                new_value=actor,
                visibility_scope="hidden",
            ),
        ),
    )


def _handle_environment_interrupt(
    rules: TrialRules,
    state: WorkingState,
    step: ScheduledStep,
    player_action: PlayerActionSpec,
) -> StepEffect:
    one_shot_key = step.payload.get("one_shot_key") or INTERRUPT_ONE_SHOT_KEY
    if state.one_shot.get(one_shot_key):
        # A fixed step whose condition no longer holds reaches an explicit terminal
        # state instead of being retried every turn.
        return StepEffect(
            status=StepStatus.CANCELLED,
            detail_code="already_fired",
            detail_message="the trial interrupt already fired",
        )
    state.one_shot[one_shot_key] = True

    perceivers = tuple(
        CognitionDraft(
            subject_type="npc",
            subject_ref=code,
            content="试炼钟声响起，峰顶阵法出现扰动。",
            memory_kind="observation",
        )
        for code, alive in sorted(state.npc_alive.items())
        if alive
    )
    return StepEffect(
        status=StepStatus.APPLIED,
        interrupts_player=True,
        events=(
            SimulationEventDraft(
                event_type="world_interrupt",
                # The bell and the formation disturbance are perceivable from every
                # location of this slice; that is what makes the interruption fair.
                visibility_scope="player_visible",
                target_ids=(),
                public_payload={
                    "kind": "trial_bell",
                    "message": "试炼钟声自峰顶传来，阵法微微扰动。",
                    "tick": step.tick,
                },
                result_json={"status": StepStatus.APPLIED, "one_shot_key": one_shot_key},
                cognition=perceivers,
            ),
        ),
        deltas=(
            SimulationDeltaDraft(
                path="world.flags.trial_interrupt",
                operation="set",
                old_value=None,
                new_value=True,
                visibility_scope="player_visible",
            ),
        ),
    )


def _handle_player_continuous_complete(
    rules: TrialRules,
    state: WorkingState,
    step: ScheduledStep,
    player_action: PlayerActionSpec,
) -> StepEffect:
    action_kind = step.payload.get("action_kind")
    if action_kind != player_action.kind:
        raise TimeSimulationStateError(
            "player completion step does not match the adjudicated player action"
        )

    if action_kind == PlayerActionKind.IDLE:
        state.player_action_status = "completed"
        return StepEffect(
            status=StepStatus.APPLIED,
            events=(
                SimulationEventDraft(
                    event_type="player_action_completed",
                    visibility_scope="player_visible",
                    target_ids=(),
                    public_payload={
                        "action_type": player_action.action_type,
                        "action_kind": action_kind,
                        "tick": step.tick,
                    },
                    result_json={"status": StepStatus.APPLIED},
                ),
            ),
        )

    target = player_action.target_location_code
    if not state.player_alive:
        return _blocked(step, "player_not_alive", "the player is not alive")
    if not isinstance(target, str) or not target:
        return _blocked(step, "missing_target", "the move has no target location")
    if not state.route_is_open(state.player_location_code, target):
        return _blocked(step, "route_closed", f"route to {target} is closed")

    previous_location = state.player_location_code
    state.player_location_code = target
    state.player_arrival_task_code = rules.arrival_task_for(target)
    state.player_action_status = "completed"
    return StepEffect(
        status=StepStatus.APPLIED,
        events=(
            SimulationEventDraft(
                event_type="player_move_completed",
                visibility_scope="player_visible",
                target_ids=(target,),
                public_payload={
                    "from": previous_location,
                    "to": target,
                    "arrival_task": state.player_arrival_task_code,
                    "tick": step.tick,
                },
                result_json={"status": StepStatus.APPLIED},
            ),
        ),
        deltas=(
            SimulationDeltaDraft(
                path="player.location_id",
                operation="set",
                old_value=previous_location,
                new_value=target,
                visibility_scope="player_visible",
            ),
        ),
    )


_HANDLERS = {
    StepKind.NPC_TRAVEL_START: _handle_npc_travel_start,
    StepKind.NPC_TRAVEL_ARRIVE: _handle_npc_travel_arrive,
    StepKind.NPC_TAKE_ITEM: _handle_npc_take_item,
    StepKind.NPC_USE_ITEM: _handle_npc_use_item,
    StepKind.ENVIRONMENT_INTERRUPT: _handle_environment_interrupt,
    StepKind.PLAYER_CONTINUOUS_COMPLETE: _handle_player_continuous_complete,
}


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def build_trial_rules(*, interrupt_enabled: bool = True) -> TrialRules:
    """Build the fixed rule set (``interrupt_enabled=False`` is the test variant)."""
    return TrialRules(interrupt_enabled=interrupt_enabled)


_PRODUCTION_RULES: Optional[TrialRules] = None


def get_trial_rules() -> TrialRules:
    """The production singleton: the interrupt is always enabled."""
    global _PRODUCTION_RULES
    if _PRODUCTION_RULES is None:
        _PRODUCTION_RULES = build_trial_rules(interrupt_enabled=True)
    return _PRODUCTION_RULES


__all__ = [
    "MICRO_WORLD_CODE",
    "MICRO_WORLD_NAME",
    "LOCATION_MOUNTAIN_GATE",
    "LOCATION_PLAZA",
    "LOCATION_TRIAL_PEAK",
    "NPC_A_CODE",
    "NPC_B_CODE",
    "TOKEN_ITEM_CODE",
    "ROUTE_GATE_TO_PLAZA",
    "ROUTE_PLAZA_TO_PEAK",
    "ROUTES",
    "START_HOUR",
    "START_MINUTE",
    "START_TICK",
    "IDLE_DURATION_MINUTES",
    "INSPECT_DURATION_MINUTES",
    "MOVE_DURATION_MINUTES",
    "TICK_NPC_A_DEPART",
    "TICK_NPC_A_ARRIVE",
    "TICK_ITEM_CONTEST",
    "TICK_NPC_B_USE",
    "TICK_INTERRUPT",
    "TICK_NPC_B_DEPART",
    "TICK_NPC_B_ARRIVE",
    "INTERRUPT_ONE_SHOT_KEY",
    "ROUTE_OPEN_RULE_KEY",
    "NPC_ALIVE_FLAG_KEY",
    "ARRIVAL_TASK_BY_LOCATION",
    "LocationSpec",
    "NPCSpec",
    "ItemSpec",
    "WORLD_SPEC",
    "LOCATION_SPECS",
    "NPC_SPECS",
    "ITEM_SPEC",
    "SCHEDULED_STEP_SPECS",
    "profile_marker",
    "is_interrupt_step",
    "CognitionDraft",
    "SimulationEventDraft",
    "SimulationDeltaDraft",
    "StepEffect",
    "TrialRules",
    "build_trial_rules",
    "get_trial_rules",
]

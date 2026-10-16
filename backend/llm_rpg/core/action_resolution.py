"""Phase 2: domain adjudication of authorized actions.

The engine — not the model — decides what actually happens, what fact events are
recorded, what deltas are audited and what necessary cognition follows.

This module is the single place where an :class:`AuthorizedAction` becomes a
:class:`ResolvedAction`. It exists so that one domain result drives all four
downstream consumers at once (actual write, fact event, delta audit, result
projection) instead of state being written by one code path and the audit being
guessed by another later.

Boundaries kept deliberately:

* It never writes to the database and never commits; it returns pure data.
* It does not own world time: the existing per-action-class time rules stay the
  authority, so no action's default cost silently changes here.
* It reuses the existing movement handler, scene-transition resolver and movement
  validator rather than re-implementing game rules.
* Model text can only become a *quoted utterance* or a bounded *display hint*. It
  never becomes a state value, a numeric result or a truth claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..models.states import CanonicalState
from .action_authorization import AuthorizedAction
from .action_reason import ActionDetailCode, ActionReasonCode, ActionStatus
from .movement_handler import MovementResult, handle_movement
from .validation.context import ValidationContext


class ResolvedEventKind(str, Enum):
    """Kind of engine fact this resolution produces."""

    ACTION_RESOLVED = "action_resolved"
    MOVEMENT_BLOCKED = "movement_blocked"
    PLAYER_TALK = "player_talk"
    PLAYER_INSPECT = "player_inspect"
    PLAYER_IDLE = "player_idle"
    NPC_OBSERVE = "npc_observe"
    NPC_IDLE = "npc_idle"
    NPC_TALK = "npc_talk"
    NPC_REFUSE = "npc_refuse"
    WORLD_REFERENCE = "world_reference"
    SCENE_REFERENCE = "scene_reference"


#: Kinds whose payload text is a *quotation*, not a truth claim.
SPEECH_EVENT_KINDS = frozenset(
    {
        ResolvedEventKind.PLAYER_TALK,
        ResolvedEventKind.NPC_TALK,
        ResolvedEventKind.NPC_REFUSE,
    }
)


class CognitionKind(str, Enum):
    """Necessary cognition the engine derives from an adjudicated event."""

    FACT = "fact"
    BELIEF = "belief"
    SUMMARY = "summary"


@dataclass(frozen=True)
class ResolvedEvent:
    """One engine fact event this turn will write.

    ``game_event_type`` is the ``game_events.event_type`` the caller persists; it
    is ``None`` for a fact that is carried by an event the turn already writes
    (so resolution never duplicates an existing row).
    """

    kind: ResolvedEventKind
    actor_id: str
    action_type: str
    game_event_type: Optional[str] = None
    target_ids: Tuple[str, ...] = ()
    visibility_scope: str = "player_visible"
    public_payload: Optional[Dict[str, Any]] = None
    private_payload: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    #: True when this event is the causal action a delta may point at.
    is_action_cause: bool = False

    @property
    def carries_speech(self) -> bool:
        return self.kind in SPEECH_EVENT_KINDS


@dataclass(frozen=True)
class ResolvedCognition:
    """One necessary cognition write, bound to its engine source event.

    ``source_event_kind`` names the :class:`ResolvedEvent` this cognition is
    derived from, so a memory can always be traced to a committed fact event
    rather than to model text.
    """

    kind: CognitionKind
    content: str
    source_event_kind: ResolvedEventKind
    fact_type: Optional[str] = None
    subject_ref: Optional[str] = None
    fact_key: Optional[str] = None
    belief_type: Optional[str] = None
    scope_type: Optional[str] = None
    scope_ref_id: Optional[str] = None
    importance: float = 0.5
    confidence: float = 0.5
    #: True when the content is a quotation that must never be read as truth.
    is_speech: bool = False


@dataclass
class ResolvedAction:
    """The complete engine adjudication of one authorized action."""

    action: Optional[AuthorizedAction]
    status: ActionStatus
    reason_code: Optional[ActionReasonCode] = None
    detail_code: Optional[ActionDetailCode] = None
    detail_message: str = ""
    movement_result: Optional[MovementResult] = None
    #: Engine-decided state changes for this action (audit/result projection).
    state_changes: Dict[str, Any] = field(default_factory=dict)
    events: List[ResolvedEvent] = field(default_factory=list)
    cognition: List[ResolvedCognition] = field(default_factory=list)
    audit: Dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.status == ActionStatus.ACCEPTED

    def action_cause_event(self) -> Optional[ResolvedEvent]:
        """The engine event a state delta may point at as its cause."""
        for event in self.events:
            if event.is_action_cause:
                return event
        return None


def reject_action(
    action: Optional[AuthorizedAction],
    detail: ActionDetailCode,
    message: str = "",
    *,
    reason: Optional[ActionReasonCode] = None,
) -> ResolvedAction:
    """Build a rejected resolution (the action effect is refused)."""
    from .action_reason import public_reason_for_detail

    return ResolvedAction(
        action=action,
        status=ActionStatus.REJECTED,
        reason_code=reason or public_reason_for_detail(detail) or ActionReasonCode.INVALID_PARAMS,
        detail_code=detail,
        detail_message=message,
    )


def _action_cause_event(
    action: AuthorizedAction,
    target_ids: Sequence[str],
    public_payload: Dict[str, Any],
    result_json: Optional[Dict[str, Any]] = None,
) -> ResolvedEvent:
    return ResolvedEvent(
        kind=ResolvedEventKind.ACTION_RESOLVED,
        actor_id=action.actor_id,
        action_type=action.action_type,
        game_event_type="action_resolved",
        target_ids=tuple(target_ids),
        visibility_scope="player_visible",
        public_payload=public_payload,
        result_json=result_json,
        is_action_cause=True,
    )


# ---------------------------------------------------------------------------
# Player actions
# ---------------------------------------------------------------------------


@dataclass
class MovementResolutionContext:
    """Inputs the movement path needs, kept explicit instead of re-read."""

    db: Session
    session_id: str
    canonical_state: CanonicalState
    turn_no: int = 0
    validation_context: Optional[ValidationContext] = None
    current_location_id: Optional[str] = None
    defer_location_write: bool = True
    planned_session_state: Optional[Any] = None
    planned_player_state: Optional[Any] = None


def resolve_player_move(
    action: AuthorizedAction,
    movement: MovementResolutionContext,
) -> ResolvedAction:
    """Adjudicate a player move through the existing movement rules.

    Reuses the scene-transition resolver, the movement validator (with the
    explicit player perspective from the validation context) and the movement
    handler. The location write stays planned when ``defer_location_write`` is set,
    so preparation remains write-free.
    """
    from ..engines.scene_transition import SceneTransitionResolver
    from .validation.movement_validator import MovementValidator
    from ..models.common import ProposedAction

    from_location_id = movement.current_location_id or ""
    target_location_code = action.target_location_code or ""
    target_location_id = action.target_location_id or target_location_code

    scene_transition_resolver = SceneTransitionResolver()
    can_move, blocked_reason = scene_transition_resolver.can_move_to(
        from_location=from_location_id,
        to_location=target_location_code or target_location_id,
        game_state={
            "player_location": from_location_id,
            "current_turn": movement.turn_no,
        },
    )

    if not can_move:
        reason = blocked_reason or "Movement blocked by scene"
        return ResolvedAction(
            action=action,
            status=ActionStatus.REJECTED,
            reason_code=ActionReasonCode.TARGET_UNAVAILABLE,
            detail_code=ActionDetailCode.DOMAIN_RULE_BLOCKED,
            detail_message=reason,
            movement_result=MovementResult(
                success=False,
                blocked_reason=reason,
                previous_location_id=from_location_id,
            ),
            state_changes={"blocked_reason": reason},
            events=[
                ResolvedEvent(
                    kind=ResolvedEventKind.MOVEMENT_BLOCKED,
                    actor_id=action.actor_id,
                    action_type=action.action_type,
                    game_event_type="movement_blocked",
                    target_ids=(target_location_id,),
                    visibility_scope="player_visible",
                    public_payload={
                        "from_location_id": from_location_id,
                        "to_location_id": target_location_id,
                        "blocked_reason": reason,
                    },
                    # The refusal *is* this turn's adjudicated action outcome, so it is
                    # the causal event a time delta must point at (never narration).
                    is_action_cause=True,
                )
            ],
            audit={"rule": "scene_transition", "blocked_reason": reason},
        )

    movement_action = ProposedAction(
        action_id="turn-move",
        actor_id=action.actor_id,
        action_type="move",
        target_ids=[target_location_code or target_location_id],
        summary=f"移动到 {target_location_code or target_location_id}",
    )
    movement_validator = MovementValidator()
    movement_validation = movement_validator.validate_movement(
        action=movement_action,
        state=movement.canonical_state,
        context=movement.validation_context,
    )

    if not movement_validation.is_valid:
        first_error = (
            movement_validation.errors[0]
            if movement_validation.errors
            else "Movement validation failed"
        )
        return ResolvedAction(
            action=action,
            status=ActionStatus.REJECTED,
            reason_code=ActionReasonCode.TARGET_UNAVAILABLE,
            detail_code=ActionDetailCode.DOMAIN_RULE_BLOCKED,
            detail_message=first_error,
            movement_result=MovementResult(
                success=False,
                blocked_reason=first_error,
                previous_location_id=from_location_id,
            ),
            state_changes={"blocked_reason": first_error},
            audit={
                "rule": "movement_validator",
                "errors": list(movement_validation.errors),
            },
        )

    movement_result = handle_movement(
        movement.db,
        movement.session_id,
        action.target_location_code or target_location_id,
        defer_location_write=movement.defer_location_write,
        planned_session_state=movement.planned_session_state,
        planned_player_state=movement.planned_player_state,
    )

    if not movement_result.success:
        reason = movement_result.blocked_reason or "Movement failed"
        return ResolvedAction(
            action=action,
            status=ActionStatus.REJECTED,
            reason_code=ActionReasonCode.TARGET_UNAVAILABLE,
            detail_code=ActionDetailCode.DOMAIN_RULE_BLOCKED,
            detail_message=reason,
            movement_result=movement_result,
            state_changes={"blocked_reason": reason},
            audit={"rule": "movement_handler", "blocked_reason": reason},
        )

    cause = _action_cause_event(
        action,
        target_ids=(movement_result.new_location_id or target_location_id,),
        public_payload={
            "action_type": action.action_type,
            "from_location_id": from_location_id,
            "to_location_id": movement_result.new_location_id,
            "to_location_code": movement_result.new_location_code,
        },
        result_json={"movement_success": True},
    )
    return ResolvedAction(
        action=action,
        status=ActionStatus.ACCEPTED,
        movement_result=movement_result,
        state_changes={
            "location_id": movement_result.new_location_id,
            "new_location_code": movement_result.new_location_code,
        },
        events=[cause],
        cognition=[
            ResolvedCognition(
                kind=CognitionKind.FACT,
                content=str(movement_result.new_location_name or movement_result.new_location_code or ""),
                source_event_kind=ResolvedEventKind.ACTION_RESOLVED,
                fact_type="location_change",
                subject_ref="player",
                fact_key="current_location",
                importance=1.0,
                confidence=1.0,
            )
        ],
        audit={"rule": "movement_handler", "deferred_write": movement.defer_location_write},
    )


def resolve_player_talk(action: AuthorizedAction) -> ResolvedAction:
    """Adjudicate a player talk: speech only, no physical effect.

    The engine promises nothing about a reply, a relationship change or a quest
    reward. What is recorded is that the player addressed the target about a
    bounded topic.
    """
    target_ids: Tuple[str, ...] = ()
    payload: Dict[str, Any] = {"action_type": action.action_type}
    if action.target_npc_id:
        target_ids = (action.target_npc_id,)
        payload["target_npc_id"] = action.target_npc_id
    if action.topic:
        payload["topic"] = action.topic

    # The action still gets its own engine fact event: the turn's time delta must
    # point at the adjudicated *action*, never at the narration presentation event.
    event = _action_cause_event(
        action,
        target_ids=target_ids,
        public_payload=payload,
        result_json={"physical_effect": False},
    )
    return ResolvedAction(
        action=action,
        status=ActionStatus.ACCEPTED,
        state_changes={},
        events=[event],
        audit={"rule": "player_talk", "physical_effect": False},
    )


def resolve_player_inspect(action: AuthorizedAction) -> ResolvedAction:
    """Adjudicate a player inspect: existing visible information only."""
    target_ids: Tuple[str, ...] = ()
    payload: Dict[str, Any] = {"action_type": action.action_type}
    if action.target_npc_id:
        target_ids = (action.target_npc_id,)
        payload["target_npc_id"] = action.target_npc_id

    return ResolvedAction(
        action=action,
        status=ActionStatus.ACCEPTED,
        state_changes={},
        events=[_action_cause_event(
            action,
            target_ids=target_ids,
            public_payload=payload,
            result_json={"physical_effect": False, "new_information": False},
        )],
        audit={"rule": "player_inspect", "physical_effect": False, "new_information": False},
    )


def resolve_player_idle(action: AuthorizedAction) -> ResolvedAction:
    """Adjudicate a player idle/wait: the engine owns the duration."""
    return ResolvedAction(
        action=action,
        status=ActionStatus.ACCEPTED,
        state_changes={},
        events=[_action_cause_event(
            action,
            target_ids=(),
            public_payload={"action_type": action.action_type},
            result_json={"physical_effect": False},
        )],
        audit={"rule": "player_idle", "physical_effect": False},
    )


def resolve_player_action(
    action: AuthorizedAction,
    movement: Optional[MovementResolutionContext] = None,
) -> ResolvedAction:
    """Dispatch an authorized player action to its domain handler."""
    if action.handler == "player_move":
        if movement is None:
            return reject_action(
                action,
                ActionDetailCode.DOMAIN_RULE_BLOCKED,
                "movement resolution context missing",
            )
        return resolve_player_move(action, movement)
    if action.handler == "player_talk":
        return resolve_player_talk(action)
    if action.handler == "player_inspect":
        return resolve_player_inspect(action)
    if action.handler == "player_idle":
        return resolve_player_idle(action)
    return reject_action(
        action, ActionDetailCode.NO_HANDLER, f"no handler for {action.handler!r}"
    )


# ---------------------------------------------------------------------------
# NPC actions
# ---------------------------------------------------------------------------


def _engine_action_record(action: AuthorizedAction) -> str:
    """Engine-authored one-line record of an adjudicated NPC action."""
    who = action.target_npc_name or action.actor_id
    if action.action_type == "observe":
        return f"{who}观察了当前场景"
    if action.action_type == "idle":
        return f"{who}在原地等待"
    return f"{who}执行了{action.action_type}动作"


def resolve_npc_action(action: AuthorizedAction) -> ResolvedAction:
    """Adjudicate an NPC action: controlled observation, wait or speech.

    No NPC action in this phase changes state. A talk/refuse records only that the
    sentence was said — never that its proposition is true.
    """
    kind_map = {
        "observe": ResolvedEventKind.NPC_OBSERVE,
        "idle": ResolvedEventKind.NPC_IDLE,
        "talk": ResolvedEventKind.NPC_TALK,
        "refuse": ResolvedEventKind.NPC_REFUSE,
    }
    kind = kind_map.get(action.action_type)
    if kind is None:
        return reject_action(
            action,
            ActionDetailCode.NO_HANDLER,
            f"no NPC handler for {action.action_type!r}",
        )

    target_ids: Tuple[str, ...] = ()
    if action.target_npc_id:
        target_ids = (action.target_npc_id,)
    elif action.action_type in ("talk", "refuse"):
        target_ids = ("player",)

    payload: Dict[str, Any] = {
        "npc_name": action.target_npc_name,
        "action_type": action.action_type,
        "summary": action.summary,
        "visible_motivation": action.visible_motivation,
        "physical_effect": False,
    }
    if action.utterance:
        # Named explicitly so no reader can mistake a quotation for a fact.
        payload["utterance"] = action.utterance
        payload["utterance_is_claim"] = False

    cognition: List[ResolvedCognition] = []
    if kind in SPEECH_EVENT_KINDS:
        spoken = action.utterance or action.summary or ""
        if spoken:
            cognition.append(
                ResolvedCognition(
                    kind=CognitionKind.BELIEF,
                    content=f"{action.target_npc_name or action.actor_id}说：{spoken}",
                    source_event_kind=kind,
                    belief_type="speech",
                    importance=0.4,
                    confidence=0.5,
                    is_speech=True,
                )
            )
    else:
        # The retrievable cognition is authored by the engine from the adjudicated
        # action. The model's ``summary`` stays a presentation field on the event
        # payload and is deliberately *not* copied into a retrievable memory.
        engine_text = _engine_action_record(action)
        if engine_text:
            cognition.append(
                ResolvedCognition(
                    kind=CognitionKind.SUMMARY,
                    content=engine_text,
                    source_event_kind=kind,
                    scope_type="npc",
                    importance=0.6,
                    confidence=0.6,
                )
            )

    return ResolvedAction(
        action=action,
        status=ActionStatus.ACCEPTED,
        state_changes={},
        events=[
            ResolvedEvent(
                kind=kind,
                actor_id=action.actor_id,
                action_type=action.action_type,
                game_event_type="npc_decision",
                target_ids=target_ids,
                visibility_scope="player_visible" if action.visible_to_player else "hidden",
                public_payload=payload if action.visible_to_player else None,
                private_payload=None if action.visible_to_player else payload,
                result_json={"physical_effect": False},
            )
        ],
        cognition=cognition,
        audit={
            "rule": f"npc_{action.action_type}",
            "physical_effect": False,
            "used_memory_ids": list(action.used_memory_ids),
        },
    )


# ---------------------------------------------------------------------------
# World / scene references
# ---------------------------------------------------------------------------


def resolve_world_reference(action: AuthorizedAction) -> ResolvedAction:
    """Adjudicate a world-stage proposal: organize already-decided results."""
    return ResolvedAction(
        action=action,
        status=ActionStatus.ACCEPTED,
        state_changes={},
        events=[
            ResolvedEvent(
                kind=ResolvedEventKind.WORLD_REFERENCE,
                actor_id="world_engine",
                action_type="reference",
                game_event_type="world_tick",
                target_ids=tuple(action.referenced_event_ids),
                visibility_scope="player_visible",
                public_payload={
                    "referenced_event_ids": list(action.referenced_event_ids),
                    "display_hint": action.display_hint,
                },
                result_json={"creates_facts": False},
            )
        ],
        audit={"rule": "world_reference", "creates_facts": False},
    )


def resolve_scene_reference(action: AuthorizedAction) -> ResolvedAction:
    """Adjudicate a scene-stage proposal: reference events, select legal actions."""
    return ResolvedAction(
        action=action,
        status=ActionStatus.ACCEPTED,
        state_changes={},
        events=[
            ResolvedEvent(
                kind=ResolvedEventKind.SCENE_REFERENCE,
                actor_id="scene_engine",
                action_type="reference",
                game_event_type="scene",
                target_ids=tuple(action.referenced_event_ids),
                visibility_scope="player_visible",
                public_payload={
                    "referenced_event_ids": list(action.referenced_event_ids),
                    "display_hint": action.display_hint,
                },
                result_json={
                    "creates_facts": False,
                    "recommended_actions": list(action.recommended_actions),
                },
            )
        ],
        audit={"rule": "scene_reference", "creates_facts": False},
    )


__all__ = [
    "ResolvedEventKind",
    "SPEECH_EVENT_KINDS",
    "CognitionKind",
    "ResolvedEvent",
    "ResolvedCognition",
    "ResolvedAction",
    "MovementResolutionContext",
    "reject_action",
    "resolve_player_move",
    "resolve_player_talk",
    "resolve_player_inspect",
    "resolve_player_idle",
    "resolve_player_action",
    "resolve_npc_action",
    "resolve_world_reference",
    "resolve_scene_reference",
]

"""Strict production output contract (contract_version=2) for LLM proposals.

This module is the *production wire schema* for every model-generated proposal
that reaches the authoritative turn path. It is deliberately separate from
``models/proposals.py``:

* ``proposals.py`` keeps the historical internal/auxiliary proposal types. Those
  types are permissive (free ``parameters``, ``state_deltas``, ``effects``) and
  remain valid for non-production callers, but they are **not** a wire schema and
  they are **not** an authorization credential.
* This module defines the only shapes a production model may return. Every model
  is recursive ``extra="forbid"``, uses closed literal sets and hard length
  bounds, and contains no executable field: no state deltas, no effects, no
  arbitrary paths/operations/values, no success flags, no damage/reward/
  relationship numbers, no time, no audit identity and no privilege fields.

Actor, session, transaction, turn, source, visibility ceiling and audit metadata
are produced by the server. The wire never carries them.

Free text (``summary``, ``visible_motivation``, ``utterance``, ``display_hint``,
``narration text``) is presentation or speech only. It is never an executable
parameter and never becomes an authoritative fact by itself.
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

#: Version stamped into every production proposal.
PRODUCTION_CONTRACT_VERSION = 2

#: Bounds fixed by the phase-2 contract (see the implementation plan section 3.2).
MAX_REFERENCED_EVENTS = 3
MAX_RECOMMENDED_ACTIONS = 4
MAX_DISPLAY_HINT_CHARS = 500
MAX_NPC_UTTERANCE_CHARS = 1000
MAX_TOPIC_CHARS = 240
MAX_CLARIFICATION_CHARS = 240
MAX_ID_CHARS = 128
MAX_SUMMARY_CHARS = 500
MAX_MEMORY_IDS = 32
MAX_USED_MEMORY_IDS = 32


class StrictContractModel(BaseModel):
    """Base class: unknown fields are rejected at every nesting level."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Player intent (input_intent stage)
# ---------------------------------------------------------------------------

#: Actions the engine has an authorized domain handler for in this phase.
AUTHORIZED_PLAYER_ACTIONS = ("move", "talk", "inspect", "idle")

#: Actions that keep their existing input classification and time cost but have
#: no authorized domain handler: the engine must answer unsupported/no-effect.
UNSUPPORTED_PLAYER_ACTIONS = ("attack", "interact", "action", "unknown")


class MoveIntentParams(StrictContractModel):
    """Move to one currently selectable location. No other effect parameter."""

    action_type: Literal["move"]
    target_location_id: Optional[str] = Field(default=None, max_length=MAX_ID_CHARS)


class TalkIntentParams(StrictContractModel):
    """Talk to an optional same-scene visible NPC about a bounded topic."""

    action_type: Literal["talk"]
    target_npc_id: Optional[str] = Field(default=None, max_length=MAX_ID_CHARS)
    topic: Optional[str] = Field(default=None, max_length=MAX_TOPIC_CHARS)


class InspectIntentParams(StrictContractModel):
    """Inspect the current scene, or one same-scene visible NPC."""

    action_type: Literal["inspect"]
    target_npc_id: Optional[str] = Field(default=None, max_length=MAX_ID_CHARS)


class IdleIntentParams(StrictContractModel):
    """Wait. The engine owns the duration; the wire carries no duration."""

    action_type: Literal["idle"]


class UnsupportedIntentParams(StrictContractModel):
    """Declared-but-unauthorized actions, kept only to classify input and cost."""

    action_type: Literal["attack", "interact", "action", "unknown"]
    target: Optional[str] = Field(default=None, max_length=MAX_ID_CHARS)


PlayerIntentParams = Annotated[
    Union[
        MoveIntentParams,
        TalkIntentParams,
        InspectIntentParams,
        IdleIntentParams,
        UnsupportedIntentParams,
    ],
    Field(discriminator="action_type"),
]


class PlayerIntentV2(StrictContractModel):
    """Production player-intent proposal."""

    contract_version: Literal[2]
    intent: PlayerIntentParams
    needs_clarification: bool = False
    clarification_question: Optional[str] = Field(
        default=None, max_length=MAX_CLARIFICATION_CHARS
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# NPC action (npc stage)
# ---------------------------------------------------------------------------

#: NPC actions with an authorized domain handler in this phase. ``dialogue`` is
#: kept as a wire-level alias of ``talk`` and is adjudicated identically.
AUTHORIZED_NPC_ACTIONS = ("observe", "idle", "talk", "refuse")

#: Wire aliases that the engine normalizes to an authorized NPC action.
NPC_ACTION_ALIASES = {"dialogue": "talk"}


class NPCObserveParams(StrictContractModel):
    """Observe the current scene. No physical effect parameter."""

    action_type: Literal["observe"]


class NPCIdleParams(StrictContractModel):
    """Wait. No physical effect parameter."""

    action_type: Literal["idle"]


class NPCTalkParams(StrictContractModel):
    """Say something to an in-scene target. Speech only, no state change."""

    action_type: Literal["talk", "dialogue"]
    target_id: Optional[str] = Field(default=None, max_length=MAX_ID_CHARS)
    utterance: Optional[str] = Field(default=None, max_length=MAX_NPC_UTTERANCE_CHARS)


class NPCRefuseParams(StrictContractModel):
    """Refuse an in-scene target. Speech only, no state change."""

    action_type: Literal["refuse"]
    target_id: Optional[str] = Field(default=None, max_length=MAX_ID_CHARS)
    utterance: Optional[str] = Field(default=None, max_length=MAX_NPC_UTTERANCE_CHARS)


NPCActionParams = Annotated[
    Union[NPCObserveParams, NPCIdleParams, NPCTalkParams, NPCRefuseParams],
    Field(discriminator="action_type"),
]


class NPCActionV2(StrictContractModel):
    """Production NPC action proposal.

    The actor is bound by the server: the wire carries no ``npc_id``, no
    ``state_deltas``, no ``new_memory_candidates`` and no audit/decision fields.
    Necessary cognition is derived by the engine from the adjudicated events.
    """

    contract_version: Literal[2]
    action: NPCActionParams
    summary: str = Field(..., min_length=1, max_length=MAX_SUMMARY_CHARS)
    visible_motivation: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    visible_to_player: bool = True
    used_memory_ids: List[str] = Field(default_factory=list, max_length=MAX_USED_MEMORY_IDS)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# World / scene stages: reference-only, no free facts
# ---------------------------------------------------------------------------


class WorldTickV2(StrictContractModel):
    """Production world-stage proposal: organize results the engine already made.

    It may only reference this turn's engine events. It cannot create free
    facts, effects, deltas or time changes.
    """

    contract_version: Literal[2]
    referenced_event_ids: List[str] = Field(
        default_factory=list, max_length=MAX_REFERENCED_EVENTS
    )
    display_hint: Optional[str] = Field(default=None, max_length=MAX_DISPLAY_HINT_CHARS)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class SceneEventV2(StrictContractModel):
    """Production scene-stage proposal: reference this turn's engine events and
    select from the engine's legal recommended actions."""

    contract_version: Literal[2]
    referenced_event_ids: List[str] = Field(
        default_factory=list, max_length=MAX_REFERENCED_EVENTS
    )
    recommended_actions: List[str] = Field(
        default_factory=list, max_length=MAX_RECOMMENDED_ACTIONS
    )
    display_hint: Optional[str] = Field(default=None, max_length=MAX_DISPLAY_HINT_CHARS)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Narration (post-commit presentation only)
# ---------------------------------------------------------------------------


class NarrationV2(StrictContractModel):
    """Production narration proposal. Presentation text only."""

    contract_version: Literal[2]
    text: str = Field(..., min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Registry used by the strict parser / pipeline
# ---------------------------------------------------------------------------

#: Proposal-type key -> production DTO. Keys match ``ProposalType`` values.
PRODUCTION_CONTRACT_MODELS: dict[str, type[StrictContractModel]] = {
    "input_intent": PlayerIntentV2,
    "npc_action": NPCActionV2,
    "world_tick": WorldTickV2,
    "scene_event": SceneEventV2,
    "narration": NarrationV2,
}


def production_contract_model(proposal_type: str) -> type[StrictContractModel]:
    """Return the production DTO for a proposal type key.

    Raises:
        KeyError: when the proposal type has no production contract.
    """
    return PRODUCTION_CONTRACT_MODELS[proposal_type]


__all__ = [
    "PRODUCTION_CONTRACT_VERSION",
    "MAX_REFERENCED_EVENTS",
    "MAX_RECOMMENDED_ACTIONS",
    "MAX_DISPLAY_HINT_CHARS",
    "MAX_NPC_UTTERANCE_CHARS",
    "MAX_TOPIC_CHARS",
    "MAX_CLARIFICATION_CHARS",
    "MAX_ID_CHARS",
    "MAX_SUMMARY_CHARS",
    "MAX_MEMORY_IDS",
    "MAX_USED_MEMORY_IDS",
    "AUTHORIZED_PLAYER_ACTIONS",
    "UNSUPPORTED_PLAYER_ACTIONS",
    "AUTHORIZED_NPC_ACTIONS",
    "NPC_ACTION_ALIASES",
    "StrictContractModel",
    "MoveIntentParams",
    "TalkIntentParams",
    "InspectIntentParams",
    "IdleIntentParams",
    "UnsupportedIntentParams",
    "PlayerIntentParams",
    "PlayerIntentV2",
    "NPCObserveParams",
    "NPCIdleParams",
    "NPCTalkParams",
    "NPCRefuseParams",
    "NPCActionParams",
    "NPCActionV2",
    "WorldTickV2",
    "SceneEventV2",
    "NarrationV2",
    "PRODUCTION_CONTRACT_MODELS",
    "production_contract_model",
]

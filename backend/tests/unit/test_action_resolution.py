"""Phase 2 unit coverage: domain adjudication of authorized actions.

Scope (plan sections 3.1, 3.4, 3.5 and 5):

* the engine — not the model — decides what actually happens: a talk/inspect/idle
  action is speech/observation/waiting with no physical effect;
* an NPC talk records that a sentence was said, never that its proposition is true;
* the refused-action path produces no state change and no fact event;
* world/scene resolutions are reference-only: they organize engine results and
  create no facts, effects or state changes;
* resolution never writes to the database.

The tests drive :mod:`llm_rpg.core.action_resolution` directly with pure-data
authorized actions, so they need no turn service and no model provider.
"""

import pytest

from llm_rpg.core.action_authorization import AuthorizedAction
from llm_rpg.core.action_reason import ActionDetailCode, ActionReasonCode, ActionStatus
from llm_rpg.core.action_resolution import (
    CognitionKind,
    ResolvedAction,
    ResolvedEventKind,
    SPEECH_EVENT_KINDS,
    reject_action,
    resolve_npc_action,
    resolve_player_action,
    resolve_player_idle,
    resolve_player_inspect,
    resolve_player_talk,
    resolve_scene_reference,
    resolve_world_reference,
)
from llm_rpg.rules.action_schema import ActorRole, TimePolicy


def _player_action(handler, action_type, **kwargs):
    return AuthorizedAction(
        actor_id="player",
        actor_role=ActorRole.player,
        action_type=action_type,
        handler=handler,
        time_policy=TimePolicy.ENGINE_ADJUDICATED,
        **kwargs,
    )


def _npc_action(action_type, handler, **kwargs):
    return AuthorizedAction(
        actor_id="snpc-1",
        actor_role=ActorRole.npc,
        action_type=action_type,
        handler=handler,
        time_policy=TimePolicy.ENGINE_ADJUDICATED,
        **kwargs,
    )


class TestPlayerNonPhysicalActions:
    def test_talk_has_no_physical_effect(self):
        action = _player_action(
            "player_talk", "talk", target_npc_id="snpc-1", topic="宗门规矩"
        )
        resolved = resolve_player_talk(action)
        assert resolved.status is ActionStatus.ACCEPTED
        assert resolved.state_changes == {}
        assert resolved.audit["physical_effect"] is False
        # The action still gets its own engine fact event, and that event is the
        # causal source a time delta may point at (never the narration event).
        assert len(resolved.events) == 1
        assert resolved.events[0].game_event_type == "action_resolved"
        assert resolved.events[0].is_action_cause is True
        assert resolved.action_cause_event() is resolved.events[0]

    def test_talk_records_the_topic_but_promises_nothing(self):
        action = _player_action("player_talk", "talk", target_npc_id="snpc-1", topic="宝藏")
        resolved = resolve_player_talk(action)
        payload = resolved.events[0].public_payload
        assert payload["topic"] == "宝藏"
        # The engine never records a reply, a reward or a relationship change.
        for forbidden in ("reply", "reward", "relationship", "success", "quest_progress"):
            assert forbidden not in payload

    def test_untargeted_talk_is_only_a_scene_facing_attempt(self):
        action = _player_action("player_talk", "talk")
        resolved = resolve_player_talk(action)
        assert resolved.accepted
        assert resolved.events[0].target_ids == ()

    def test_inspect_returns_existing_information_only(self):
        action = _player_action("player_inspect", "inspect", target_npc_id="snpc-1")
        resolved = resolve_player_inspect(action)
        assert resolved.accepted
        assert resolved.state_changes == {}
        assert resolved.events[0].result_json["new_information"] is False
        assert resolved.events[0].result_json["physical_effect"] is False

    def test_idle_does_not_choose_its_own_duration(self):
        action = _player_action("player_idle", "idle")
        resolved = resolve_player_idle(action)
        assert resolved.accepted
        assert resolved.state_changes == {}
        # No duration field: the existing per-action-class time rules own the cost.
        assert "elapsed_minutes" not in resolved.events[0].public_payload
        assert "duration" not in resolved.events[0].public_payload

    def test_player_action_without_a_handler_is_refused(self):
        action = _player_action("player_unknown_handler", "action")
        resolved = resolve_player_action(action, None)
        assert resolved.status is ActionStatus.REJECTED
        assert resolved.detail_code is ActionDetailCode.NO_HANDLER
        assert resolved.reason_code is ActionReasonCode.UNSUPPORTED

    def test_move_without_a_movement_context_is_refused_not_executed(self):
        action = _player_action(
            "player_move", "move", target_location_id="loc-1", target_location_code="trial_hall"
        )
        resolved = resolve_player_action(action, None)
        assert resolved.status is ActionStatus.REJECTED
        assert resolved.movement_result is None


class TestNpcActions:
    def test_observe_is_a_controlled_observation(self):
        action = _npc_action("observe", "npc_observe", summary="向导静静看着")
        resolved = resolve_npc_action(action)
        assert resolved.accepted
        assert resolved.state_changes == {}
        assert resolved.events[0].kind is ResolvedEventKind.NPC_OBSERVE
        assert resolved.events[0].game_event_type == "npc_decision"

    def test_idle_is_a_controlled_wait(self):
        action = _npc_action("idle", "npc_idle", summary="向导等待着")
        resolved = resolve_npc_action(action)
        assert resolved.accepted
        assert resolved.events[0].kind is ResolvedEventKind.NPC_IDLE

    def test_talk_records_speech_not_truth(self):
        action = _npc_action(
            "talk", "npc_talk", utterance="北边有妖物", target_npc_id="snpc-2",
            target_npc_name="向导", summary="向导开口",
        )
        resolved = resolve_npc_action(action)
        assert resolved.accepted
        payload = resolved.events[0].public_payload
        assert payload["utterance"] == "北边有妖物"
        # The payload marks the sentence as a claim, not a fact.
        assert payload["utterance_is_claim"] is False
        assert resolved.events[0].kind in SPEECH_EVENT_KINDS

        beliefs = [c for c in resolved.cognition if c.kind is CognitionKind.BELIEF]
        assert beliefs, "a speech act must produce a source-bound belief"
        assert beliefs[0].belief_type == "speech"
        assert beliefs[0].is_speech is True
        # The belief says the sentence was heard; it does not assert the content.
        assert "说" in beliefs[0].content

    def test_refuse_is_speech_too(self):
        action = _npc_action(
            "refuse", "npc_refuse", utterance="我不能说", target_npc_name="向导",
            summary="向导拒绝",
        )
        resolved = resolve_npc_action(action)
        assert resolved.events[0].kind is ResolvedEventKind.NPC_REFUSE
        assert resolved.events[0].kind in SPEECH_EVENT_KINDS

    def test_hidden_npc_action_does_not_expose_a_public_payload(self):
        action = _npc_action(
            "observe", "npc_observe", summary="暗中观察", visible_to_player=False
        )
        resolved = resolve_npc_action(action)
        event = resolved.events[0]
        assert event.visibility_scope == "hidden"
        assert event.public_payload is None
        assert event.private_payload is not None

    def test_no_npc_action_changes_state(self):
        for action_type, handler in (
            ("observe", "npc_observe"),
            ("idle", "npc_idle"),
            ("talk", "npc_talk"),
            ("refuse", "npc_refuse"),
        ):
            resolved = resolve_npc_action(
                _npc_action(action_type, handler, summary="x", utterance="y")
            )
            assert resolved.state_changes == {}, action_type
            assert resolved.audit["physical_effect"] is False

    def test_unauthorized_npc_action_is_refused(self):
        action = _npc_action("attack", "npc_attack", summary="攻击")
        resolved = resolve_npc_action(action)
        assert resolved.status is ActionStatus.REJECTED
        assert resolved.reason_code is ActionReasonCode.UNSUPPORTED
        assert resolved.events == []


class TestWorldAndSceneReferences:
    def test_world_reference_creates_no_facts(self):
        action = AuthorizedAction(
            actor_id="world_engine",
            actor_role=ActorRole.world,
            action_type="reference",
            handler="world_reference",
            time_policy=TimePolicy.NONE,
            referenced_event_ids=("evt-1",),
            display_hint="远处钟声响起",
        )
        resolved = resolve_world_reference(action)
        assert resolved.accepted
        assert resolved.state_changes == {}
        assert resolved.audit["creates_facts"] is False
        event = resolved.events[0]
        assert event.game_event_type == "world_tick"
        assert event.result_json["creates_facts"] is False
        payload = event.public_payload
        assert payload["referenced_event_ids"] == ["evt-1"]
        for forbidden in ("candidate_events", "effects", "state_deltas", "importance"):
            assert forbidden not in payload

    def test_scene_reference_creates_no_facts_and_only_lists_legal_actions(self):
        action = AuthorizedAction(
            actor_id="scene_engine",
            actor_role=ActorRole.scene,
            action_type="reference",
            handler="scene_reference",
            time_policy=TimePolicy.NONE,
            referenced_event_ids=(),
            recommended_actions=("前往试炼堂",),
            display_hint="晨光洒在广场上",
        )
        resolved = resolve_scene_reference(action)
        assert resolved.accepted
        assert resolved.state_changes == {}
        assert resolved.audit["creates_facts"] is False
        event = resolved.events[0]
        assert event.result_json["recommended_actions"] == ["前往试炼堂"]
        for forbidden in ("candidate_events", "scene_name", "effects", "state_deltas"):
            assert forbidden not in (event.public_payload or {})

    def test_world_and_scene_references_do_not_advance_time(self):
        for handler, resolver in (
            ("world_reference", resolve_world_reference),
            ("scene_reference", resolve_scene_reference),
        ):
            action = AuthorizedAction(
                actor_id="engine",
                actor_role=ActorRole.world,
                action_type="reference",
                handler=handler,
                time_policy=TimePolicy.NONE,
            )
            resolved = resolver(action)
            assert resolved.accepted
            # TimePolicy.NONE: nothing in the result may carry a duration.
            assert "elapsed_minutes" not in resolved.audit
            assert resolved.state_changes == {}


class TestRejectionShape:
    def test_reject_action_produces_no_events_and_no_state_changes(self):
        resolved = reject_action(None, ActionDetailCode.ENTITY_NOT_FOUND, "missing")
        assert resolved.status is ActionStatus.REJECTED
        assert resolved.events == []
        assert resolved.state_changes == {}
        assert resolved.movement_result is None
        assert resolved.reason_code is ActionReasonCode.TARGET_UNAVAILABLE

    def test_rejection_does_not_expose_hidden_entity_existence(self):
        """A concealed location and a non-existent one share one public code."""
        concealed = reject_action(None, ActionDetailCode.LOCATION_NOT_DISCOVERED)
        missing = reject_action(None, ActionDetailCode.ENTITY_NOT_FOUND)
        assert concealed.reason_code is missing.reason_code
        assert concealed.reason_code is ActionReasonCode.TARGET_UNAVAILABLE

    def test_resolved_action_accepted_property(self):
        accepted = ResolvedAction(action=None, status=ActionStatus.ACCEPTED)
        rejected = ResolvedAction(action=None, status=ActionStatus.REJECTED)
        assert accepted.accepted is True
        assert rejected.accepted is False

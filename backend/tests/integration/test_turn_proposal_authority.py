"""Phase 2 integration coverage: the LLM authority chain through the real entry point.

Every test here drives ``execute_turn_service`` — the sole production entry point —
with a provider that returns raw model JSON, so the whole chain runs for real:
prompt -> provider -> strict contract -> authorization -> domain adjudication ->
single authoritative commit -> database.

Two injection levels are covered on purpose (plan section 5, "双层注入"):

* a malicious provider whose raw JSON tries to smuggle executable fields, and
* a directly tampered internal proposal / stage result, so the tests do not merely
  prove that the parser is safe.
"""

import json

import pytest

from llm_rpg.core import turn_service
from llm_rpg.storage.models import (
    GameEventModel,
    LocationModel,
    SessionNPCStateModel,
    SessionStateModel,
    StateDeltaModel,
)

from llm_rpg.llm.proposal_pipeline import ProposalPipeline

from .turn_authority_fixtures import (
    authority_session,
    contract_json,
    enable_all_stages,
    game_events,
    narration_json,
    npc_action_json,
    patch_llm_provider,
    player_intent_json,
    scene_event_json,
    world_tick_json,
)


def _turn(authority_session, player_input="我观察四周", key="authority-key"):
    return turn_service.execute_turn_service(
        authority_session.db,
        authority_session.session.id,
        player_input,
        idempotency_key=key,
        use_mock=False,
    )


class TestMaliciousProviderRawJson:
    """The provider returns raw JSON that tries to gain authority directly."""

    def test_direct_state_delta_in_intent_is_refused(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": contract_json({
                "contract_version": 2,
                "intent": {"action_type": "idle"},
                # Executable fields the wire must never accept.
                "state_deltas": [
                    {"path": "player_state.hp", "operation": "set", "value": 0}
                ],
            }),
            "可见上下文": narration_json("你静静地站着。"),
        })

        result = _turn(authority_session)
        db = authority_session.db

        hp_deltas = [
            delta for delta in db.query(StateDeltaModel).filter_by(
                session_id=authority_session.session.id
            ).all()
            if "hp" in delta.path
        ]
        assert hp_deltas == [], "a model-supplied state delta must never be written"
        assert result.action_resolution["status"] in {"rejected", "accepted"}

    def test_effects_and_success_flags_are_refused(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": contract_json({
                "contract_version": 2,
                "intent": {
                    "action_type": "attack",
                    "target": "向导",
                    "effects": {"damage": 999, "reward": "神器"},
                    "success": True,
                },
            }),
            "可见上下文": narration_json("空气安静下来。"),
        })

        result = _turn(authority_session, "我攻击向导", key="effects-key")
        assert result.action_resolution["status"] == "rejected"
        # The action class itself is unauthorized, so the public reason stays
        # ``unsupported`` (the more accurate statement about the action) while the
        # contract violation remains visible in the stage audit.
        assert result.action_resolution["reason_code"] == "unsupported"
        intent_stage = next(
            stage for stage in result.llm_stage_results
            if stage.stage_name == "input_intent"
        )
        assert intent_stage.contract_reason_code == "contract_schema_violation"

        db = authority_session.db
        hp_deltas = [
            delta for delta in db.query(StateDeltaModel).filter_by(
                session_id=authority_session.session.id
            ).all()
            if "hp" in delta.path
        ]
        assert hp_deltas == []

    def test_forged_actor_and_audit_identity_are_refused(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": contract_json({
                "contract_version": 2,
                "intent": {"action_type": "idle"},
                "actor_id": "npc-guide",
                "session_id": "someone-elses-session",
                "audit": {"source_engine": "world_engine", "permission": "admin"},
            }),
            "可见上下文": narration_json("一切照旧。"),
        })

        result = _turn(authority_session, key="identity-key")
        assert result.action_resolution["status"] in {"rejected", "accepted"}
        intent_stage = next(
            stage for stage in result.llm_stage_results
            if stage.stage_name == "input_intent"
        )
        assert intent_stage.contract_reason_code == "contract_schema_violation"
        assert intent_stage.fallback_reason.startswith("contract_incompatible")

    def test_old_contract_version_is_refused_explicitly(
        self, authority_session, monkeypatch
    ):
        """An old template's answer is recorded as contract-incompatible."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": json.dumps({
                "intent_type": "move",
                "target": "试炼堂",
                "confidence": 0.9,
            }),
            "可见上下文": narration_json("你环顾四周。"),
        })

        result = _turn(authority_session, "前往试炼堂", key="old-template-key")
        # Plan section 3.6: when the model's answer is unusable, only the raw input
        # is parsed deterministically and re-authorized. That legal move therefore
        # still happens, and the summary records that it came from the fallback.
        assert result.action_resolution["action_type"] == "move"
        assert result.action_resolution["status"] == "accepted"
        assert result.action_resolution["fallback_used"] is True

        intent_stage = next(
            stage for stage in result.llm_stage_results
            if stage.stage_name == "input_intent"
        )
        assert intent_stage.accepted is False
        assert intent_stage.contract_reason_code == "contract_version_mismatch"
        assert "contract_incompatible" in (intent_stage.fallback_reason or "")

        # Nothing from the old template's payload was reinterpreted as authority.
        db = authority_session.db
        session_state = db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one()
        assert session_state.current_location_id == authority_session.hall.id

    def test_legal_move_still_commits_through_the_strict_chain(
        self, authority_session, monkeypatch
    ):
        """The chain must not pass by refusing everything."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.hall.id
            ),
            "可见上下文": narration_json("你走进了试炼堂。"),
        })

        result = _turn(authority_session, "去试炼堂", key="legal-move-key")
        db = authority_session.db

        assert result.action_resolution == {
            "version": 1,
            "action_type": "move",
            "status": "accepted",
            "reason_code": None,
            "fallback_used": False,
        }
        assert result.movement_result is not None and result.movement_result.success

        session_state = db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one()
        assert session_state.current_location_id == authority_session.hall.id

        location_deltas = [
            delta for delta in db.query(StateDeltaModel).filter_by(
                session_id=authority_session.session.id, turn_no=result.turn_no
            ).all()
            if delta.path == "session_state.current_location_id"
        ]
        assert location_deltas, "a successful move must be audited as a delta"
        assert location_deltas[0].new_value_json == authority_session.hall.id

    def test_move_to_a_concealed_location_is_refused(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.vault.id
            ),
            "可见上下文": narration_json("你停住了脚步。"),
        })

        result = _turn(authority_session, "去秘藏", key="concealed-key")
        assert result.action_resolution["status"] == "rejected"
        assert result.action_resolution["reason_code"] == "target_unavailable"

        session_state = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one()
        assert session_state.current_location_id == authority_session.square.id

    def test_attack_intent_is_unsupported_not_a_success(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(action_type="attack", target="向导"),
            "可见上下文": narration_json("向导皱起眉头。"),
        })

        result = _turn(authority_session, "我攻击向导", key="attack-key")
        assert result.action_resolution["status"] == "rejected"
        assert result.action_resolution["reason_code"] == "unsupported"
        assert result.actions_committed == 0


class TestInjectedInternalProposal:
    """The internal stage result is tampered with directly."""

    def test_forged_world_event_reference_cannot_grant_authority(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)

        def fake_world_production(*_args, **_kwargs):
            async def _coro():
                from llm_rpg.llm.proposal_pipeline import ProductionContractOutcome
                from llm_rpg.models.action_contract import WorldTickV2

                return ProductionContractOutcome(contract=WorldTickV2(
                    contract_version=2,
                    referenced_event_ids=["forged-event-id"],
                    display_hint="伪造引用",
                ))
            return _coro()

        monkeypatch.setattr(
            ProposalPipeline,
            "generate_world_tick_production",
            fake_world_production,
        )
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("世界很安静。"),
        })

        result = _turn(authority_session, key="forged-event-key")
        world_stage = next(
            stage for stage in result.llm_stage_results if stage.stage_name == "world"
        )
        assert world_stage.accepted is False
        assert "authorization_rejected" in (world_stage.fallback_reason or "")

    def test_npc_actor_impersonation_is_refused(
        self, authority_session, monkeypatch
    ):
        """A tampered stage result that acts as the wrong identity is refused."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "NPC 上下文": npc_action_json(
                action={"action_type": "talk", "utterance": "我以对手的身份说话"},
                summary="向导开口",
            ),
            "可见上下文": narration_json("有人说话了。"),
        })

        # Force the NPC stage to bind the guide row to the rival template.
        original_authorize = turn_service.authorize_npc_action

        def tampering_authorize(ctx, contract, *, npc_id, npc_template_id, npc_name=None):
            return original_authorize(
                ctx, contract,
                npc_id=npc_id,
                npc_template_id=authority_session.guide.id,  # wrong identity
                npc_name=npc_name,
            )

        monkeypatch.setattr(turn_service, "authorize_npc_action", tampering_authorize)

        result = _turn(authority_session, key="impersonation-key")
        npc_stage = next(
            stage for stage in result.llm_stage_results if stage.stage_name == "npc"
        )
        reactions = npc_stage.parsed_proposal["npc_reactions"]
        assert reactions, "the NPC stage must still report a reaction"

        # The tampering declares the guide template for every row. Only the guide's
        # own row may act; the rival's row is a different identity and must be
        # refused rather than silently acting as the guide.
        by_id = {reaction["npc_id"]: reaction for reaction in reactions}
        rival_reaction = by_id[authority_session.rival_state.id]
        assert rival_reaction["accepted"] is False, (
            "a row bound to one identity must not act under another identity"
        )
        assert "authorization_rejected" in (rival_reaction["fallback_reason"] or "")
        assert rival_reaction["authorization_detail"] == "actor_impersonation"

        guide_reaction = by_id[authority_session.guide_state.id]
        assert guide_reaction["accepted"] is True, (
            "the row whose identity actually matches must still be allowed"
        )

    def test_rejected_proposal_does_not_become_an_accepted_stage(
        self, authority_session, monkeypatch
    ):
        """A validation/authorization failure must not leave accepted=True."""
        enable_all_stages(monkeypatch)

        def fake_scene_production(*_args, **_kwargs):
            async def _coro():
                from llm_rpg.llm.proposal_pipeline import ProductionContractOutcome
                from llm_rpg.models.action_contract import SceneEventV2

                return ProductionContractOutcome(contract=SceneEventV2(
                    contract_version=2,
                    referenced_event_ids=["not-this-turns-event"],
                ))
            return _coro()

        monkeypatch.setattr(
            ProposalPipeline,
            "generate_scene_event_production",
            fake_scene_production,
        )
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("场景平静。"),
        })

        result = _turn(authority_session, key="scene-ref-key")
        scene_stage = next(
            stage for stage in result.llm_stage_results if stage.stage_name == "scene"
        )
        assert scene_stage.accepted is False
        assert scene_stage.validation_errors or scene_stage.fallback_reason


class TestInjectionIntegrity:
    """Guards against the injection silently becoming a no-op.

    An earlier version of ``patch_llm_provider`` was a ``@contextmanager`` whose body
    returned without ``yield``; the patch never applied, every stage fell back to the
    default mock provider, and the assertions still "passed" because a fallback also
    produces rejections. These tests fail loudly if that regresses.
    """

    def test_injected_provider_is_actually_consulted(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        provider = patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(action_type="idle"),
            "可见上下文": narration_json("你站着不动。"),
        })

        _turn(authority_session, "我等着", key="injection-guard-key")
        assert provider.call_count > 0, (
            "the injected provider must actually receive the model calls"
        )

    def test_injected_contract_is_what_reaches_the_chain(
        self, authority_session, monkeypatch
    ):
        """A valid injected contract must be *accepted*, not fall back."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(action_type="idle"),
            "可见上下文": narration_json("你站着不动。"),
        })

        result = _turn(authority_session, "我等着", key="injection-accept-key")
        assert result.action_resolution["action_type"] == "idle"
        assert result.action_resolution["status"] == "accepted"
        assert result.action_resolution["fallback_used"] is False, (
            "an accepted production contract must not be reported as a fallback"
        )


class TestClarificationMarkerBoundary:
    def test_unsupported_action_cannot_use_the_clarification_marker(
        self, authority_session, monkeypatch
    ):
        """``needs_clarification`` must not turn an unsupported action into a free turn."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": contract_json({
                "contract_version": 2,
                "intent": {"action_type": "attack", "target": "向导"},
                "needs_clarification": True,
                "clarification_question": "你想攻击谁？",
            }),
            "可见上下文": narration_json("向导看着你。"),
        })

        before = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one().current_time

        result = _turn(authority_session, "我攻击向导", key="clarify-marker-key")

        assert result.action_resolution["status"] == "rejected", (
            "an unauthorized action class must not be reclassified as a clarification"
        )
        assert result.action_resolution["reason_code"] == "unsupported"
        after = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one().current_time
        assert after != before, (
            "a refused action keeps its action-class time cost, it is not zero-time"
        )

    def test_authorized_action_may_still_ask_for_clarification(
        self, authority_session, monkeypatch
    ):
        """The legitimate case keeps working: an authorized class may clarify."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": contract_json({
                "contract_version": 2,
                "intent": {"action_type": "move", "target_location_id": None},
                "needs_clarification": True,
                "clarification_question": "你想前往哪里？",
            }),
            "可见上下文": narration_json("你等待着。"),
        })

        result = _turn(authority_session, "我去", key="clarify-authorized-key")
        assert result.action_resolution["status"] == "clarification"
        assert result.actions_committed == 0


class TestDeltaCauseForEveryActionClass:
    @pytest.mark.parametrize(
        "player_input,intent,key",
        [
            ("我等着", {"action_type": "idle"}, "cause-idle-key"),
            ("我观察四周", {"action_type": "inspect"}, "cause-inspect-key"),
            (
                "去不存在的地方",
                {"action_type": "move", "target_location_id": "loc-does-not-exist"},
                "cause-blocked-key",
            ),
        ],
    )
    def test_non_move_actions_never_use_narration_as_the_delta_cause(
        self, authority_session, monkeypatch, player_input, intent, key
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(**intent),
            "可见上下文": narration_json("时间缓缓流逝。"),
        })

        result = _turn(authority_session, player_input, key=key)
        db = authority_session.db

        deltas = db.query(StateDeltaModel).filter_by(
            session_id=authority_session.session.id, turn_no=result.turn_no
        ).all()
        assert deltas, "a committed turn with a time change must audit a delta"
        for delta in deltas:
            source = db.query(GameEventModel).filter_by(id=delta.source_event_id).one()
            assert source.event_type != "narration", (
                f"{intent['action_type']}: a narration presentation event must never "
                "be a delta's cause"
            )


class TestDeltaCausality:
    def test_state_delta_source_is_an_engine_action_event(
        self, authority_session, monkeypatch
    ):
        """A delta's cause is the engine action event, never the narration event."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.hall.id
            ),
            "可见上下文": narration_json("你走进了试炼堂。"),
        })

        result = _turn(authority_session, "去试炼堂", key="delta-cause-key")
        db = authority_session.db

        deltas = db.query(StateDeltaModel).filter_by(
            session_id=authority_session.session.id, turn_no=result.turn_no
        ).all()
        assert deltas
        for delta in deltas:
            assert delta.source_event_id is not None
            source = db.query(GameEventModel).filter_by(id=delta.source_event_id).one()
            assert source.event_type != "narration", (
                "a narration presentation event must never be a delta's cause"
            )

    def test_every_delta_points_at_a_real_game_event(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("时间缓缓流逝。"),
        })

        result = _turn(authority_session, "我等待", key="delta-real-key")
        db = authority_session.db

        event_ids = {
            event.id for event in db.query(GameEventModel).filter_by(
                session_id=authority_session.session.id, turn_no=result.turn_no
            ).all()
        }
        deltas = db.query(StateDeltaModel).filter_by(
            session_id=authority_session.session.id, turn_no=result.turn_no
        ).all()
        assert deltas, "a committed turn must audit its time change"
        for delta in deltas:
            assert delta.source_event_id in event_ids

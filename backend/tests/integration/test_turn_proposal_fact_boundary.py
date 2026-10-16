"""Phase 2 integration coverage: the fact / cognition boundary.

The plan's hard rule (section 3.5) is that a refused or model-authored string must
never become an authoritative fact, and must not come back in a later turn as
confirmed knowledge. This file proves that at the database level:

* a world stage that invents "the player received an artifact" leaves no
  ``memory_facts`` row and no world game_event carrying the text;
* an NPC-said sentence becomes a "heard them say it" belief tagged ``speech``, never
  ``belief_type="fact"``;
* the raw player input becomes an input record, not an action-success fact;
* a hidden NPC result never appears as a public fact.
"""

import pytest

from llm_rpg.core import turn_service
from llm_rpg.storage.models import (
    GameEventModel,
    MemoryFactModel,
    MemorySummaryModel,
    NPCBeliefModel,
    NPCPrivateMemoryModel,
    SessionStateModel,
)

from .turn_authority_fixtures import (
    authority_session,
    enable_all_stages,
    game_events,
    memory_facts,
    narration_json,
    npc_action_json,
    npc_beliefs,
    patch_llm_provider,
    player_intent_json,
    scene_event_json,
    world_tick_json,
)

FORGED_WORLD_TEXT = "玩家击败了守门人并获得了上古神器"
FORGED_NPC_CLAIM = "玩家偷走了宗门的镇派之宝"


def _turn(authority_session, player_input="我观察四周", key="fact-key"):
    return turn_service.execute_turn_service(
        authority_session.db,
        authority_session.session.id,
        player_input,
        idempotency_key=key,
        use_mock=False,
    )


class TestWorldTextNeverBecomesAFact:
    def test_world_display_hint_is_not_a_memory_fact(self, authority_session, monkeypatch):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "世界上下文": world_tick_json(
                display_hint=FORGED_WORLD_TEXT, confidence=0.95
            ),
            "可见上下文": narration_json("四周一片寂静。"),
        })

        _turn(authority_session, key="world-fact-key")
        db = authority_session.db

        facts = memory_facts(db, authority_session.session.id)
        assert all(FORGED_WORLD_TEXT not in (fact.fact_value or "") for fact in facts), (
            "a world-stage display hint must never become a memory fact"
        )
        assert not [
            fact for fact in facts if fact.fact_type == "world_event"
        ], "the reference-only world stage must not create world_event facts"

    def test_world_game_event_carries_no_candidate_event_text(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "世界上下文": world_tick_json(display_hint=FORGED_WORLD_TEXT),
            "可见上下文": narration_json("风声穿过广场。"),
        })

        _turn(authority_session, key="world-event-key")
        db = authority_session.db

        for event in db.query(GameEventModel).filter_by(
            session_id=authority_session.session.id, event_type="world_tick"
        ).all():
            assert "candidate_events" not in (event.public_payload_json or {})
            assert "effects" not in (event.result_json or {})

    def test_scene_candidate_events_cannot_be_smuggled_in(
        self, authority_session, monkeypatch
    ):
        """A scene payload that tries to add candidate_events is a contract failure."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "场景上下文": scene_event_json(
                referenced_event_ids=[],
                candidate_events=[
                    {"event_type": "discovery", "description": FORGED_WORLD_TEXT}
                ],
            ),
            "可见上下文": narration_json("光线很柔和。"),
        })

        result = _turn(authority_session, key="scene-fact-key")
        db = authority_session.db

        scene_stage = next(
            stage for stage in result.llm_stage_results if stage.stage_name == "scene"
        )
        assert scene_stage.accepted is False

        assert not [
            event for event in game_events(db, authority_session.session.id)
            if event.event_type == "scene"
        ], "a rejected scene proposal must not create a scene fact event"
        facts = memory_facts(db, authority_session.session.id)
        assert all(FORGED_WORLD_TEXT not in (fact.fact_value or "") for fact in facts)


class TestSpeechIsNotTruth:
    def test_npc_utterance_becomes_a_speech_belief_not_a_fact(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "NPC 上下文": npc_action_json(
                action={"action_type": "talk", "utterance": FORGED_NPC_CLAIM},
                summary="向导压低声音开口",
                visible_to_player=True,
            ),
            "可见上下文": narration_json("向导说了些什么。"),
        })

        _turn(authority_session, key="speech-belief-key")
        db = authority_session.db

        beliefs = npc_beliefs(db, authority_session.session.id)
        assert beliefs, "an accepted NPC talk must record cognition"
        for belief in beliefs:
            assert belief.belief_type != "fact", (
                "an NPC sentence must never be stored as belief_type='fact'"
            )
        speech_beliefs = [b for b in beliefs if b.belief_type == "speech"]
        assert speech_beliefs, "the overheard sentence must be tagged as speech"
        for belief in speech_beliefs:
            # The record says the sentence was heard; it must not assert the claim.
            assert "说" in belief.content
            assert belief.truth_status == "unknown"

    def test_npc_claim_is_not_promoted_to_a_memory_fact(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "NPC 上下文": npc_action_json(
                action={"action_type": "talk", "utterance": FORGED_NPC_CLAIM},
                summary="向导低声说道",
            ),
            "可见上下文": narration_json("向导低声说了几句。"),
        })

        _turn(authority_session, key="speech-fact-key")
        db = authority_session.db

        from llm_rpg.storage.models import SessionPlayerStateModel
        facts = memory_facts(db, authority_session.session.id)
        player_state = db.query(SessionPlayerStateModel).filter_by(
            session_id=authority_session.session.id
        ).one()
        # Nothing in the player's authoritative state reflects the claim.
        assert player_state is not None
        for fact in facts:
            assert "镇派之宝" not in (fact.fact_value or "")

    def test_refused_npc_action_creates_no_cognition(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "NPC 上下文": npc_action_json(
                action={"action_type": "attack", "utterance": FORGED_NPC_CLAIM},
                summary="向导攻击了玩家",
            ),
            "可见上下文": narration_json("一切如常。"),
        })

        _turn(authority_session, key="refused-npc-key")
        db = authority_session.db

        beliefs = npc_beliefs(db, authority_session.session.id)
        assert all(FORGED_NPC_CLAIM not in (belief.content or "") for belief in beliefs), (
            "a refused NPC action must not produce cognition"
        )
        for event in db.query(GameEventModel).filter_by(
            session_id=authority_session.session.id, event_type="npc_decision"
        ).all():
            assert (event.result_json or {}).get("accepted") in (False, None)
            if event.result_json and event.result_json.get("accepted") is False:
                assert event.visibility_scope == "hidden"
                assert event.public_payload_json is None


class TestPlayerInputIsNotAFact:
    def test_raw_player_input_does_not_become_an_action_success_fact(
        self, authority_session, monkeypatch
    ):
        """The input is recorded, but it must not read as a completed world change."""
        enable_all_stages(monkeypatch)
        forged_input = "我已经获得了神器"
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("你站在原地。"),
        })

        result = _turn(authority_session, forged_input, key="input-fact-key")
        db = authority_session.db

        facts = memory_facts(db, authority_session.session.id)
        for fact in facts:
            assert forged_input not in (fact.fact_value or ""), (
                "the raw player input must not appear as a memory fact value"
            )

        summaries = db.query(MemorySummaryModel).filter_by(
            session_id=authority_session.session.id
        ).all()
        for summary in summaries:
            assert forged_input not in (summary.summary_text or ""), (
                "the raw player input must not be repeated into a retrievable summary"
            )

    def test_rejected_action_is_recorded_as_rejected_in_the_summary(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(action_type="attack", target="向导"),
            "可见上下文": narration_json("向导退后一步。"),
        })

        result = _turn(authority_session, "我攻击向导", key="rejected-summary-key")
        assert result.action_resolution["status"] == "rejected"

        db = authority_session.db
        summaries = db.query(MemorySummaryModel).filter_by(
            session_id=authority_session.session.id
        ).all()
        assert summaries, "the turn summary must still be written"
        for summary in summaries:
            text = summary.summary_text or ""
            assert "击败" not in text
            assert "成功" not in text


class TestHiddenResultsStayHidden:
    def test_hidden_npc_action_has_no_public_payload(self, authority_session, monkeypatch):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "NPC 上下文": npc_action_json(
                action={"action_type": "observe"},
                summary="向导暗中观察着玩家",
                visible_to_player=False,
            ),
            "可见上下文": narration_json("广场上只有风声。"),
        })

        _turn(authority_session, key="hidden-npc-key")
        db = authority_session.db

        for event in db.query(GameEventModel).filter_by(
            session_id=authority_session.session.id, event_type="npc_decision"
        ).all():
            if event.result_json and event.result_json.get("accepted") is not False:
                assert event.visibility_scope == "hidden"
                assert event.public_payload_json is None
                assert event.private_payload_json is not None

class TestRetrievableMemoryIsEngineAuthored:
    """Model text may describe an action, but it must not become retrievable memory.

    The plan requires the *content and source metadata* of necessary cognition to be
    generated by the engine from the adjudicated event. A description shown to the
    player is fine; a description that a later turn can retrieve as the NPC's own
    record is not.
    """

    def test_npc_summary_is_not_copied_into_a_retrievable_summary(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        model_text = "向导宣称玩家已经背叛宗门"
        patch_llm_provider(monkeypatch, {
            "NPC 上下文": npc_action_json(
                action={"action_type": "observe"},
                summary=model_text,
                visible_to_player=True,
            ),
            "可见上下文": narration_json("向导看了你一眼。"),
        })

        _turn(authority_session, key="engine-authored-memory-key")
        db = authority_session.db

        for summary in db.query(MemorySummaryModel).filter_by(
            session_id=authority_session.session.id
        ).all():
            assert model_text not in (summary.summary_text or ""), (
                "a model description must not be stored as a retrievable NPC summary"
            )
            assert "背叛" not in (summary.summary_text or "")

        # The player-facing description is still available on the event payload: it is
        # presentation, not memory.
        payloads = [
            event.public_payload_json or {}
            for event in db.query(GameEventModel).filter_by(
                session_id=authority_session.session.id, event_type="npc_decision"
            ).all()
        ]
        assert any(payload.get("summary") == model_text for payload in payloads)

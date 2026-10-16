"""Phase 2 integration coverage: fallback, reason codes and recovery consistency.

Plan sections 3.6 and 5 require that:

* a rejected action is a *committed failed turn* with the existing action-class time
  cost, not a free clarification and not a fake success;
* a model outage falls back to deterministic parsing of the raw input, and never
  reuses a target from the refused proposal;
* the public ``action_resolution`` summary is a fact of the committed turn: a
  same-key retry reads it back verbatim and never re-runs authorization or a model
  call, and a legacy snapshot without one reports ``None``;
* the presentation CAS (post-commit narration) cannot modify the summary.
"""

import json

import pytest

from llm_rpg.core import turn_service
from llm_rpg.storage.models import EventLogModel, SessionStateModel

from .turn_authority_fixtures import (
    authority_session,
    enable_all_stages,
    narration_json,
    patch_llm_provider,
    player_intent_json,
)


def _turn(authority_session, player_input="我观察四周", key="recovery-key", **kwargs):
    return turn_service.execute_turn_service(
        authority_session.db,
        authority_session.session.id,
        player_input,
        idempotency_key=key,
        use_mock=False,
        **kwargs,
    )


class TestCommittedFailedTurn:
    def test_rejected_action_keeps_the_action_class_time_cost(
        self, authority_session, monkeypatch
    ):
        """A refusal is not a free clarification: the existing time rule applies."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.vault.id
            ),
            "可见上下文": narration_json("你停住了。"),
        })

        before = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one().current_time

        result = _turn(authority_session, "去秘藏", key="rejected-time-key")

        assert result.action_resolution["status"] == "rejected"
        assert result.time_advance_result["accepted_elapsed_minutes"] > 0, (
            "a refused action must keep its action-class time cost, not become "
            "a zero-time clarification"
        )
        after = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one().current_time
        assert after != before

    def test_unknown_input_keeps_the_ordinary_fallback_time_rule(
        self, authority_session, monkeypatch
    ):
        """Unrecognized input must not be reclassified as a clarification."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("没什么特别的。"),
        })

        result = _turn(authority_session, "qzxv nonsense", key="unknown-time-key")
        assert result.time_advance_result["accepted_elapsed_minutes"] > 0
        assert result.action_resolution["status"] in {"rejected", "accepted"}

    def test_move_without_a_destination_is_a_zero_time_clarification(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("你等待着。"),
        })

        before = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one().current_time

        result = _turn(authority_session, "去", key="clarify-time-key")

        assert result.action_resolution["status"] == "clarification"
        assert result.action_resolution["reason_code"] is None
        assert result.time_advance_result["accepted_elapsed_minutes"] == 0
        assert result.actions_committed == 0
        after = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one().current_time
        assert after == before


class TestModelOutageFallback:
    def test_timeout_falls_back_to_deterministic_parsing(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.vault.id
            ),
        })

        async def timeout_generate(*_args, **_kwargs):
            raise TimeoutError("provider timed out")

        from llm_rpg.llm.service import LLMService, MockLLMProvider

        broken = LLMService(provider=MockLLMProvider(), db_session=None)
        broken.generate = timeout_generate
        monkeypatch.setattr(
            turn_service, "_create_llm_service_from_config", lambda *a, **k: broken
        )

        # The deterministic parser reads "试炼堂" from the raw input, so the legal
        # move still happens -- but the refused proposal's concealed target is never
        # reused.
        result = _turn(authority_session, "前往试炼堂", key="timeout-fallback-key")
        assert result.action_resolution["fallback_used"] is True
        assert result.action_resolution["action_type"] == "move"
        assert result.movement_result is not None
        assert result.movement_result.new_location_code == "trial_hall"

    def test_fallback_does_not_reuse_a_refused_proposal_target(
        self, authority_session, monkeypatch
    ):
        """A refused concealed target must not leak into the deterministic path."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.vault.id
            ),
            "可见上下文": narration_json("你站着不动。"),
        })

        result = _turn(authority_session, "我等着", key="no-target-reuse-key")
        assert result.action_resolution["status"] != "accepted"
        session_state = authority_session.db.query(SessionStateModel).filter_by(
            session_id=authority_session.session.id
        ).one()
        assert session_state.current_location_id == authority_session.square.id

    def test_provider_failure_does_not_fake_a_success(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)

        async def exploding_generate(*_args, **_kwargs):
            raise RuntimeError("provider exploded")

        from llm_rpg.llm.service import LLMService, MockLLMProvider

        broken = LLMService(provider=MockLLMProvider(), db_session=None)
        broken.generate = exploding_generate
        monkeypatch.setattr(
            turn_service, "_create_llm_service_from_config", lambda *a, **k: broken
        )

        result = _turn(authority_session, "我观察四周", key="provider-down-key")
        assert result.action_resolution["fallback_used"] is True
        assert result.action_resolution["action_type"] in {"inspect", "action", "idle"}


class TestSummaryRecoveryConsistency:
    def test_same_key_recovery_returns_the_saved_summary_verbatim(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.hall.id
            ),
            "可见上下文": narration_json("你走进了试炼堂。"),
        })

        first = _turn(authority_session, "去试炼堂", key="recovery-same-key")
        second = _turn(authority_session, "去试炼堂", key="recovery-same-key")

        assert second.turn_no == first.turn_no
        assert second.action_resolution == first.action_resolution
        assert second.recovery_status == "complete"

        db = authority_session.db
        rows = db.query(EventLogModel).filter_by(
            session_id=authority_session.session.id, event_type="player_turn"
        ).all()
        assert len(rows) == 1, "a same-key retry must not commit a second turn"

    def test_summary_is_persisted_in_the_turn_snapshot(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(action_type="attack", target="向导"),
            "可见上下文": narration_json("向导皱眉。"),
        })

        result = _turn(authority_session, "我攻击向导", key="snapshot-key")
        db = authority_session.db
        event = db.query(EventLogModel).filter_by(
            session_id=authority_session.session.id, turn_no=result.turn_no,
            event_type="player_turn",
        ).one()

        snapshot = event.result_json["turn_result_v1"]
        assert snapshot["action_resolution"] == result.action_resolution
        assert snapshot["action_resolution"]["status"] == "rejected"
        assert snapshot["action_resolution"]["reason_code"] == "unsupported"

    def test_legacy_snapshot_without_a_summary_reports_none(
        self, authority_session, monkeypatch
    ):
        """A historical snapshot must not trigger a fresh authorization on read."""
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("平静无事。"),
        })

        result = _turn(authority_session, "我等待", key="legacy-snapshot-key")
        db = authority_session.db
        event = db.query(EventLogModel).filter_by(
            session_id=authority_session.session.id, turn_no=result.turn_no,
            event_type="player_turn",
        ).one()

        # Simulate a pre-phase-2 snapshot: strip the new field everywhere.
        stored = dict(event.result_json)
        stored.pop("action_resolution", None)
        snapshot = dict(stored.get("turn_result_v1") or {})
        snapshot.pop("action_resolution", None)
        stored["turn_result_v1"] = snapshot
        event.result_json = stored
        db.commit()

        recovered = turn_service._get_existing_turn_result(
            db, authority_session.session.id, result.turn_no
        )
        assert recovered is not None
        assert recovered.action_resolution is None

    def test_presentation_cas_does_not_modify_the_summary(
        self, authority_session, monkeypatch
    ):
        """Post-commit narration may rewrite presentation only, never the summary."""
        enable_all_stages(monkeypatch)
        narration_text = "试炼堂的门在你身后合拢，钟声远远传来。"
        patch_llm_provider(monkeypatch, {
            "玩家输入": player_intent_json(
                action_type="move", target_location_id=authority_session.hall.id
            ),
            "可见上下文": narration_json(narration_text),
        })

        result = _turn(authority_session, "去试炼堂", key="cas-summary-key")
        db = authority_session.db
        event = db.query(EventLogModel).filter_by(
            session_id=authority_session.session.id, turn_no=result.turn_no,
            event_type="player_turn",
        ).one()

        snapshot = event.result_json["turn_result_v1"]
        assert snapshot["action_resolution"] == result.action_resolution
        assert snapshot["presentation_version"] >= 1
        assert snapshot["presentation_status"] == "finalized"
        # Presentation moved on, the facts did not.
        assert snapshot["state_deltas"] == result.state_deltas
        assert snapshot["world_time"] == result.world_time
        assert snapshot["actions_committed"] == result.actions_committed

class TestManagedWriteFailures:
    """A necessary write failure inside the managed turn must roll the turn back.

    The turn service owns every authoritative write through one unit of work, so a
    failure in the *buffered* preparation writes (validation reports, game events) is
    just as fatal as one in the direct writes. Logging and continuing would let a
    turn commit with missing audit rows.
    """

    def test_buffered_game_event_write_failure_rolls_back(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("你静静地站着。"),
        })

        from llm_rpg.storage.repositories import GameEventRepository

        original_create = GameEventRepository.create

        def failing_create(self, data):
            raise RuntimeError("injected buffered game-event failure")

        monkeypatch.setattr(GameEventRepository, "create", failing_create)

        with pytest.raises(RuntimeError, match="injected buffered game-event failure"):
            _turn(authority_session, "我等待", key="buffered-write-key")

        monkeypatch.setattr(GameEventRepository, "create", original_create)

        db = authority_session.db
        from llm_rpg.storage.models import EventLogModel, GameEventModel, TurnTransactionModel

        assert db.query(EventLogModel).filter_by(
            session_id=authority_session.session.id
        ).count() == 0
        assert db.query(GameEventModel).filter_by(
            session_id=authority_session.session.id
        ).count() == 0
        claim = db.query(TurnTransactionModel).filter_by(
            session_id=authority_session.session.id
        ).one()
        assert claim.status == "aborted"

    def test_buffered_validation_report_write_failure_rolls_back(
        self, authority_session, monkeypatch
    ):
        enable_all_stages(monkeypatch)
        patch_llm_provider(monkeypatch, {
            "可见上下文": narration_json("你静静地站着。"),
        })

        from llm_rpg.storage.repositories import ValidationReportRepository

        original_create = ValidationReportRepository.create

        def failing_create(self, data):
            raise RuntimeError("injected buffered validation-report failure")

        monkeypatch.setattr(ValidationReportRepository, "create", failing_create)

        with pytest.raises(RuntimeError, match="injected buffered validation-report failure"):
            _turn(authority_session, "我等待", key="buffered-report-key")

        monkeypatch.setattr(ValidationReportRepository, "create", original_create)

        db = authority_session.db
        from llm_rpg.storage.models import EventLogModel, TurnTransactionModel

        assert db.query(EventLogModel).filter_by(
            session_id=authority_session.session.id
        ).count() == 0
        claim = db.query(TurnTransactionModel).filter_by(
            session_id=authority_session.session.id
        ).one()
        assert claim.status == "aborted"

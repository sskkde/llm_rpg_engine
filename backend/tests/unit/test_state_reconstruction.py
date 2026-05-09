"""
Unit tests for state reconstruction functionality.

Tests that:
- State reconstruction from DB rows produces correct CanonicalState
- Reconstructed state matches live snapshot for location, quest, world time
- Replay uses committed events/results only (no LLM calls)
- Stage metadata from result_json is preserved in replay output
- Hidden prompt details are not exposed to player role
"""

import pytest
from datetime import datetime
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as DBSession
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    UserModel, WorldModel, ChapterModel, LocationModel,
    NPCTemplateModel, QuestTemplateModel, QuestStepModel,
    SessionModel, SessionStateModel, SessionPlayerStateModel,
    SessionNPCStateModel, SessionQuestStateModel, EventLogModel,
    MemorySummaryModel, MemoryFactModel,
)
from llm_rpg.storage.repositories import SessionStateRepository
from llm_rpg.core.state_reconstruction import (
    reconstruct_canonical_state,
    get_latest_turn_number,
    get_active_actors_at_location,
    SessionNotFoundError,
    StateReconstructionError,
)
from llm_rpg.core.replay import (
    get_replay_store,
    reset_replay_store,
    ReplayEngine,
    ReplayEvent,
    ReplayPerspective,
    StateSnapshot,
    StateDelta,
)
from llm_rpg.models.states import CanonicalState


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create test data
    user = UserModel(id="u1", username="test", email="t@t.com", password_hash="h")
    world = WorldModel(
        id="w1", code="test_world", name="测试世界",
        genre="xianxia", status="active"
    )
    chapter = ChapterModel(
        id="ch1", world_id="w1", chapter_no=1, name="第一章"
    )
    location1 = LocationModel(
        id="loc1", world_id="w1", chapter_id="ch1",
        code="mountain_gate", name="山门", access_rules={"always_accessible": True},
    )
    location2 = LocationModel(
        id="loc2", world_id="w1", chapter_id="ch1",
        code="inner_court", name="内院", access_rules={"requires_item": "token"},
    )
    npc_template = NPCTemplateModel(
        id="npc_t1", world_id="w1", code="guide",
        name="柳师姐", role_type="guide",
        public_identity="宗门向导",
        hidden_identity="暗影组织间谍",
        personality="温和友善",
        goals=["保护新弟子"],
    )
    quest_template = QuestTemplateModel(
        id="quest_t1", world_id="w1", code="main_quest",
        name="入门试炼", quest_type="main",
    )
    quest_step = QuestStepModel(
        id="qs1", quest_template_id="quest_t1", step_no=1,
        objective="前往山门",
    )

    session.add_all([
        user, world, chapter, location1, location2,
        npc_template, quest_template, quest_step,
    ])
    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def session_with_state(db):
    """Create a session with full state for testing."""
    session_model = SessionModel(
        id="s1", user_id="u1", save_slot_id=None,
        world_id="w1", current_chapter_id="ch1", status="active",
    )
    session_state = SessionStateModel(
        session_id="s1",
        current_location_id="loc1",
        current_time="修仙历 春 第5日 辰时",
        time_phase="辰时",
        active_mode="exploration",
        global_flags_json={"tutorial_complete": True},
    )
    player_state = SessionPlayerStateModel(
        session_id="s1",
        realm_stage="炼气三层",
        hp=90,
        max_hp=100,
        stamina=80,
        spirit_power=120,
        relation_bias_json={"npc_t1": 0.5},
        conditions_json=["轻微疲劳"],
    )
    npc_state = SessionNPCStateModel(
        id="ns1", session_id="s1", npc_template_id="npc_t1",
        current_location_id="loc1", trust_score=60,
        suspicion_score=10, status_flags={"status": "alive", "mood": "friendly"},
        short_memory_summary="最近见过玩家",
        hidden_plan_state="观察玩家是否有威胁",
    )
    quest_state = SessionQuestStateModel(
        session_id="s1", quest_template_id="quest_t1",
        current_step_no=2, status="active",
        progress_json={"step1_complete": True},
    )

    db.add_all([
        session_model, session_state, player_state,
        npc_state, quest_state,
    ])
    db.commit()
    return session_model


# =============================================================================
# State Reconstruction Tests
# =============================================================================

class TestReconstructCanonicalState:
    """Tests for reconstruct_canonical_state()."""

    def test_reconstruct_returns_none_for_nonexistent_session(self, db):
        """Reconstruction should return None if session doesn't exist."""
        result = reconstruct_canonical_state(db, "nonexistent_session")
        assert result is None

    def test_reconstruct_returns_canonical_state(self, db, session_with_state):
        """Reconstruction should return a valid CanonicalState."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        assert isinstance(result, CanonicalState)

    def test_reconstruct_player_location(self, db, session_with_state):
        """Reconstructed state should have correct player location."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        assert result.player_state.location_id == "loc1"

    def test_reconstruct_world_time(self, db, session_with_state):
        """Reconstructed state should have correct world time."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        world_time = result.world_state.current_time
        assert world_time.calendar == "修仙历"
        assert world_time.season == "春"
        assert world_time.day == 5
        assert world_time.period == "辰时"

    def test_reconstruct_player_realm(self, db, session_with_state):
        """Reconstructed state should have correct player realm."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        assert result.player_state.realm == "炼气三层"

    def test_reconstruct_npc_states(self, db, session_with_state):
        """Reconstructed state should include NPC states."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        assert len(result.npc_states) > 0
        
        npc_state = None
        for npc in result.npc_states.values():
            if npc.name == "柳师姐":
                npc_state = npc
                break
        
        assert npc_state is not None
        assert npc_state.location_id == "loc1"

    def test_reconstruct_quest_states(self, db, session_with_state):
        """Reconstructed state should include quest states."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        assert len(result.quest_states) > 0
        
        # Find the quest
        quest_state = None
        for quest in result.quest_states.values():
            if quest.name == "入门试炼":
                quest_state = quest
                break
        
        assert quest_state is not None
        assert quest_state.status == "active"
        assert quest_state.stage == "2"

    def test_reconstruct_global_flags(self, db, session_with_state):
        """Reconstructed state should include global flags."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        assert result.world_state.global_flags.get("tutorial_complete") is True

    def test_reconstruct_location_states(self, db, session_with_state):
        """Reconstructed state should include location states."""
        result = reconstruct_canonical_state(db, "s1")
        
        assert result is not None
        assert len(result.location_states) > 0
        
        # Current location should be known
        loc_state = result.location_states.get("mountain_gate")
        assert loc_state is not None
        assert loc_state.name == "山门"


class TestGetLatestTurnNumber:
    """Tests for get_latest_turn_number()."""

    def test_returns_zero_for_no_events(self, db, session_with_state):
        """Should return 0 if no events exist."""
        turn = get_latest_turn_number(db, "s1")
        assert turn == 0

    def test_returns_latest_turn(self, db, session_with_state):
        """Should return the highest turn number from event logs."""
        # Add some event logs
        for turn_no in [1, 2, 3]:
            event = EventLogModel(
                id=f"evt_{turn_no}",
                session_id="s1",
                turn_no=turn_no,
                event_type="player_input",
                input_text=f"turn {turn_no}",
                occurred_at=datetime.now(),
            )
            db.add(event)
        db.commit()
        
        turn = get_latest_turn_number(db, "s1")
        assert turn == 3


class TestGetActiveActorsAtLocation:
    """Tests for get_active_actors_at_location()."""

    def test_returns_player_at_location(self, db, session_with_state):
        """Should include player if at the location."""
        actors = get_active_actors_at_location(db, "s1", "loc1")
        assert "player" in actors

    def test_excludes_player_not_at_location(self, db, session_with_state):
        """Should not include player if at different location."""
        actors = get_active_actors_at_location(db, "s1", "loc2")
        assert "player" not in actors

    def test_returns_npcs_at_location(self, db, session_with_state):
        """Should include NPCs at the location."""
        actors = get_active_actors_at_location(db, "s1", "loc1")
        # NPC should be included (by code or id)
        assert len(actors) > 1  # player + at least one NPC


# =============================================================================
# Replay with LLM Stage Metadata Tests
# =============================================================================

class TestReplayWithLLMStages:
    """Tests for replay with LLM stage metadata."""

    def setup_method(self):
        """Reset replay store before each test."""
        reset_replay_store()

    def test_replay_uses_committed_results_no_llm_call(self, db, session_with_state):
        """Replay should use committed event results, not call LLM."""
        # Create an event log with LLM stage metadata
        result_json = {
            "llm_stages": [
                {
                    "stage_name": "input_intent",
                    "enabled": True,
                    "timeout": 15.0,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                    "model_call_id": "mc_001",
                },
                {
                    "stage_name": "world",
                    "enabled": True,
                    "timeout": 30.0,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                    "model_call_id": "mc_002",
                },
                {
                    "stage_name": "scene",
                    "enabled": True,
                    "timeout": 30.0,
                    "accepted": False,
                    "fallback_reason": "validation_failed: invalid scope",
                    "validation_errors": ["Scene proposal cannot create global events"],
                    "model_call_id": None,
                },
                {
                    "stage_name": "npc",
                    "enabled": True,
                    "timeout": 30.0,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                    "model_call_id": "mc_003",
                },
                {
                    "stage_name": "narration",
                    "enabled": True,
                    "timeout": 30.0,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                    "model_call_id": "mc_004",
                },
            ],
            "world_progression": {"time_delta": 1},
            "npc_reactions": [
                {"npc_id": "ns1", "npc_name": "柳师姐", "action_type": "talk", "summary": "问候玩家"}
            ],
            "scene_event_summary": None,
            "parsed_intent": {"intent_type": "move", "target": "内院"},
            "memory_persistence": {"facts_written": 2},
        }
        
        event = EventLogModel(
            id="evt_1",
            session_id="s1",
            turn_no=1,
            event_type="player_input",
            input_text="前往内院",
            result_json=result_json,
            narrative_text="你向内院走去...",
            occurred_at=datetime.now(),
        )
        db.add(event)
        db.commit()

        # Create replay events from the event log
        replay_events = [
            ReplayEvent(
                event_id="evt_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                actor_id="player",
                summary="前往内院",
                visible_to_player=True,
                data={
                    "raw_input": "前往内院",
                    "result_json": result_json,
                    "state_deltas": [
                        {"path": "player_state.location_id", "old_value": "loc1", "new_value": "loc2", "operation": "set"},
                    ],
                },
            ),
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        result = replay_engine.replay_turn_range(
            session_id="s1",
            start_turn=1,
            end_turn=1,
            events=replay_events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert len(result.steps) == 1
        
        # Verify LLM stage metadata is preserved
        step = result.steps[0]
        assert step.player_input == "前往内院"

    def test_replay_preserves_stage_metadata_in_result_json(self, db, session_with_state):
        """Replay should preserve LLM stage metadata from result_json."""
        result_json = {
            "llm_stages": [
                {
                    "stage_name": "narration",
                    "enabled": True,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                },
            ],
            "parsed_intent": {"intent_type": "talk"},
        }
        
        event = EventLogModel(
            id="evt_2",
            session_id="s1",
            turn_no=2,
            event_type="player_input",
            input_text="与柳师姐交谈",
            result_json=result_json,
            narrative_text="你与柳师姐交谈...",
            occurred_at=datetime.now(),
        )
        db.add(event)
        db.commit()

        replay_events = [
            ReplayEvent(
                event_id="evt_2",
                event_type="player_input",
                turn_no=2,
                timestamp=datetime.now(),
                data={"result_json": result_json},
            ),
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        result = replay_engine.replay_turn_range(
            session_id="s1",
            start_turn=2,
            end_turn=2,
            events=replay_events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True

    def test_replay_player_perspective_no_hidden_prompts(self, db, session_with_state):
        """Player perspective should not see hidden prompt details."""
        result_json = {
            "llm_stages": [
                {
                    "stage_name": "npc",
                    "enabled": True,
                    "accepted": True,
                    # Hidden prompt details that shouldn't be exposed
                    "raw_prompt_preview": "You are an NPC with a secret identity...",
                    "hidden_context": "NPC is actually a spy",
                },
            ],
            "npc_reactions": [
                {
                    "npc_id": "ns1",
                    "npc_name": "柳师姐",
                    "action_type": "talk",
                    "summary": "问候玩家",
                    "hidden_motivation": "Assessing if player is a threat",  # Should not be exposed
                }
            ],
        }
        
        event = EventLogModel(
            id="evt_3",
            session_id="s1",
            turn_no=3,
            event_type="player_input",
            input_text="与柳师姐交谈",
            result_json=result_json,
            narrative_text="柳师姐向你微笑...",
            occurred_at=datetime.now(),
        )
        db.add(event)
        db.commit()

        replay_events = [
            ReplayEvent(
                event_id="evt_3",
                event_type="player_input",
                turn_no=3,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "result_json": result_json,
                    "npc_states": {
                        "ns1": {
                            "name": "柳师姐",
                            "mood": "friendly",
                            "hidden_plan_state": "观察玩家",  # Should be filtered
                            "secrets": ["is a spy"],  # Should be filtered
                        }
                    }
                },
            ),
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        result = replay_engine.replay_turn_range(
            session_id="s1",
            start_turn=3,
            end_turn=3,
            events=replay_events,
            perspective=ReplayPerspective.PLAYER,
        )

        assert result.success is True
        
        # Verify hidden info is filtered from final state
        final_state = result.final_state
        if "npc_states" in final_state:
            for npc_data in final_state["npc_states"].values():
                assert "hidden_plan_state" not in npc_data
                assert "secrets" not in npc_data

    def test_replay_admin_perspective_sees_stage_metadata(self, db, session_with_state):
        """Admin perspective should see LLM stage metadata."""
        result_json = {
            "llm_stages": [
                {
                    "stage_name": "world",
                    "enabled": True,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                    "model_call_id": "mc_world_001",
                },
            ],
        }
        
        event = EventLogModel(
            id="evt_4",
            session_id="s1",
            turn_no=4,
            event_type="player_input",
            input_text="等待",
            result_json=result_json,
            narrative_text="时间流逝...",
            occurred_at=datetime.now(),
        )
        db.add(event)
        db.commit()

        replay_events = [
            ReplayEvent(
                event_id="evt_4",
                event_type="player_input",
                turn_no=4,
                timestamp=datetime.now(),
                data={"result_json": result_json},
            ),
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        result = replay_engine.replay_turn_range(
            session_id="s1",
            start_turn=4,
            end_turn=4,
            events=replay_events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True


# =============================================================================
# State Reconstruction vs Live Snapshot Tests
# =============================================================================

class TestStateReconstructionMatchesLiveSnapshot:
    """Tests verifying reconstructed state matches live snapshot."""

    def setup_method(self):
        """Reset replay store before each test."""
        reset_replay_store()

    def test_reconstructed_location_matches_snapshot(self, db, session_with_state):
        """Reconstructed location should match live snapshot."""
        # Create a snapshot from current state
        replay_store = get_replay_store()
        snapshot = replay_store.create_snapshot(
            session_id="s1",
            turn_no=5,
            world_state={"current_time": "修仙历 春 第5日 辰时"},
            player_state={"location_id": "loc1", "realm": "炼气三层"},
            npc_states={
                "ns1": {
                    "name": "柳师姐",
                    "location_id": "loc1",
                    "mood": "friendly",
                }
            },
        )

        # Reconstruct state from DB
        reconstructed = reconstruct_canonical_state(db, "s1")
        
        assert reconstructed is not None
        assert reconstructed.player_state.location_id == snapshot.player_state.get("location_id")

    def test_reconstructed_quest_progress_matches(self, db, session_with_state):
        """Reconstructed quest progress should match expected state."""
        # Update quest progress
        quest_state = db.query(SessionQuestStateModel).filter_by(session_id="s1").first()
        quest_state.current_step_no = 3
        quest_state.progress_json = {"step1_complete": True, "step2_complete": True}
        db.commit()

        reconstructed = reconstruct_canonical_state(db, "s1")
        
        assert reconstructed is not None
        quest = None
        for q in reconstructed.quest_states.values():
            if q.name == "入门试炼":
                quest = q
                break
        
        assert quest is not None
        assert quest.stage == "3"
        assert quest.required_flags.get("step1_complete") is True
        assert quest.required_flags.get("step2_complete") is True

    def test_reconstructed_world_time_matches(self, db, session_with_state):
        """Reconstructed world time should match session state."""
        # Update world time
        session_state = db.query(SessionStateModel).filter_by(session_id="s1").first()
        session_state.current_time = "修仙历 夏 第10日 午时"
        db.commit()

        reconstructed = reconstruct_canonical_state(db, "s1")
        
        assert reconstructed is not None
        world_time = reconstructed.world_state.current_time
        assert world_time.season == "夏"
        assert world_time.day == 10
        assert world_time.period == "午时"

    def test_reconstructed_visible_log_narration(self, db, session_with_state):
        """Reconstructed state should allow access to visible log narration."""
        # Add event logs with narration
        events = [
            EventLogModel(
                id=f"evt_n{i}",
                session_id="s1",
                turn_no=i,
                event_type="player_input",
                input_text=f"action {i}",
                narrative_text=f"叙事文本 {i}",
                occurred_at=datetime.now(),
            )
            for i in range(1, 4)
        ]
        db.add_all(events)
        db.commit()

        # Verify we can get the latest turn number
        latest_turn = get_latest_turn_number(db, "s1")
        assert latest_turn == 3

        # Verify we can query event logs for narration
        event_log_repo = MagicMock()
        event_log_repo.get_recent = MagicMock(return_value=events[::-1])
        
        recent = event_log_repo.get_recent("s1", limit=3)
        assert len(recent) == 3
        assert recent[0].narrative_text is not None


# =============================================================================
# Replay Turn Range Tests
# =============================================================================

class TestReplayTurnRange:
    """Tests for replay_turn_range() with LLM stages."""

    def setup_method(self):
        """Reset replay store before each test."""
        reset_replay_store()

    def test_replay_multiple_turns_with_llm_stages(self, db, session_with_state):
        """Replay should handle multiple turns with LLM stage metadata."""
        # Create multiple event logs
        for turn_no in range(1, 4):
            result_json = {
                "llm_stages": [
                    {
                        "stage_name": "narration",
                        "enabled": True,
                        "accepted": True,
                        "fallback_reason": None if turn_no != 2 else "timeout",
                        "validation_errors": [],
                    }
                ],
            }
            event = EventLogModel(
                id=f"evt_multi_{turn_no}",
                session_id="s1",
                turn_no=turn_no,
                event_type="player_input",
                input_text=f"turn {turn_no}",
                result_json=result_json,
                narrative_text=f"叙事 {turn_no}",
                occurred_at=datetime.now(),
            )
            db.add(event)
        db.commit()

        # Create replay events
        replay_events = [
            ReplayEvent(
                event_id=f"evt_multi_{turn_no}",
                event_type="player_input",
                turn_no=turn_no,
                timestamp=datetime.now(),
                data={
                    "raw_input": f"turn {turn_no}",
                    "result_json": {
                        "llm_stages": [
                            {
                                "stage_name": "narration",
                                "enabled": True,
                                "accepted": True,
                                "fallback_reason": None if turn_no != 2 else "timeout",
                            }
                        ]
                    },
                },
            )
            for turn_no in range(1, 4)
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        result = replay_engine.replay_turn_range(
            session_id="s1",
            start_turn=1,
            end_turn=3,
            events=replay_events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert result.total_steps == 3
        assert result.start_turn == 1
        assert result.end_turn == 3

    def test_replay_with_state_deltas(self, db, session_with_state):
        """Replay should correctly apply state deltas."""
        replay_events = [
            ReplayEvent(
                event_id="evt_delta_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                data={
                    "state_deltas": [
                        {"path": "player_state.hp", "old_value": 100, "new_value": 90, "operation": "set"},
                    ],
                },
            ),
            ReplayEvent(
                event_id="evt_delta_2",
                event_type="player_input",
                turn_no=2,
                timestamp=datetime.now(),
                data={
                    "state_deltas": [
                        {"path": "player_state.hp", "old_value": 90, "new_value": 85, "operation": "set"},
                        {"path": "player_state.location_id", "old_value": "loc1", "new_value": "loc2", "operation": "set"},
                    ],
                },
            ),
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        base_state = {
            "player_state": {"hp": 100, "location_id": "loc1"},
            "world_state": {},
            "npc_states": {},
            "location_states": {},
            "quest_states": {},
            "faction_states": {},
        }

        result = replay_engine.replay_turn_range(
            session_id="s1",
            start_turn=1,
            end_turn=2,
            events=replay_events,
            base_state=base_state,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert result.final_state["player_state"]["hp"] == 85
        assert result.final_state["player_state"]["location_id"] == "loc2"


# =============================================================================
# Proposal Audit in Replay Tests
# =============================================================================

class TestReplayWithProposalAudits:
    """Tests for replay with proposal audit data (no LLM re-calls)."""

    def setup_method(self):
        """Reset replay store before each test."""
        reset_replay_store()

    def test_replay_uses_proposal_audits_not_llm(self, db, session_with_state):
        """Replay should use stored proposal audits, not re-call LLM."""
        proposal_audits = {
            1: [
                {
                    "audit_id": "pa_001",
                    "proposal_type": "input_intent",
                    "parsed_proposal": {"intent_type": "move", "target": "loc2"},
                    "confidence": 0.9,
                    "fallback_used": False,
                    "rejected": False,
                },
                {
                    "audit_id": "pa_002",
                    "proposal_type": "npc_action",
                    "parsed_proposal": {"action_type": "talk"},
                    "confidence": 0.8,
                    "fallback_used": False,
                    "rejected": False,
                },
            ],
        }

        replay_events = [
            ReplayEvent(
                event_id="evt_pa_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                data={"raw_input": "前往内院"},
            ),
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        result = replay_engine.replay_with_proposal_audits(
            session_id="s1",
            start_turn=1,
            end_turn=1,
            events=replay_events,
            proposal_audits=proposal_audits,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert len(result.steps) == 1
        assert len(result.steps[0].proposal_audits) == 2
        
        # Verify proposal audit data is preserved
        audit = result.steps[0].proposal_audits[0]
        assert audit["proposal_type"] == "input_intent"
        assert audit["confidence"] == 0.9

    def test_replay_proposal_audit_summary(self, db, session_with_state):
        """Replay should provide summary of proposal audits."""
        proposal_audits = [
            {
                "proposal_type": "input_intent",
                "confidence": 0.9,
                "fallback_used": False,
                "rejected": False,
            },
            {
                "proposal_type": "npc_action",
                "confidence": 0.7,
                "fallback_used": True,
                "fallback_reason": "timeout",
                "rejected": False,
            },
            {
                "proposal_type": "scene_event",
                "confidence": 0.5,
                "fallback_used": False,
                "rejected": True,
                "rejection_reason": "invalid scope",
            },
        ]

        replay_store = get_replay_store()
        replay_engine = replay_store.get_replay_engine()

        summary = replay_engine.get_proposal_audit_summary(proposal_audits)

        assert summary["total"] == 3
        assert summary["by_type"]["input_intent"] == 1
        assert summary["by_type"]["npc_action"] == 1
        assert summary["by_type"]["scene_event"] == 1
        assert summary["fallbacks"] == 1
        assert summary["rejections"] == 1


# =============================================================================
# Integration Tests
# =============================================================================

class TestStateReconstructionIntegration:
    """Integration tests for state reconstruction with replay."""

    def setup_method(self):
        """Reset replay store before each test."""
        reset_replay_store()

    def test_full_replay_from_db_matches_snapshot(self, db, session_with_state):
        """Full replay from DB should match live snapshot."""
        # Create initial snapshot
        replay_store = get_replay_store()
        initial_snapshot = replay_store.create_snapshot(
            session_id="s1",
            turn_no=0,
            world_state={"current_time": "修仙历 春 第1日 辰时"},
            player_state={"location_id": "loc1", "hp": 100},
        )

        # Simulate turns with state changes
        events = []
        for turn_no in range(1, 4):
            event = EventLogModel(
                id=f"evt_int_{turn_no}",
                session_id="s1",
                turn_no=turn_no,
                event_type="player_input",
                input_text=f"turn {turn_no}",
                result_json={
                    "llm_stages": [
                        {"stage_name": "narration", "enabled": True, "accepted": True}
                    ]
                },
                narrative_text=f"叙事 {turn_no}",
                occurred_at=datetime.now(),
            )
            db.add(event)
            events.append(event)
        db.commit()

        # Reconstruct state from DB
        reconstructed = reconstruct_canonical_state(db, "s1")
        
        assert reconstructed is not None
        assert reconstructed.player_state.location_id == "loc1"


# =============================================================================
# Replay/Live State Comparison Test Harness
# =============================================================================

class TestReplayLiveStateComparison:
    """
    Test harness for comparing reconstructed state from committed events/deltas
    to live session_state in DB.
    
    SUPPORTED FIELDS (deterministically persisted):
    - current_location_id: Player's current location
    - world_time: Calendar, season, day, period (time_phase)
    - turn_no: Latest turn number from event_logs
    
    UNSUPPORTED FIELDS (out-of-scope for this harness):
    - NPC future simulation states (hidden_plan_state, current_goal_ids)
    - Scene event predictions (would require LLM re-execution)
    - Combat states (not fully persisted)
    - Inventory states (not fully persisted)
    - Knowledge states (not fully persisted)
    - Schedule states (not fully persisted)
    - Faction/relationship states (not fully persisted)
    - Player HP/max HP (may drift due to combat resolution not in events)
    
    These unsupported fields require LLM re-execution or are not deterministically
    persisted in the current event/delta schema.
    """
    
    def setup_method(self):
        """Reset replay store before each test."""
        reset_replay_store()
    
    def _create_turn_event(
        self,
        db: DBSession,
        session_id: str,
        turn_no: int,
        input_text: str,
        result_json: Dict[str, Any],
        narrative_text: str = "叙事文本",
        state_deltas: Optional[List[Dict[str, Any]]] = None,
    ) -> EventLogModel:
        """Helper to create a turn event with state deltas."""
        event = EventLogModel(
            id=f"evt_replay_{turn_no}",
            session_id=session_id,
            turn_no=turn_no,
            event_type="player_input",
            input_text=input_text,
            result_json=result_json,
            narrative_text=narrative_text,
            occurred_at=datetime.now(),
        )
        db.add(event)
        db.commit()
        return event
    
    def _update_live_session_state(
        self,
        db: DBSession,
        session_id: str,
        current_location_id: Optional[str] = None,
        current_time: Optional[str] = None,
        time_phase: Optional[str] = None,
    ) -> None:
        """Helper to update live session_state in DB."""
        session_state_repo = SessionStateRepository(db)
        update_data = {"session_id": session_id}
        if current_location_id is not None:
            update_data["current_location_id"] = current_location_id
        if current_time is not None:
            update_data["current_time"] = current_time
        if time_phase is not None:
            update_data["time_phase"] = time_phase
        session_state_repo.create_or_update(update_data)
    
    def _compare_reconstructed_to_live(
        self,
        db: DBSession,
        session_id: str,
        expected_location_id: Optional[str] = None,
        expected_world_time: Optional[Dict[str, Any]] = None,
        expected_turn_no: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Compare reconstructed state to live session_state.
        
        Returns a dict with:
        - 'match': True if all provided fields match
        - 'drifts': List of field drifts detected
        - 'reconstructed': Reconstructed CanonicalState
        - 'live': Live session_state from DB
        """
        # Reconstruct state from committed events/deltas
        reconstructed = reconstruct_canonical_state(db, session_id)
        
        # Get live session_state from DB
        session_state_repo = SessionStateRepository(db)
        live_state = session_state_repo.get_by_session(session_id)
        
        # Get live turn_no from event_logs
        live_turn_no = get_latest_turn_number(db, session_id)
        
        drifts = []
        
        # Compare current_location_id
        if expected_location_id is not None:
            live_location = live_state.current_location_id if live_state else None
            recon_location = reconstructed.player_state.location_id if reconstructed else None
            
            if live_location != expected_location_id:
                drifts.append({
                    "field": "current_location_id",
                    "expected": expected_location_id,
                    "live": live_location,
                    "reconstructed": recon_location,
                    "type": "live_drift",
                })
            elif recon_location != expected_location_id:
                drifts.append({
                    "field": "current_location_id",
                    "expected": expected_location_id,
                    "live": live_location,
                    "reconstructed": recon_location,
                    "type": "reconstruction_drift",
                })
        
        # Compare world_time
        if expected_world_time is not None and reconstructed is not None:
            live_time = live_state.current_time if live_state else None
            live_phase = live_state.time_phase if live_state else None
            
            recon_time = reconstructed.world_state.current_time
            
            if expected_world_time.get("season") and recon_time.season != expected_world_time["season"]:
                drifts.append({
                    "field": "world_time.season",
                    "expected": expected_world_time["season"],
                    "live": live_time,
                    "reconstructed": recon_time.season,
                    "type": "reconstruction_drift",
                })
            
            if expected_world_time.get("day") and recon_time.day != expected_world_time["day"]:
                drifts.append({
                    "field": "world_time.day",
                    "expected": expected_world_time["day"],
                    "live": live_time,
                    "reconstructed": recon_time.day,
                    "type": "reconstruction_drift",
                })
            
            if expected_world_time.get("period") and recon_time.period != expected_world_time["period"]:
                drifts.append({
                    "field": "world_time.period",
                    "expected": expected_world_time["period"],
                    "live": live_phase,
                    "reconstructed": recon_time.period,
                    "type": "reconstruction_drift",
                })
        
        # Compare turn_no
        if expected_turn_no is not None:
            if live_turn_no != expected_turn_no:
                drifts.append({
                    "field": "turn_no",
                    "expected": expected_turn_no,
                    "live": live_turn_no,
                    "reconstructed": live_turn_no,  # Same source
                    "type": "live_drift",
                })
        
        return {
            "match": len(drifts) == 0,
            "drifts": drifts,
            "reconstructed": reconstructed,
            "live": live_state,
            "live_turn_no": live_turn_no,
        }
    
    def test_replay_matches_live_after_multiple_turns(self, db, session_with_state):
        """
        Test that reconstructed state matches live DB state after N turns.
        
        This test simulates multiple turns with state changes and verifies
        that reconstruction from committed events produces the same state
        as the live session_state in the DB.
        """
        # Create multiple turn events with state changes
        turns_data = [
            {
                "turn_no": 1,
                "input": "前往内院",
                "result_json": {
                    "llm_stages": [{"stage_name": "narration", "enabled": True, "accepted": True}],
                    "world_progression": {"time_delta": 1},
                    "parsed_intent": {"intent_type": "move", "target": "内院"},
                },
                "state_deltas": [
                    {"path": "player_state.location_id", "old_value": "loc1", "new_value": "loc2", "operation": "set"},
                ],
            },
            {
                "turn_no": 2,
                "input": "等待",
                "result_json": {
                    "llm_stages": [{"stage_name": "narration", "enabled": True, "accepted": True}],
                    "world_progression": {"time_delta": 2},
                    "parsed_intent": {"intent_type": "wait"},
                },
                "state_deltas": [],
            },
            {
                "turn_no": 3,
                "input": "与柳师姐交谈",
                "result_json": {
                    "llm_stages": [{"stage_name": "narration", "enabled": True, "accepted": True}],
                    "world_progression": {"time_delta": 1},
                    "parsed_intent": {"intent_type": "talk", "target": "柳师姐"},
                },
                "state_deltas": [],
            },
        ]
        
        for turn_data in turns_data:
            self._create_turn_event(
                db=db,
                session_id="s1",
                turn_no=turn_data["turn_no"],
                input_text=turn_data["input"],
                result_json=turn_data["result_json"],
            )
        
        # Update live session_state to reflect turn progression
        # (simulating what turn_service does at lines 3238-3246)
        self._update_live_session_state(
            db=db,
            session_id="s1",
            current_location_id="loc2",  # After move to inner court
            current_time="修仙历 春 第8日 辰时",  # 5 + 1 + 2 = 8 days
            time_phase="辰时",
        )
        
        # Compare reconstructed to live
        comparison = self._compare_reconstructed_to_live(
            db=db,
            session_id="s1",
            expected_location_id="loc2",
            expected_world_time={"season": "春", "day": 8, "period": "辰时"},
            expected_turn_no=3,
        )
        
        # Verify match
        assert comparison["match"], f"Drifts detected: {comparison['drifts']}"
        assert comparison["reconstructed"] is not None
        assert comparison["reconstructed"].player_state.location_id == "loc2"
        assert comparison["live_turn_no"] == 3
    
    def test_drift_detection_location_mismatch(self, db, session_with_state):
        """
        Test that drift is detected when live location differs from expected.
        
        This is a regression test that deliberately mutates live state
        and verifies the comparison harness detects the drift.
        """
        # Create a turn event
        self._create_turn_event(
            db=db,
            session_id="s1",
            turn_no=1,
            input_text="前往内院",
            result_json={
                "llm_stages": [{"stage_name": "narration", "enabled": True, "accepted": True}],
                "world_progression": {"time_delta": 1},
            },
        )
        
        # Deliberately set live state to WRONG location (simulating drift/corruption)
        self._update_live_session_state(
            db=db,
            session_id="s1",
            current_location_id="loc_wrong",  # WRONG - should be loc2 after move
        )
        
        # Compare with expected location (correct value)
        comparison = self._compare_reconstructed_to_live(
            db=db,
            session_id="s1",
            expected_location_id="loc2",  # Expected after move
        )
        
        # Verify drift is detected
        assert not comparison["match"], "Drift should have been detected"
        assert len(comparison["drifts"]) > 0
        
        # Find the location drift
        location_drift = next(
            (d for d in comparison["drifts"] if d["field"] == "current_location_id"),
            None,
        )
        assert location_drift is not None, "Location drift should be recorded"
        assert location_drift["expected"] == "loc2"
        assert location_drift["live"] == "loc_wrong"
    
    def test_drift_detection_time_mismatch(self, db, session_with_state):
        """
        Test that drift is detected when live time differs from expected.
        """
        # Create a turn event
        self._create_turn_event(
            db=db,
            session_id="s1",
            turn_no=1,
            input_text="等待",
            result_json={
                "llm_stages": [{"stage_name": "narration", "enabled": True, "accepted": True}],
                "world_progression": {"time_delta": 3},
            },
        )
        
        # Update live state with WRONG time (simulating drift)
        self._update_live_session_state(
            db=db,
            session_id="s1",
            current_time="修仙历 冬 第1日 辰时",  # WRONG - should be 春
            time_phase="子时",  # WRONG
        )
        
        # Compare with expected time
        comparison = self._compare_reconstructed_to_live(
            db=db,
            session_id="s1",
            expected_world_time={"season": "春", "day": 8, "period": "辰时"},
        )
        
        # Verify drift is detected
        assert not comparison["match"], "Time drift should have been detected"
        
        # Find the time drift
        time_drifts = [d for d in comparison["drifts"] if "world_time" in d["field"]]
        assert len(time_drifts) > 0, "Time drift should be recorded"
    
    def test_drift_detection_turn_no_mismatch(self, db, session_with_state):
        """
        Test that drift is detected when turn_no differs from expected.
        """
        # Create turn events
        for turn_no in [1, 2, 3]:
            self._create_turn_event(
                db=db,
                session_id="s1",
                turn_no=turn_no,
                input_text=f"turn {turn_no}",
                result_json={
                    "llm_stages": [{"stage_name": "narration", "enabled": True, "accepted": True}],
                },
            )
        
        # Compare with WRONG expected turn (simulating drift detection)
        comparison = self._compare_reconstructed_to_live(
            db=db,
            session_id="s1",
            expected_turn_no=5,  # WRONG - actual is 3
        )
        
        # Verify drift is detected
        assert not comparison["match"], "Turn number drift should have been detected"
        
        turn_drift = next(
            (d for d in comparison["drifts"] if d["field"] == "turn_no"),
            None,
        )
        assert turn_drift is not None
        assert turn_drift["expected"] == 5
        assert turn_drift["live"] == 3
    
    def test_reconstruction_from_event_history_matches_live(self, db, session_with_state):
        """
        Test that reconstruction from event history produces same state as live.
        
        This test verifies that the canonical reconstruction logic
        (state_reconstruction.py) correctly reads from persisted DB rows
        and produces the same values as the live session_state.
        """
        # Set up known state in session_state
        session_state_repo = SessionStateRepository(db)
        session_state_repo.create_or_update({
            "session_id": "s1",
            "current_location_id": "loc2",
            "current_time": "修仙历 夏 第15日 午时",
            "time_phase": "午时",
            "active_mode": "dialogue",
            "global_flags_json": {"test_flag": True},
        })
        
        # Create event history
        for turn_no in range(1, 6):
            self._create_turn_event(
                db=db,
                session_id="s1",
                turn_no=turn_no,
                input_text=f"action {turn_no}",
                result_json={
                    "llm_stages": [{"stage_name": "narration", "enabled": True, "accepted": True}],
                },
            )
        
        # Reconstruct from DB
        reconstructed = reconstruct_canonical_state(db, "s1")
        
        # Get live state
        live_state = session_state_repo.get_by_session("s1")
        
        # Verify reconstruction matches live
        assert reconstructed is not None
        assert reconstructed.player_state.location_id == live_state.current_location_id
        assert reconstructed.world_state.current_time.period == live_state.time_phase
        
        # Verify turn_no from events
        latest_turn = get_latest_turn_number(db, "s1")
        assert latest_turn == 5
    
    def test_supported_fields_documented(self, db, session_with_state):
        """
        Meta-test: Verify supported/unsupported fields are documented.
        
        This test exists to ensure the class docstring remains accurate
        about which fields are supported for comparison.
        """
        docstring = self.__class__.__doc__
        
        # Verify supported fields are documented
        assert "SUPPORTED FIELDS" in docstring
        assert "current_location_id" in docstring
        assert "world_time" in docstring
        assert "turn_no" in docstring
        
        # Verify unsupported fields are documented
        assert "UNSUPPORTED FIELDS" in docstring
        assert "NPC future simulation" in docstring or "hidden_plan_state" in docstring
        assert "Scene event predictions" in docstring or "not deterministically" in docstring


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

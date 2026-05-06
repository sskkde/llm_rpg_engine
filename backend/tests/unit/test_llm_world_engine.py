"""
Tests for WorldEngine proposal pipeline integration.

Tests that:
- WorldEngine uses ProposalPipeline for WorldTickProposal
- Valid proposals are candidates only (no direct state mutation)
- Fallback behavior works when pipeline is unavailable
- Deterministic time advancement remains authoritative
- Existing check_world_events remains as fallback
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any

from llm_rpg.models.states import (
    CanonicalState,
    WorldState,
    PlayerState,
    CurrentSceneState,
    NPCState,
)
from llm_rpg.models.events import WorldTime
from llm_rpg.models.proposals import (
    WorldTickProposal,
    CandidateEvent,
    StateDeltaCandidate,
    ProposalType,
    ProposalSource,
    ProposalAuditMetadata,
    ValidationStatus,
    RepairStatus,
)
from llm_rpg.engines.world_engine import WorldEngine


class MockCanonicalStateManager:
    def __init__(self, state: CanonicalState):
        self._state = state
    
    def get_state(self, game_id: str):
        return self._state


class MockEventLog:
    def __init__(self):
        self.events = []
    
    def record_event(self, transaction, event):
        self.events.append(event)


def create_mock_state() -> CanonicalState:
    return CanonicalState(
        world_state=WorldState(
            entity_id="world_1",
            world_id="test_world",
            current_time=WorldTime(
                calendar="standard",
                season="春",
                day=1,
                period="卯时",
            ),
            weather="晴",
            global_flags={},
        ),
        player_state=PlayerState(
            entity_id="player_1",
            name="Test Player",
            location_id="square",
        ),
        current_scene_state=CurrentSceneState(
            entity_id="square",
            scene_id="square",
            location_id="square",
            active_actor_ids=["player_1", "npc_1"],
        ),
        location_states={},
        npc_states={
            "npc_1": NPCState(
                entity_id="npc_1",
                npc_id="npc_1",
                name="Test NPC",
                location_id="square",
                status="alive",
                mood="neutral",
            ),
        },
        quest_states={},
        faction_states={},
    )


def create_mock_proposal(
    time_delta_turns: int = 1,
    is_fallback: bool = False,
    confidence: float = 0.8,
) -> WorldTickProposal:
    return WorldTickProposal(
        time_delta_turns=time_delta_turns,
        time_description="时间缓缓流逝...",
        candidate_events=[
            CandidateEvent(
                event_type="time_based",
                description="深夜时分，妖气加重",
                target_entity_ids=[],
                effects={"danger_level": 0.1},
                importance=0.5,
                visibility="player_visible",
            ),
        ],
        state_deltas=[
            StateDeltaCandidate(
                path="world_state.weather",
                operation="set",
                value="阴",
                reason="天气变化",
            ),
        ],
        affected_entities=[],
        visibility="mixed",
        confidence=confidence,
        audit=ProposalAuditMetadata(
            proposal_type=ProposalType.WORLD_TICK,
            source_engine=ProposalSource.WORLD_ENGINE,
            validation_status=ValidationStatus.PASSED,
            repair_status=RepairStatus.NONE,
        ),
        is_fallback=is_fallback,
    )


class TestWorldEngineProposalPipeline:
    """Test WorldEngine integration with ProposalPipeline."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def event_log(self):
        return MockEventLog()

    def test_world_engine_fallback_without_pipeline(
        self,
        state_manager,
        event_log,
    ):
        """WorldEngine should use fallback when no pipeline is provided."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        proposal = engine.generate_world_candidates(
            game_id="game_1",
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert proposal.audit.fallback_reason == "ProposalPipeline not configured"

    def test_world_engine_fallback_with_missing_state(
        self,
        event_log,
    ):
        """WorldEngine should return fallback when state is not found."""
        state_manager = MockCanonicalStateManager(None)
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=MagicMock(),
        )
        
        proposal = engine.generate_world_candidates(
            game_id="nonexistent_game",
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert "State not found" in proposal.audit.fallback_reason

    def test_world_engine_proposal_is_candidate_only(
        self,
        state,
        state_manager,
        event_log,
    ):
        """World proposal should not directly mutate state."""
        original_time = state.world_state.current_time.model_copy(deep=True)
        original_weather = state.world_state.weather
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        proposal = engine.generate_world_candidates(
            game_id="game_1",
            current_turn=1,
        )
        
        assert state.world_state.current_time == original_time
        assert state.world_state.weather == original_weather
        assert proposal.is_fallback is True

    def test_world_engine_deterministic_time_advancement(
        self,
        state,
        state_manager,
        event_log,
    ):
        """Deterministic time advancement should remain authoritative."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        original_period = state.world_state.current_time.period
        event = engine.advance_time("game_1", time_delta=1)
        
        assert event is not None
        assert event.time_before.period == original_period
        assert event.time_after.period != original_period

    def test_world_engine_check_world_events_fallback(
        self,
        state,
        state_manager,
        event_log,
    ):
        """check_world_events should be used as fallback for events."""
        state.world_state.current_time.period = "子时"
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        events = engine.check_world_events("game_1")
        
        assert len(events) > 0
        assert events[0]["type"] == "time_based"
        assert "妖气" in events[0]["description"]

    def test_world_engine_audit_log(
        self,
        state_manager,
        event_log,
    ):
        """WorldEngine should record audit entries."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        engine.generate_world_candidates(
            game_id="game_1",
            current_turn=1,
        )
        
        audit_log = engine.get_audit_log()
        assert len(audit_log) > 0
        assert audit_log[0]["type"] == "world_proposal_fallback"


class TestWorldContextBuilding:
    """Test world context building for LLM proposals."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def event_log(self):
        return MockEventLog()

    def test_build_world_context_includes_time(
        self,
        state_manager,
        event_log,
    ):
        """World context should include current time."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
        )
        
        state = state_manager.get_state("game_1")
        context = engine._build_world_context(state, current_turn=5)
        
        assert "time" in context
        assert context["time"]["period"] == "卯时"
        assert context["time"]["season"] == "春"
        assert context["time"]["day"] == 1

    def test_build_world_context_includes_weather(
        self,
        state_manager,
        event_log,
    ):
        """World context should include weather."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
        )
        
        state = state_manager.get_state("game_1")
        context = engine._build_world_context(state, current_turn=1)
        
        assert "weather" in context
        assert context["weather"] == "晴"

    def test_build_world_context_includes_global_flags(
        self,
        state,
        state_manager,
        event_log,
    ):
        """World context should include global flags."""
        state.world_state.global_flags = {"event_triggered": True}
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
        )
        
        context = engine._build_world_context(state, current_turn=1)
        
        assert "global_flags" in context
        assert context["global_flags"]["event_triggered"] is True

    def test_build_world_context_includes_npc_count(
        self,
        state_manager,
        event_log,
    ):
        """World context should include NPC count."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
        )
        
        state = state_manager.get_state("game_1")
        context = engine._build_world_context(state, current_turn=1)
        
        assert "npc_count" in context
        assert context["npc_count"] == 1


class TestProposalConversion:
    """Test conversion of WorldTickProposal fields."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def event_log(self):
        return MockEventLog()

    def test_fallback_proposal_structure(
        self,
        state_manager,
        event_log,
    ):
        """Fallback proposal should have correct structure."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        proposal = engine.generate_world_candidates(
            game_id="game_1",
            current_turn=1,
        )
        
        assert proposal.time_delta_turns == 1
        assert proposal.time_description == "时间缓缓流逝..."
        assert proposal.is_fallback is True
        assert proposal.audit.fallback_used is True

    def test_fallback_proposal_with_state_events(
        self,
        state,
        state_manager,
        event_log,
    ):
        """Fallback proposal should include check_world_events results."""
        state.world_state.current_time.period = "子时"
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        proposal = engine._create_fallback_proposal(
            reason="Test fallback",
            current_turn=1,
            state=state,
        )
        
        assert len(proposal.candidate_events) > 0
        assert proposal.candidate_events[0]["event_type"] == "time_based"


class TestTimeAdvancement:
    """Test deterministic time advancement."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def event_log(self):
        return MockEventLog()

    def test_advance_time_period(
        self,
        state_manager,
        event_log,
    ):
        """Time advancement should correctly advance period."""
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
        )
        
        event = engine.advance_time("game_1", time_delta=1)
        
        assert event.time_after.period == "辰时"

    def test_advance_time_day_change(
        self,
        state,
        state_manager,
        event_log,
    ):
        """Time advancement should correctly handle day changes."""
        state.world_state.current_time.period = "亥时"
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
        )
        
        event = engine.advance_time("game_1", time_delta=1)
        
        assert event.time_after.period == "子时"
        assert event.time_after.day == 2

    def test_advance_time_season_change(
        self,
        state,
        state_manager,
        event_log,
    ):
        """Time advancement should correctly handle season changes."""
        state.world_state.current_time.day = 30
        state.world_state.current_time.period = "亥时"
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
        )
        
        event = engine.advance_time("game_1", time_delta=1)
        
        assert event.time_after.day == 1
        assert event.time_after.season == "夏"


class TestNoStateMutation:
    """Test that world proposals do not mutate state."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def event_log(self):
        return MockEventLog()

    def test_proposal_does_not_mutate_weather(
        self,
        state,
        state_manager,
        event_log,
    ):
        """Proposal with weather delta should not mutate state."""
        original_weather = state.world_state.weather
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        proposal = engine._create_fallback_proposal(
            reason="Test",
            current_turn=1,
            state=state,
        )
        
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="world_state.weather",
                operation="set",
                value="暴风雨",
                reason="天气突变",
            )
        ]
        
        assert state.world_state.weather == original_weather

    def test_proposal_does_not_mutate_global_flags(
        self,
        state,
        state_manager,
        event_log,
    ):
        """Proposal with global flag delta should not mutate state."""
        state.world_state.global_flags = {"test_flag": False}
        original_flags = state.world_state.global_flags.copy()
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=None,
        )
        
        proposal = engine._create_fallback_proposal(
            reason="Test",
            current_turn=1,
            state=state,
        )
        
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="world_state.global_flags.test_flag",
                operation="set",
                value=True,
                reason="Flag triggered",
            )
        ]
        
        assert state.world_state.global_flags == original_flags


class TestWorldTickExceptionFallback:
    """Tests for world tick LLM exception fallback."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def event_log(self):
        return MockEventLog()

    def test_generate_world_tick_exception_falls_back(self, state, state_manager, event_log):
        mock_pipeline = MagicMock()
        
        async def mock_generate_error(*args, **kwargs):
            raise RuntimeError("LLM service unavailable")
        
        mock_pipeline.generate_world_tick = mock_generate_error
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=mock_pipeline,
        )
        
        proposal = engine.generate_world_candidates(
            game_id="test_game",
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert len(engine._audit_log) >= 1

    def test_turn_succeeds_with_world_fallback(self, state, state_manager, event_log):
        mock_pipeline = MagicMock()
        
        async def mock_generate_error(*args, **kwargs):
            raise RuntimeError("LLM timeout")
        
        mock_pipeline.generate_world_tick = mock_generate_error
        
        engine = WorldEngine(
            state_manager=state_manager,
            event_log=event_log,
            proposal_pipeline=mock_pipeline,
        )
        
        proposal = engine.generate_world_candidates(
            game_id="test_game",
            current_turn=1,
        )
        
        assert proposal.time_delta_turns == 1
        assert proposal.candidate_events == []
        assert proposal.confidence == 0.0


class TestWorldStageValidation:
    """Tests for world proposal validation in turn_service."""

    def test_validate_world_proposal_none(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        is_valid, errors = _validate_world_proposal(None)
        assert is_valid is False
        assert "proposal is None" in errors

    def test_validate_world_proposal_valid(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import StateDeltaCandidate
        proposal = create_mock_proposal()
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="global_flags.danger_level",
                operation="set",
                value=0.3,
                reason="深夜妖气加重",
            )
        ]
        is_valid, errors = _validate_world_proposal(proposal)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_world_proposal_forbidden_pattern(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        proposal = create_mock_proposal()
        proposal.candidate_events[0].description = "隐藏身份的秘密被发现"
        is_valid, errors = _validate_world_proposal(proposal)
        assert is_valid is False
        assert any("forbidden pattern" in e for e in errors)

    def test_validate_world_proposal_invalid_delta_path(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import StateDeltaCandidate
        proposal = create_mock_proposal()
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="player_state.hp",
                operation="set",
                value=0,
                reason="test",
            )
        ]
        is_valid, errors = _validate_world_proposal(proposal)
        assert is_valid is False
        assert any("not in allowed paths" in e for e in errors)

    def test_validate_world_proposal_valid_delta_paths(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import StateDeltaCandidate
        proposal = create_mock_proposal()
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="global_flags.event_triggered",
                operation="set",
                value=True,
                reason="test",
            ),
            StateDeltaCandidate(
                path="quest_progress.main_quest",
                operation="set",
                value="step_2",
                reason="test",
            ),
        ]
        is_valid, errors = _validate_world_proposal(proposal)
        assert is_valid is True

    def test_validate_world_proposal_empty_candidate_events(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import StateDeltaCandidate
        proposal = create_mock_proposal()
        proposal.candidate_events = []
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="global_flags.test",
                operation="set",
                value=True,
                reason="test",
            )
        ]
        is_valid, errors = _validate_world_proposal(proposal)
        assert is_valid is True

    def test_validate_world_proposal_empty_event_type(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import CandidateEvent
        proposal = create_mock_proposal()
        proposal.candidate_events = [
            CandidateEvent(
                event_type="",
                description="test event",
                target_entity_ids=[],
                effects={},
                importance=0.5,
                visibility="player_visible",
            )
        ]
        is_valid, errors = _validate_world_proposal(proposal)
        assert is_valid is False
        assert any("empty event_type" in e for e in errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

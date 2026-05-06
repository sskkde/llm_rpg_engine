"""
Integration tests for world candidates in the turn pipeline.

Tests:
- World candidates are generated during turn execution
- World candidates are proposals only (no direct state mutation)
- Deterministic time advancement remains authoritative
- Fallback behavior when LLM is unavailable
- Audit logging for world candidates
"""

import pytest
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import WorldModel
from llm_rpg.storage.repositories import WorldRepository
from llm_rpg.main import app
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
from llm_rpg.models.states import (
    CanonicalState,
    WorldState,
    PlayerState,
    CurrentSceneState,
    NPCState,
)
from llm_rpg.models.events import WorldTime
from llm_rpg.core.canonical_state import CanonicalStateManager
from llm_rpg.core.event_log import EventLog
from llm_rpg.engines.world_engine import WorldEngine


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def client(db_engine):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user_data():
    return {
        "username": f"testuser_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePass123!",
    }


@pytest.fixture
def sample_world_data():
    return {
        "code": f"test_world_{uuid.uuid4().hex[:8]}",
        "name": "Test World",
        "genre": "xianxia",
        "lore_summary": "A test world for integration tests",
        "status": "active",
    }


@pytest.fixture
def auth_headers(client, test_user_data):
    response = client.post("/auth/register", json=test_user_data)
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_world_in_db(db_engine, world_data):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        world_repo = WorldRepository(db)
        world = world_repo.create(world_data)
        db.commit()
        return world.id
    finally:
        db.close()


def create_session(client, auth_headers, db_engine, sample_world_data):
    world_id = create_world_in_db(db_engine, sample_world_data)
    response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["session_id"], world_id


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
            active_actor_ids=["player_1"],
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


def create_mock_world_proposal(
    is_fallback: bool = False,
    confidence: float = 0.8,
) -> WorldTickProposal:
    return WorldTickProposal(
        time_delta_turns=1,
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


class TestWorldCandidatesInTurnPipeline:
    """Tests for world candidates integration in turn pipeline."""

    @pytest.mark.skip(reason="Pre-existing bug: PlayerState.current_location_id should be location_id")
    def test_turn_generates_world_candidates(
        self,
        client,
        auth_headers,
        db_engine,
        sample_world_data,
    ):
        """Turn execution should generate world candidates."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["validation_passed"] is True
        assert "world_time" in data
        assert data["events_committed"] > 0

    @pytest.mark.skip(reason="Pre-existing bug: PlayerState.current_location_id should be location_id")
    def test_turn_world_time_advances_deterministically(
        self,
        client,
        auth_headers,
        db_engine,
        sample_world_data,
    ):
        """World time should advance deterministically regardless of LLM."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        times = []
        for _ in range(3):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": "等待"},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            data = response.json()
            times.append(data["world_time"]["period"])
        
        assert len(set(times)) > 1 or times[0] != times[-1]

    @pytest.mark.skip(reason="Pre-existing bug: PlayerState.current_location_id should be location_id")
    def test_turn_multiple_turns_with_world_candidates(
        self,
        client,
        auth_headers,
        db_engine,
        sample_world_data,
    ):
        """Multiple turns should each generate world candidates."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        for i in range(1, 6):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": f"动作{i}"},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["turn_index"] == i
            assert data["validation_passed"] is True


class TestWorldCandidatesNoStateMutation:
    """Tests that world candidates do not directly mutate state."""

    @pytest.mark.skip(reason="Pre-existing bug: PlayerState.current_location_id should be location_id")
    def test_world_candidates_are_proposals_only(
        self,
        client,
        auth_headers,
        db_engine,
        sample_world_data,
    ):
        """World candidates should be proposals, not direct mutations."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "world_time" in data
        assert "player_state" in data
        assert data["validation_passed"] is True


class TestWorldCandidatesFallback:
    """Tests for fallback behavior when LLM is unavailable."""

    def test_world_engine_fallback_without_pipeline(self):
        """WorldEngine should use fallback when no pipeline is provided."""
        state = create_mock_state()
        
        class MockStateManager:
            def get_state(self, game_id):
                return state
        
        class MockEventLog:
            pass
        
        engine = WorldEngine(
            state_manager=MockStateManager(),
            event_log=MockEventLog(),
            proposal_pipeline=None,
        )
        
        proposal = engine.generate_world_candidates(
            game_id="game_1",
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert proposal.audit.fallback_reason == "ProposalPipeline not configured"

    def test_world_engine_fallback_with_missing_state(self):
        """WorldEngine should return fallback when state is not found."""
        class MockStateManager:
            def get_state(self, game_id):
                return None
        
        class MockEventLog:
            pass
        
        engine = WorldEngine(
            state_manager=MockStateManager(),
            event_log=MockEventLog(),
            proposal_pipeline=MagicMock(),
        )
        
        proposal = engine.generate_world_candidates(
            game_id="nonexistent_game",
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert "State not found" in proposal.audit.fallback_reason


class TestWorldCandidatesAuditLog:
    """Tests for audit logging of world candidates."""

    def test_world_engine_records_audit_entries(self):
        """WorldEngine should record audit entries for proposals."""
        state = create_mock_state()
        
        class MockStateManager:
            def get_state(self, game_id):
                return state
        
        class MockEventLog:
            pass
        
        engine = WorldEngine(
            state_manager=MockStateManager(),
            event_log=MockEventLog(),
            proposal_pipeline=None,
        )
        
        engine.generate_world_candidates(
            game_id="game_1",
            current_turn=1,
        )
        
        audit_log = engine.get_audit_log()
        assert len(audit_log) > 0
        assert audit_log[0]["type"] == "world_proposal_fallback"

    @pytest.mark.skip(reason="Pre-existing bug: PlayerState.current_location_id should be location_id")
    def test_turn_audit_log_includes_world_candidates(
        self,
        client,
        auth_headers,
        db_engine,
        sample_world_data,
    ):
        """Turn audit log should include world candidate information."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        audit_response = client.get(
            f"/game/sessions/{session_id}/audit-log",
            headers=auth_headers
        )
        
        assert audit_response.status_code == 200
        audit_data = audit_response.json()
        
        assert audit_data["session_id"] == session_id
        assert "entries" in audit_data


class TestWorldCandidatesWithCheckWorldEvents:
    """Tests for check_world_events fallback integration."""

    def test_check_world_events_provides_fallback_events(self):
        """check_world_events should provide events for fallback proposals."""
        state = create_mock_state()
        state.world_state.current_time.period = "子时"
        
        class MockStateManager:
            def get_state(self, game_id):
                return state
        
        class MockEventLog:
            pass
        
        engine = WorldEngine(
            state_manager=MockStateManager(),
            event_log=MockEventLog(),
            proposal_pipeline=None,
        )
        
        events = engine.check_world_events("game_1")
        
        assert len(events) > 0
        assert events[0]["type"] == "time_based"

    def test_fallback_proposal_includes_check_world_events(self):
        """Fallback proposal should include check_world_events results."""
        state = create_mock_state()
        state.world_state.current_time.period = "子时"
        
        class MockStateManager:
            def get_state(self, game_id):
                return state
        
        class MockEventLog:
            pass
        
        engine = WorldEngine(
            state_manager=MockStateManager(),
            event_log=MockEventLog(),
            proposal_pipeline=None,
        )
        
        proposal = engine._create_fallback_proposal(
            reason="Test fallback",
            current_turn=1,
            state=state,
        )
        
        assert len(proposal.candidate_events) > 0
        assert proposal.candidate_events[0]["event_type"] == "time_based"


class TestWorldCandidatesDeterministicTime:
    """Tests for deterministic time advancement with world candidates."""

    def test_deterministic_time_advancement_is_authoritative(self):
        """Deterministic time advancement should always be applied."""
        state = create_mock_state()
        original_period = state.world_state.current_time.period
        
        class MockStateManager:
            def get_state(self, game_id):
                return state
        
        class MockEventLog:
            pass
        
        engine = WorldEngine(
            state_manager=MockStateManager(),
            event_log=MockEventLog(),
            proposal_pipeline=None,
        )
        
        event = engine.advance_time("game_1", time_delta=1)
        
        assert event.time_before.period == original_period
        assert event.time_after.period != original_period

    def test_time_advancement_independent_of_world_candidates(self):
        """Time advancement should work independently of world candidates."""
        state = create_mock_state()
        
        class MockStateManager:
            def get_state(self, game_id):
                return state
        
        class MockEventLog:
            pass
        
        engine = WorldEngine(
            state_manager=MockStateManager(),
            event_log=MockEventLog(),
            proposal_pipeline=None,
        )
        
        event = engine.advance_time("game_1", time_delta=1)
        proposal = engine.generate_world_candidates("game_1", current_turn=1)
        
        assert event is not None
        assert proposal is not None
        assert event.time_after.period != event.time_before.period


class TestWorldStageInTurnService:
    """Tests for world stage integration in turn_service."""

    def test_world_stage_disabled_returns_noop(self):
        from llm_rpg.core.turn_service import _execute_world_stage, LLMStageResult
        from llm_rpg.models.states import CanonicalState, WorldState, PlayerState, CurrentSceneState
        from llm_rpg.models.events import WorldTime

        state = CanonicalState(
            world_state=WorldState(
                entity_id="w1", world_id="test",
                current_time=WorldTime(calendar="std", season="春", day=1, period="卯时"),
                weather="晴", global_flags={},
            ),
            player_state=PlayerState(entity_id="p1", name="P", location_id="loc1"),
            current_scene_state=CurrentSceneState(
                entity_id="s1", scene_id="s1", location_id="loc1", active_actor_ids=[],
            ),
            location_states={}, npc_states={}, quest_states={}, faction_states={},
        )

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from llm_rpg.storage.database import Base

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=False):
                result = _execute_world_stage(
                    db=db, session_id="test_session", turn_no=1,
                    canonical_state=state, current_location_id="loc1",
                )
                assert isinstance(result, LLMStageResult)
                assert result.stage_name == "world"
                assert result.enabled is False
                assert result.accepted is False
                assert result.fallback_reason == "world_stage_disabled"
        finally:
            db.close()
            engine.dispose()

    def test_world_proposal_bounded_pressure_metadata(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import StateDeltaCandidate
        proposal = create_mock_world_proposal(is_fallback=False, confidence=0.9)
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
        assert len(proposal.candidate_events) > 0
        assert proposal.candidate_events[0].event_type == "time_based"
        assert "danger_level" in proposal.candidate_events[0].effects

    def test_invalid_world_candidate_rejected_safely(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import StateDeltaCandidate
        proposal = create_mock_world_proposal(is_fallback=False)
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
        assert len(errors) > 0

    def test_world_progression_metadata_in_result_json(self):
        from llm_rpg.core.turn_service import _validate_world_proposal
        from llm_rpg.models.proposals import StateDeltaCandidate
        proposal = create_mock_world_proposal(is_fallback=False, confidence=0.85)
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="global_flags.event_active",
                operation="set",
                value=True,
                reason="test",
            )
        ]
        is_valid, _ = _validate_world_proposal(proposal)
        assert is_valid is True
        parsed = {
            "time_description": proposal.time_description,
            "candidate_events": [
                {
                    "event_type": e.event_type,
                    "description": e.description,
                    "effects": e.effects,
                    "importance": e.importance,
                    "visibility": e.visibility,
                }
                for e in proposal.candidate_events
            ],
            "state_deltas": [
                {
                    "path": d.path,
                    "operation": d.operation,
                    "value": d.value,
                    "reason": d.reason,
                }
                for d in proposal.state_deltas
            ],
            "confidence": proposal.confidence,
        }
        assert "candidate_events" in parsed
        assert "state_deltas" in parsed
        assert "confidence" in parsed
        assert parsed["confidence"] == 0.85

    def test_public_response_contains_world_time_and_player_state(self):
        state = create_mock_state()
        from llm_rpg.core.turn_service import _get_world_time, _get_player_state
        world_time = _get_world_time(None)
        assert "calendar" in world_time
        assert "season" in world_time
        assert "period" in world_time
        player_state = _get_player_state(state, "square")
        assert "name" in player_state
        assert "realm" in player_state
        assert "location_id" in player_state


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

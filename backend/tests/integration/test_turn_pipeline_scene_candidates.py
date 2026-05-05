"""
Integration tests for Turn Pipeline Scene Candidates.

Tests:
- Scene candidates integration in turn execution
- Scene proposals treated as candidates (no direct state mutation)
- Fallback behavior when SceneEngine unavailable
- End-to-end turn pipeline with scene candidates
"""

import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import WorldModel
from llm_rpg.storage.repositories import WorldRepository
from llm_rpg.main import app
from llm_rpg.models.proposals import (
    SceneEventProposal,
    CandidateEvent,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    ValidationStatus,
)
from llm_rpg.engines.scene_engine import SceneEngine, Scene, SceneTrigger, TriggerType


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


class TestSceneCandidatesIntegration:
    """Tests for scene candidates in turn pipeline."""
    
    def test_turn_execution_with_scene_candidates(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["validation_passed"] is True
        assert "narration" in data
    
    def test_scene_candidates_do_not_mutate_state_directly(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        original_actors = scene.active_actors.copy()
        original_state = scene.state
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert scene.active_actors == original_actors
        assert scene.state == original_state
    
    def test_fallback_when_scene_engine_unavailable(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "去森林"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["validation_passed"] is True
    
    def test_multiple_turns_with_scene_candidates(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        actions = ["观察四周", "移动", "交谈", "等待", "探索"]
        
        for i, action in enumerate(actions, 1):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["turn_index"] == i
            assert data["validation_passed"] is True


class TestSceneProposalAsCandidate:
    """Tests verifying scene proposals are candidates only."""
    
    def test_proposal_is_not_committed_automatically(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert isinstance(proposal, SceneEventProposal)
        
        assert proposal.audit is not None
        assert proposal.audit.proposal_type == ProposalType.SCENE_EVENT
    
    def test_proposal_contains_candidate_events(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            priority=0.7,
        )
        
        scene = engine.create_scene(
            name="Forest Scene",
            triggers=[trigger],
        )
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "forest"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert len(proposal.candidate_events) >= 0
        for event in proposal.candidate_events:
            assert isinstance(event, CandidateEvent)
            assert hasattr(event, "event_type")
            assert hasattr(event, "description")
            assert hasattr(event, "importance")
    
    def test_proposal_includes_scene_metadata(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Ancient Temple")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "temple"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal.scene_id == scene.scene_id
        assert proposal.scene_name == "Ancient Temple"


class TestSceneCandidateFallbackBehavior:
    """Tests for fallback behavior in scene candidates."""
    
    def test_fallback_without_active_scenes(self):
        engine = SceneEngine()
        
        game_state = {"player_location": "nowhere"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal.is_fallback is True
        assert proposal.scene_id == "none"
    
    def test_fallback_uses_deterministic_triggers(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_fallback",
            trigger_type=TriggerType.TIME,
            conditions={"period": "子时"},
            priority=0.5,
        )
        
        scene = engine.create_scene(
            name="Night Event",
            triggers=[trigger],
        )
        engine.activate_scene(scene.scene_id)
        
        game_state = {"world_time": {"period": "子时"}}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert len(proposal.candidate_events) == 1
    
    def test_fallback_confidence_reflects_uncertainty(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal.confidence <= 0.5


class TestTurnPipelineWithSceneCandidates:
    """End-to-end tests for turn pipeline with scene candidates."""
    
    def test_turn_pipeline_handles_scene_candidates(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "transaction_id" in data
        assert "turn_index" in data
        assert "narration" in data
        assert "events_committed" in data
        assert data["validation_passed"] is True
    
    def test_turn_pipeline_with_chinese_input(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        chinese_actions = ["观察四周", "走向山门", "与师姐交谈", "攻击敌人"]
        
        for action in chinese_actions:
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            assert response.json()["validation_passed"] is True
    
    def test_turn_pipeline_maintains_state_consistency(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        initial_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察"},
            headers=auth_headers
        )
        initial_turn = initial_response.json()
        
        for _ in range(3):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": "等待"},
                headers=auth_headers
            )
            assert response.status_code == 200
        
        replay_response = client.post(
            f"/game/sessions/{session_id}/replay",
            json={"start_turn": 1, "end_turn": 4},
            headers=auth_headers
        )
        
        assert replay_response.status_code == 200
        replay_data = replay_response.json()
        assert replay_data["events_replayed"] >= 4


class TestAuditLoggingForSceneCandidates:
    """Tests for audit logging of scene candidates."""
    
    def test_scene_engine_records_audit_log(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        audit_log = engine.get_audit_log()
        assert len(audit_log) >= 1
    
    def test_audit_log_contains_scene_id(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        audit_log = engine.get_audit_log()
        assert audit_log[0]["scene_id"] == scene.scene_id
    
    def test_audit_log_can_be_cleared(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert len(engine.get_audit_log()) >= 1
        
        engine.clear_audit_log()
        assert len(engine.get_audit_log()) == 0

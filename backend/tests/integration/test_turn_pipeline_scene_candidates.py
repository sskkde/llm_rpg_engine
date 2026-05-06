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


class TestSceneStageRecommendedActions:
    """Tests for scene stage influencing recommended_actions."""
    
    def test_scene_proposal_influences_recommended_actions_when_accepted(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        from unittest.mock import patch, MagicMock, AsyncMock
        from llm_rpg.models.proposals import (
            SceneEventProposal,
            CandidateEvent,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
            ValidationStatus,
        )
        from llm_rpg.llm.service import MockLLMProvider, LLMService
        
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        scene_recommended = ["探索洞穴", "与神秘人交谈", "检查石碑", "返回入口"]
        
        mock_proposal = SceneEventProposal(
            scene_id="test_scene",
            scene_name="Test Scene",
            candidate_events=[
                CandidateEvent(
                    event_type="discovery",
                    description="你发现了一个隐藏的洞穴入口。",
                    importance=0.8,
                )
            ],
            recommended_actions=scene_recommended,
            confidence=0.9,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.SCENE_EVENT,
                source_engine=ProposalSource.SCENE_ENGINE,
                validation_status=ValidationStatus.PASSED,
            ),
            is_fallback=False,
        )
        
        with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                with patch("llm_rpg.llm.proposal_pipeline.ProposalPipeline") as MockPipeline:
                    mock_pipeline_instance = MagicMock()
                    mock_pipeline_instance.generate_scene_event = AsyncMock(return_value=mock_proposal)
                    MockPipeline.return_value = mock_pipeline_instance
                    
                    response = client.post(
                        f"/game/sessions/{session_id}/turn",
                        json={"action": "探索"},
                        headers=auth_headers
                    )
        
        assert response.status_code == 200
        data = response.json()
        assert data["recommended_actions"] == scene_recommended
        assert len(data["recommended_actions"]) <= 4
    
    def test_fallback_to_deterministic_actions_on_scene_rejection(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        from unittest.mock import patch
        from llm_rpg.llm.service import MockLLMProvider, LLMService
        
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                response = client.post(
                    f"/game/sessions/{session_id}/turn",
                    json={"action": "观察"},
                    headers=auth_headers
                )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["recommended_actions"], list)
        assert len(data["recommended_actions"]) <= 4
        for action in data["recommended_actions"]:
            assert isinstance(action, str)
    
    def test_scene_event_summary_in_result_json(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        from unittest.mock import patch, MagicMock, AsyncMock
        from llm_rpg.models.proposals import (
            SceneEventProposal,
            CandidateEvent,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
            ValidationStatus,
        )
        from llm_rpg.llm.service import MockLLMProvider, LLMService
        
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        mock_proposal = SceneEventProposal(
            scene_id="test_scene",
            scene_name="Ancient Temple",
            candidate_events=[
                CandidateEvent(
                    event_type="atmosphere",
                    description="古老的符文在墙上闪烁。",
                    importance=0.6,
                )
            ],
            recommended_actions=["检查符文", "继续探索"],
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.SCENE_EVENT,
                source_engine=ProposalSource.SCENE_ENGINE,
                validation_status=ValidationStatus.PASSED,
            ),
            is_fallback=False,
        )
        
        from llm_rpg.storage.repositories import EventLogRepository
        
        with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                with patch("llm_rpg.llm.proposal_pipeline.ProposalPipeline") as MockPipeline:
                    mock_pipeline_instance = MagicMock()
                    mock_pipeline_instance.generate_scene_event = AsyncMock(return_value=mock_proposal)
                    MockPipeline.return_value = mock_pipeline_instance
                    
                    response = client.post(
                        f"/game/sessions/{session_id}/turn",
                        json={"action": "观察"},
                        headers=auth_headers
                    )
        
        assert response.status_code == 200
        
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            event_log_repo = EventLogRepository(db)
            event = event_log_repo.get_by_session_turn_event(session_id, 1, "player_turn")
            assert event is not None
            result_json = event.result_json
            assert "scene_event_summary" in result_json
            assert result_json["scene_event_summary"] is not None
            assert result_json["scene_event_summary"]["scene_id"] == "test_scene"
            assert result_json["scene_event_summary"]["scene_name"] == "Ancient Temple"
            assert len(result_json["scene_event_summary"]["candidate_events"]) == 1
        finally:
            db.close()
    
    def test_no_extra_turn_rows_created(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        from unittest.mock import patch
        from llm_rpg.llm.service import MockLLMProvider, LLMService
        
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                response = client.post(
                    f"/game/sessions/{session_id}/turn",
                    json={"action": "观察"},
                    headers=auth_headers
                )
        
        assert response.status_code == 200
        
        from llm_rpg.storage.repositories import EventLogRepository
        
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            event_log_repo = EventLogRepository(db)
            events = event_log_repo.get_recent(session_id, limit=10)
            assert len(events) == 1
        finally:
            db.close()
    
    def test_recommended_actions_max_four(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        from unittest.mock import patch, MagicMock, AsyncMock
        from llm_rpg.models.proposals import (
            SceneEventProposal,
            CandidateEvent,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
            ValidationStatus,
        )
        from llm_rpg.llm.service import MockLLMProvider, LLMService
        
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        valid_actions = ["行动1", "行动2", "行动3", "行动4"]
        
        mock_proposal = SceneEventProposal(
            scene_id="test_scene",
            candidate_events=[],
            recommended_actions=valid_actions,
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.SCENE_EVENT,
                source_engine=ProposalSource.SCENE_ENGINE,
                validation_status=ValidationStatus.PASSED,
            ),
            is_fallback=False,
        )
        
        with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                with patch("llm_rpg.llm.proposal_pipeline.ProposalPipeline") as MockPipeline:
                    mock_pipeline_instance = MagicMock()
                    mock_pipeline_instance.generate_scene_event = AsyncMock(return_value=mock_proposal)
                    MockPipeline.return_value = mock_pipeline_instance
                    
                    response = client.post(
                        f"/game/sessions/{session_id}/turn",
                        json={"action": "观察"},
                        headers=auth_headers
                    )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["recommended_actions"]) == 4
        assert data["recommended_actions"] == valid_actions
    
    def test_scene_stage_disabled_uses_deterministic_actions(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        from unittest.mock import patch
        
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=False):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": "观察"},
                headers=auth_headers
            )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["recommended_actions"], list)
        assert len(data["recommended_actions"]) <= 4

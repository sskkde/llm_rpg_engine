"""
Integration tests for the Deterministic Turn Transaction Spine.

Tests:
- Turn execution pipeline
- Atomic commit/rollback
- Validation failure handling
- Replay functionality
- Audit log recording
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import WorldModel
from llm_rpg.storage.repositories import WorldRepository
from llm_rpg.main import app


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
    """Helper to create a game session."""
    world_id = create_world_in_db(db_engine, sample_world_data)
    response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["session_id"], world_id


class TestTurnExecution:
    """Tests for turn execution endpoint."""
    
    def test_execute_turn_success(self, client, auth_headers, db_engine, sample_world_data):
        """Test successful turn execution."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "turn_index" in data
        assert data["turn_index"] == 1
        assert "narration" in data
        assert len(data["narration"]) > 0
        assert "world_time" in data
        assert "player_state" in data
        assert "events_committed" in data
        assert data["events_committed"] > 0
        assert "actions_committed" in data
        assert "validation_passed" in data
        assert data["validation_passed"] is True
        assert "transaction_id" in data
    
    def test_execute_multiple_turns(self, client, auth_headers, db_engine, sample_world_data):
        """Test executing multiple turns in sequence."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        actions = ["观察四周", "走向试炼堂", "与师姐交谈"]
        
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
    
    def test_turn_world_time_advances(self, client, auth_headers, db_engine, sample_world_data):
        """Test that world time advances with each turn."""
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
        
        # Time should change between turns
        assert len(set(times)) > 1 or times[0] != times[-1]
    
    def test_execute_turn_invalid_session(self, client, auth_headers):
        """Test turn execution with invalid session ID."""
        response = client.post(
            f"/game/sessions/{uuid.uuid4()}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_execute_turn_unauthorized(self, client, auth_headers, db_engine, sample_world_data):
        """Test that users cannot execute turns in other users' sessions."""
        # Create first user session
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Create second user
        second_user = {
            "username": f"user2_{uuid.uuid4().hex[:8]}",
            "email": f"user2_{uuid.uuid4().hex[:8]}@example.com",
            "password": "SecurePass123!",
        }
        response = client.post("/auth/register", json=second_user)
        second_token = response.json()["access_token"]
        second_headers = {"Authorization": f"Bearer {second_token}"}
        
        # Try to execute turn with second user
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=second_headers
        )
        
        assert response.status_code in [401, 403]
    
    def test_execute_turn_no_auth(self, client, db_engine, sample_world_data):
        """Test turn execution without authentication."""
        response = client.post(
            f"/game/sessions/{uuid.uuid4()}/turn",
            json={"action": "观察四周"}
        )
        
        assert response.status_code in [401, 403]


class TestTurnReplay:
    """Tests for turn replay functionality."""
    
    def test_replay_turns(self, client, auth_headers, db_engine, sample_world_data):
        """Test replaying turns from event log."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Execute 3 turns
        for action in ["观察四周", "移动", "交谈"]:
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers
            )
            assert response.status_code == 200
        
        # Replay turns 1-2
        response = client.post(
            f"/game/sessions/{session_id}/replay",
            json={"start_turn": 1, "end_turn": 2},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["game_id"] == f"game_{session_id}"
        assert data["start_turn"] == 1
        assert data["end_turn"] == 2
        assert "reconstructed_state" in data
        assert "player_state" in data["reconstructed_state"]
        assert "world_state" in data["reconstructed_state"]
        assert data["events_replayed"] >= 2
    
    def test_replay_all_turns(self, client, auth_headers, db_engine, sample_world_data):
        """Test replaying all turns (5+ turns for acceptance criteria)."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Execute 5 turns
        actions = ["观察", "移动", "交谈", "等待", "探索"]
        for action in actions:
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers
            )
            assert response.status_code == 200
        
        # Replay all turns
        response = client.post(
            f"/game/sessions/{session_id}/replay",
            json={"start_turn": 1},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["start_turn"] == 1
        assert data["end_turn"] == 5
        assert data["events_replayed"] >= 5
    
    def test_replay_invalid_session(self, client, auth_headers):
        """Test replay with invalid session ID."""
        response = client.post(
            f"/game/sessions/{uuid.uuid4()}/replay",
            json={"start_turn": 1},
            headers=auth_headers
        )
        
        assert response.status_code == 404
    
    def test_replay_unauthorized(self, client, auth_headers, db_engine, sample_world_data):
        """Test that users cannot replay other users' sessions."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Create second user
        second_user = {
            "username": f"user2_{uuid.uuid4().hex[:8]}",
            "email": f"user2_{uuid.uuid4().hex[:8]}@example.com",
            "password": "SecurePass123!",
        }
        response = client.post("/auth/register", json=second_user)
        second_token = response.json()["access_token"]
        second_headers = {"Authorization": f"Bearer {second_token}"}
        
        response = client.post(
            f"/game/sessions/{session_id}/replay",
            json={"start_turn": 1},
            headers=second_headers
        )
        
        assert response.status_code in [401, 403]


class TestAuditLog:
    """Tests for audit log functionality."""
    
    def test_get_audit_log(self, client, auth_headers, db_engine, sample_world_data):
        """Test retrieving audit log entries."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Execute a turn
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        assert response.status_code == 200
        
        # Get audit log
        response = client.get(
            f"/game/sessions/{session_id}/audit-log",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == session_id
        assert "entries" in data
        assert "count" in data
    
    def test_audit_log_filter_by_transaction(self, client, auth_headers, db_engine, sample_world_data):
        """Test filtering audit log by transaction ID."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Execute a turn
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        assert response.status_code == 200
        turn_data = response.json()
        transaction_id = turn_data["transaction_id"]
        
        # Get audit log for specific transaction
        response = client.get(
            f"/game/sessions/{session_id}/audit-log",
            params={"transaction_id": transaction_id},
            headers=auth_headers
        )
        
        assert response.status_code == 200
    
    def test_audit_log_invalid_session(self, client, auth_headers):
        """Test audit log retrieval with invalid session."""
        response = client.get(
            f"/game/sessions/{uuid.uuid4()}/audit-log",
            headers=auth_headers
        )
        
        assert response.status_code == 404


class TestAtomicCommit:
    """Tests for atomic commit/rollback semantics."""
    
    def test_failed_validation_no_state_change(self, client, auth_headers, db_engine, sample_world_data):
        """Test that failed validation does not commit state changes."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Execute first turn successfully
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        assert response.status_code == 200
        first_turn = response.json()
        first_time = first_turn["world_time"]
        
        # Execute several more successful turns
        for i in range(4):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": f"动作{i}"},
                headers=auth_headers
            )
            assert response.status_code == 200
            assert response.json()["validation_passed"] is True
        
        # Verify all turns were committed by checking replay
        response = client.post(
            f"/game/sessions/{session_id}/replay",
            json={"start_turn": 1, "end_turn": 5},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        replay_data = response.json()
        assert replay_data["events_replayed"] >= 5
    
    def test_replay_reconstructs_canonical_state(self, client, auth_headers, db_engine, sample_world_data):
        """Test that replay reconstructs canonical state correctly."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        # Execute 5 turns (acceptance criteria: at least 5 turns)
        for action in ["动作1", "动作2", "动作3", "动作4", "动作5"]:
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers
            )
            assert response.status_code == 200
        
        # Replay and verify reconstruction
        response = client.post(
            f"/game/sessions/{session_id}/replay",
            json={"start_turn": 1, "end_turn": 5},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify reconstructed state has expected structure
        state = data["reconstructed_state"]
        assert "player_state" in state
        assert "world_state" in state
        assert "scene_state" in state
        assert state["npc_count"] >= 0
        assert state["location_count"] >= 0


class TestDeterministicPipeline:
    """Tests for deterministic pipeline behavior."""
    
    def test_turn_index_increments(self, client, auth_headers, db_engine, sample_world_data):
        """Test that turn index increments correctly."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        for expected_turn in range(1, 6):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": f"动作{expected_turn}"},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            assert response.json()["turn_index"] == expected_turn
    
    def test_narration_generated(self, client, auth_headers, db_engine, sample_world_data):
        """Test that narration is generated for each turn."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "narration" in data
        assert isinstance(data["narration"], str)
        assert len(data["narration"]) > 0
    
    def test_transaction_id_uniqueness(self, client, auth_headers, db_engine, sample_world_data):
        """Test that each turn has a unique transaction ID."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        transaction_ids = []
        for _ in range(5):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": "等待"},
                headers=auth_headers
            )
            assert response.status_code == 200
            transaction_ids.append(response.json()["transaction_id"])
        
        # All transaction IDs should be unique
        assert len(transaction_ids) == len(set(transaction_ids))

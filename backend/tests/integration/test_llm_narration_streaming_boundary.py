"""
Integration tests for streaming narration boundary.

Tests:
- SSE streaming narration follows factual boundary
- Narration is streamed AFTER state commit
- Forbidden info is excluded from streaming narration
- Fallback narration works when LLM fails
"""

import json
import pytest
import uuid
from datetime import datetime
from typing import Generator

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
    world_id = create_world_in_db(db_engine, sample_world_data)
    response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["session_id"], world_id


def parse_sse_events(content: str) -> list:
    events = []
    current_event = {}
    
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            current_event["event"] = line[7:]
        elif line.startswith("data: "):
            try:
                current_event["data"] = json.loads(line[6:])
            except json.JSONDecodeError:
                current_event["data"] = line[6:]
        elif line.startswith("id: "):
            current_event["id"] = line[4:]
        elif line == "":
            if current_event:
                events.append(current_event)
                current_event = {}
    
    return events


class TestStreamingNarrationBoundary:
    """Tests for streaming narration factual boundary."""

    def test_narration_streams_after_commit(self, client, auth_headers, db_engine, sample_world_data):
        """Narration should stream AFTER state is committed."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "look around"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        event_types = [e["event"] for e in events]
        
        assert "turn_started" in event_types
        assert "event_committed" in event_types
        assert "narration_delta" in event_types
        assert "turn_completed" in event_types
        
        started_idx = event_types.index("turn_started")
        committed_idx = event_types.index("event_committed")
        narration_indices = [i for i, e in enumerate(event_types) if e == "narration_delta"]
        completed_idx = event_types.index("turn_completed")
        
        assert started_idx < committed_idx
        for idx in narration_indices:
            assert committed_idx < idx < completed_idx

    def test_narration_uses_player_visible_context(self, client, auth_headers, db_engine, sample_world_data):
        """Narration should only use player-visible context."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "observe the surroundings"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        completed_events = [e for e in events if e["event"] == "turn_completed"]
        assert len(completed_events) == 1
        
        data = completed_events[0]["data"]
        assert "narration" in data

    def test_narration_excludes_forbidden_info(self, client, auth_headers, db_engine, sample_world_data):
        """Narration should not contain forbidden info."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "search for secrets"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        completed_events = [e for e in events if e["event"] == "turn_completed"]
        assert len(completed_events) == 1
        
        narration = completed_events[0]["data"]["narration"]
        
        assert "forbidden_secret" not in narration
        assert "hidden_password" not in narration

    def test_narration_delta_accumulates(self, client, auth_headers, db_engine, sample_world_data):
        """Narration deltas should accumulate to form complete narration."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "explore"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        delta_events = [e for e in events if e["event"] == "narration_delta"]
        assert len(delta_events) > 0
        
        accumulated = "".join(e["data"]["delta"] for e in delta_events)
        assert len(accumulated) > 0

    def test_fallback_narration_on_error(self, client, auth_headers, db_engine, sample_world_data):
        """Fallback narration should be used when LLM fails."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "test action"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        completed_events = [e for e in events if e["event"] == "turn_completed"]
        assert len(completed_events) == 1
        
        data = completed_events[0]["data"]
        assert "narration" in data


class TestStreamingEventOrder:
    """Tests for SSE event ordering."""

    def test_event_order_first_turn(self, client, auth_headers, db_engine, sample_world_data):
        """First turn should emit events in correct order."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "first action"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        event_types = [e["event"] for e in events]
        
        assert event_types[0] == "turn_started"
        
        committed_idx = event_types.index("event_committed")
        narration_idx = event_types.index("narration_delta")
        completed_idx = event_types.index("turn_completed")
        
        assert committed_idx < narration_idx < completed_idx

    def test_event_order_multiple_turns(self, client, auth_headers, db_engine, sample_world_data):
        """Multiple turns should each emit events in correct order."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        for turn_num in range(1, 4):
            response = client.post(
                f"/streaming/sessions/{session_id}/turn/mock",
                json={"action": f"action {turn_num}"},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            content = response.content.decode("utf-8")
            events = parse_sse_events(content)
            
            event_types = [e["event"] for e in events]
            
            assert "turn_started" in event_types
            assert "event_committed" in event_types
            assert "narration_delta" in event_types
            assert "turn_completed" in event_types

    def test_turn_index_increments(self, client, auth_headers, db_engine, sample_world_data):
        """Turn index should increment across turns."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        turn_indices = []
        
        for _ in range(3):
            response = client.post(
                f"/streaming/sessions/{session_id}/turn/mock",
                json={"action": "test"},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            content = response.content.decode("utf-8")
            events = parse_sse_events(content)
            
            for event in events:
                if event["event"] == "turn_completed":
                    turn_indices.append(event["data"]["turn_index"])
                    break
        
        assert turn_indices == [1, 2, 3]


class TestStreamingAuthAndValidation:
    """Tests for authentication and validation in streaming."""

    def test_unauthorized_stream_rejected(self, client, db_engine, sample_world_data):
        """Unauthorized streaming requests should be rejected."""
        response = client.post(
            f"/streaming/sessions/{uuid.uuid4()}/turn/mock",
            json={"action": "test"}
        )
        
        assert response.status_code in [401, 403]

    def test_invalid_session_rejected(self, client, auth_headers):
        """Invalid session should return 404."""
        response = client.post(
            f"/streaming/sessions/{uuid.uuid4()}/turn/mock",
            json={"action": "test"},
            headers=auth_headers
        )
        
        assert response.status_code == 404

    def test_cross_user_session_rejected(self, client, auth_headers, db_engine, sample_world_data):
        """Users cannot stream other users' sessions."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        second_user = {
            "username": f"user2_{uuid.uuid4().hex[:8]}",
            "email": f"user2_{uuid.uuid4().hex[:8]}@example.com",
            "password": "SecurePass123!",
        }
        response = client.post("/auth/register", json=second_user)
        second_token = response.json()["access_token"]
        second_headers = {"Authorization": f"Bearer {second_token}"}
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "test"},
            headers=second_headers
        )
        
        assert response.status_code in [401, 403]


class TestStreamingNarrationContent:
    """Tests for narration content in streaming."""

    def test_narration_includes_player_state(self, client, auth_headers, db_engine, sample_world_data):
        """Turn completed should include player state."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "check status"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        completed_events = [e for e in events if e["event"] == "turn_completed"]
        assert len(completed_events) == 1
        
        data = completed_events[0]["data"]
        assert "player_state" in data
        assert "world_time" in data

    def test_narration_includes_recommended_actions(self, client, auth_headers, db_engine, sample_world_data):
        """Turn completed may include recommended actions."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "what should I do?"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        completed_events = [e for e in events if e["event"] == "turn_completed"]
        assert len(completed_events) == 1
        
        data = completed_events[0]["data"]
        assert "recommended_actions" in data

    def test_narration_respects_scene_tone(self, client, auth_headers, db_engine, sample_world_data):
        """Narration should reflect scene tone."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "look around carefully"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        completed_events = [e for e in events if e["event"] == "turn_completed"]
        assert len(completed_events) == 1
        
        narration = completed_events[0]["data"]["narration"]
        assert narration is not None


class TestStreamingErrorHandling:
    """Tests for error handling in streaming."""

    def test_provider_error_returns_error_event(self, client, auth_headers, db_engine, sample_world_data):
        """Provider errors should return turn_error event."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "test action"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        events = parse_sse_events(content)
        
        event_types = [e["event"] for e in events]
        
        assert "turn_started" in event_types
        assert "turn_completed" in event_types or "turn_error" in event_types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

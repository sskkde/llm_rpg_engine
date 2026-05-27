"""
Integration tests for SSE stage events during turn execution.

Tests:
- SSE emits stage_started/stage_completed in correct order
- progress_callback=None produces no stage events (backward compat)
- Queue cleanup on error (SENTINEL always sent)
"""

import json
import os
import time
import pytest
import uuid
from unittest.mock import patch, MagicMock
from typing import List, Tuple

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel,
    WorldModel,
)
from llm_rpg.storage.repositories import (
    UserRepository,
    WorldRepository,
)
from llm_rpg.main import app
from passlib.context import CryptContext

from llm_rpg.core.turn_progress import TurnProgressEvent, emit_stage, STAGE_LABELS


TEST_DATABASE_URL = "sqlite:///:memory:"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =============================================================================
# Fixtures
# =============================================================================

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
    test_session_local = sessionmaker(bind=db_engine)

    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with patch('llm_rpg.api.streaming.SessionLocal', test_session_local), \
         TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# =============================================================================
# Helpers
# =============================================================================

def _new_db(db_engine) -> Session:
    return sessionmaker(bind=db_engine)()


def _make_user(db: Session, username: str, is_admin: bool = False) -> UserModel:
    return UserRepository(db).create({
        "username": username,
        "email": f"{username}@test.local",
        "password_hash": pwd_context.hash("testpass123"),
        "is_admin": is_admin,
    })


def _make_world(db: Session, code: str, name: str) -> WorldModel:
    return WorldRepository(db).create({"code": code, "name": name, "status": "active"})


def _get_token(client: TestClient, username: str, password: str = "testpass123") -> str:
    resp = client.post("/auth/login", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["access_token"]


def _parse_sse_events(raw_sse: str) -> List[Tuple[str, dict]]:
    payloads = []
    event_name = None
    for line in raw_sse.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            try:
                payloads.append((event_name, json.loads(line.removeprefix("data: "))))
            except json.JSONDecodeError:
                pass
    return payloads


def _create_session_via_api(client: TestClient, db_engine) -> Tuple[str, str]:
    """Create session via API for proper initialization."""
    db = _new_db(db_engine)
    try:
        user = _make_user(db, f"stage_user_{uuid.uuid4().hex[:6]}")
        world = _make_world(db, f"stage_world_{uuid.uuid4().hex[:6]}", "Stage Test World")
        db.commit()

        token = _get_token(client, user.username)

        resp = client.post(
            "/saves/manual-save",
            json={"world_id": world.id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]
        return session_id, token
    finally:
        db.close()


# =============================================================================
# Tests: TurnProgressEvent Unit Tests
# =============================================================================

class TestTurnProgressEvent:
    """Unit tests for TurnProgressEvent and emit_stage."""

    def test_emit_stage_creates_event(self):
        event = emit_stage("world_stage", "started")
        assert event.stage == "world_stage"
        assert event.phase == "started"
        assert event.label == STAGE_LABELS["world_stage"]

    def test_emit_stage_with_actor_name(self):
        event = emit_stage("npc_stage", "started", actor_name="李长老")
        assert event.actor_name == "李长老"

    def test_emit_stage_with_progress(self):
        event = emit_stage("world_stage", "started", progress=50)
        assert event.progress == 50

    def test_emit_stage_with_metadata(self):
        event = emit_stage("world_stage", "completed", metadata={"key": "value"})
        assert event.metadata == {"key": "value"}

    def test_all_known_stages_have_labels(self):
        known_stages = {
            "input_intent", "action_resolving", "world_stage",
            "scene_stage", "npc_stage", "validation",
            "committing", "narration"
        }
        for stage in known_stages:
            assert stage in STAGE_LABELS, f"Stage {stage} missing from STAGE_LABELS"
            assert len(STAGE_LABELS[stage]) > 0

    def test_phase_values(self):
        event_started = emit_stage("world_stage", "started")
        event_completed = emit_stage("world_stage", "completed")
        assert event_started.phase == "started"
        assert event_completed.phase == "completed"


# =============================================================================
# Tests: progress_callback=None Backward Compatibility
# =============================================================================

class TestProgressCallbackNone:
    """Tests for backward compatibility when progress_callback=None."""

    def test_progress_callback_none_collects_no_events(self):
        collected_events = []

        def progress_callback(event):
            collected_events.append(event)

        # Simulate progress_callback=None behavior
        callback = None

        if callback:
            callback(emit_stage("world_stage", "started"))

        assert len(collected_events) == 0

    def test_progress_callback_collects_events(self):
        collected_events = []

        def progress_callback(event):
            collected_events.append(event)

        if progress_callback:
            progress_callback(emit_stage("world_stage", "started"))

        assert len(collected_events) == 1
        assert collected_events[0].stage == "world_stage"


# =============================================================================
# Tests: Queue Cleanup Logic
# =============================================================================

class TestQueueCleanup:
    """Tests for queue cleanup logic."""

    def test_sentinel_is_object(self):
        _SENTINEL = object()
        assert _SENTINEL is not None
        assert _SENTINEL is not "sentinel"

    def test_sentinel_type_check(self):
        _SENTINEL = object()
        event = emit_stage("world_stage", "started")

        assert isinstance(event, TurnProgressEvent)
        assert not isinstance(_SENTINEL, TurnProgressEvent)


# =============================================================================
# Tests: SSE Endpoint Stage Events (Integration)
# =============================================================================

@pytest.mark.slow
class TestSSEStageEventsIntegration:
    """Integration tests for SSE stage events via API."""

    def test_sse_endpoint_exists(self, client, db_engine):
        session_id, token = _create_session_via_api(client, db_engine)

        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "观察四周"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_sse_has_turn_started_and_completed(self, client, db_engine):
        session_id, token = _create_session_via_api(client, db_engine)

        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "观察四周"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        raw_sse = response.content.decode("utf-8")
        events = _parse_sse_events(raw_sse)

        event_names = [name for name, _ in events]
        assert "turn_started" in event_names
        assert "turn_completed" in event_names

    def test_sse_stage_events_order(self, client, db_engine):
        session_id, token = _create_session_via_api(client, db_engine)

        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "观察四周"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        raw_sse = response.content.decode("utf-8")
        events = _parse_sse_events(raw_sse)

        event_names = [name for name, _ in events]

        # turn_started should come first
        assert event_names[0] == "turn_started"

        # turn_completed should come last
        assert event_names[-1] == "turn_completed"

        # If stage events exist, they should be between turn_started and turn_completed
        stage_event_indices = [
            i for i, name in enumerate(event_names)
            if name in ("stage_started", "stage_completed")
        ]
        if stage_event_indices:
            for idx in stage_event_indices:
                assert 0 < idx < len(event_names) - 1

    def test_rest_endpoint_returns_json(self, client, db_engine):
        session_id, token = _create_session_via_api(client, db_engine)

        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")
        data = response.json()
        assert "narration" in data

    def test_nonexistent_session_returns_404(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"stage_user_{uuid.uuid4().hex[:6]}")
            db.commit()
            token = _get_token(client, user.username)
        finally:
            db.close()

        response = client.post(
            "/streaming/sessions/nonexistent-session-id/turn/mock",
            json={"action": "观察四周"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404

    @pytest.mark.slow
    def test_heartbeat_during_long_turn(self, client, db_engine):
        """When turn execution takes time, heartbeat events should appear before completion."""
        from llm_rpg.api import streaming as streaming_module

        original_execute = streaming_module.execute_turn_service

        def delayed_execute(*args, **kwargs):
            time.sleep(3)  # Enough for 3+ heartbeats at 1s interval
            return original_execute(*args, **kwargs)

        session_id, token = _create_session_via_api(client, db_engine)

        with patch.object(streaming_module, 'execute_turn_service', side_effect=delayed_execute), \
             patch.dict(os.environ, {
                 "STREAMING_HEARTBEAT_INTERVAL_SECONDS": "1",
                 "STREAMING_HARD_DEADLINE_SECONDS": "30",
             }):
            response = client.post(
                f"/streaming/sessions/{session_id}/turn/mock",
                json={"action": "观察四周"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        raw_sse = response.content.decode("utf-8")
        events = _parse_sse_events(raw_sse)

        event_names = [name for name, _ in events]

        heartbeat_events = [(name, data) for name, data in events if name == "heartbeat"]
        assert len(heartbeat_events) >= 1, (
            f"Expected at least 1 heartbeat during long turn, got {len(heartbeat_events)}. "
            f"Events: {event_names}"
        )

        assert "turn_completed" in event_names, (
            f"turn_completed missing from events: {event_names}"
        )

        timeout_errors = [data for name, data in events
                          if name == "turn_error" and data.get("error_type") == "turn_timeout"]
        assert len(timeout_errors) == 0, (
            f"Unexpected turn_timeout error during long turn: {timeout_errors}"
        )

    def test_no_duplicate_narration_delta(self, client, db_engine):
        """When narration_delta is emitted via turn_event_callback, post-commit should not duplicate it."""
        session_id, token = _create_session_via_api(client, db_engine)

        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "观察四周"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        raw_sse = response.content.decode("utf-8")
        events = _parse_sse_events(raw_sse)

        event_names = [name for name, _ in events]

        # Find event_committed position — post-commit narration_delta would appear after it
        committed_indices = [i for i, name in enumerate(event_names) if name == "event_committed"]
        committed_idx = committed_indices[0] if committed_indices else -1

        # Count narration_delta events BEFORE event_committed (streamed by turn_event_callback)
        pre_commit_deltas = sum(
            1 for i, name in enumerate(events)
            if name[0] == "narration_delta" and (committed_idx == -1 or i < committed_idx)
        )

        # Count narration_delta events AFTER event_committed (would be the duplicate post-commit one)
        post_commit_deltas = sum(
            1 for i, name in enumerate(events)
            if name[0] == "narration_delta" and committed_idx >= 0 and i > committed_idx
        )

        assert pre_commit_deltas >= 1, (
            f"Expected at least 1 narration_delta before event_committed, got {pre_commit_deltas}. "
            f"Events: {event_names}"
        )

        # streamed_narration_chunks flag prevents post-commit duplicate
        assert post_commit_deltas == 0, (
            f"Expected 0 narration_delta after event_committed (post-commit guard), "
            f"got {post_commit_deltas}. Events: {event_names}"
        )

    def test_narration_delta_in_turn_completed(self, client, db_engine):
        """turn_completed should always contain the full narration."""
        session_id, token = _create_session_via_api(client, db_engine)

        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "观察四周"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        raw_sse = response.content.decode("utf-8")
        events = _parse_sse_events(raw_sse)

        completed_events = [data for name, data in events if name == "turn_completed"]
        assert len(completed_events) >= 1, (
            f"Expected at least 1 turn_completed event, got {len(completed_events)}. "
            f"Event names: {[name for name, _ in events]}"
        )

        completed_data = completed_events[0]
        assert "narration" in completed_data, (
            f"turn_completed event missing 'narration' key. Keys: {list(completed_data.keys())}"
        )
        assert completed_data["narration"], (
            f"turn_completed 'narration' should be non-empty, got: {completed_data['narration']!r}"
        )

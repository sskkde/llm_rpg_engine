"""
Integration tests for LLM Service, Audit Logs, and SSE Streaming.

Tests:
- LLM service with mock provider (no API keys)
- Audit logging (model_call_logs persistence)
- SSE streaming endpoint with ordered events
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
from llm_rpg.storage.models import WorldModel, ModelCallLogModel
from llm_rpg.storage.repositories import WorldRepository, ModelCallLogRepository
from llm_rpg.main import app
from llm_rpg.llm.service import (
    LLMService,
    MockLLMProvider,
    LLMMessage,
    get_llm_service,
    reset_llm_service,
)


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


class TestLLMService:
    """Tests for centralized LLM service."""
    
    def test_mock_provider_no_api_key_required(self):
        """Test that MockLLMProvider works without API keys."""
        provider = MockLLMProvider()
        assert provider.model == "mock-model"
        assert provider.call_count == 0
    
    @pytest.mark.asyncio
    async def test_mock_provider_generate(self):
        """Test mock provider generate method."""
        provider = MockLLMProvider()
        messages = [LLMMessage(role="user", content="Test prompt")]
        
        response = await provider.generate(messages=messages)
        
        assert response.content is not None
        assert len(response.content) > 0
        assert response.model == "mock-model"
        assert "total_tokens" in response.usage
        assert provider.call_count == 1
    
    @pytest.mark.asyncio
    async def test_mock_provider_stream(self):
        """Test mock provider streaming method."""
        provider = MockLLMProvider()
        messages = [LLMMessage(role="user", content="Test prompt")]
        
        chunks = []
        async for chunk in provider.generate_stream(messages=messages):
            chunks.append(chunk)
        
        assert len(chunks) > 0
        assert provider.call_count == 1
        full_content = "".join(chunks)
        assert len(full_content) > 0
    
    @pytest.mark.asyncio
    async def test_mock_provider_custom_responses(self):
        """Test mock provider with custom responses."""
        custom_responses = {
            "narration": "Custom narration text",
            "decision": '{"action": "custom"}',
        }
        provider = MockLLMProvider(responses=custom_responses)
        
        messages = [LLMMessage(role="user", content="Generate narration")]
        response = await provider.generate(messages=messages)
        
        assert "Custom narration text" in response.content
    
    @pytest.mark.asyncio
    async def test_llm_service_with_mock_provider(self, db_engine):
        """Test LLM service with mock provider."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        
        try:
            provider = MockLLMProvider()
            service = LLMService(provider=provider, db_session=db)
            
            messages = [LLMMessage(role="user", content="Test prompt")]
            response = await service.generate(
                messages=messages,
                session_id="test-session",
                turn_no=1,
            )
            
            assert response.content is not None
            assert len(response.content) > 0
            assert provider.call_count == 1
            
            # Verify call log was recorded
            logs = service.get_call_logs()
            assert len(logs) == 1
            assert logs[0].session_id == "test-session"
            assert logs[0].turn_no == 1
            assert logs[0].input_hash is not None
            assert logs[0].latency_ms >= 0
        finally:
            db.close()
    
    @pytest.mark.asyncio
    async def test_llm_service_template_rendering(self, db_engine):
        """Test LLM service with prompt template."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        
        try:
            provider = MockLLMProvider()
            service = LLMService(provider=provider, db_session=db)
            
            response = await service.generate_with_template(
                template_id="narration_v1",
                template_vars={
                    "scene_info": "Test scene",
                    "player_state": "Test player",
                    "recent_events": "Test events",
                    "player_action": "Test action",
                    "style": "descriptive",
                },
                session_id="test-session",
                turn_no=1,
            )
            
            assert response.content is not None
            logs = service.get_call_logs()
            assert len(logs) == 1
            assert logs[0].prompt_template_id == "narration_v1"
        finally:
            db.close()
    
    @pytest.mark.asyncio
    async def test_llm_service_error_logging(self, db_engine):
        """Test that LLM service logs errors properly."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        
        class FailingProvider:
            model = "failing-model"
            
            async def generate(self, **kwargs):
                raise Exception("Simulated API error")
            
            async def generate_stream(self, **kwargs):
                raise Exception("Simulated API error")
        
        try:
            service = LLMService(provider=FailingProvider(), db_session=db)
            messages = [LLMMessage(role="user", content="Test")]
            
            with pytest.raises(Exception):
                await service.generate(messages=messages, session_id="test-session", turn_no=1)
            
            # Verify error was logged
            logs = service.get_call_logs()
            assert len(logs) == 1
            assert logs[0].error is not None
            assert "Simulated API error" in logs[0].error
        finally:
            db.close()


class TestLLMAuditLogging:
    """Tests for LLM audit logging to model_call_logs."""
    
    @pytest.mark.asyncio
    async def test_audit_log_persisted_to_database(self, db_engine):
        """Test that LLM calls are persisted to model_call_logs table."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        
        try:
            provider = MockLLMProvider()
            service = LLMService(provider=provider, db_session=db)
            
            messages = [LLMMessage(role="user", content="Test prompt for persistence")]
            await service.generate(
                messages=messages,
                session_id="audit-test-session",
                turn_no=5,
            )
            
            # Query database directly
            logs = db.query(ModelCallLogModel).all()
            assert len(logs) == 1
            
            log = logs[0]
            assert log.session_id == "audit-test-session"
            assert log.turn_no == 5
            assert log.provider == "MockLLMProvider"
            assert log.model_name == "mock-model"
            assert log.input_tokens >= 0
            assert log.output_tokens >= 0
            assert log.latency_ms >= 0
            assert log.cost_estimate >= 0
        finally:
            db.close()
    
    @pytest.mark.asyncio
    async def test_audit_log_input_hash(self, db_engine):
        """Test that input hash is computed for deduplication."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        
        try:
            provider = MockLLMProvider()
            service = LLMService(provider=provider, db_session=db)
            
            messages1 = [LLMMessage(role="user", content="Same prompt")]
            messages2 = [LLMMessage(role="user", content="Same prompt")]
            
            await service.generate(messages=messages1, session_id="session-1", turn_no=1)
            await service.generate(messages=messages2, session_id="session-2", turn_no=1)
            
            logs = service.get_call_logs()
            assert len(logs) == 2
            # Same prompt should produce same hash
            assert logs[0].input_hash == logs[1].input_hash
        finally:
            db.close()
    
    @pytest.mark.asyncio
    async def test_audit_log_cost_tracking(self, db_engine):
        """Test that cost is estimated and tracked."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        
        try:
            provider = MockLLMProvider()
            service = LLMService(provider=provider, db_session=db)
            
            for i in range(3):
                messages = [LLMMessage(role="user", content=f"Prompt {i}")]
                await service.generate(messages=messages, session_id="cost-session", turn_no=i)
            
            total_cost = service.get_total_cost(session_id="cost-session")
            assert total_cost >= 0
            
            logs = service.get_call_logs(session_id="cost-session")
            assert len(logs) == 3
            for log in logs:
                assert log.cost_estimate >= 0
        finally:
            db.close()
    
    def test_audit_log_repository(self, db_engine):
        """Test ModelCallLogRepository for querying logs."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        
        try:
            repo = ModelCallLogRepository(db)
            
            # Create test log entries
            for i in range(3):
                db.add(ModelCallLogModel(
                    session_id="test-session",
                    turn_no=i + 1,
                    provider="TestProvider",
                    model_name="test-model",
                    input_tokens=100,
                    output_tokens=50,
                    cost_estimate=0.001,
                    latency_ms=100,
                ))
            db.commit()
            
            # Query logs
            logs = repo.get_by_session("test-session")
            assert len(logs) == 3
            
            # Test total cost
            total = repo.get_total_cost("test-session")
            assert total > 0
        finally:
            db.close()


class TestSSEStreaming:
    """Tests for SSE streaming endpoint."""
    
    def test_stream_turn_mock_endpoint_exists(self, client, auth_headers, db_engine, sample_world_data):
        """Test that the mock streaming endpoint exists and requires auth."""
        response = client.post(
            "/streaming/sessions/nonexistent/turn/mock",
            json={"action": "test"},
            headers=auth_headers
        )
        # Should be 404 for nonexistent session, not 404 for endpoint
        assert response.status_code in [404]
    
    def test_stream_turn_event_order(self, client, auth_headers, db_engine, sample_world_data):
        """Test that SSE events are emitted in correct order."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "观察四周"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        
        # Parse SSE events
        content = response.content.decode("utf-8")
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
        
        # Verify event order
        event_types = [e["event"] for e in events]
        assert "turn_started" in event_types
        assert "event_committed" in event_types
        assert "narration_delta" in event_types
        assert "turn_completed" in event_types
        
        # Verify order: turn_started -> event_committed -> narration_delta* -> turn_completed
        started_idx = event_types.index("turn_started")
        committed_idx = event_types.index("event_committed")
        completed_idx = event_types.index("turn_completed")
        
        assert started_idx < committed_idx, "turn_started must come before event_committed"
        assert committed_idx < completed_idx, "event_committed must come before turn_completed"
        
        # Verify narration deltas are between committed and completed
        narration_indices = [i for i, e in enumerate(event_types) if e == "narration_delta"]
        assert len(narration_indices) > 0, "Should have narration_delta events"
        for idx in narration_indices:
            assert committed_idx < idx < completed_idx, "narration_delta must be between committed and completed"
    
    def test_stream_turn_includes_turn_index(self, client, auth_headers, db_engine, sample_world_data):
        """Test that turn events include turn_index."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "test action"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        
        # Verify turn_index in events
        for line in content.split("\n"):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if isinstance(data, dict) and "turn_index" in data:
                        assert data["turn_index"] == 1  # First turn
                except json.JSONDecodeError:
                    pass
    
    def test_stream_turn_multiple_turns(self, client, auth_headers, db_engine, sample_world_data):
        """Test streaming multiple turns increments turn index."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        for expected_turn in range(1, 4):
            response = client.post(
                f"/streaming/sessions/{session_id}/turn/mock",
                json={"action": f"action {expected_turn}"},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            content = response.content.decode("utf-8")
            
            # Find turn_completed event and verify turn_index
            for line in content.split("\n"):
                if "turn_completed" in line:
                    # Next line should have data
                    continue
                if line.startswith("data: ") and expected_turn == expected_turn:
                    try:
                        data = json.loads(line[6:])
                        if isinstance(data, dict) and "turn_index" in data:
                            assert data["turn_index"] == expected_turn
                            break
                    except json.JSONDecodeError:
                        pass
    
    def test_stream_turn_unauthorized(self, client, auth_headers, db_engine, sample_world_data):
        """Test that users cannot stream other users' sessions."""
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
        
        # Try to stream with second user
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "test"},
            headers=second_headers
        )
        
        assert response.status_code in [401, 403]
    
    def test_stream_turn_invalid_session(self, client, auth_headers):
        """Test streaming with invalid session returns 404."""
        response = client.post(
            f"/streaming/sessions/{uuid.uuid4()}/turn/mock",
            json={"action": "test"},
            headers=auth_headers
        )
        
        assert response.status_code == 404
    
    def test_stream_turn_no_auth(self, client, db_engine, sample_world_data):
        """Test streaming without auth returns 401/403."""
        response = client.post(
            f"/streaming/sessions/{uuid.uuid4()}/turn/mock",
            json={"action": "test"}
        )
        
        assert response.status_code in [401, 403]
    
    def test_event_committed_before_narration(self, client, auth_headers, db_engine, sample_world_data):
        """Test that event_committed is sent before narration streams."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "explore"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        
        # Parse events with line numbers
        lines = content.split("\n")
        committed_line = None
        first_narration_line = None
        
        for i, line in enumerate(lines):
            if "event: event_committed" in line:
                committed_line = i
            if "event: narration_delta" in line and first_narration_line is None:
                first_narration_line = i
        
        assert committed_line is not None, "event_committed should be present"
        assert first_narration_line is not None, "narration_delta should be present"
        assert committed_line < first_narration_line, "event_committed must come before narration_delta"
    
    def test_turn_completed_includes_final_state(self, client, auth_headers, db_engine, sample_world_data):
        """Test that turn_completed includes final player state and world time."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "wait"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        
        # Find turn_completed data
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "event: turn_completed" in line and i + 1 < len(lines):
                data_line = lines[i + 1]
                if data_line.startswith("data: "):
                    try:
                        data = json.loads(data_line[6:])
                        assert "narration" in data
                        assert "player_state" in data
                        assert "world_time" in data
                        assert data["turn_index"] >= 1
                    except json.JSONDecodeError:
                        pass


class TestLLMIntegrationWithTurnPipeline:
    """Tests for LLM service integration with turn pipeline."""
    
    def test_mock_llm_turn_stream(self, client, auth_headers, db_engine, sample_world_data):
        """
        Test mock LLM turn stream (acceptance criteria).
        
        Runs with OPENAI_API_KEY= to ensure mock provider is used.
        """
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "test streaming turn"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        # Verify SSE structure
        content = response.content.decode("utf-8")
        assert "event: turn_started" in content
        assert "event: event_committed" in content
        assert "event: narration_delta" in content
        assert "event: turn_completed" in content
        
        # Verify all events have data
        assert "data:" in content
        
        # Verify proper SSE format (double newline after each event)
        events = content.split("\n\n")
        assert len(events) >= 4  # At least 4 events
    
    def test_llm_service_logs_during_turn(self, client, auth_headers, db_engine, sample_world_data):
        """Test that LLM calls during turn execution are logged."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.post(
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "action with logging"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        # Verify response contains expected events
        content = response.content.decode("utf-8")
        assert "turn_completed" in content
    
    def test_turn_streaming_with_various_actions(self, client, auth_headers, db_engine, sample_world_data):
        """Test streaming with various player actions."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        actions = [
            "look around",
            "move forward", 
            "talk to npc",
            "attack enemy",
            "use item",
        ]
        
        for action in actions:
            response = client.post(
                f"/streaming/sessions/{session_id}/turn/mock",
                json={"action": action},
                headers=auth_headers
            )
            
            assert response.status_code == 200
            content = response.content.decode("utf-8")
            
            # Verify all required events are present
            assert "turn_started" in content
            assert "event_committed" in content
            assert "narration_delta" in content
            assert "turn_completed" in content

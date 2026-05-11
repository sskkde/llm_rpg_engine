"""
Integration tests for debug endpoint observability contracts.

Tests that debug GET endpoints:
- Return proper 200/404/empty states for admin users
- Return 401 for unauthenticated requests
- Return 403 for non-admin authenticated requests
- Do NOT modify database state (read-only verification)
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel, WorldModel, SessionModel, EventLogModel,
    ModelCallLogModel, SessionStateModel, SessionPlayerStateModel,
    SessionNPCStateModel, SessionInventoryItemModel, SessionQuestStateModel,
    NPCTemplateModel, ItemTemplateModel, QuestTemplateModel, LocationModel,
    ChapterModel,
)
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
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


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
def admin_user_data():
    return {
        "username": f"admin_{uuid.uuid4().hex[:8]}",
        "email": f"admin_{uuid.uuid4().hex[:8]}@example.com",
        "password": "AdminPass123!",
    }


@pytest.fixture
def regular_user_data():
    return {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"user_{uuid.uuid4().hex[:8]}@example.com",
        "password": "UserPass123!",
    }


def create_user_in_db(db_engine, user_data, is_admin=False):
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        user = UserModel(
            id=str(uuid.uuid4()),
            username=user_data["username"],
            email=user_data["email"],
            password_hash=pwd_context.hash(user_data["password"]),
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def get_auth_header(client, user_data):
    response = client.post("/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"],
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def setup_test_session_with_data(db: Session):
    """Create a test session with related data for testing."""
    world = WorldModel(
        id="test_world_debug",
        code="debug_world",
        name="Debug Test World",
        genre="xianxia",
        lore_summary="Test world for debug observability",
        status="active",
    )
    db.add(world)
    
    chapter = ChapterModel(
        id="test_chapter_debug",
        world_id="test_world_debug",
        chapter_no=1,
        name="Debug Chapter",
        summary="Test chapter",
    )
    db.add(chapter)
    
    location = LocationModel(
        id="test_location_debug",
        world_id="test_world_debug",
        code="debug_loc",
        name="Debug Location",
        description="Test location",
    )
    db.add(location)
    
    npc_template = NPCTemplateModel(
        id="test_npc_template_debug",
        world_id="test_world_debug",
        code="debug_npc",
        name="Debug NPC",
        role_type="npc",
    )
    db.add(npc_template)
    
    item_template = ItemTemplateModel(
        id="test_item_template_debug",
        world_id="test_world_debug",
        code="debug_item",
        name="Debug Item",
        description="Test item",
        item_type="misc",
    )
    db.add(item_template)
    
    quest_template = QuestTemplateModel(
        id="test_quest_template_debug",
        world_id="test_world_debug",
        code="debug_quest",
        name="Debug Quest",
        summary="Test quest",
    )
    db.add(quest_template)
    
    user = UserModel(
        id="test_user_debug",
        username="debug_test_user",
        email="debug@test.com",
        password_hash="hashed",
        is_admin=True,
    )
    db.add(user)
    
    session = SessionModel(
        id="test_session_debug",
        user_id="test_user_debug",
        world_id="test_world_debug",
        current_chapter_id="test_chapter_debug",
        status="active",
    )
    db.add(session)
    
    session_state = SessionStateModel(
        id="test_session_state_debug",
        session_id="test_session_debug",
        current_time="Day 1",
        time_phase="morning",
        current_location_id="test_location_debug",
        active_mode="exploration",
        global_flags_json={},
    )
    db.add(session_state)
    
    player_state = SessionPlayerStateModel(
        id="test_player_state_debug",
        session_id="test_session_debug",
        realm_stage="炼气一层",
        hp=100,
        max_hp=100,
        stamina=100,
        spirit_power=100,
        relation_bias_json={},
        conditions_json=[],
    )
    db.add(player_state)
    
    npc_state = SessionNPCStateModel(
        id="test_npc_state_debug",
        session_id="test_session_debug",
        npc_template_id="test_npc_template_debug",
        current_location_id="test_location_debug",
        trust_score=50,
        suspicion_score=0,
        status_flags={},
    )
    db.add(npc_state)
    
    inventory_item = SessionInventoryItemModel(
        id="test_inventory_debug",
        session_id="test_session_debug",
        item_template_id="test_item_template_debug",
        owner_type="player",
        quantity=1,
        bound_flag=False,
    )
    db.add(inventory_item)
    
    quest_state = SessionQuestStateModel(
        id="test_quest_state_debug",
        session_id="test_session_debug",
        quest_template_id="test_quest_template_debug",
        current_step_no=1,
        progress_json={},
        status="active",
    )
    db.add(quest_state)
    
    event_log = EventLogModel(
        id="test_event_log_debug",
        session_id="test_session_debug",
        turn_no=1,
        event_type="player_input",
        input_text="test action",
        narrative_text="Test narration",
        result_json={"test": "data"},
    )
    db.add(event_log)
    
    model_call = ModelCallLogModel(
        id="test_model_call_debug",
        session_id="test_session_debug",
        turn_no=1,
        provider="openai",
        model_name="gpt-4",
        prompt_type="narration",
        input_tokens=100,
        output_tokens=50,
        cost_estimate=0.01,
        latency_ms=500,
    )
    db.add(model_call)
    
    error_event = EventLogModel(
        id="test_error_log_debug",
        session_id="test_session_debug",
        turn_no=2,
        event_type="error",
        narrative_text="Test error message",
        result_json={"error_details": "test"},
    )
    db.add(error_event)
    
    db.commit()
    
    return {
        "session_id": "test_session_debug",
        "world_id": "test_world_debug",
        "user_id": "test_user_debug",
    }


def count_all_rows(db: Session) -> dict:
    """Count rows in all relevant tables."""
    return {
        "users": db.query(func.count(UserModel.id)).scalar(),
        "sessions": db.query(func.count(SessionModel.id)).scalar(),
        "event_logs": db.query(func.count(EventLogModel.id)).scalar(),
        "model_calls": db.query(func.count(ModelCallLogModel.id)).scalar(),
        "session_states": db.query(func.count(SessionStateModel.id)).scalar(),
        "player_states": db.query(func.count(SessionPlayerStateModel.id)).scalar(),
        "npc_states": db.query(func.count(SessionNPCStateModel.id)).scalar(),
        "inventory_items": db.query(func.count(SessionInventoryItemModel.id)).scalar(),
        "quest_states": db.query(func.count(SessionQuestStateModel.id)).scalar(),
    }


class TestDebugSessionLogsEndpoint:
    """Test GET /debug/sessions/{session_id}/logs endpoint."""

    def test_admin_can_get_session_logs(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_debug/logs",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test_session_debug"
        assert data["total_count"] >= 1
        assert len(data["logs"]) >= 1
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after, "GET endpoint should not modify database"

    def test_admin_gets_404_for_nonexistent_session_logs(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get(
            "/debug/sessions/nonexistent_session/logs",
            headers=headers
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_non_admin_forbidden_from_session_logs(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_debug/logs",
            headers=headers
        )
        
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_unauthenticated_gets_401_from_session_logs(self, client, db_session):
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/sessions/test_session_debug/logs")
        
        assert response.status_code == 401
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after


class TestDebugSessionStateEndpoint:
    """Test GET /debug/sessions/{session_id}/state endpoint."""

    def test_admin_can_get_session_state(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_debug/state",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test_session_debug"
        assert data["user_id"] == "test_user_debug"
        assert data["world_id"] == "test_world_debug"
        assert data["status"] == "active"
        assert len(data["npc_states"]) >= 1
        assert len(data["inventory_items"]) >= 1
        assert len(data["quest_states"]) >= 1
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after, "GET endpoint should not modify database"

    def test_admin_gets_404_for_nonexistent_session_state(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get(
            "/debug/sessions/nonexistent_session/state",
            headers=headers
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_non_admin_forbidden_from_session_state(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_debug/state",
            headers=headers
        )
        
        assert response.status_code == 403
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_unauthenticated_gets_401_from_session_state(self, client, db_session):
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/sessions/test_session_debug/state")
        
        assert response.status_code == 401
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after


class TestDebugModelCallsEndpoint:
    """Test GET /debug/model-calls endpoint."""

    def test_admin_can_get_model_calls(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] >= 1
        assert data["total_cost"] >= 0
        assert len(data["calls"]) >= 1
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after, "GET endpoint should not modify database"

    def test_admin_can_filter_model_calls_by_session(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get(
            "/debug/model-calls?session_id=test_session_debug",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] >= 1
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_admin_gets_empty_list_for_no_model_calls(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["calls"] == []
        assert data["total_cost"] == 0.0
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_non_admin_forbidden_from_model_calls(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 403
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_unauthenticated_gets_401_from_model_calls(self, client, db_session):
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/model-calls")
        
        assert response.status_code == 401
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after


class TestDebugErrorsEndpoint:
    """Test GET /debug/errors endpoint."""

    def test_admin_can_get_errors(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/errors", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] >= 1
        assert len(data["errors"]) >= 1
        
        error = data["errors"][0]
        assert "timestamp" in error
        assert error["error_type"] == "error"
        assert error["message"] == "Test error message"
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after, "GET endpoint should not modify database"

    def test_admin_gets_empty_list_for_no_errors(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/errors", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["errors"] == []
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_non_admin_forbidden_from_errors(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/errors", headers=headers)
        
        assert response.status_code == 403
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_unauthenticated_gets_401_from_errors(self, client, db_session):
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/errors")
        
        assert response.status_code == 401
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after


class TestDebugReadOnlyVerification:
    """Comprehensive tests that debug GET endpoints are truly read-only."""

    def test_all_get_endpoints_preserve_row_counts(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        endpoints = [
            "/debug/sessions/test_session_debug/logs",
            "/debug/sessions/test_session_debug/state",
            "/debug/model-calls",
            "/debug/errors",
        ]
        
        for endpoint in endpoints:
            rows_before = count_all_rows(db_session)
            
            response = client.get(endpoint, headers=headers)
            
            assert response.status_code in [200, 404], f"Endpoint {endpoint} returned unexpected status"
            
            rows_after = count_all_rows(db_session)
            assert rows_before == rows_after, f"Endpoint {endpoint} modified database state"

    def test_multiple_requests_preserve_row_counts(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        rows_initial = count_all_rows(db_session)
        
        for _ in range(3):
            client.get("/debug/sessions/test_session_debug/logs", headers=headers)
            client.get("/debug/sessions/test_session_debug/state", headers=headers)
            client.get("/debug/model-calls", headers=headers)
            client.get("/debug/errors", headers=headers)
        
        rows_final = count_all_rows(db_session)
        assert rows_initial == rows_final, "Multiple GET requests modified database state"


class TestDebugDisabledSettings:
    """Test behavior when debug endpoints are disabled."""

    def test_debug_disabled_returns_403(self, client, db_engine, db_session, admin_user_data):
        from llm_rpg.services.settings import SystemSettingsService
        
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        settings_service = SystemSettingsService(db_session)
        settings = settings_service.get_settings()
        settings.debug_enabled = False
        db_session.commit()
        
        rows_before = count_all_rows(db_session)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

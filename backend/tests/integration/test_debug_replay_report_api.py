"""
Integration tests for Debug Replay Report API endpoint.

Tests that POST /debug/sessions/{session_id}/replay-report:
- Returns proper response for admin users
- Returns 401 for unauthenticated requests
- Returns 403 for non-admin authenticated requests
- Perspective filter works correctly
- Does NOT call LLM (llm_calls_made == 0)
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
    SessionStateModel, SessionPlayerStateModel,
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
        id="test_world_replay",
        code="replay_world",
        name="Replay Test World",
        genre="xianxia",
        lore_summary="Test world for replay report",
        status="active",
    )
    db.add(world)
    
    chapter = ChapterModel(
        id="test_chapter_replay",
        world_id="test_world_replay",
        chapter_no=1,
        name="Replay Chapter",
        summary="Test chapter",
    )
    db.add(chapter)
    
    location = LocationModel(
        id="test_location_replay",
        world_id="test_world_replay",
        code="replay_loc",
        name="Replay Location",
        description="Test location",
    )
    db.add(location)
    
    npc_template = NPCTemplateModel(
        id="test_npc_template_replay",
        world_id="test_world_replay",
        code="replay_npc",
        name="Replay NPC",
        role_type="npc",
    )
    db.add(npc_template)
    
    item_template = ItemTemplateModel(
        id="test_item_template_replay",
        world_id="test_world_replay",
        code="replay_item",
        name="Replay Item",
        description="Test item",
        item_type="misc",
    )
    db.add(item_template)
    
    quest_template = QuestTemplateModel(
        id="test_quest_template_replay",
        world_id="test_world_replay",
        code="replay_quest",
        name="Replay Quest",
        summary="Test quest",
    )
    db.add(quest_template)
    
    user = UserModel(
        id="test_user_replay",
        username="replay_test_user",
        email="replay@test.com",
        password_hash="hashed",
        is_admin=True,
    )
    db.add(user)
    
    session = SessionModel(
        id="test_session_replay",
        user_id="test_user_replay",
        world_id="test_world_replay",
        current_chapter_id="test_chapter_replay",
        status="active",
    )
    db.add(session)
    
    session_state = SessionStateModel(
        id="test_session_state_replay",
        session_id="test_session_replay",
        current_time="Day 1",
        time_phase="morning",
        current_location_id="test_location_replay",
        active_mode="exploration",
        global_flags_json={},
    )
    db.add(session_state)
    
    player_state = SessionPlayerStateModel(
        id="test_player_state_replay",
        session_id="test_session_replay",
        realm_stage="炼气一层",
        hp=100,
        max_hp=100,
        stamina=100,
        spirit_power=100,
        relation_bias_json={},
        conditions_json=[],
    )
    db.add(player_state)
    
    db.commit()
    
    return {
        "session_id": "test_session_replay",
        "world_id": "test_world_replay",
        "user_id": "test_user_replay",
    }


def count_all_rows(db: Session) -> dict:
    """Count rows in all relevant tables."""
    return {
        "users": db.query(func.count(UserModel.id)).scalar(),
        "sessions": db.query(func.count(SessionModel.id)).scalar(),
        "event_logs": db.query(func.count(EventLogModel.id)).scalar(),
    }


class TestReplayReportEndpointAuth:
    """Test authentication and authorization for replay-report endpoint."""

    def test_admin_can_access_replay_report(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test_session_replay"
        assert data["from_turn"] == 1
        assert data["to_turn"] == 5
        assert "state_diff" in data
        assert "deterministic" in data
        assert "llm_calls_made" in data
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after, "POST endpoint should not modify database for report generation"

    def test_non_admin_forbidden_from_replay_report(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_unauthenticated_gets_401_from_replay_report(self, client, db_session):
        setup_test_session_with_data(db_session)
        
        rows_before = count_all_rows(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5"
        )
        
        assert response.status_code == 401
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after

    def test_admin_gets_404_for_nonexistent_session(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        rows_before = count_all_rows(db_session)
        
        response = client.post(
            "/debug/sessions/nonexistent_session/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        
        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after


class TestReplayReportNoLLMCalls:
    """Test that replay report does NOT call LLM."""

    def test_llm_calls_made_is_zero(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["llm_calls_made"] == 0, "Replay report should not make any LLM calls"

    def test_deterministic_is_true_when_no_llm_calls(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deterministic"] is True


class TestReplayReportPerspectiveFilter:
    """Test perspective filtering in replay report."""

    def test_admin_perspective_includes_all_fields(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5&perspective=admin",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test_session_replay"

    def test_player_perspective_filters_hidden_fields(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5&perspective=player",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        for entry in data["state_diff"]["entries"]:
            path = entry["path"]
            assert "hidden_plan_state" not in path
            assert "hidden_identity" not in path
            assert "secrets" not in path
            assert "forbidden_knowledge" not in path

    def test_auditor_perspective_filters_hidden_lore(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5&perspective=auditor",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test_session_replay"


class TestReplayReportResponseStructure:
    """Test the structure of replay report response."""

    def test_response_has_required_fields(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "session_id" in data
        assert "snapshot_id" in data
        assert "from_turn" in data
        assert "to_turn" in data
        assert "replayed_event_count" in data
        assert "deterministic" in data
        assert "llm_calls_made" in data
        assert "state_diff" in data
        assert "warnings" in data
        assert "created_at" in data

    def test_state_diff_has_required_fields(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        state_diff = data["state_diff"]
        
        assert "entries" in state_diff
        assert "added_keys" in state_diff
        assert "removed_keys" in state_diff
        assert "changed_keys" in state_diff

    def test_response_includes_warnings(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        
        response = client.post(
            "/debug/sessions/test_session_replay/replay-report?start_turn=1&end_turn=5",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["warnings"], list)

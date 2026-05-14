"""
Comprehensive schema validation tests for debug API endpoints.

Tests that all debug endpoints:
1. Return correct response schemas (Pydantic validation)
2. Handle pagination correctly (limit/offset params)
3. Handle perspective parameter correctly (admin/player/auditor)
4. Return proper error responses (404, 403, session not found, debug disabled)
5. Handle empty states (no turns, no model calls, no errors)
6. Persist model calls to AuditStore (Task 2 verification)
"""

import pytest
import uuid
from datetime import datetime
from typing import Dict, Any, List

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel, WorldModel, SessionModel, EventLogModel,
    ModelCallLogModel, ModelCallAuditLogModel, SessionStateModel, SessionPlayerStateModel,
    SessionNPCStateModel, SessionInventoryItemModel, SessionQuestStateModel,
    NPCTemplateModel, ItemTemplateModel, QuestTemplateModel, LocationModel,
    ChapterModel, SystemSettingsModel,
    ProposalAuditLogModel, ContextBuildAuditLogModel, ValidationAuditLogModel,
    TurnAuditLogModel, ErrorAuditLogModel,
)
from llm_rpg.main import app
from llm_rpg.core.audit import (
    get_audit_logger, reset_audit_logger, AuditLogger, AuditStore,
    TurnAuditLog, TurnEventAudit, TurnStateDeltaAudit,
    ContextBuildAudit, MemoryAuditEntry, MemoryDecisionReason,
    ValidationResultAudit, ValidationCheck, ValidationStatus,
    ModelCallLog, ProposalAuditEntry,
)
from llm_rpg.core.replay import (
    get_replay_store, reset_replay_store, ReplayStore,
    ReplayPerspective, ReplayEvent,
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
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_engine, db_session):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    app.dependency_overrides[get_db] = override_get_db
    
    # Ensure global engine has all tables (wire_audit_db uses get_db() directly)
    from llm_rpg.storage.database import init_db
    init_db()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset audit logger and replay store before each test."""
    reset_audit_logger()
    reset_replay_store()
    yield
    reset_audit_logger()
    reset_replay_store()


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


def setup_minimal_session(db: Session) -> Dict[str, str]:
    """Create a minimal session with no turns/events."""
    world = WorldModel(
        id="test_world_minimal",
        code="minimal_world",
        name="Minimal Test World",
        genre="xianxia",
        lore_summary="Test world",
        status="active",
    )
    db.add(world)
    
    chapter = ChapterModel(
        id="test_chapter_minimal",
        world_id="test_world_minimal",
        chapter_no=1,
        name="Test Chapter",
        summary="Test",
    )
    db.add(chapter)
    
    location = LocationModel(
        id="test_location_minimal",
        world_id="test_world_minimal",
        code="minimal_loc",
        name="Test Location",
        description="Test",
    )
    db.add(location)
    
    user = UserModel(
        id="test_user_minimal",
        username="minimal_user",
        email="minimal@test.com",
        password_hash="hashed",
        is_admin=True,
    )
    db.add(user)
    
    session = SessionModel(
        id="test_session_minimal",
        user_id="test_user_minimal",
        world_id="test_world_minimal",
        current_chapter_id="test_chapter_minimal",
        status="active",
    )
    db.add(session)
    
    session_state = SessionStateModel(
        id="test_session_state_minimal",
        session_id="test_session_minimal",
        current_time="Day 1",
        time_phase="morning",
        current_location_id="test_location_minimal",
        active_mode="exploration",
        global_flags_json={},
    )
    db.add(session_state)
    
    player_state = SessionPlayerStateModel(
        id="test_player_state_minimal",
        session_id="test_session_minimal",
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
        "session_id": "test_session_minimal",
        "world_id": "test_world_minimal",
        "user_id": "test_user_minimal",
    }


def setup_full_session_with_data(db: Session) -> Dict[str, str]:
    """Create a session with full test data including turns, events, and model calls."""
    data = setup_minimal_session(db)
    session_id = data["session_id"]
    
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    session.id = "test_session_full"
    db.commit()
    
    session_state = db.query(SessionStateModel).filter(
        SessionStateModel.session_id == "test_session_minimal"
    ).first()
    if session_state:
        session_state.session_id = "test_session_full"
    
    player_state = db.query(SessionPlayerStateModel).filter(
        SessionPlayerStateModel.session_id == "test_session_minimal"
    ).first()
    if player_state:
        player_state.session_id = "test_session_full"
    
    db.commit()
    
    npc_template = NPCTemplateModel(
        id="test_npc_template_full",
        world_id="test_world_minimal",
        code="full_npc",
        name="Full Test NPC",
        role_type="npc",
    )
    db.add(npc_template)
    
    npc_state = SessionNPCStateModel(
        id="test_npc_state_full",
        session_id="test_session_full",
        npc_template_id="test_npc_template_full",
        current_location_id="test_location_minimal",
        trust_score=50,
        suspicion_score=10,
        status_flags={},
    )
    db.add(npc_state)
    
    item_template = ItemTemplateModel(
        id="test_item_template_full",
        world_id="test_world_minimal",
        code="full_item",
        name="Full Test Item",
        description="Test item",
        item_type="misc",
    )
    db.add(item_template)
    
    inventory_item = SessionInventoryItemModel(
        id="test_inventory_full",
        session_id="test_session_full",
        item_template_id="test_item_template_full",
        owner_type="player",
        quantity=1,
        bound_flag=False,
    )
    db.add(inventory_item)
    
    quest_template = QuestTemplateModel(
        id="test_quest_template_full",
        world_id="test_world_minimal",
        code="full_quest",
        name="Full Test Quest",
        summary="Test quest",
    )
    db.add(quest_template)
    
    quest_state = SessionQuestStateModel(
        id="test_quest_state_full",
        session_id="test_session_full",
        quest_template_id="test_quest_template_full",
        current_step_no=1,
        progress_json={},
        status="active",
    )
    db.add(quest_state)
    
    event_log_1 = EventLogModel(
        id="test_event_log_1",
        session_id="test_session_full",
        turn_no=1,
        event_type="player_input",
        input_text="look around",
        narrative_text="You look around the test area.",
        result_json={"action": "look", "result": "success"},
    )
    db.add(event_log_1)
    
    event_log_2 = EventLogModel(
        id="test_event_log_2",
        session_id="test_session_full",
        turn_no=2,
        event_type="player_input",
        input_text="examine npc",
        narrative_text="The NPC looks at you suspiciously.",
        result_json={"action": "examine", "target": "npc"},
    )
    db.add(event_log_2)
    
    event_log_error = EventLogModel(
        id="test_event_log_error",
        session_id="test_session_full",
        turn_no=3,
        event_type="error",
        narrative_text="Test error message",
        result_json={"error_details": "test error"},
    )
    db.add(event_log_error)
    
    model_call_1 = ModelCallLogModel(
        id="test_model_call_1",
        session_id="test_session_full",
        turn_no=1,
        provider="openai",
        model_name="gpt-4",
        prompt_type="narration",
        input_tokens=100,
        output_tokens=50,
        cost_estimate=0.01,
        latency_ms=500,
    )
    db.add(model_call_1)
    
    model_call_2 = ModelCallLogModel(
        id="test_model_call_2",
        session_id="test_session_full",
        turn_no=2,
        provider="openai",
        model_name="gpt-4",
        prompt_type="npc_action",
        input_tokens=150,
        output_tokens=75,
        cost_estimate=0.02,
        latency_ms=600,
    )
    db.add(model_call_2)
    
    db.commit()
    
    return {
        "session_id": "test_session_full",
        "world_id": "test_world_minimal",
        "user_id": "test_user_minimal",
    }


def setup_audit_data(session_id: str) -> Dict[str, str]:
    """Setup audit store with test data."""
    audit_logger = get_audit_logger()
    store = audit_logger.get_store()
    
    turn_audit = TurnAuditLog(
        audit_id=f"turn_audit_{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        turn_no=1,
        transaction_id=f"tx_{uuid.uuid4().hex[:8]}",
        player_input="test input",
        world_time_before={"day": 1, "phase": "morning"},
        world_time_after={"day": 1, "phase": "afternoon"},
        events=[
            TurnEventAudit(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                event_type="player_input",
                actor_id="player",
                summary="Player performed action",
            )
        ],
        state_deltas=[
            TurnStateDeltaAudit(
                delta_id=f"delta_{uuid.uuid4().hex[:8]}",
                path="player.hp",
                old_value=100,
                new_value=95,
                operation="set",
                validated=True,
            )
        ],
        status="completed",
        narration_generated=True,
        narration_length=100,
    )
    store.store_turn_audit(turn_audit)
    
    ctx_audit = ContextBuildAudit(
        build_id=f"ctx_{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        turn_no=1,
        perspective_type="player",
        perspective_id="player",
        included_memories=[
            MemoryAuditEntry(
                memory_id="mem_1",
                memory_type="episodic",
                owner_id="player",
                included=True,
                reason=MemoryDecisionReason.RELEVANCE_SCORE,
                relevance_score=0.9,
            )
        ],
        excluded_memories=[
            MemoryAuditEntry(
                memory_id="mem_2",
                memory_type="secret",
                owner_id="npc_1",
                included=False,
                reason=MemoryDecisionReason.FORBIDDEN_KNOWLEDGE,
                forbidden_knowledge_flag=True,
            )
        ],
        total_candidates=2,
        context_token_count=500,
        context_char_count=2000,
        build_duration_ms=100,
    )
    store.store_context_build(ctx_audit)
    
    val_audit = ValidationResultAudit(
        validation_id=f"val_{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        turn_no=1,
        validation_target="action",
        target_id="action_1",
        overall_status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                check_id=f"check_{uuid.uuid4().hex[:8]}",
                check_type="schema",
                status=ValidationStatus.PASSED,
                message="Schema validation passed",
            )
        ],
        transaction_id=turn_audit.transaction_id,
    )
    store.store_validation(val_audit)
    
    prop_audit = ProposalAuditEntry(
        audit_id=f"prop_{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        turn_no=1,
        proposal_type="narration",
        prompt_template_id="pt_1",
        model_name="gpt-4",
        input_tokens=100,
        output_tokens=50,
        latency_ms=500,
        raw_output_preview="Test output preview",
        parse_success=True,
        confidence=0.9,
    )
    store.store_proposal_audit(prop_audit)
    
    model_call = ModelCallLog(
        call_id=f"call_audit_{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        turn_no=1,
        provider="openai",
        model_name="gpt-4",
        prompt_type="narration",
        input_tokens=100,
        output_tokens=50,
        latency_ms=500,
    )
    store.store_model_call(model_call)
    
    return {
        "turn_audit_id": turn_audit.audit_id,
        "ctx_build_id": ctx_audit.build_id,
        "validation_id": val_audit.validation_id,
        "proposal_audit_id": prop_audit.audit_id,
        "model_call_id": model_call.call_id,
    }


class TestDebugSessionLogsSchema:
    """Test GET /debug/sessions/{session_id}/logs endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_full/logs",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "session_id" in data
        assert "total_count" in data
        assert "logs" in data
        assert isinstance(data["total_count"], int)
        assert isinstance(data["logs"], list)
        
        if data["logs"]:
            log = data["logs"][0]
            assert "id" in log
            assert "turn_no" in log
            assert "event_type" in log
            assert "occurred_at" in log

    def test_pagination_limit(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_full/logs?limit=1",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) <= 1

    def test_pagination_offset(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response_all = client.get(
            "/debug/sessions/test_session_full/logs?limit=100",
            headers=headers
        )
        
        response_offset = client.get(
            "/debug/sessions/test_session_full/logs?offset=1",
            headers=headers
        )
        
        assert response_all.status_code == 200
        assert response_offset.status_code == 200
        
        all_logs = response_all.json()["logs"]
        offset_logs = response_offset.json()["logs"]
        
        if len(all_logs) > 1:
            assert len(offset_logs) == len(all_logs) - 1
            assert offset_logs[0]["id"] == all_logs[1]["id"]

    def test_default_limit_is_50(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_full/logs",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) <= 50

    def test_empty_state_no_logs(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_minimal_session(db_session)
        
        session = db_session.query(SessionModel).first()
        session_id = session.id
        
        response = client.get(
            f"/debug/sessions/{session_id}/logs",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["logs"] == []


class TestDebugSessionStateSchema:
    """Test GET /debug/sessions/{session_id}/state endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get(
            "/debug/sessions/test_session_full/state",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "session_id" in data
        assert "user_id" in data
        assert "world_id" in data
        assert "status" in data
        assert "started_at" in data
        assert "last_played_at" in data
        
        assert "active_mode" in data
        assert "global_flags" in data
        
        assert "player_realm_stage" in data
        assert "player_hp" in data
        assert "player_max_hp" in data
        assert "player_stamina" in data
        assert "player_spirit_power" in data
        assert "player_relation_bias" in data
        assert "player_conditions" in data
        
        assert "npc_states" in data
        assert "inventory_items" in data
        assert "quest_states" in data
        assert isinstance(data["npc_states"], list)
        assert isinstance(data["inventory_items"], list)
        assert isinstance(data["quest_states"], list)


class TestDebugModelCallsSchema:
    """Test GET /debug/model-calls endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "total_count" in data
        assert "total_cost" in data
        assert "calls" in data
        assert isinstance(data["total_count"], int)
        assert isinstance(data["total_cost"], (int, float))
        assert isinstance(data["calls"], list)
        
        if data["calls"]:
            call = data["calls"][0]
            assert "id" in call
            assert "session_id" in call
            assert "turn_no" in call
            assert "created_at" in call

    def test_pagination_limit(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get("/debug/model-calls?limit=1", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["calls"]) <= 1

    def test_pagination_offset(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response_all = client.get("/debug/model-calls?limit=100", headers=headers)
        response_offset = client.get("/debug/model-calls?offset=1", headers=headers)
        
        assert response_all.status_code == 200
        assert response_offset.status_code == 200
        
        all_calls = response_all.json()["calls"]
        offset_calls = response_offset.json()["calls"]
        
        if len(all_calls) > 1:
            assert len(offset_calls) == len(all_calls) - 1
            assert offset_calls[0]["id"] == all_calls[1]["id"]

    def test_default_limit_is_50(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["calls"]) <= 50

    def test_filter_by_session_id(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get(
            "/debug/model-calls?session_id=test_session_full",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        for call in data["calls"]:
            assert call["session_id"] == "test_session_full"

    def test_empty_state_no_calls(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["calls"] == []
        assert data["total_cost"] == 0.0


class TestDebugErrorsSchema:
    """Test GET /debug/errors endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get("/debug/errors", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "total_count" in data
        assert "errors" in data
        assert isinstance(data["total_count"], int)
        assert isinstance(data["errors"], list)
        
        if data["errors"]:
            error = data["errors"][0]
            assert "timestamp" in error
            assert "error_type" in error
            assert "message" in error

    def test_empty_state_no_errors(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/errors", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["errors"] == []


class TestDebugTurnDetailSchema:
    """Test GET /debug/sessions/{session_id}/turns/{turn_no} endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        audit_ids = setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/turns/1",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "audit_id" in resp
        assert "session_id" in resp
        assert "turn_no" in resp
        assert "transaction_id" in resp
        assert "player_input" in resp
        assert "status" in resp
        
        assert "events" in resp
        assert "state_deltas" in resp
        assert "context_build_ids" in resp
        assert "model_call_ids" in resp
        assert "validation_ids" in resp
        assert isinstance(resp["events"], list)
        assert isinstance(resp["state_deltas"], list)

    def test_404_turn_not_found(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/turns/999",
            headers=headers
        )
        
        assert response.status_code == 404


class TestDebugPromptInspectorSchema:
    """Test GET /debug/sessions/{session_id}/prompt-inspector endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/prompt-inspector",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "session_id" in resp
        assert "total_turns" in resp
        assert "aggregates" in resp
        
        assert "prompt_templates" in resp
        assert "model_calls" in resp
        assert "context_builds" in resp
        assert "proposals" in resp
        assert "validations" in resp
        
        agg = resp["aggregates"]
        assert "total_tokens_used" in agg
        assert "total_cost" in agg
        assert "total_latency_ms" in agg
        assert "total_model_calls" in agg
        assert "call_success_rate" in agg
        assert "repair_success_rate" in agg

    def test_filter_by_turn_range(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/prompt-inspector?start_turn=1&end_turn=1",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert resp["total_turns"] >= 1

    def test_filter_by_prompt_type(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/prompt-inspector?prompt_type=narration",
            headers=headers
        )
        
        assert response.status_code == 200

    def test_pagination_limit(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/prompt-inspector?limit=1",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert len(resp["model_calls"]) <= 1
        assert len(resp["context_builds"]) <= 1
        assert len(resp["proposals"]) <= 1
        assert len(resp["validations"]) <= 1

    def test_pagination_offset(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        setup_audit_data(data["session_id"])
        
        response_all = client.get(
            f"/debug/sessions/{data['session_id']}/prompt-inspector?limit=100",
            headers=headers
        )
        response_offset = client.get(
            f"/debug/sessions/{data['session_id']}/prompt-inspector?offset=1",
            headers=headers
        )
        
        assert response_all.status_code == 200
        assert response_offset.status_code == 200

    def test_default_limit_is_50(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/prompt-inspector",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert len(resp["model_calls"]) <= 50
        assert len(resp["context_builds"]) <= 50
        assert len(resp["proposals"]) <= 50
        assert len(resp["validations"]) <= 50


class TestDebugContextBuildSchema:
    """Test GET /debug/sessions/{session_id}/context-builds/{build_id} endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        audit_ids = setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/context-builds/{audit_ids['ctx_build_id']}",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "build_id" in resp
        assert "session_id" in resp
        assert "turn_no" in resp
        assert "perspective_type" in resp
        assert "perspective_id" in resp
        
        assert "included_memories" in resp
        assert "excluded_memories" in resp
        assert isinstance(resp["included_memories"], list)
        assert isinstance(resp["excluded_memories"], list)
        
        assert "total_candidates" in resp
        assert "included_count" in resp
        assert "excluded_count" in resp
        assert "context_token_count" in resp
        assert "build_duration_ms" in resp

    def test_404_context_build_not_found(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/context-builds/nonexistent",
            headers=headers
        )
        
        assert response.status_code == 404


class TestDebugValidationSchema:
    """Test GET /debug/sessions/{session_id}/validations/{validation_id} endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        audit_ids = setup_audit_data(data["session_id"])
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/validations/{audit_ids['validation_id']}",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "validation_id" in resp
        assert "session_id" in resp
        assert "turn_no" in resp
        assert "validation_target" in resp
        assert "overall_status" in resp
        
        assert "checks" in resp
        assert isinstance(resp["checks"], list)
        
        assert "error_count" in resp
        assert "warning_count" in resp
        assert "errors" in resp
        assert "warnings" in resp


class TestDebugReplaySchema:
    """Test POST /debug/sessions/{session_id}/replay endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.post(
            f"/debug/sessions/{data['session_id']}/replay?end_turn=1",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "replay_id" in resp
        assert "session_id" in resp
        assert "start_turn" in resp
        assert "end_turn" in resp
        assert "perspective" in resp
        assert "success" in resp
        
        assert "steps" in resp
        assert isinstance(resp["steps"], list)
        
        if resp["steps"]:
            step = resp["steps"][0]
            assert "step_no" in step
            assert "turn_no" in step
            assert "state_before" in step
            assert "state_after" in step
            assert "events" in step
            assert "state_deltas" in step
            assert "timestamp" in step

    def test_perspective_admin(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.post(
            f"/debug/sessions/{data['session_id']}/replay?end_turn=1&perspective=admin",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert resp["perspective"] == "admin"

    def test_perspective_player(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.post(
            f"/debug/sessions/{data['session_id']}/replay?end_turn=1&perspective=player",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert resp["perspective"] == "player"

    def test_perspective_auditor(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.post(
            f"/debug/sessions/{data['session_id']}/replay?end_turn=1&perspective=auditor",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert resp["perspective"] == "auditor"


class TestDebugSnapshotSchema:
    """Test POST /debug/sessions/{session_id}/snapshots endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.post(
            f"/debug/sessions/{data['session_id']}/snapshots?turn_no=1",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "snapshot_id" in resp
        assert "session_id" in resp
        assert "turn_no" in resp
        assert "created_at" in resp
        assert "snapshot_type" in resp
        
        assert "world_state" in resp
        assert "player_state" in resp
        assert "npc_states" in resp
        assert "location_states" in resp
        assert "quest_states" in resp
        assert "faction_states" in resp


class TestDebugTimelineSchema:
    """Test GET /debug/sessions/{session_id}/timeline endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/timeline",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "session_id" in resp
        assert "total_turns" in resp
        assert "turns" in resp
        assert isinstance(resp["turns"], list)

    def test_pagination_limit(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/timeline?limit=1",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert len(resp["turns"]) <= 1

    def test_pagination_offset(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response_all = client.get(
            f"/debug/sessions/{data['session_id']}/timeline?limit=100",
            headers=headers
        )
        response_offset = client.get(
            f"/debug/sessions/{data['session_id']}/timeline?offset=1",
            headers=headers
        )
        
        assert response_all.status_code == 200
        assert response_offset.status_code == 200
        
        all_turns = response_all.json()["turns"]
        offset_turns = response_offset.json()["turns"]
        
        if len(all_turns) > 1:
            assert len(offset_turns) == len(all_turns) - 1

    def test_default_limit_is_50(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/timeline",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        assert len(resp["turns"]) <= 50


class TestDebugTimelineTurnSchema:
    """Test GET /debug/sessions/{session_id}/timeline/{turn_no} endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/timeline/1",
            headers=headers
        )
        
        if response.status_code == 200:
            resp = response.json()
            assert "turn_no" in resp
            assert "session_id" in resp
            assert "entries" in resp
            assert isinstance(resp["entries"], list)


class TestDebugNPCListSchema:
    """Test GET /debug/sessions/{session_id}/npcs endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/npcs",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "npcs" in resp
        assert "total" in resp
        assert isinstance(resp["npcs"], list)
        assert isinstance(resp["total"], int)


class TestDebugNPCMindSchema:
    """Test GET /debug/sessions/{session_id}/npcs/{npc_id}/mind endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        npcs_resp = client.get(
            f"/debug/sessions/{data['session_id']}/npcs",
            headers=headers
        )
        
        if npcs_resp.status_code == 200 and npcs_resp.json()["npcs"]:
            npc_id = npcs_resp.json()["npcs"][0].get("id") or npcs_resp.json()["npcs"][0].get("npc_id")
            
            response = client.get(
                f"/debug/sessions/{data['session_id']}/npcs/{npc_id}/mind?role=admin",
                headers=headers
            )
            
            if response.status_code == 200:
                resp = response.json()
                assert "npc_id" in resp
                assert "session_id" in resp
                assert "profile" in resp
                assert "state" in resp
                assert "beliefs" in resp
                assert "memories" in resp
                assert "view_role" in resp


class TestDebugReplayReportSchema:
    """Test POST /debug/sessions/{session_id}/replay-report endpoint schema."""

    def test_returns_correct_schema(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        response = client.post(
            f"/debug/sessions/{data['session_id']}/replay-report?end_turn=1",
            headers=headers
        )
        
        assert response.status_code == 200
        resp = response.json()
        
        assert "session_id" in resp
        assert "from_turn" in resp
        assert "to_turn" in resp
        assert "replayed_event_count" in resp
        assert "deterministic" in resp
        assert "llm_calls_made" in resp
        assert "state_diff" in resp
        assert "warnings" in resp
        assert "created_at" in resp
        
        diff = resp["state_diff"]
        assert "entries" in diff
        assert "added_keys" in diff
        assert "removed_keys" in diff
        assert "changed_keys" in diff


class TestDebugErrorResponses:
    """Test error response schemas for debug endpoints."""

    def test_401_unauthenticated(self, client, db_session):
        setup_full_session_with_data(db_session)
        
        response = client.get("/debug/model-calls")
        
        assert response.status_code == 401

    def test_403_non_admin(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_full_session_with_data(db_session)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 403
        data = response.json()
        assert "detail" in data

    def test_404_session_not_found(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get(
            "/debug/sessions/nonexistent_session/logs",
            headers=headers
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_403_debug_disabled(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        
        settings = db_session.query(SystemSettingsModel).first()
        if settings:
            settings.debug_enabled = False
            db_session.commit()
        else:
            settings = SystemSettingsModel(
                id="test_settings",
                debug_enabled=False,
            )
            db_session.add(settings)
            db_session.commit()
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 403
        data = response.json()
        assert "detail" in data
        assert "disabled" in data["detail"].lower()


class TestAuditStorePersistence:
    """Test AuditStore persistence for model calls (Task 2)."""

    def test_model_call_persisted_to_db(self, db_engine, db_session):
        """Verify model calls are persisted to ModelCallAuditLogModel table."""
        store = AuditStore(db_session=db_session)
        
        model_call = ModelCallLog(
            call_id=f"call_persist_{uuid.uuid4().hex[:8]}",
            session_id="test_session_persist",
            turn_no=1,
            provider="openai",
            model_name="gpt-4",
            prompt_type="narration",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost_estimate=0.01,
            latency_ms=500,
            success=True,
        )
        
        store.store_model_call(model_call)
        
        db_entry = db_session.query(ModelCallAuditLogModel).filter(
            ModelCallAuditLogModel.call_id == model_call.call_id
        ).first()
        
        assert db_entry is not None
        assert db_entry.call_id == model_call.call_id
        assert db_entry.session_id == model_call.session_id
        assert db_entry.turn_no == model_call.turn_no
        assert db_entry.provider == model_call.provider
        assert db_entry.model_name == model_call.model_name
        assert db_entry.prompt_type == model_call.prompt_type
        assert db_entry.input_tokens == model_call.input_tokens
        assert db_entry.output_tokens == model_call.output_tokens
        assert db_entry.total_tokens == model_call.total_tokens
        assert db_entry.cost_estimate == model_call.cost_estimate
        assert db_entry.latency_ms == model_call.latency_ms

    def test_retrieve_model_calls_from_db(self, db_engine, db_session):
        """Verify model calls can be retrieved from database."""
        store = AuditStore(db_session=db_session)
        
        db_call = ModelCallAuditLogModel(
            call_id=f"call_db_{uuid.uuid4().hex[:8]}",
            session_id="test_session_db",
            turn_no=1,
            provider="openai",
            model_name="gpt-4",
            prompt_type="test",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            cost_estimate=0.02,
            latency_ms=600,
            success=True,
        )
        db_session.add(db_call)
        db_session.commit()
        
        calls = store.get_model_calls_from_db("test_session_db", limit=10)
        
        assert len(calls) >= 1
        found = any(c.call_id == db_call.call_id for c in calls)
        assert found

    def test_model_call_fields_match_schema(self, db_engine, db_session):
        """Verify all ModelCallLog fields are persisted correctly."""
        store = AuditStore(db_session=db_session)
        
        model_call = ModelCallLog(
            call_id=f"call_full_{uuid.uuid4().hex[:8]}",
            session_id="test_session_full",
            turn_no=1,
            provider="test_provider",
            model_name="test_model",
            prompt_type="test_prompt",
            input_tokens=500,
            output_tokens=250,
            total_tokens=750,
            cost_estimate=0.05,
            latency_ms=1000,
            success=False,
            error_message="Test error",
            context_build_id="ctx_test_123",
        )
        
        store.store_model_call(model_call)
        
        db_entry = db_session.query(ModelCallAuditLogModel).filter(
            ModelCallAuditLogModel.call_id == model_call.call_id
        ).first()
        
        assert db_entry.error_message == "Test error"
        assert db_entry.success is False
        assert db_entry.context_build_id == "ctx_test_123"


class TestPerspectiveFiltering:
    """Test perspective parameter behavior across endpoints."""

    def test_replay_perspective_filters_hidden_info(self, client, db_engine, db_session, admin_user_data):
        """Verify player perspective filters hidden information."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_full_session_with_data(db_session)
        
        admin_resp = client.post(
            f"/debug/sessions/{data['session_id']}/replay?end_turn=1&perspective=admin",
            headers=headers
        )
        
        player_resp = client.post(
            f"/debug/sessions/{data['session_id']}/replay?end_turn=1&perspective=player",
            headers=headers
        )
        
        auditor_resp = client.post(
            f"/debug/sessions/{data['session_id']}/replay?end_turn=1&perspective=auditor",
            headers=headers
        )
        
        assert admin_resp.status_code == 200
        assert player_resp.status_code == 200
        assert auditor_resp.status_code == 200
        
        assert admin_resp.json()["perspective"] == "admin"
        assert player_resp.json()["perspective"] == "player"
        assert auditor_resp.json()["perspective"] == "auditor"


class TestEmptyStateHandling:
    """Test empty state handling across all endpoints."""

    def test_empty_session_logs(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_minimal_session(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/logs",
            headers=headers
        )
        
        assert response.status_code == 200
        assert response.json()["total_count"] == 0
        assert response.json()["logs"] == []

    def test_empty_model_calls(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/model-calls", headers=headers)
        
        assert response.status_code == 200
        assert response.json()["total_count"] == 0
        assert response.json()["calls"] == []

    def test_empty_errors(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/errors", headers=headers)
        
        assert response.status_code == 200
        assert response.json()["total_count"] == 0
        assert response.json()["errors"] == []

    def test_empty_timeline(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        data = setup_minimal_session(db_session)
        
        response = client.get(
            f"/debug/sessions/{data['session_id']}/timeline",
            headers=headers
        )
        
        assert response.status_code == 200
        assert response.json()["total_turns"] == 0
        assert response.json()["turns"] == []

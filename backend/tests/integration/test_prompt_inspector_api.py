"""
Integration tests for Prompt Inspector API endpoints.

Tests:
- Enhanced GET /debug/sessions/{id}/turns/{turn_no} with new fields
- GET /debug/sessions/{id}/prompt-inspector aggregated endpoint
- Filtering by turn_range (start_turn, end_turn) and prompt_type
- Authentication and authorization (401, 403)
- Read-only verification (no DB mutations)
"""

import hashlib
import json
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.audit import (
    get_audit_logger, reset_audit_logger, AuditLogger, AuditStore,
    TurnAuditLog, TurnEventAudit, TurnStateDeltaAudit,
    ModelCallLog, ContextBuildAudit, ValidationResultAudit,
    ValidationCheck, ValidationStatus, MemoryDecisionReason,
    MemoryAuditEntry, ProposalAuditEntry,
)
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel, WorldModel, SessionModel, EventLogModel,
    SessionStateModel, SessionPlayerStateModel, SessionNPCStateModel,
    SessionInventoryItemModel, SessionQuestStateModel,
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


def setup_test_session_with_data(db):
    """Create a test session with related data for testing."""
    world = WorldModel(
        id="test_world_pi",
        code="pi_world",
        name="PI Test World",
        genre="xianxia",
        lore_summary="Test world for prompt inspector",
        status="active",
    )
    db.add(world)

    chapter = ChapterModel(
        id="test_chapter_pi",
        world_id="test_world_pi",
        chapter_no=1,
        name="PI Chapter",
        summary="Test chapter",
    )
    db.add(chapter)

    location = LocationModel(
        id="test_location_pi",
        world_id="test_world_pi",
        code="pi_loc",
        name="PI Location",
        description="Test location",
    )
    db.add(location)

    npc_template = NPCTemplateModel(
        id="test_npc_template_pi",
        world_id="test_world_pi",
        code="pi_npc",
        name="PI NPC",
        role_type="npc",
    )
    db.add(npc_template)

    item_template = ItemTemplateModel(
        id="test_item_template_pi",
        world_id="test_world_pi",
        code="pi_item",
        name="PI Item",
        description="Test item",
        item_type="misc",
    )
    db.add(item_template)

    quest_template = QuestTemplateModel(
        id="test_quest_template_pi",
        world_id="test_world_pi",
        code="pi_quest",
        name="PI Quest",
        summary="Test quest",
    )
    db.add(quest_template)

    user = UserModel(
        id="test_user_pi",
        username="pi_test_user",
        email="pi@test.com",
        password_hash="hashed",
        is_admin=True,
    )
    db.add(user)

    session = SessionModel(
        id="test_session_pi",
        user_id="test_user_pi",
        world_id="test_world_pi",
        current_chapter_id="test_chapter_pi",
        status="active",
    )
    db.add(session)

    session_state = SessionStateModel(
        id="test_session_state_pi",
        session_id="test_session_pi",
        current_time="Day 1",
        time_phase="morning",
        current_location_id="test_location_pi",
        active_mode="exploration",
        global_flags_json={},
    )
    db.add(session_state)

    player_state = SessionPlayerStateModel(
        id="test_player_state_pi",
        session_id="test_session_pi",
        realm_stage="炼气一层",
        hp=100, max_hp=100, stamina=100, spirit_power=100,
        relation_bias_json={},
        conditions_json=[],
    )
    db.add(player_state)

    npc_state = SessionNPCStateModel(
        id="test_npc_state_pi",
        session_id="test_session_pi",
        npc_template_id="test_npc_template_pi",
        current_location_id="test_location_pi",
        trust_score=50,
        suspicion_score=0,
        status_flags={},
    )
    db.add(npc_state)

    inventory_item = SessionInventoryItemModel(
        id="test_inventory_pi",
        session_id="test_session_pi",
        item_template_id="test_item_template_pi",
        owner_type="player",
        quantity=1,
        bound_flag=False,
    )
    db.add(inventory_item)

    quest_state = SessionQuestStateModel(
        id="test_quest_state_pi",
        session_id="test_session_pi",
        quest_template_id="test_quest_template_pi",
        current_step_no=1,
        progress_json={},
        status="active",
    )
    db.add(quest_state)

    db.commit()


def seed_audit_store(session_id="test_session_pi"):
    """Seed the global AuditStore with test data for prompt inspector tests."""
    reset_audit_logger()
    logger = get_audit_logger()

    # --- Model Call Logs (3 calls across 2 turns) ---
    call_1 = logger.log_model_call(
        session_id=session_id, turn_no=1,
        provider="openai", model_name="gpt-4",
        prompt_type="input_intent",
        input_tokens=150, output_tokens=80,
        cost_estimate=0.005, latency_ms=300,
        context_build_id="ctx_intent_001",
    )
    call_2 = logger.log_model_call(
        session_id=session_id, turn_no=1,
        provider="openai", model_name="gpt-4",
        prompt_type="narration",
        input_tokens=500, output_tokens=200,
        cost_estimate=0.015, latency_ms=800,
        context_build_id="ctx_narr_001",
    )
    call_3 = logger.log_model_call(
        session_id=session_id, turn_no=2,
        provider="openai", model_name="gpt-4",
        prompt_type="npc_action",
        input_tokens=300, output_tokens=120,
        cost_estimate=0.010, latency_ms=500,
        context_build_id="ctx_npc_001",
    )

    # --- Context Build Audits ---
    ctx_1 = logger.log_context_build(
        session_id=session_id, turn_no=1,
        perspective_type="world", perspective_id="world_view",
        included_memories=[
            MemoryAuditEntry(
                memory_id="mem_001", memory_type="episodic", owner_id="player",
                included=True, reason=MemoryDecisionReason.RELEVANCE_SCORE,
                relevance_score=0.9, importance_score=0.8, recency_score=0.7,
            ),
            MemoryAuditEntry(
                memory_id="mem_002", memory_type="semantic", owner_id="player",
                included=True, reason=MemoryDecisionReason.RECENCY_PRIORITY,
                relevance_score=0.7, importance_score=0.6, recency_score=0.9,
            ),
        ],
        excluded_memories=[
            MemoryAuditEntry(
                memory_id="mem_003", memory_type="episodic", owner_id="npc_1",
                included=False, reason=MemoryDecisionReason.FORBIDDEN_KNOWLEDGE,
                relevance_score=0.8, forbidden_knowledge_flag=True,
                notes="NPC knows hidden lore - excluded",
            ),
        ],
        total_candidates=3, context_token_count=450, context_char_count=1800,
        build_duration_ms=15,
    )
    ctx_2 = logger.log_context_build(
        session_id=session_id, turn_no=1,
        perspective_type="narrator", perspective_id="narrator_view",
        included_memories=[
            MemoryAuditEntry(
                memory_id="mem_001", memory_type="episodic", owner_id="player",
                included=True, reason=MemoryDecisionReason.ENTITY_VISIBLE,
                relevance_score=0.9,
            ),
        ],
        excluded_memories=[],
        total_candidates=1, context_token_count=200, context_char_count=800,
        build_duration_ms=8,
    )
    ctx_3 = logger.log_context_build(
        session_id=session_id, turn_no=2,
        perspective_type="npc", perspective_id="npc_1",
        owner_id="npc_1",
        included_memories=[
            MemoryAuditEntry(
                memory_id="mem_004", memory_type="episodic", owner_id="npc_1",
                included=True, reason=MemoryDecisionReason.ENTITY_VISIBLE,
                relevance_score=0.95, importance_score=0.7,
            ),
        ],
        excluded_memories=[
            MemoryAuditEntry(
                memory_id="mem_005", memory_type="episodic", owner_id="player",
                included=False, reason=MemoryDecisionReason.PERSPECTIVE_FILTERED,
                relevance_score=0.6,
                perspective_filter_applied=True,
            ),
        ],
        total_candidates=2, context_token_count=300, context_char_count=1200,
        build_duration_ms=12,
    )

    # --- Validation Result Audits ---
    val_1 = logger.log_validation(
        session_id=session_id, turn_no=1,
        validation_target="narration",
        overall_status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                check_id="chk_001", check_type="perspective_safety",
                status=ValidationStatus.PASSED,
                message="No forbidden knowledge leaked",
            ),
        ],
    )
    val_2 = logger.log_validation(
        session_id=session_id, turn_no=2,
        validation_target="npc_action",
        overall_status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                check_id="chk_002", check_type="action_validity",
                status=ValidationStatus.PASSED,
                message="NPC action is valid",
            ),
            ValidationCheck(
                check_id="chk_003", check_type="state_bounds",
                status=ValidationStatus.WARNING,
                message="Action near capacity limit",
            ),
        ],
        errors=[], warnings=["near capacity limit"],
    )

    # --- Proposal Audits ---
    prop_1 = logger.log_proposal(
        session_id=session_id, turn_no=1,
        proposal_type="input_intent",
        prompt_template_id="input_intent_v1",
        model_name="gpt-4",
        input_tokens=150, output_tokens=80, latency_ms=300,
        raw_output_preview='{"intent": "explore", "target": "forest"}',
        raw_output_hash=hashlib.sha256(b'{"intent": "explore", "target": "forest"}').hexdigest(),
        parsed_proposal={"intent": "explore", "target": "forest"},
        parse_success=True,
        validation_passed=True,
        validation_errors=[],
        fallback_used=False,
    )
    prop_2 = logger.log_proposal(
        session_id=session_id, turn_no=1,
        proposal_type="narration",
        prompt_template_id="narration_v1",
        model_name="gpt-4",
        input_tokens=500, output_tokens=200, latency_ms=800,
        raw_output_preview="You enter the misty forest, ancient trees looming...",
        raw_output_hash=hashlib.sha256(b"You enter the misty forest...").hexdigest(),
        parsed_proposal={"narrative": "You enter the misty forest, ancient trees looming..."},
        parse_success=True,
        validation_passed=True,
        validation_errors=[],
        confidence=0.9,
        fallback_used=False,
    )
    prop_3 = logger.log_proposal(
        session_id=session_id, turn_no=2,
        proposal_type="npc_action",
        prompt_template_id="npc_action_v1",
        model_name="gpt-4",
        input_tokens=300, output_tokens=120, latency_ms=500,
        raw_output_preview='{"action": "greet", "dialogue": "Welcome, traveler."}',
        raw_output_hash=hashlib.sha256(b'{"action": "greet", "dialogue": "Welcome, traveler."}').hexdigest(),
        parsed_proposal={"action": "greet", "dialogue": "Welcome, traveler."},
        parse_success=True,
        validation_passed=True,
        validation_errors=[],
        confidence=0.85,
        fallback_used=False,
    )

    # --- Turn Audit Logs ---
    logger.log_turn(
        session_id=session_id, turn_no=1,
        transaction_id="txn_001",
        player_input="I want to explore the forest",
        world_time_before={"day": 1, "phase": "morning"},
        world_time_after={"day": 1, "phase": "noon"},
        parsed_intent={"intent": "explore", "target": "forest"},
        model_call_ids=[call_1.call_id, call_2.call_id],
        context_build_ids=[ctx_1.build_id, ctx_2.build_id],
        validation_ids=[val_1.validation_id],
        status="completed",
        narration_generated=True,
        narration_length=125,
        turn_duration_ms=1200,
    )
    logger.log_turn(
        session_id=session_id, turn_no=2,
        transaction_id="txn_002",
        player_input="Talk to the NPC",
        world_time_before={"day": 1, "phase": "noon"},
        world_time_after={"day": 1, "phase": "afternoon"},
        parsed_intent={"intent": "talk", "target": "npc_1"},
        model_call_ids=[call_3.call_id],
        context_build_ids=[ctx_3.build_id],
        validation_ids=[val_2.validation_id],
        status="completed",
        narration_generated=True,
        narration_length=80,
        turn_duration_ms=600,
    )

    return {
        "calls": [call_1, call_2, call_3],
        "contexts": [ctx_1, ctx_2, ctx_3],
        "validations": [val_1, val_2],
        "proposals": [prop_1, prop_2, prop_3],
    }


def count_all_rows(db) -> dict:
    """Count rows in all relevant tables."""
    return {
        "users": db.query(func.count(UserModel.id)).scalar(),
        "sessions": db.query(func.count(SessionModel.id)).scalar(),
        "event_logs": db.query(func.count(EventLogModel.id)).scalar(),
    }


# ============================================================
# Enhanced Turn Debug Tests
# ============================================================

class TestEnhancedTurnDebug:
    """Test enhanced GET /debug/sessions/{id}/turns/{turn_no} endpoint."""

    def test_turn_debug_includes_prompt_template_ids(self, client, db_engine, db_session, admin_user_data):
        """New fields: prompt_template_ids in turn debug response."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        response = client.get(
            "/debug/sessions/test_session_pi/turns/1",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "prompt_template_ids" in data, "Should include prompt_template_ids field"
        assert isinstance(data["prompt_template_ids"], list)
        templates = data["prompt_template_ids"]
        assert len(templates) >= 2  # input_intent and narration proposals
        assert any("narration_v1" in str(t) for t in templates) or \
               any("input_intent" in str(t) for t in templates)

        # Verify existing fields still present
        assert data["session_id"] == "test_session_pi"
        assert data["turn_no"] == 1
        assert "model_call_ids" in data
        assert "context_build_ids" in data

    def test_turn_debug_includes_context_hashes(self, client, db_engine, db_session, admin_user_data):
        """New fields: context_hashes in turn debug response."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        response = client.get(
            "/debug/sessions/test_session_pi/turns/1",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "context_hashes" in data, "Should include context_hashes field"
        assert isinstance(data["context_hashes"], list)
        assert len(data["context_hashes"]) >= 2  # Two context builds for turn 1

        for ctx_hash in data["context_hashes"]:
            assert "build_id" in ctx_hash, "Each hash entry should have build_id"
            assert "context_hash" in ctx_hash, "Each hash entry should have context_hash"
            assert len(ctx_hash["context_hash"]) == 64  # SHA256 hex digest

    def test_turn_debug_includes_model_call_references(self, client, db_engine, db_session, admin_user_data):
        """New fields: model_call_references in turn debug response."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        response = client.get(
            "/debug/sessions/test_session_pi/turns/1",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "model_call_references" in data, "Should include model_call_references field"
        assert isinstance(data["model_call_references"], list)
        assert len(data["model_call_references"]) >= 2

        for ref in data["model_call_references"]:
            assert "call_id" in ref
            assert "prompt_type" in ref
            assert "model_name" in ref
            assert "input_tokens" in ref
            assert "output_tokens" in ref
            assert "cost_estimate" in ref
            assert "latency_ms" in ref

    def test_turn_debug_404_for_nonexistent_turn(self, client, db_engine, db_session, admin_user_data):
        """Returns 404 for nonexistent turn."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        response = client.get(
            "/debug/sessions/test_session_pi/turns/99",
            headers=headers,
        )

        assert response.status_code == 404


# ============================================================
# Prompt Inspector Endpoint Tests
# ============================================================

class TestPromptInspectorEndpoint:
    """Test GET /debug/sessions/{id}/prompt-inspector endpoint."""

    def test_prompt_inspector_returns_aggregated_data(self, client, db_engine, db_session, admin_user_data):
        """Prompt inspector returns all prompt-related data for a session."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        response = client.get(
            "/debug/sessions/test_session_pi/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Top-level structure
        assert data["session_id"] == "test_session_pi"
        assert "total_turns" in data
        assert data["total_turns"] >= 2

        # prompt_templates field
        assert "prompt_templates" in data, "Should include prompt_templates"
        assert isinstance(data["prompt_templates"], list)
        assert len(data["prompt_templates"]) >= 3

        for tmpl in data["prompt_templates"]:
            assert "prompt_template_id" in tmpl
            assert "proposal_type" in tmpl
            assert "turn_no" in tmpl

        # context_builds field
        assert "context_builds" in data, "Should include context_builds"
        assert isinstance(data["context_builds"], list)
        assert len(data["context_builds"]) >= 3

        for ctx in data["context_builds"]:
            assert "build_id" in ctx
            assert "perspective_type" in ctx
            assert "included_memories" in ctx
            assert "excluded_memories" in ctx
            assert "turn_no" in ctx

        # model_calls field
        assert "model_calls" in data, "Should include model_calls"
        assert isinstance(data["model_calls"], list)
        assert len(data["model_calls"]) >= 3

        for mc in data["model_calls"]:
            assert "call_id" in mc
            assert "turn_no" in mc
            assert "prompt_type" in mc

        # proposals field
        assert "proposals" in data, "Should include proposals"
        assert isinstance(data["proposals"], list)
        assert len(data["proposals"]) >= 3

        for prop in data["proposals"]:
            assert "proposal_type" in prop
            assert "turn_no" in prop
            assert "prompt_template_id" in prop
            assert "raw_output_preview" in prop
            assert "raw_output_hash" in prop
            assert "parsed_proposal" in prop
            assert "repair_attempts" in prop
            assert "parse_success" in prop
            assert "validation_passed" in prop

        # validations field
        assert "validations" in data, "Should include validations"
        assert isinstance(data["validations"], list)
        assert len(data["validations"]) >= 2

        for val in data["validations"]:
            assert "validation_id" in val
            assert "turn_no" in val
            assert "overall_status" in val

        # aggregates
        assert "aggregates" in data, "Should include aggregates"
        agg = data["aggregates"]
        assert "total_tokens_used" in agg
        assert "total_cost" in agg
        assert "total_latency_ms" in agg
        assert agg["total_tokens_used"] > 0
        assert agg["total_cost"] > 0
        assert agg["total_latency_ms"] > 0

    def test_prompt_inspector_filter_by_turn_range(self, client, db_engine, db_session, admin_user_data):
        """Filtering by start_turn and end_turn."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        # Filter to turn 1 only
        response = client.get(
            "/debug/sessions/test_session_pi/prompt-inspector?start_turn=1&end_turn=1",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_turns"] == 1

        # All entries should be turn 1
        for mc in data["model_calls"]:
            assert mc["turn_no"] == 1
        for prop in data["proposals"]:
            assert prop["turn_no"] == 1

    def test_prompt_inspector_filter_by_prompt_type(self, client, db_engine, db_session, admin_user_data):
        """Filtering by prompt_type query parameter."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        response = client.get(
            "/debug/sessions/test_session_pi/prompt-inspector?prompt_type=narration",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # All model calls should have prompt_type "narration"
        for mc in data["model_calls"]:
            assert mc["prompt_type"] == "narration"

    def test_prompt_inspector_combined_filters(self, client, db_engine, db_session, admin_user_data):
        """Combined filtering by turn_range and prompt_type."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        response = client.get(
            "/debug/sessions/test_session_pi/prompt-inspector?start_turn=2&end_turn=2&prompt_type=npc_action",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_turns"] == 1
        assert len(data["model_calls"]) >= 1
        for mc in data["model_calls"]:
            assert mc["turn_no"] == 2
            assert mc["prompt_type"] == "npc_action"

    def test_prompt_inspector_404_for_nonexistent_session(self, client, db_engine, db_session, admin_user_data):
        """Returns 404 for nonexistent session."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/sessions/nonexistent_session/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 404

    def test_prompt_inspector_non_admin_forbidden(self, client, db_engine, db_session, regular_user_data):
        """Non-admin users get 403."""
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_test_session_with_data(db_session)

        response = client.get(
            "/debug/sessions/test_session_pi/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 403

    def test_prompt_inspector_unauthenticated_gets_401(self, client, db_session):
        """Unauthenticated users get 401."""
        setup_test_session_with_data(db_session)

        response = client.get("/debug/sessions/test_session_pi/prompt-inspector")

        assert response.status_code == 401


# ============================================================
# Read-Only Verification
# ============================================================

class TestPromptInspectorReadOnly:
    """Verify prompt inspector endpoints do not modify database state."""

    def test_prompt_inspector_is_read_only(self, client, db_engine, db_session, admin_user_data):
        """Prompt inspector endpoint does not mutate DB."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        rows_before = count_all_rows(db_session)

        client.get(
            "/debug/sessions/test_session_pi/prompt-inspector",
            headers=headers,
        )
        client.get(
            "/debug/sessions/test_session_pi/turns/1",
            headers=headers,
        )
        client.get(
            "/debug/sessions/test_session_pi/prompt-inspector?start_turn=1&end_turn=2",
            headers=headers,
        )

        rows_after = count_all_rows(db_session)
        assert rows_before == rows_after, "GET endpoints must not modify database"

    def test_prompt_inspector_multiple_requests_no_mutation(self, client, db_engine, db_session, admin_user_data):
        """Multiple requests to prompt inspector don't accumulate mutations."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_data(db_session)
        seed_audit_store("test_session_pi")

        rows_initial = count_all_rows(db_session)

        for _ in range(5):
            client.get(
                "/debug/sessions/test_session_pi/prompt-inspector",
                headers=headers,
            )
            client.get(
                "/debug/sessions/test_session_pi/turns/1",
                headers=headers,
            )

        rows_final = count_all_rows(db_session)
        assert rows_initial == rows_final, "Multiple GET requests must not modify database"

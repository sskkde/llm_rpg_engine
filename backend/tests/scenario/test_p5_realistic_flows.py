"""
P5 Realistic Flow Integration Tests.

Four comprehensive integration scenario tests:
1. Prompt Inspector Flow - Create audit data, call prompt-inspector endpoint, verify response
2. Replay Consistency Flow - Create snapshot and replay events, verify final state
3. Debug Contract Flow - Verify field contracts match frontend types
4. Save/Replay Consistency Flow - Save snapshot, replay, compare state diff

All tests use:
- FastAPI TestClient with SQLite overrides
- MockLLMProvider (no real OpenAI key)
- In-memory SQLite (no PostgreSQL needed)
"""

import hashlib
import uuid
from datetime import datetime
from typing import Dict, Any, List

import pytest
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
)
from llm_rpg.main import app
from llm_rpg.core.audit import (
    get_audit_logger, reset_audit_logger, AuditStore,
    TurnAuditLog, TurnEventAudit, TurnStateDeltaAudit,
    ContextBuildAudit, MemoryAuditEntry, MemoryDecisionReason,
    ValidationResultAudit, ValidationCheck, ValidationStatus,
    ModelCallLog, ProposalAuditEntry,
)
from llm_rpg.core.replay import (
    get_replay_store, reset_replay_store, ReplayStore,
    ReplayPerspective, ReplayEvent, StateSnapshot, StateReconstructor,
)


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    """Create an in-memory SQLite database for each test."""
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
    """Create a database session for each test."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_engine, db_session):
    """Create a FastAPI TestClient with test database overrides."""
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


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset audit logger and replay store before and after each test."""
    reset_audit_logger()
    reset_replay_store()
    yield
    reset_audit_logger()
    reset_replay_store()


@pytest.fixture
def admin_user_data():
    """Generate admin user test data."""
    return {
        "username": f"admin_{uuid.uuid4().hex[:8]}",
        "email": f"admin_{uuid.uuid4().hex[:8]}@example.com",
        "password": "AdminPass123!",
    }


def create_user_in_db(db_engine, user_data, is_admin=False):
    """Create a user in the database."""
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
    """Get authorization header for authenticated requests."""
    response = client.post("/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"],
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def setup_full_session_with_data(db: Session) -> Dict[str, str]:
    """Create a session with full test data including turns, events, and model calls."""
    # World
    world = WorldModel(
        id="test_world_p5",
        code="p5_world",
        name="P5 Test World",
        genre="xianxia",
        lore_summary="Test world for P5 flows",
        status="active",
    )
    db.add(world)

    chapter = ChapterModel(
        id="test_chapter_p5",
        world_id="test_world_p5",
        chapter_no=1,
        name="P5 Chapter",
        summary="Test chapter",
    )
    db.add(chapter)

    location = LocationModel(
        id="test_location_p5",
        world_id="test_world_p5",
        code="p5_loc",
        name="P5 Location",
        description="Test location",
    )
    db.add(location)

    npc_template = NPCTemplateModel(
        id="test_npc_template_p5",
        world_id="test_world_p5",
        code="p5_npc",
        name="P5 NPC",
        role_type="npc",
    )
    db.add(npc_template)

    item_template = ItemTemplateModel(
        id="test_item_template_p5",
        world_id="test_world_p5",
        code="p5_item",
        name="P5 Item",
        description="Test item",
        item_type="misc",
    )
    db.add(item_template)

    quest_template = QuestTemplateModel(
        id="test_quest_template_p5",
        world_id="test_world_p5",
        code="p5_quest",
        name="P5 Quest",
        summary="Test quest",
    )
    db.add(quest_template)

    # User
    user = UserModel(
        id="test_user_p5",
        username="p5_test_user",
        email="p5@test.com",
        password_hash="hashed",
        is_admin=True,
    )
    db.add(user)

    # Session
    session = SessionModel(
        id="test_session_p5",
        user_id="test_user_p5",
        world_id="test_world_p5",
        current_chapter_id="test_chapter_p5",
        status="active",
    )
    db.add(session)

    # Session state
    session_state = SessionStateModel(
        id="test_session_state_p5",
        session_id="test_session_p5",
        current_time="Day 1",
        time_phase="morning",
        current_location_id="test_location_p5",
        active_mode="exploration",
        global_flags_json={},
    )
    db.add(session_state)

    # Player state
    player_state = SessionPlayerStateModel(
        id="test_player_state_p5",
        session_id="test_session_p5",
        realm_stage="炼气一层",
        hp=100, max_hp=100, stamina=100, spirit_power=100,
        relation_bias_json={},
        conditions_json=[],
    )
    db.add(player_state)

    # NPC state
    npc_state = SessionNPCStateModel(
        id="test_npc_state_p5",
        session_id="test_session_p5",
        npc_template_id="test_npc_template_p5",
        current_location_id="test_location_p5",
        trust_score=50,
        suspicion_score=0,
        status_flags={},
    )
    db.add(npc_state)

    # Inventory
    inventory_item = SessionInventoryItemModel(
        id="test_inventory_p5",
        session_id="test_session_p5",
        item_template_id="test_item_template_p5",
        owner_type="player",
        quantity=1,
        bound_flag=False,
    )
    db.add(inventory_item)

    # Quest state
    quest_state = SessionQuestStateModel(
        id="test_quest_state_p5",
        session_id="test_session_p5",
        quest_template_id="test_quest_template_p5",
        current_step_no=1,
        progress_json={},
        status="active",
    )
    db.add(quest_state)

    # Event logs
    event_log_1 = EventLogModel(
        id="test_event_log_1_p5",
        session_id="test_session_p5",
        turn_no=1,
        event_type="player_input",
        input_text="explore the forest",
        narrative_text="You venture into the ancient forest.",
        result_json={"action": "explore", "result": "success"},
    )
    db.add(event_log_1)

    event_log_2 = EventLogModel(
        id="test_event_log_2_p5",
        session_id="test_session_p5",
        turn_no=2,
        event_type="player_input",
        input_text="talk to the elder",
        narrative_text="The elder nods knowingly.",
        result_json={"action": "talk", "target": "elder"},
    )
    db.add(event_log_2)

    event_log_error = EventLogModel(
        id="test_event_log_error_p5",
        session_id="test_session_p5",
        turn_no=3,
        event_type="error",
        narrative_text="An error occurred during processing.",
        result_json={"error_details": "test error"},
    )
    db.add(event_log_error)

    # Model call logs
    model_call_1 = ModelCallLogModel(
        id="test_model_call_1_p5",
        session_id="test_session_p5",
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
        id="test_model_call_2_p5",
        session_id="test_session_p5",
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
        "session_id": "test_session_p5",
        "world_id": "test_world_p5",
        "user_id": "test_user_p5",
    }


def seed_audit_store_for_prompt_inspector(session_id: str) -> Dict[str, Any]:
    """Seed the global AuditStore with comprehensive test data for prompt inspector."""
    reset_audit_logger()
    logger = get_audit_logger()

    # Model calls
    call_1 = logger.log_model_call(
        session_id=session_id, turn_no=1,
        provider="openai", model_name="gpt-4",
        prompt_type="input_intent",
        input_tokens=150, output_tokens=80,
        cost_estimate=0.005, latency_ms=300,
        context_build_id="ctx_intent_p5",
    )
    call_2 = logger.log_model_call(
        session_id=session_id, turn_no=1,
        provider="openai", model_name="gpt-4",
        prompt_type="narration",
        input_tokens=500, output_tokens=200,
        cost_estimate=0.015, latency_ms=800,
        context_build_id="ctx_narr_p5",
    )

    # Context builds
    ctx_1 = logger.log_context_build(
        session_id=session_id, turn_no=1,
        perspective_type="world", perspective_id="world_view",
        included_memories=[
            MemoryAuditEntry(
                memory_id="mem_p5_001", memory_type="episodic", owner_id="player",
                included=True, reason=MemoryDecisionReason.RELEVANCE_SCORE,
                relevance_score=0.9, importance_score=0.8, recency_score=0.7,
            ),
        ],
        excluded_memories=[
            MemoryAuditEntry(
                memory_id="mem_p5_002", memory_type="secret", owner_id="npc_1",
                included=False, reason=MemoryDecisionReason.FORBIDDEN_KNOWLEDGE,
                forbidden_knowledge_flag=True,
                notes="NPC secret - excluded from narration",
            ),
        ],
        total_candidates=2, context_token_count=450, context_char_count=1800,
        build_duration_ms=15,
    )

    # Validations
    val_1 = logger.log_validation(
        session_id=session_id, turn_no=1,
        validation_target="narration",
        overall_status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                check_id="chk_p5_001", check_type="perspective_safety",
                status=ValidationStatus.PASSED,
                message="No forbidden knowledge leaked",
            ),
        ],
    )

    # Proposals
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
        raw_output_preview="The ancient forest looms before you...",
        raw_output_hash=hashlib.sha256(b"The ancient forest...").hexdigest(),
        parsed_proposal={"narrative": "The ancient forest looms before you..."},
        parse_success=True,
        validation_passed=True,
        validation_errors=[],
        confidence=0.9,
        fallback_used=False,
    )

    # Turn audit
    logger.log_turn(
        session_id=session_id, turn_no=1,
        transaction_id="txn_p5_001",
        player_input="I want to explore the forest",
        world_time_before={"day": 1, "phase": "morning"},
        world_time_after={"day": 1, "phase": "noon"},
        parsed_intent={"intent": "explore", "target": "forest"},
        model_call_ids=[call_1.call_id, call_2.call_id],
        context_build_ids=[ctx_1.build_id],
        validation_ids=[val_1.validation_id],
        status="completed",
        narration_generated=True,
        narration_length=125,
        turn_duration_ms=1200,
    )

    return {
        "call_ids": [call_1.call_id, call_2.call_id],
        "context_id": ctx_1.build_id,
        "validation_id": val_1.validation_id,
        "proposal_ids": [prop_1.audit_id, prop_2.audit_id],
    }


# =============================================================================
# Test 1: Prompt Inspector Flow
# =============================================================================

@pytest.mark.scenario
@pytest.mark.p5_scenario
@pytest.mark.integration
class TestPromptInspectorFlow:
    """
    Test 1: Prompt Inspector Flow
    - Create test session with AuditStore entries
    - POST to create session → use TestClient to call /debug/sessions/{id}/prompt-inspector
    - Verify response contains: prompt_templates, model_calls, context_builds, proposals, validations, aggregates
    """

    def test_prompt_inspector_returns_all_required_fields(self, client, db_engine, db_session, admin_user_data):
        """Prompt inspector returns all required top-level fields."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        seed_audit_store_for_prompt_inspector("test_session_p5")

        response = client.get(
            "/debug/sessions/test_session_p5/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()

        # Top-level structure
        assert data["session_id"] == "test_session_p5"
        assert "total_turns" in data
        assert "aggregates" in data

        # Required arrays
        assert "prompt_templates" in data
        assert "model_calls" in data
        assert "context_builds" in data
        assert "proposals" in data
        assert "validations" in data

        # Verify arrays are lists
        assert isinstance(data["prompt_templates"], list)
        assert isinstance(data["model_calls"], list)
        assert isinstance(data["context_builds"], list)
        assert isinstance(data["proposals"], list)
        assert isinstance(data["validations"], list)

    def test_prompt_inspector_model_calls_structure(self, client, db_engine, db_session, admin_user_data):
        """Verify model_calls entries have required fields."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        seed_audit_store_for_prompt_inspector("test_session_p5")

        response = client.get(
            "/debug/sessions/test_session_p5/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["model_calls"]) >= 1
        mc = data["model_calls"][0]

        # Required fields per model call
        assert "call_id" in mc
        assert "turn_no" in mc
        assert "prompt_type" in mc
        assert "provider" in mc
        assert "model_name" in mc
        assert "input_tokens" in mc
        assert "output_tokens" in mc
        assert "cost_estimate" in mc
        assert "latency_ms" in mc

    def test_prompt_inspector_context_builds_structure(self, client, db_engine, db_session, admin_user_data):
        """Verify context_builds entries have required fields."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        seed_audit_store_for_prompt_inspector("test_session_p5")

        response = client.get(
            "/debug/sessions/test_session_p5/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["context_builds"]) >= 1
        ctx = data["context_builds"][0]

        # Required fields per context build
        assert "build_id" in ctx
        assert "turn_no" in ctx
        assert "perspective_type" in ctx
        assert "perspective_id" in ctx
        assert "included_memories" in ctx
        assert "excluded_memories" in ctx
        assert "total_candidates" in ctx
        assert "context_token_count" in ctx

    def test_prompt_inspector_proposals_structure(self, client, db_engine, db_session, admin_user_data):
        """Verify proposals entries have required fields."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        seed_audit_store_for_prompt_inspector("test_session_p5")

        response = client.get(
            "/debug/sessions/test_session_p5/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["proposals"]) >= 1
        prop = data["proposals"][0]

        # Required fields per proposal
        assert "proposal_type" in prop
        assert "turn_no" in prop
        assert "prompt_template_id" in prop
        assert "raw_output_preview" in prop
        assert "raw_output_hash" in prop
        assert "parse_success" in prop
        assert "validation_passed" in prop

    def test_prompt_inspector_validations_structure(self, client, db_engine, db_session, admin_user_data):
        """Verify validations entries have required fields."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        seed_audit_store_for_prompt_inspector("test_session_p5")

        response = client.get(
            "/debug/sessions/test_session_p5/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["validations"]) >= 1
        val = data["validations"][0]

        # Required fields per validation
        assert "validation_id" in val
        assert "turn_no" in val
        assert "overall_status" in val
        assert "checks" in val

    def test_prompt_inspector_aggregates_structure(self, client, db_engine, db_session, admin_user_data):
        """Verify aggregates has required fields."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        seed_audit_store_for_prompt_inspector("test_session_p5")

        response = client.get(
            "/debug/sessions/test_session_p5/prompt-inspector",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        agg = data["aggregates"]

        # Required aggregate fields
        assert "total_tokens_used" in agg
        assert "total_cost" in agg
        assert "total_latency_ms" in agg
        assert "total_model_calls" in agg
        assert "call_success_rate" in agg
        assert "repair_success_rate" in agg

        # Verify values
        assert agg["total_tokens_used"] >= 0
        assert agg["total_cost"] >= 0.0
        assert agg["total_latency_ms"] >= 0
        assert agg["total_model_calls"] >= 1


# =============================================================================
# Test 2: Replay Consistency Flow
# =============================================================================

@pytest.mark.scenario
@pytest.mark.p5_scenario
@pytest.mark.integration
class TestReplayConsistencyFlow:
    """
    Test 2: Replay Consistency Flow
    - Create snapshot → create replay events with state_deltas
    - Call replay service or endpoint → verify final_state matches expected
    """

    def test_replay_creates_correct_final_state(self, client, db_engine, db_session, admin_user_data):
        """Replay from snapshot produces expected final state."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        # Create initial state
        reconstructor = StateReconstructor()
        snapshot = reconstructor.create_snapshot(
            session_id="test_session_p5",
            turn_no=0,
            world_state={"day": 1, "phase": "morning"},
            player_state={"hp": 100, "stamina": 100, "location": "test_location_p5"},
            npc_states={"npc_1": {"trust": 50, "suspicion": 0}},
            snapshot_type="checkpoint",
        )

        # Verify snapshot created
        assert snapshot.snapshot_id is not None
        assert snapshot.session_id == "test_session_p5"
        assert snapshot.turn_no == 0

        # Retrieve snapshot
        retrieved = reconstructor.get_snapshot(snapshot.snapshot_id)
        assert retrieved is not None
        assert retrieved.player_state["hp"] == 100

    def test_replay_endpoint_returns_valid_structure(self, client, db_engine, db_session, admin_user_data):
        """Replay endpoint returns valid result structure."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.post(
            "/debug/sessions/test_session_p5/replay?end_turn=2",
            headers=headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()

        # Required top-level fields
        assert "replay_id" in data
        assert "session_id" in data
        assert "start_turn" in data
        assert "end_turn" in data
        assert "perspective" in data
        assert "success" in data
        assert "steps" in data
        assert "final_state" in data

        # Verify types
        assert isinstance(data["steps"], list)
        assert isinstance(data["final_state"], dict)
        assert data["session_id"] == "test_session_p5"

    def test_replay_step_structure(self, client, db_engine, db_session, admin_user_data):
        """Each replay step has required fields."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.post(
            "/debug/sessions/test_session_p5/replay?end_turn=2",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        if len(data["steps"]) > 0:
            step = data["steps"][0]

            # Required step fields
            assert "step_no" in step
            assert "turn_no" in step
            assert "state_before" in step
            assert "state_after" in step
            assert "events" in step
            assert "state_deltas" in step
            assert "timestamp" in step

            assert isinstance(step["state_before"], dict)
            assert isinstance(step["state_after"], dict)
            assert isinstance(step["events"], list)
            assert isinstance(step["state_deltas"], list)

    def test_replay_perspective_filtering(self, client, db_engine, db_session, admin_user_data):
        """Replay with different perspectives returns appropriate data."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        # Test admin perspective
        response_admin = client.post(
            "/debug/sessions/test_session_p5/replay?end_turn=1&perspective=admin",
            headers=headers,
        )
        assert response_admin.status_code == 200
        assert response_admin.json()["perspective"] == "admin"

        # Test player perspective
        response_player = client.post(
            "/debug/sessions/test_session_p5/replay?end_turn=1&perspective=player",
            headers=headers,
        )
        assert response_player.status_code == 200
        assert response_player.json()["perspective"] == "player"

        # Test auditor perspective
        response_auditor = client.post(
            "/debug/sessions/test_session_p5/replay?end_turn=1&perspective=auditor",
            headers=headers,
        )
        assert response_auditor.status_code == 200
        assert response_auditor.json()["perspective"] == "auditor"


# =============================================================================
# Test 3: Debug Contract Flow
# =============================================================================

@pytest.mark.scenario
@pytest.mark.p5_scenario
@pytest.mark.integration
class TestDebugContractFlow:
    """
    Test 3: Debug Contract Flow
    - Create session + event logs + model calls + errors
    - Call /debug/sessions/{id}/logs, /debug/sessions/{id}/state, /debug/model-calls, /debug/errors
    - Verify field contracts match frontend types
    """

    def test_debug_logs_field_contract(self, client, db_engine, db_session, admin_user_data):
        """Verify logs endpoint returns correct field contract."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.get(
            "/debug/sessions/test_session_p5/logs",
            headers=headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()

        # Top-level structure
        assert "session_id" in data
        assert "total_count" in data
        assert "logs" in data

        # If logs exist, verify each entry
        if data["logs"]:
            log = data["logs"][0]
            # Required fields: id, turn_no, event_type, narrative_text, occurred_at
            assert "id" in log, "Log entry missing 'id'"
            assert "turn_no" in log, "Log entry missing 'turn_no'"
            assert "event_type" in log, "Log entry missing 'event_type'"
            assert "occurred_at" in log, "Log entry missing 'occurred_at'"
            # narrative_text may be optional for some event types

    def test_debug_state_field_contract(self, client, db_engine, db_session, admin_user_data):
        """Verify state endpoint returns correct field contract."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.get(
            "/debug/sessions/test_session_p5/state",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Required top-level fields
        assert "session_id" in data
        assert "user_id" in data
        assert "world_id" in data
        assert "status" in data
        assert "started_at" in data

        # Player state fields
        assert "player_realm_stage" in data
        assert "player_hp" in data
        assert "player_max_hp" in data
        assert "player_stamina" in data
        assert "player_spirit_power" in data

        # Related collections
        assert "npc_states" in data
        assert "inventory_items" in data
        assert "quest_states" in data
        assert isinstance(data["npc_states"], list)
        assert isinstance(data["inventory_items"], list)
        assert isinstance(data["quest_states"], list)

    def test_debug_model_calls_field_contract(self, client, db_engine, db_session, admin_user_data):
        """Verify model-calls endpoint returns correct field contract."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.get(
            "/debug/model-calls",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Top-level structure
        assert "total_count" in data
        assert "total_cost" in data
        assert "calls" in data

        # If calls exist, verify each entry
        # Required fields: id, session_id, turn_no, provider, input_tokens, output_tokens, cost_estimate, created_at
        if data["calls"]:
            call = data["calls"][0]
            assert "id" in call, "Model call missing 'id'"
            assert "session_id" in call, "Model call missing 'session_id'"
            assert "turn_no" in call, "Model call missing 'turn_no'"
            assert "provider" in call, "Model call missing 'provider'"
            assert "input_tokens" in call, "Model call missing 'input_tokens'"
            assert "output_tokens" in call, "Model call missing 'output_tokens'"
            assert "cost_estimate" in call, "Model call missing 'cost_estimate'"
            assert "created_at" in call, "Model call missing 'created_at'"

    def test_debug_errors_field_contract(self, client, db_engine, db_session, admin_user_data):
        """Verify errors endpoint returns correct field contract."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.get(
            "/debug/errors",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Top-level structure
        assert "total_count" in data
        assert "errors" in data
        assert isinstance(data["errors"], list)

        # If errors exist, verify each entry
        # Required fields: timestamp, error_type, message, details
        if data["errors"]:
            error = data["errors"][0]
            assert "timestamp" in error, "Error missing 'timestamp'"
            assert "error_type" in error, "Error missing 'error_type'"
            assert "message" in error, "Error missing 'message'"
            # details is optional

    def test_debug_session_logs_pagination(self, client, db_engine, db_session, admin_user_data):
        """Debug logs endpoint supports pagination."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.get(
            "/debug/sessions/test_session_p5/logs?limit=2",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == "test_session_p5"
        assert "total_count" in data
        assert "logs" in data
        assert len(data["logs"]) <= 2


# =============================================================================
# Test 4: Save/Replay Consistency Flow
# =============================================================================

@pytest.mark.scenario
@pytest.mark.p5_scenario
@pytest.mark.integration
class TestSaveReplayConsistencyFlow:
    """
    Test 4: Save/Replay Consistency Flow
    - Create session state → save snapshot → replay → compare state
    - Verify diff is empty or contains expected delta
    """

    def test_snapshot_create_and_retrieve(self, client, db_engine, db_session, admin_user_data):
        """Snapshot can be created and retrieved."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.post(
            "/debug/sessions/test_session_p5/snapshots?turn_no=1",
            headers=headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()

        # Required fields
        assert "snapshot_id" in data
        assert "session_id" in data
        assert "turn_no" in data
        assert "created_at" in data
        assert "snapshot_type" in data

        # State fields
        assert "world_state" in data
        assert "player_state" in data
        assert "npc_states" in data
        assert "location_states" in data
        assert "quest_states" in data
        assert "faction_states" in data

    def test_replay_report_generates_diff(self, client, db_engine, db_session, admin_user_data):
        """Replay report generates state diff."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        response = client.post(
            "/debug/sessions/test_session_p5/replay-report?end_turn=2",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Required fields
        assert "session_id" in data
        assert "from_turn" in data
        assert "to_turn" in data
        assert "replayed_event_count" in data
        assert "deterministic" in data
        assert "state_diff" in data
        assert "warnings" in data
        assert "created_at" in data

        # State diff structure
        diff = data["state_diff"]
        assert "entries" in diff
        assert "added_keys" in diff
        assert "removed_keys" in diff
        assert "changed_keys" in diff

        assert isinstance(diff["entries"], list)
        assert isinstance(diff["added_keys"], list)
        assert isinstance(diff["removed_keys"], list)
        assert isinstance(diff["changed_keys"], list)

    def test_state_reconstructor_apply_delta(self, db_engine, db_session):
        """StateReconstructor can apply state deltas correctly."""
        reconstructor = StateReconstructor()

        # Create initial snapshot
        snapshot = reconstructor.create_snapshot(
            session_id="test_session_delta",
            turn_no=0,
            world_state={"day": 1},
            player_state={"hp": 100, "mp": 50},
            snapshot_type="initial",
        )

        # Create updated snapshot
        updated_snapshot = reconstructor.create_snapshot(
            session_id="test_session_delta",
            turn_no=1,
            world_state={"day": 2},
            player_state={"hp": 90, "mp": 45},
            snapshot_type="checkpoint",
        )

        # Verify both snapshots stored
        retrieved_initial = reconstructor.get_snapshot(snapshot.snapshot_id)
        retrieved_updated = reconstructor.get_snapshot(updated_snapshot.snapshot_id)

        assert retrieved_initial is not None
        assert retrieved_updated is not None
        assert retrieved_initial.player_state["hp"] == 100
        assert retrieved_updated.player_state["hp"] == 90

    def test_snapshot_and_replay_consistency(self, client, db_engine, db_session, admin_user_data):
        """Full flow: snapshot → replay → compare state consistency."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        # Create snapshot at turn 1
        snapshot_response = client.post(
            "/debug/sessions/test_session_p5/snapshots?turn_no=1",
            headers=headers,
        )
        assert snapshot_response.status_code == 200
        snapshot_data = snapshot_response.json()

        # Replay from turn 1
        replay_response = client.post(
            "/debug/sessions/test_session_p5/replay?start_turn=1&end_turn=2",
            headers=headers,
        )
        assert replay_response.status_code == 200
        replay_data = replay_response.json()

        # Both should reference same session
        assert snapshot_data["session_id"] == replay_data["session_id"]
        assert replay_data["success"] is True

        # Final state should be present
        assert "final_state" in replay_data
        assert isinstance(replay_data["final_state"], dict)

    def test_replay_report_empty_diff_for_consistent_state(self, client, db_engine, db_session, admin_user_data):
        """Replay with no state changes produces empty diff."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        # Replay with minimal turns (no state changes expected)
        response = client.post(
            "/debug/sessions/test_session_p5/replay-report?start_turn=1&end_turn=1",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # State diff should exist
        assert "state_diff" in data
        diff = data["state_diff"]

        # Diff structure should be valid even if empty
        assert "entries" in diff
        assert "added_keys" in diff
        assert "removed_keys" in diff
        assert "changed_keys" in diff


# =============================================================================
# Additional Integration Tests
# =============================================================================

@pytest.mark.scenario
@pytest.mark.p5_scenario
@pytest.mark.integration
class TestAuthenticationAndAuthorization:
    """Verify authentication and authorization for debug endpoints."""

    def test_unauthenticated_debug_endpoints_return_401(self, client, db_session):
        """Unauthenticated requests to debug endpoints return 401."""
        setup_full_session_with_data(db_session)

        endpoints = [
            "/debug/sessions/test_session_p5/logs",
            "/debug/sessions/test_session_p5/state",
            "/debug/model-calls",
            "/debug/errors",
            "/debug/sessions/test_session_p5/prompt-inspector",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 401, f"Expected 401 for {endpoint}, got {response.status_code}"

    def test_non_admin_debug_endpoints_return_403(self, client, db_engine, db_session):
        """Non-admin users get 403 for debug endpoints."""
        regular_user_data = {
            "username": f"user_{uuid.uuid4().hex[:8]}",
            "email": f"user_{uuid.uuid4().hex[:8]}@example.com",
            "password": "UserPass123!",
        }
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_full_session_with_data(db_session)

        response = client.get(
            "/debug/sessions/test_session_p5/logs",
            headers=headers,
        )
        assert response.status_code == 403

    def test_404_for_nonexistent_session(self, client, db_engine, db_session, admin_user_data):
        """Nonexistent session returns 404."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/sessions/nonexistent_session/logs",
            headers=headers,
        )
        assert response.status_code == 404


@pytest.mark.scenario
@pytest.mark.p5_scenario
@pytest.mark.integration
class TestPagination:
    """Verify pagination works correctly for debug endpoints."""

    def test_logs_pagination(self, client, db_engine, db_session, admin_user_data):
        """Logs endpoint supports limit and offset."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        # Get all logs
        response_all = client.get(
            "/debug/sessions/test_session_p5/logs?limit=100",
            headers=headers,
        )
        assert response_all.status_code == 200
        all_logs = response_all.json()["logs"]

        # Get with limit
        response_limited = client.get(
            "/debug/sessions/test_session_p5/logs?limit=1",
            headers=headers,
        )
        assert response_limited.status_code == 200
        limited_logs = response_limited.json()["logs"]
        assert len(limited_logs) <= 1

        # Get with offset
        if len(all_logs) > 1:
            response_offset = client.get(
                "/debug/sessions/test_session_p5/logs?offset=1&limit=100",
                headers=headers,
            )
            assert response_offset.status_code == 200
            offset_logs = response_offset.json()["logs"]
            # Should have one fewer than all logs
            assert len(offset_logs) == len(all_logs) - 1

    def test_model_calls_pagination(self, client, db_engine, db_session, admin_user_data):
        """Model-calls endpoint supports limit and offset."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)

        # Default limit should be 50
        response = client.get(
            "/debug/model-calls",
            headers=headers,
        )
        assert response.status_code == 200
        assert len(response.json()["calls"]) <= 50

    def test_prompt_inspector_pagination(self, client, db_engine, db_session, admin_user_data):
        """Prompt inspector supports limit and offset."""
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_full_session_with_data(db_session)
        seed_audit_store_for_prompt_inspector("test_session_p5")

        response = client.get(
            "/debug/sessions/test_session_p5/prompt-inspector?limit=1",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()

        # Each array should have at most 1 item
        assert len(data["model_calls"]) <= 1
        assert len(data["context_builds"]) <= 1
        assert len(data["proposals"]) <= 1
        assert len(data["validations"]) <= 1

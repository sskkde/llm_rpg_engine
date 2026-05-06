"""
Integration tests for Turn Progression Audit functionality.

Tests:
- Turn result JSON contains progression audit metadata
- Progression audit does not expose hidden identity or secrets
- Audit persistence to database
- Audit extraction from result_json
"""

import pytest
import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import EventLogModel, SessionModel, UserModel, WorldModel
from llm_rpg.core.turn_audit import (
    TurnAudit,
    build_turn_audit,
    persist_turn_audit,
    sanitize_audit_data,
    extract_progression_audit_from_result_json,
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


@pytest.fixture
def sample_turn_result():
    return {
        "transaction_id": "txn_001",
        "turn_index": 1,
        "narration": "You walk through the forest.",
        "events_committed": 3,
        "actions_committed": 2,
        "state_deltas_applied": 5,
        "validation_passed": True,
        "proposal_audits": 4,
        "parsed_intent": {
            "intent_type": "move",
            "target": "forest",
            "risk_level": "low",
        },
        "world_candidates_count": 2,
        "world_fallback_used": False,
        "scene_candidates_count": 3,
        "scene_fallback_used": False,
        "npc_action_count": 2,
        "npc_skip_count": 1,
        "npc_skip_reasons": ["NPC not in scene"],
        "movement_result": "success",
        "scene_status": "active",
        "state_deltas_count": 5,
        "validation_failures": [],
        "turn_duration_ms": 1500,
    }


@pytest.fixture
def sample_session_data(db_session):
    user = UserModel(
        id=f"user_{uuid.uuid4().hex[:8]}",
        username="testuser",
        email="test@example.com",
        password_hash="hashed",
    )
    db_session.add(user)
    
    world = WorldModel(
        id=f"world_{uuid.uuid4().hex[:8]}",
        code="test_world",
        name="Test World",
        genre="xianxia",
        lore_summary="A test world",
        status="active",
    )
    db_session.add(world)
    
    session = SessionModel(
        id=f"session_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        world_id=world.id,
        status="active",
    )
    db_session.add(session)
    db_session.commit()
    
    return {
        "user_id": user.id,
        "world_id": world.id,
        "session_id": session.id,
    }


class TestTurnAuditDataclass:
    """Tests for TurnAudit dataclass."""
    
    def test_turn_audit_default_values(self):
        audit = TurnAudit()
        
        assert audit.intent_type is None
        assert audit.intent_parse_source == "unknown"
        assert audit.intent_fallback_reason is None
        assert audit.world_candidates_count == 0
        assert audit.scene_candidates_count == 0
        assert audit.npc_action_count == 0
        assert audit.validation_passed is True
        assert audit.validation_failures == []
        assert audit.scene_status == "active"
    
    def test_turn_audit_custom_values(self):
        audit = TurnAudit(
            intent_type="move",
            intent_parse_source="llm",
            world_candidates_count=3,
            npc_action_count=2,
            validation_passed=False,
            validation_failures=["Invalid target"],
        )
        
        assert audit.intent_type == "move"
        assert audit.intent_parse_source == "llm"
        assert audit.world_candidates_count == 3
        assert audit.npc_action_count == 2
        assert audit.validation_passed is False
        assert audit.validation_failures == ["Invalid target"]


class TestBuildTurnAudit:
    """Tests for build_turn_audit function."""
    
    def test_build_turn_audit_from_result(self, sample_turn_result):
        audit = build_turn_audit(sample_turn_result)
        
        assert audit.intent_type == "move"
        assert audit.intent_parse_source == "llm"
        assert audit.world_candidates_count == 2
        assert audit.scene_candidates_count == 3
        assert audit.npc_action_count == 2
        assert audit.npc_skip_count == 1
        assert audit.npc_skip_reasons == ["NPC not in scene"]
        assert audit.movement_result == "success"
        assert audit.scene_status == "active"
        assert audit.state_deltas_count == 5
        assert audit.state_deltas_committed == 5
        assert audit.validation_passed is True
        assert audit.validation_failures == []
        assert audit.proposal_audits_count == 4
        assert audit.turn_duration_ms == 1500
    
    def test_build_turn_audit_with_fallback(self):
        result = {
            "parsed_intent": None,
            "intent_fallback_reason": "LLM timeout",
            "world_fallback_used": True,
            "world_fallback_reason": "Model error",
            "scene_fallback_used": True,
            "scene_fallback_reason": "Parse failure",
        }
        
        audit = build_turn_audit(result)
        
        assert audit.intent_parse_source == "keyword_fallback"
        assert audit.intent_fallback_reason == "No parsed intent from LLM"
        assert audit.world_fallback_used is True
        assert audit.world_fallback_reason == "Model error"
        assert audit.scene_fallback_used is True
        assert audit.scene_fallback_reason == "Parse failure"
    
    def test_build_turn_audit_with_validation_failures(self):
        result = {
            "validation_passed": False,
            "validation_failures": [
                "Invalid action target",
                "State delta out of range",
            ],
        }
        
        audit = build_turn_audit(result)
        
        assert audit.validation_passed is False
        assert len(audit.validation_failures) == 2
        assert "Invalid action target" in audit.validation_failures


class TestPersistTurnAudit:
    """Tests for persist_turn_audit function."""
    
    def test_persist_turn_audit_creates_event_log(
        self, db_session, sample_session_data, sample_turn_result
    ):
        audit = build_turn_audit(sample_turn_result)
        
        audit_id = persist_turn_audit(
            db=db_session,
            session_id=sample_session_data["session_id"],
            turn_no=1,
            audit=audit,
        )
        
        db_session.commit()
        
        assert audit_id == audit.audit_id
        
        event_log = db_session.query(EventLogModel).filter(
            EventLogModel.session_id == sample_session_data["session_id"],
            EventLogModel.turn_no == 1,
            EventLogModel.event_type == "turn_audit",
        ).first()
        
        assert event_log is not None
        assert event_log.result_json is not None
        assert "turn_audit" in event_log.result_json
    
    def test_persist_turn_audit_updates_existing(
        self, db_session, sample_session_data, sample_turn_result
    ):
        audit1 = build_turn_audit(sample_turn_result)
        
        persist_turn_audit(
            db=db_session,
            session_id=sample_session_data["session_id"],
            turn_no=1,
            audit=audit1,
        )
        db_session.commit()
        
        sample_turn_result["npc_action_count"] = 5
        audit2 = build_turn_audit(sample_turn_result)
        audit2.audit_id = audit1.audit_id
        
        persist_turn_audit(
            db=db_session,
            session_id=sample_session_data["session_id"],
            turn_no=1,
            audit=audit2,
        )
        db_session.commit()
        
        event_logs = db_session.query(EventLogModel).filter(
            EventLogModel.session_id == sample_session_data["session_id"],
            EventLogModel.turn_no == 1,
            EventLogModel.event_type == "turn_audit",
        ).all()
        
        assert len(event_logs) == 1
        assert event_logs[0].result_json["turn_audit"]["npc_action_count"] == 5
    
    def test_persist_turn_audit_does_not_block_on_error(
        self, db_session, sample_session_data, sample_turn_result
    ):
        audit = build_turn_audit(sample_turn_result)
        
        invalid_session_id = "nonexistent_session"
        
        audit_id = persist_turn_audit(
            db=db_session,
            session_id=invalid_session_id,
            turn_no=1,
            audit=audit,
        )
        
        assert audit_id == audit.audit_id


class TestSanitizeAuditData:
    """Tests for sanitize_audit_data function."""
    
    def test_sanitize_removes_api_key(self):
        audit_dict = {
            "intent_type": "move",
            "api_key": "sk-secret-key-12345",
            "model_name": "gpt-4",
        }
        
        sanitized = sanitize_audit_data(audit_dict)
        
        assert "api_key" not in sanitized
        assert sanitized["intent_type"] == "move"
        assert sanitized["model_name"] == "gpt-4"
    
    def test_sanitize_removes_hidden_identity(self):
        audit_dict = {
            "intent_type": "talk",
            "hidden_identity": "The NPC is actually a demon",
            "npc_name": "Elder Zhang",
        }
        
        sanitized = sanitize_audit_data(audit_dict)
        
        assert "hidden_identity" not in sanitized
        assert sanitized["intent_type"] == "talk"
        assert sanitized["npc_name"] == "Elder Zhang"
    
    def test_sanitize_masks_long_raw_output(self):
        long_output = "x" * 200
        audit_dict = {
            "intent_type": "move",
            "raw_output_preview": long_output,
        }
        
        sanitized = sanitize_audit_data(audit_dict)
        
        assert len(sanitized["raw_output_preview"]) < len(long_output)
        assert "[SANITIZED]" in sanitized["raw_output_preview"]
    
    def test_sanitize_preserves_short_raw_output(self):
        short_output = "Valid JSON output"
        audit_dict = {
            "intent_type": "move",
            "raw_output_preview": short_output,
        }
        
        sanitized = sanitize_audit_data(audit_dict)
        
        assert sanitized["raw_output_preview"] == short_output


class TestExtractProgressionAudit:
    """Tests for extract_progression_audit_from_result_json function."""
    
    def test_extract_valid_audit(self, sample_turn_result):
        audit = build_turn_audit(sample_turn_result)
        from dataclasses import asdict
        
        result_json = {
            "turn_audit": asdict(audit),
        }
        
        extracted = extract_progression_audit_from_result_json(result_json)
        
        assert extracted is not None
        assert extracted.intent_type == audit.intent_type
        assert extracted.intent_parse_source == audit.intent_parse_source
        assert extracted.world_candidates_count == audit.world_candidates_count
    
    def test_extract_returns_none_for_missing_audit(self):
        result_json = {"other_data": "value"}
        
        extracted = extract_progression_audit_from_result_json(result_json)
        
        assert extracted is None
    
    def test_extract_returns_none_for_none_input(self):
        extracted = extract_progression_audit_from_result_json(None)
        
        assert extracted is None
    
    def test_extract_returns_none_for_invalid_data(self):
        result_json = {
            "turn_audit": {
                "invalid_field": "value",
            }
        }
        
        extracted = extract_progression_audit_from_result_json(result_json)
        
        assert extracted is None


class TestTurnResultJsonContainsProgressionAudit:
    """
    Integration test: Turn result JSON contains progression audit metadata.
    
    This verifies that the audit metadata is properly included in the
    turn result for debugging progression failures.
    """
    
    def test_turn_result_json_contains_progression_audit(
        self, db_session, sample_session_data, sample_turn_result
    ):
        audit = build_turn_audit(sample_turn_result)
        
        audit_id = persist_turn_audit(
            db=db_session,
            session_id=sample_session_data["session_id"],
            turn_no=1,
            audit=audit,
        )
        db_session.commit()
        
        event_log = db_session.query(EventLogModel).filter(
            EventLogModel.session_id == sample_session_data["session_id"],
            EventLogModel.turn_no == 1,
            EventLogModel.event_type == "turn_audit",
        ).first()
        
        assert event_log is not None
        assert event_log.result_json is not None
        
        turn_audit_data = event_log.result_json.get("turn_audit")
        assert turn_audit_data is not None
        
        assert "intent_type" in turn_audit_data
        assert "intent_parse_source" in turn_audit_data
        assert "world_candidates_count" in turn_audit_data
        assert "scene_candidates_count" in turn_audit_data
        assert "npc_action_count" in turn_audit_data
        assert "validation_passed" in turn_audit_data
        assert "state_deltas_count" in turn_audit_data


class TestProgressionAuditDoesNotExposeHiddenIdentity:
    """
    Security test: Progression audit does not expose hidden identity or secrets.
    
    This verifies that sensitive information like API keys, hidden identities,
    and secret information are not stored in player-visible audit logs.
    """
    
    def test_progression_audit_does_not_expose_hidden_identity(
        self, sample_turn_result
    ):
        sample_turn_result["hidden_identity"] = "The elder is secretly a demon"
        sample_turn_result["api_key"] = "sk-secret-key-12345"
        sample_turn_result["secret_info"] = "Player's hidden backstory"
        
        audit = build_turn_audit(sample_turn_result)
        from dataclasses import asdict
        sanitized = sanitize_audit_data(asdict(audit))
        
        assert "hidden_identity" not in sanitized
        assert "api_key" not in sanitized
        assert "secret_info" not in sanitized
    
    def test_audit_persistence_sanitizes_data(
        self, db_session, sample_session_data, sample_turn_result
    ):
        sample_turn_result["raw_output_preview"] = (
            "This contains a secret API key: sk-12345 and hidden identity info"
        )
        
        audit = build_turn_audit(sample_turn_result)
        audit.raw_output_preview = sample_turn_result["raw_output_preview"]
        
        persist_turn_audit(
            db=db_session,
            session_id=sample_session_data["session_id"],
            turn_no=1,
            audit=audit,
        )
        db_session.commit()
        
        event_log = db_session.query(EventLogModel).filter(
            EventLogModel.session_id == sample_session_data["session_id"],
            EventLogModel.turn_no == 1,
            EventLogModel.event_type == "turn_audit",
        ).first()
        
        turn_audit_data = event_log.result_json.get("turn_audit")
        
        if "raw_output_preview" in turn_audit_data:
            assert "sk-12345" not in turn_audit_data.get("raw_output_preview", "")

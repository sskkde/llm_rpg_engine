"""Tests for AuditStore full DB persistence (5 new audit types)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.core.audit import (
    AuditStore,
    ProposalAuditEntry,
    ContextBuildAudit,
    ValidationResultAudit,
    TurnAuditLog,
    ErrorLogEntry,
    ErrorSeverity,
    ValidationStatus,
)

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_persist_proposal_audit(db_session):
    store = AuditStore(db_session=db_session)
    audit = ProposalAuditEntry(
        audit_id="test-proposal-1",
        session_id="session-1",
        turn_no=1,
        proposal_type="narration",
    )
    store.store_proposal_audit(audit)

    assert store.get_proposal_audit("test-proposal-1") is not None

    from llm_rpg.storage.models import ProposalAuditLogModel
    db_record = db_session.query(ProposalAuditLogModel).filter_by(
        audit_id="test-proposal-1"
    ).first()
    assert db_record is not None
    assert db_record.session_id == "session-1"
    assert db_record.turn_no == 1
    assert db_record.proposal_type == "narration"
    assert db_record.payload_json is not None
    assert db_record.payload_json["proposal_type"] == "narration"


def test_persist_context_build_audit(db_session):
    store = AuditStore(db_session=db_session)
    audit = ContextBuildAudit(
        build_id="test-ctx-1",
        session_id="session-1",
        turn_no=2,
        perspective_type="player",
        perspective_id="player_view",
    )
    store.store_context_build(audit)

    assert store.get_context_build("test-ctx-1") is not None

    from llm_rpg.storage.models import ContextBuildAuditLogModel
    db_record = db_session.query(ContextBuildAuditLogModel).filter_by(
        build_id="test-ctx-1"
    ).first()
    assert db_record is not None
    assert db_record.session_id == "session-1"
    assert db_record.turn_no == 2
    assert db_record.perspective_type == "player"
    assert db_record.payload_json is not None
    assert db_record.payload_json["perspective_type"] == "player"


def test_persist_validation_audit(db_session):
    store = AuditStore(db_session=db_session)
    audit = ValidationResultAudit(
        validation_id="test-val-1",
        session_id="session-1",
        turn_no=3,
        validation_target="action",
        overall_status=ValidationStatus.PASSED,
    )
    store.store_validation(audit)

    assert store.get_validation("test-val-1") is not None

    from llm_rpg.storage.models import ValidationAuditLogModel
    db_record = db_session.query(ValidationAuditLogModel).filter_by(
        validation_id="test-val-1"
    ).first()
    assert db_record is not None
    assert db_record.session_id == "session-1"
    assert db_record.turn_no == 3
    assert db_record.validation_type == "action"
    assert db_record.payload_json is not None
    assert db_record.payload_json["validation_target"] == "action"


def test_persist_turn_audit(db_session):
    store = AuditStore(db_session=db_session)
    audit = TurnAuditLog(
        audit_id="test-turn-1",
        session_id="session-1",
        turn_no=4,
        transaction_id="tx-1",
        player_input="look around",
        world_time_before={"day": 1},
    )
    store.store_turn_audit(audit)

    assert store.get_turn_audit("test-turn-1") is not None

    from llm_rpg.storage.models import TurnAuditLogModel
    db_record = db_session.query(TurnAuditLogModel).filter_by(
        audit_id="test-turn-1"
    ).first()
    assert db_record is not None
    assert db_record.session_id == "session-1"
    assert db_record.turn_no == 4
    assert db_record.payload_json is not None
    assert db_record.payload_json["player_input"] == "look around"


def test_persist_error_audit(db_session):
    store = AuditStore(db_session=db_session)
    error = ErrorLogEntry(
        error_id="test-err-1",
        session_id="session-1",
        severity=ErrorSeverity.ERROR,
        error_type="ValueError",
        message="Something went wrong",
        component="test_component",
    )
    store.store_error(error)

    assert store.get_error("test-err-1") is not None

    from llm_rpg.storage.models import ErrorAuditLogModel
    db_record = db_session.query(ErrorAuditLogModel).filter_by(
        error_id="test-err-1"
    ).first()
    assert db_record is not None
    assert db_record.session_id == "session-1"
    assert db_record.error_type == "ValueError"
    assert db_record.payload_json is not None
    assert db_record.payload_json["message"] == "Something went wrong"


def test_persist_error_audit_no_session(db_session):
    store = AuditStore(db_session=db_session)
    error = ErrorLogEntry(
        error_id="test-err-2",
        session_id=None,
        severity=ErrorSeverity.CRITICAL,
        error_type="RuntimeError",
        message="No session",
        component="system",
    )
    store.store_error(error)

    from llm_rpg.storage.models import ErrorAuditLogModel
    db_record = db_session.query(ErrorAuditLogModel).filter_by(
        error_id="test-err-2"
    ).first()
    assert db_record is not None
    assert db_record.session_id is None
    assert db_record.error_type == "RuntimeError"


def test_persist_proposal_no_session(db_session):
    store = AuditStore(db_session=db_session)
    audit = ProposalAuditEntry(
        audit_id="test-proposal-2",
        session_id=None,
        turn_no=1,
        proposal_type="input_intent",
    )
    store.store_proposal_audit(audit)

    from llm_rpg.storage.models import ProposalAuditLogModel
    db_record = db_session.query(ProposalAuditLogModel).filter_by(
        audit_id="test-proposal-2"
    ).first()
    assert db_record is not None
    assert db_record.session_id is None


def test_no_persist_without_db_session():
    store = AuditStore(db_session=None)
    audit = ProposalAuditEntry(
        audit_id="test-no-db-1",
        session_id="session-1",
        turn_no=1,
        proposal_type="narration",
    )
    store.store_proposal_audit(audit)

    assert store.get_proposal_audit("test-no-db-1") is not None


def test_rollback_on_db_error(db_session):
    store = AuditStore(db_session=db_session)

    from llm_rpg.storage.models import ProposalAuditLogModel
    existing = ProposalAuditLogModel(
        audit_id="existing-1",
        session_id="session-1",
        turn_no=1,
        proposal_type="narration",
        payload_json={},
    )
    db_session.add(existing)
    db_session.commit()

    duplicate_audit = ProposalAuditEntry(
        audit_id="existing-1",
        session_id="session-2",
        turn_no=2,
        proposal_type="npc_action",
    )
    with pytest.raises(Exception):
        store.store_proposal_audit(duplicate_audit)

    db_record = db_session.query(ProposalAuditLogModel).filter_by(
        audit_id="existing-1"
    ).first()
    assert db_record.session_id == "session-1"

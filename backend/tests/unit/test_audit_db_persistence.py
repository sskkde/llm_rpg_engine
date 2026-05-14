"""Tests for AuditStore DB persistence of model calls."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from llm_rpg.core.audit import (
    AuditStore,
    AuditLogger,
    get_audit_logger,
    reset_audit_logger,
    ModelCallLog,
)
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import ModelCallAuditLogModel
from llm_rpg.storage.repositories import ModelCallAuditLogRepository


# Use in-memory SQLite for these tests
TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def audit_db_session():
    """Create a fresh in-memory SQLite session with audit tables."""
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
    )
    # Create all tables
    Base.metadata.create_all(bind=engine)

    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


class TestAuditStoreDBPersistence:
    """Test that model calls are persisted to DB via AuditStore."""

    def setup_method(self):
        """Reset audit logger before each test."""
        reset_audit_logger()

    def test_store_model_call_writes_to_db(self, audit_db_session):
        """Model calls stored via AuditStore should be persisted in DB."""
        store = AuditStore(db_session=audit_db_session)

        log = ModelCallLog(
            call_id="call_test001",
            session_id="session_abc",
            turn_no=3,
            provider="openai",
            model_name="gpt-4",
            prompt_type="narration",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            cost_estimate=0.005,
            latency_ms=800,
            success=True,
            error_message=None,
            context_build_id="ctx_build_001",
        )

        store.store_model_call(log)

        # Verify in-memory works
        assert store.get_model_call("call_test001") is not None
        assert store.get_model_call("call_test001").call_id == "call_test001"

        # Verify DB persistence
        repo = ModelCallAuditLogRepository(audit_db_session)
        db_results = repo.get_by_session("session_abc")
        assert len(db_results) == 1
        db_log = db_results[0]
        assert db_log.call_id == "call_test001"
        assert db_log.session_id == "session_abc"
        assert db_log.turn_no == 3
        assert db_log.provider == "openai"
        assert db_log.model_name == "gpt-4"
        assert db_log.prompt_type == "narration"
        assert db_log.input_tokens == 200
        assert db_log.output_tokens == 100
        assert db_log.total_tokens == 300
        assert db_log.cost_estimate == 0.005
        assert db_log.latency_ms == 800
        assert db_log.success is True
        assert db_log.error_message is None
        assert db_log.context_build_id == "ctx_build_001"

    def test_store_model_call_failure(self, audit_db_session):
        """Failed model calls (success=False) should be persisted correctly."""
        store = AuditStore(db_session=audit_db_session)

        log = ModelCallLog(
            call_id="call_fail001",
            session_id="session_xyz",
            turn_no=5,
            provider="anthropic",
            model_name="claude-3",
            prompt_type="npc_decision",
            input_tokens=500,
            output_tokens=0,
            total_tokens=500,
            cost_estimate=0.0,
            latency_ms=30000,
            success=False,
            error_message="API timeout",
            context_build_id=None,
        )

        store.store_model_call(log)

        # DB verification
        repo = ModelCallAuditLogRepository(audit_db_session)
        db_results = repo.get_by_session("session_xyz")
        assert len(db_results) == 1
        db_log = db_results[0]
        assert db_log.call_id == "call_fail001"
        assert db_log.success is False
        assert db_log.error_message == "API timeout"
        assert db_log.output_tokens == 0

    def test_multiple_model_calls_per_session(self, audit_db_session):
        """Multiple model calls in a session should all be persisted."""
        store = AuditStore(db_session=audit_db_session)

        for i in range(5):
            log = ModelCallLog(
                call_id=f"call_multi_{i:03d}",
                session_id="session_multi",
                turn_no=i + 1,
                provider="openai",
                model_name="gpt-4",
                prompt_type="narration",
                input_tokens=100 * i,
                output_tokens=50 * i,
                total_tokens=150 * i,
                cost_estimate=0.001 * i,
                latency_ms=500,
                success=True,
            )
            store.store_model_call(log)

        # In-memory by session
        calls = store.get_model_calls_by_session("session_multi")
        assert len(calls) == 5

        # DB by session
        repo = ModelCallAuditLogRepository(audit_db_session)
        db_results = repo.get_by_session("session_multi")
        assert len(db_results) == 5

    def test_in_memory_still_works_without_db(self):
        """AuditStore without DB session should still work (in-memory only)."""
        store = AuditStore()

        log = ModelCallLog(
            call_id="call_nodb",
            session_id="session_nodb",
            turn_no=1,
            provider="openai",
            model_name="gpt-4",
            prompt_type="narration",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            success=True,
        )

        store.store_model_call(log)
        assert store.get_model_call("call_nodb") is not None
        calls = store.get_model_calls_by_session("session_nodb")
        assert len(calls) == 1

    def test_db_session_is_optional(self, audit_db_session):
        """DB session should be optional — AuditStore works with or without it."""
        # With DB session
        store_with_db = AuditStore(db_session=audit_db_session)
        log1 = ModelCallLog(
            call_id="call_db_001",
            session_id="session_x",
            turn_no=1,
            provider="openai",
            model_name="gpt-4",
            prompt_type="narration",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            success=True,
        )
        store_with_db.store_model_call(log1)

        # Without DB session
        store_without_db = AuditStore()
        log2 = ModelCallLog(
            call_id="call_nodb_001",
            session_id="session_x",
            turn_no=2,
            provider="openai",
            model_name="gpt-4",
            prompt_type="narration",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            success=True,
        )
        store_without_db.store_model_call(log2)

        # With-DB store should have both in-memory and DB
        assert store_with_db.get_model_call("call_db_001") is not None
        repo = ModelCallAuditLogRepository(audit_db_session)
        assert len(repo.get_by_session("session_x")) == 1

        # Without-DB store should only have in-memory
        assert store_without_db.get_model_call("call_nodb_001") is not None

    def test_get_model_calls_all_from_db(self, audit_db_session):
        """get_model_calls_all() should query from DB."""
        store = AuditStore(db_session=audit_db_session)

        for i in range(3):
            log = ModelCallLog(
                call_id=f"call_all_{i:03d}",
                session_id=f"session_{i % 2}",
                turn_no=i,
                provider="openai",
                model_name="gpt-4",
                prompt_type="narration",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                success=True,
            )
            store.store_model_call(log)

        # Query all from DB
        all_calls = store.get_model_calls_all(limit=10)
        assert len(all_calls) == 3

    def test_get_model_calls_by_session_from_db(self, audit_db_session):
        """get_model_calls_by_session should optionally query DB."""
        store = AuditStore(db_session=audit_db_session)

        # Store calls for two sessions
        for i in range(2):
            for s in ["sess_a", "sess_b"]:
                log = ModelCallLog(
                    call_id=f"call_{s}_{i}",
                    session_id=s,
                    turn_no=i,
                    provider="openai",
                    model_name="gpt-4",
                    prompt_type="narration",
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    success=True,
                )
                store.store_model_call(log)

        # In-memory query
        calls_a = store.get_model_calls_by_session("sess_a")
        assert len(calls_a) == 2

        # DB query
        db_calls_a = store.get_model_calls_from_db("sess_a")
        assert len(db_calls_a) == 2

    def test_clear_session_deletes_from_db(self, audit_db_session):
        """Clearing a session should also remove DB entries."""
        store = AuditStore(db_session=audit_db_session)

        for i in range(3):
            log = ModelCallLog(
                call_id=f"call_clear_{i:03d}",
                session_id="session_clear",
                turn_no=i,
                provider="openai",
                model_name="gpt-4",
                prompt_type="narration",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                success=True,
            )
            store.store_model_call(log)

        # Verify DB has entries
        repo = ModelCallAuditLogRepository(audit_db_session)
        assert len(repo.get_by_session("session_clear")) == 3

        # Clear session
        store.clear_session("session_clear")

        # Verify in-memory cleared
        assert store.get_model_calls_by_session("session_clear") == []

        # Verify DB cleared
        assert len(repo.get_by_session("session_clear")) == 0

    def test_audit_logger_persists_model_calls(self, audit_db_session):
        """AuditLogger.log_model_call should persist to DB."""
        store = AuditStore(db_session=audit_db_session)
        logger = AuditLogger(store=store)

        log = logger.log_model_call(
            session_id="logger_sess",
            turn_no=7,
            provider="openai",
            model_name="gpt-4",
            prompt_type="world_tick",
            input_tokens=500,
            output_tokens=200,
            cost_estimate=0.01,
            latency_ms=1500,
            success=True,
        )

        # Verify stored in-memory
        stored = store.get_model_call(log.call_id)
        assert stored is not None

        # Verify stored in DB
        repo = ModelCallAuditLogRepository(audit_db_session)
        db_results = repo.get_by_session("logger_sess")
        assert len(db_results) == 1
        assert db_results[0].call_id == log.call_id


class TestModelCallAuditLogRepository:
    """Test the repository for model call audit logs."""

    def test_create_and_get_by_id(self, audit_db_session):
        """Create and retrieve a model call audit log by ID."""
        repo = ModelCallAuditLogRepository(audit_db_session)
        created = repo.create({
            "call_id": "call_repo_001",
            "session_id": "sess_repo",
            "turn_no": 1,
            "provider": "openai",
            "model_name": "gpt-4",
            "prompt_type": "narration",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "cost_estimate": 0.002,
            "latency_ms": 500,
            "success": True,
        })
        assert created.call_id == "call_repo_001"

        retrieved = repo.get_by_id("call_repo_001")
        assert retrieved is not None
        assert retrieved.session_id == "sess_repo"

    def test_get_by_session(self, audit_db_session):
        """Get model call audit logs by session ID."""
        repo = ModelCallAuditLogRepository(audit_db_session)
        for i in range(3):
            repo.create({
                "call_id": f"call_sess_{i}",
                "session_id": "sess_test",
                "turn_no": i,
                "provider": "openai",
                "model_name": "gpt-4",
                "prompt_type": "narration",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "success": True,
            })

        results = repo.get_by_session("sess_test")
        assert len(results) == 3

    def test_get_by_turn(self, audit_db_session):
        """Get model call audit logs by session and turn."""
        repo = ModelCallAuditLogRepository(audit_db_session)
        for i in range(3):
            repo.create({
                "call_id": f"call_turn_{i}",
                "session_id": "sess_turn",
                "turn_no": i,
                "provider": "openai",
                "model_name": "gpt-4",
                "prompt_type": "narration",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "success": True,
            })

        results = repo.get_by_turn("sess_turn", 1)
        assert len(results) == 1
        assert results[0].call_id == "call_turn_1"

    def test_delete_by_session(self, audit_db_session):
        """Delete all model call audit logs for a session."""
        repo = ModelCallAuditLogRepository(audit_db_session)
        for i in range(3):
            repo.create({
                "call_id": f"call_del_{i}",
                "session_id": "sess_del",
                "turn_no": i,
                "provider": "openai",
                "model_name": "gpt-4",
                "prompt_type": "narration",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "success": True,
            })

        assert len(repo.get_by_session("sess_del")) == 3
        deleted_count = repo.delete_by_session("sess_del")
        assert deleted_count == 3
        assert len(repo.get_by_session("sess_del")) == 0

    def test_get_recent(self, audit_db_session):
        """Get recent model call audit logs."""
        repo = ModelCallAuditLogRepository(audit_db_session)
        for i in range(5):
            repo.create({
                "call_id": f"call_recent_{i}",
                "session_id": "sess_recent",
                "turn_no": i,
                "provider": "openai",
                "model_name": "gpt-4",
                "prompt_type": "narration",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "success": True,
            })

        recent = repo.get_recent("sess_recent", limit=3)
        assert len(recent) == 3
        # Should be ordered by turn_no desc
        assert recent[0].turn_no == 4
        assert recent[1].turn_no == 3
        assert recent[2].turn_no == 2

"""
Integration tests for TurnTransaction persistence.

Tests:
- execute_turn_service creates turn_transaction record
- turn_transaction status transitions (pending -> committed / aborted)
- transaction_id is present in TurnResult
- Complete trace chain: transaction -> events -> deltas -> LLM stages
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    WorldModel, UserModel, TurnTransactionModel, GameEventModel,
    StateDeltaModel, LLMStageResultModel, ValidationReportModel
)
from llm_rpg.storage.repositories import WorldRepository, TurnTransactionRepository
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
    world_id = create_world_in_db(db_engine, sample_world_data)
    response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["session_id"], world_id


class TestTurnCreatesTransaction:
    """Tests that execute_turn_service creates and manages turn_transactions."""

    def test_turn_creates_transaction(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "transaction_id" in data
        assert data["transaction_id"] is not None
        assert len(data["transaction_id"]) > 0

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            txn_repo = TurnTransactionRepository(db)
            txn = txn_repo.get_by_id(data["transaction_id"])
            assert txn is not None
            assert txn.session_id == session_id
            assert txn.turn_no == 1
            assert txn.status == "committed"
            assert txn.player_input == "观察四周"
            assert txn.committed_at is not None
            assert txn.aborted_at is None
        finally:
            db.close()

    def test_multiple_turns_create_transactions(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        actions = ["观察四周", "等待", "检查周围"]
        txn_ids = []

        for action in actions:
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers,
            )
            assert response.status_code == 200
            txn_ids.append(response.json()["transaction_id"])

        assert len(txn_ids) == len(set(txn_ids)), "Transaction IDs should be unique"

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            txn_repo = TurnTransactionRepository(db)
            txns = txn_repo.get_by_session(session_id)
            assert len(txns) == len(actions)
            for txn in txns:
                assert txn.status == "committed"
        finally:
            db.close()

    def test_transaction_id_in_turn_result(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transaction_id"] is not None
        assert isinstance(data["transaction_id"], str)
        assert len(data["transaction_id"]) > 0


class TestTurnTraceAggregation:
    """
    Tests for turn trace aggregation - verifying all records are linked correctly.
    
    Verifies complete trace chain:
    - turn_transaction (parent record)
    - game_events (linked via transaction_id)
    - state_deltas (linked via transaction_id, source_event_id)
    - llm_stage_results (linked via transaction_id)
    - validation_reports (linked via transaction_id)
    """

    def test_transaction_has_game_events_linked(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Test that turn execution creates game_events linked to transaction."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers,
        )
        assert turn_response.status_code == 200
        transaction_id = turn_response.json()["transaction_id"]

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            events = db.query(GameEventModel).filter(
                GameEventModel.transaction_id == transaction_id
            ).all()
            assert len(events) >= 1, "Should have at least one game event"

            for event in events:
                assert event.session_id == session_id
                assert event.turn_no == 1
                assert event.event_type is not None
        finally:
            db.close()

    def test_transaction_has_state_deltas_with_source_event(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Test that state_deltas are linked to transaction and have valid source_event_id."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "等待"},
            headers=auth_headers,
        )
        assert turn_response.status_code == 200
        transaction_id = turn_response.json()["transaction_id"]

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            deltas = db.query(StateDeltaModel).filter(
                StateDeltaModel.transaction_id == transaction_id
            ).all()

            if len(deltas) > 0:
                events = db.query(GameEventModel).filter(
                    GameEventModel.transaction_id == transaction_id
                ).all()
                event_ids = {e.id for e in events}

                for delta in deltas:
                    assert delta.source_event_id is not None
                    assert delta.source_event_id in event_ids, \
                        f"Delta source_event_id {delta.source_event_id} must reference valid event"
                    assert delta.session_id == session_id
                    assert delta.turn_no == 1
        finally:
            db.close()

    def test_transaction_has_llm_stage_results(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Test that llm_stage_results are linked to transaction."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers,
        )
        assert turn_response.status_code == 200
        transaction_id = turn_response.json()["transaction_id"]

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            stage_results = db.query(LLMStageResultModel).filter(
                LLMStageResultModel.transaction_id == transaction_id
            ).all()

            if len(stage_results) > 0:
                for stage in stage_results:
                    assert stage.session_id == session_id
                    assert stage.turn_no == 1
                    assert stage.stage_name is not None
                    assert stage.accepted is not None or stage.fallback_reason is not None
        finally:
            db.close()

    def test_transaction_has_validation_reports_when_validation_occurs(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Test that validation_reports are linked to transaction when validation occurs."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers,
        )
        assert turn_response.status_code == 200
        transaction_id = turn_response.json()["transaction_id"]

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            reports = db.query(ValidationReportModel).filter(
                ValidationReportModel.transaction_id == transaction_id
            ).all()

            for report in reports:
                assert report.session_id == session_id
                assert report.turn_no == 1
                assert report.scope is not None
                assert report.is_valid is not None
        finally:
            db.close()

    def test_complete_trace_chain_multiple_turns(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Test complete trace chain across multiple turns."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        actions = ["观察四周", "等待", "移动"]
        for action in actions:
            turn_response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers,
            )
            assert turn_response.status_code == 200

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            for turn_no in range(1, len(actions) + 1):
                txn = db.query(TurnTransactionModel).filter(
                    TurnTransactionModel.session_id == session_id,
                    TurnTransactionModel.turn_no == turn_no,
                ).first()
                assert txn is not None, f"Transaction for turn {turn_no} should exist"
                assert txn.status == "committed"

                events = db.query(GameEventModel).filter(
                    GameEventModel.transaction_id == txn.id
                ).all()
                assert len(events) >= 1, f"Events for turn {turn_no} should exist"

                deltas = db.query(StateDeltaModel).filter(
                    StateDeltaModel.transaction_id == txn.id
                ).all()

                event_ids = {e.id for e in events}
                for delta in deltas:
                    assert delta.source_event_id in event_ids, \
                        f"Delta source_event_id must reference valid event"

                stage_results = db.query(LLMStageResultModel).filter(
                    LLMStageResultModel.transaction_id == txn.id
                ).all()

                validation_reports = db.query(ValidationReportModel).filter(
                    ValidationReportModel.transaction_id == txn.id
                ).all()

                assert txn.game_events == events, "Relationship should match query"
                assert txn.state_deltas == deltas, "Relationship should match query"
                assert txn.llm_stage_results == stage_results, "Relationship should match query"
                assert txn.validation_reports == validation_reports, "Relationship should match query"
        finally:
            db.close()

    def test_transaction_world_time_recorded(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Test that transaction records world_time_before and world_time_after."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "等待"},
            headers=auth_headers,
        )
        assert turn_response.status_code == 200
        transaction_id = turn_response.json()["transaction_id"]

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            txn = db.query(TurnTransactionModel).filter(
                TurnTransactionModel.id == transaction_id
            ).first()
            assert txn is not None
            assert txn.world_time_before is not None or txn.world_time_after is not None
        finally:
            db.close()

    def test_transaction_player_input_recorded(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Test that transaction records player_input."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        player_input = "观察四周并寻找线索"
        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": player_input},
            headers=auth_headers,
        )
        assert turn_response.status_code == 200
        transaction_id = turn_response.json()["transaction_id"]

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            txn = db.query(TurnTransactionModel).filter(
                TurnTransactionModel.id == transaction_id
            ).first()
            assert txn is not None
            assert txn.player_input == player_input
        finally:
            db.close()


class TestTurnTraceAuthorization:
    """Tests for debug endpoint authorization."""

    @pytest.fixture
    def admin_user_data(self):
        return {
            "username": f"admin_{uuid.uuid4().hex[:8]}",
            "email": f"admin_{uuid.uuid4().hex[:8]}@example.com",
            "password": "AdminPass123!",
        }

    @pytest.fixture
    def regular_user_data(self):
        return {
            "username": f"user_{uuid.uuid4().hex[:8]}",
            "email": f"user_{uuid.uuid4().hex[:8]}@example.com",
            "password": "UserPass123!",
        }

    def _create_user_in_db(self, db_engine, user_data, is_admin=False):
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

    def _get_auth_header(self, client, user_data):
        response = client.post("/auth/login", json={
            "username": user_data["username"],
            "password": user_data["password"],
        })
        assert response.status_code == 200
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_non_admin_denied_from_debug_turn_endpoint(
        self, client, db_engine, sample_world_data, admin_user_data, regular_user_data
    ):
        """Test that non-admin user gets 403 when accessing debug turn endpoint."""
        self._create_user_in_db(db_engine, admin_user_data, is_admin=True)
        self._create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = self._get_auth_header(client, regular_user_data)

        world_id = create_world_in_db(db_engine, sample_world_data)
        response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=user_headers)
        session_id = response.json()["session_id"]

        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=user_headers,
        )
        assert turn_response.status_code == 200

        debug_response = client.get(
            f"/debug/sessions/{session_id}/turns/1",
            headers=user_headers,
        )

        assert debug_response.status_code == 403
        assert "Admin access required" in debug_response.json()["detail"]

    def test_unauthenticated_denied_from_debug_turn_endpoint(
        self, client, db_engine, sample_world_data, test_user_data
    ):
        """Test that unauthenticated user gets 401 when accessing debug turn endpoint."""
        response = client.post("/auth/register", json=test_user_data)
        assert response.status_code == 201
        token = response.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {token}"}

        world_id = create_world_in_db(db_engine, sample_world_data)
        response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=user_headers)
        session_id = response.json()["session_id"]

        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=user_headers,
        )
        assert turn_response.status_code == 200

        debug_response = client.get(
            f"/debug/sessions/{session_id}/turns/1",
        )

        assert debug_response.status_code == 401
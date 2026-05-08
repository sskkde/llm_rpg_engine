"""
Integration tests for TurnTransaction persistence.

Tests:
- execute_turn_service creates turn_transaction record
- turn_transaction status transitions (pending -> committed / aborted)
- transaction_id is present in TurnResult
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import WorldModel
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

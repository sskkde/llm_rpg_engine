"""
Integration tests for admin audit API endpoints.
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel, SessionModel, WorldModel, EventLogModel,
    ModelCallAuditLogModel, ContextBuildAuditLogModel,
    ValidationAuditLogModel, ErrorAuditLogModel
)
from llm_rpg.storage.repositories import UserRepository
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
        user_repo = UserRepository(db)
        user = user_repo.create({
            "username": user_data["username"],
            "email": user_data["email"],
            "password_hash": pwd_context.hash(user_data["password"]),
            "is_admin": is_admin,
        })
        db.commit()
        return user.id
    finally:
        db.close()


def get_auth_header(client, user_data):
    response = client.post("/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"],
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_test_session(db_engine, user_id):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        world = WorldModel(code="test_world", name="Test World")
        db.add(world)
        db.commit()
        db.refresh(world)

        session = SessionModel(
            id=str(uuid.uuid4()),
            user_id=user_id,
            world_id=world.id,
            status="active"
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session.id
    finally:
        db.close()


def create_test_event_logs(db_engine, session_id, count=10):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        logs = []
        for i in range(count):
            log = EventLogModel(
                id=str(uuid.uuid4()),
                session_id=session_id,
                turn_no=i,
                event_type="player_turn" if i % 2 == 0 else "narration",
                narrative_text=f"Test narrative {i}",
                occurred_at=datetime.now()
            )
            db.add(log)
            logs.append(log)
        db.commit()
        return logs
    finally:
        db.close()


def create_test_model_calls(db_engine, session_id, count=5):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        calls = []
        for i in range(count):
            call = ModelCallAuditLogModel(
                call_id=str(uuid.uuid4()),
                session_id=session_id,
                turn_no=i,
                provider="openai",
                model_name="gpt-4",
                prompt_type="narration",
                input_tokens=100 + i,
                output_tokens=200 + i,
                total_tokens=300 + 2 * i,
                cost_estimate=0.01 * (i + 1),
                latency_ms=500 + i * 10,
                success=True
            )
            db.add(call)
            calls.append(call)
        db.commit()
        return calls
    finally:
        db.close()


def create_test_context_builds(db_engine, session_id, count=3):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        builds = []
        for i in range(count):
            build = ContextBuildAuditLogModel(
                build_id=str(uuid.uuid4()),
                session_id=session_id,
                turn_no=i,
                perspective_type="player",
                payload_json={"test": f"data_{i}"}
            )
            db.add(build)
            builds.append(build)
        db.commit()
        return builds
    finally:
        db.close()


def create_test_validations(db_engine, session_id, count=4):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        validations = []
        for i in range(count):
            validation = ValidationAuditLogModel(
                validation_id=str(uuid.uuid4()),
                session_id=session_id,
                turn_no=i,
                validation_type="narration_check",
                payload_json={"passed": True}
            )
            db.add(validation)
            validations.append(validation)
        db.commit()
        return validations
    finally:
        db.close()


def create_test_errors(db_engine, session_id, count=2):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        errors = []
        for i in range(count):
            error = ErrorAuditLogModel(
                error_id=str(uuid.uuid4()),
                session_id=session_id,
                error_type="validation_error",
                payload_json={"turn_no": i, "message": f"Error {i}"}
            )
            db.add(error)
            errors.append(error)
        db.commit()
        return errors
    finally:
        db.close()


class TestAdminAuditAuthorization:
    def test_non_admin_gets_403_on_logs(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        user_id = create_user_in_db(db_engine, regular_user_data, is_admin=False)
        session_id = create_test_session(db_engine, user_id)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs", headers=user_headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_non_admin_gets_403_on_model_calls(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        user_id = create_user_in_db(db_engine, regular_user_data, is_admin=False)
        session_id = create_test_session(db_engine, user_id)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/model-calls", headers=user_headers)
        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs")
        assert response.status_code == 401


class TestListSessionLogs:
    def test_list_session_logs_success(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=10)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] == 10
        assert len(data["items"]) == 10

    def test_pagination_respects_limit(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=100)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs?limit=10", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 100
        assert len(data["items"]) == 10

    def test_filter_by_event_type(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=10)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs?event_type=player_turn", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert all(item["event_type"] == "player_turn" for item in data["items"])

    def test_filter_by_turn_no(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=10)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs?turn_no=5", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert all(item["turn_no"] == 5 for item in data["items"])

    def test_session_not_found(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/audit/sessions/nonexistent-session/logs", headers=headers)
        assert response.status_code == 404


class TestListModelCalls:
    def test_list_model_calls_success(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_model_calls(db_engine, session_id, count=5)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/model-calls", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] == 5
        assert len(data["items"]) == 5

    def test_model_calls_no_api_keys_exposed(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_model_calls(db_engine, session_id, count=1)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/model-calls", headers=headers)
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert "api_key" not in item
            assert "secret" not in item


class TestListContextBuilds:
    def test_list_context_builds_success(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_context_builds(db_engine, session_id, count=3)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/context-builds", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3


class TestListValidations:
    def test_list_validations_success(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_validations(db_engine, session_id, count=4)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/validations", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 4
        assert len(data["items"]) == 4


class TestListErrors:
    def test_list_errors_success(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_errors(db_engine, session_id, count=2)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/errors", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_filter_errors_by_event_type(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_errors(db_engine, session_id, count=2)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/errors?event_type=validation_error", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert all(item["error_type"] == "validation_error" for item in data["items"])


class TestExportAuditData:
    def test_export_returns_data(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=5)
        create_test_model_calls(db_engine, session_id, count=3)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/export?session_id={session_id}", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 8

    def test_export_no_api_keys(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_model_calls(db_engine, session_id, count=1)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/export?session_id={session_id}", headers=headers)
        assert response.status_code == 200

        data = response.json()
        for entry in data:
            assert "api_key" not in entry.get("data", {})
            assert "secret" not in entry.get("data", {})

    def test_export_with_turn_range(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=10)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/export?session_id={session_id}&from_turn=3&to_turn=7", headers=headers)
        assert response.status_code == 200

        data = response.json()
        for entry in data:
            if entry["turn_no"] is not None:
                assert 3 <= entry["turn_no"] <= 7

    def test_export_jsonl_format(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=2)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/export?session_id={session_id}", headers=headers)
        assert response.status_code == 200

        data = response.json()
        for entry in data:
            assert "timestamp" in entry
            assert "event_type" in entry
            assert "turn_no" in entry
            assert "data" in entry


class TestPaginationLimits:
    def test_default_limit_50(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=100)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) == 50

    def test_max_limit_200(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)
        create_test_event_logs(db_engine, session_id, count=300)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs?limit=200", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) == 200

    def test_limit_over_max_returns_422(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        session_id = create_test_session(db_engine, admin_id)

        headers = get_auth_header(client, admin_user_data)

        response = client.get(f"/admin/audit/sessions/{session_id}/logs?limit=500", headers=headers)
        assert response.status_code == 422

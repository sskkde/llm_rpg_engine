"""Integration tests for Debug Asset Job API endpoints."""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel, WorldModel, SessionModel, SystemSettingsModel, AssetGenerationJobModel
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
        
        settings = db.query(SystemSettingsModel).first()
        if not settings:
            settings = SystemSettingsModel(
                id=1,
                debug_enabled=True,
                registration_enabled=True,
                maintenance_mode=False,
            )
            db.add(settings)
        else:
            settings.debug_enabled = True
        
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


def create_job_in_db(db: Session, job_id: str, status: str = "pending", session_id: str = None, asset_type: str = "portrait"):
    job = AssetGenerationJobModel(
        id=str(uuid.uuid4()),
        job_id=job_id,
        asset_type=asset_type,
        session_id=session_id,
        status=status,
        provider_name="mock",
        request_json={"prompt": "test"},
        attempt_count=0,
        max_attempts=3,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(job)
    db.commit()
    return job


def count_job_rows(db: Session) -> int:
    return db.query(func.count(AssetGenerationJobModel.id)).scalar()


class TestListAllAssetJobsDebug:
    def test_admin_can_list_jobs(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        create_job_in_db(db_session, "job-list-001", "pending")
        create_job_in_db(db_session, "job-list-002", "completed")
        
        response = client.get("/debug/assets/jobs", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["jobs"]) == 2

    def test_admin_gets_empty_list(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/assets/jobs", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["jobs"] == []

    def test_pagination_works(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        for i in range(15):
            create_job_in_db(db_session, f"job-page-{i:03d}", "pending")
        
        response = client.get("/debug/assets/jobs?skip=5&limit=10", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 15
        assert len(data["jobs"]) == 10

    def test_non_admin_forbidden(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        
        response = client.get("/debug/assets/jobs", headers=headers)
        
        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, client):
        response = client.get("/debug/assets/jobs")
        assert response.status_code == 401


class TestGetAssetJobDebug:
    def test_admin_can_get_job_detail(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        create_job_in_db(db_session, "job-detail-001", "processing", asset_type="scene")
        
        response = client.get("/debug/assets/jobs/job-detail-001", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "job-detail-001"
        assert data["asset_type"] == "scene"
        assert data["status"] == "processing"

    def test_admin_gets_404_for_nonexistent_job(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/assets/jobs/nonexistent-job-id", headers=headers)
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_non_admin_forbidden(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        
        create_job_in_db(db_session, "job-forbidden-001", "pending")
        
        response = client.get("/debug/assets/jobs/job-forbidden-001", headers=headers)
        
        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, client, db_session):
        create_job_in_db(db_session, "job-noauth-001", "pending")
        
        response = client.get("/debug/assets/jobs/job-noauth-001")
        
        assert response.status_code == 401


class TestListSessionAssetJobsDebug:
    def test_admin_can_list_session_jobs(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        world = WorldModel(
            id="world-session-jobs",
            code="test_world",
            name="Test World",
            status="active",
        )
        db_session.add(world)
        
        user = UserModel(
            id="user-session-jobs",
            username="session_jobs_user",
            email="session@test.com",
            password_hash="hashed",
            is_admin=True,
        )
        db_session.add(user)
        
        session = SessionModel(
            id="session-jobs-001",
            user_id="user-session-jobs",
            world_id="world-session-jobs",
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        create_job_in_db(db_session, "job-sess-001", "pending", session_id="session-jobs-001")
        create_job_in_db(db_session, "job-sess-002", "completed", session_id="session-jobs-001")
        create_job_in_db(db_session, "job-sess-003", "pending", session_id="other-session")
        
        response = client.get("/debug/sessions/session-jobs-001/asset-jobs", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2

    def test_admin_gets_404_for_nonexistent_session(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/sessions/nonexistent-session/asset-jobs", headers=headers)
        
        assert response.status_code == 404

    def test_non_admin_forbidden(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        
        world = WorldModel(
            id="world-session-forbidden",
            code="forbidden_world",
            name="Forbidden World",
            status="active",
        )
        db_session.add(world)
        
        user = UserModel(
            id="user-session-forbidden",
            username="forbidden_user",
            email="forbidden@test.com",
            password_hash="hashed",
            is_admin=False,
        )
        db_session.add(user)
        
        session = SessionModel(
            id="session-forbidden",
            user_id="user-session-forbidden",
            world_id="world-session-forbidden",
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        response = client.get("/debug/sessions/session-forbidden/asset-jobs", headers=headers)
        
        assert response.status_code == 403


class TestRetryAssetJobDebug:
    def test_admin_can_retry_failed_job(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        create_job_in_db(db_session, "job-retry-001", "failed")
        
        response = client.post("/debug/assets/jobs/job-retry-001/retry", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "job-retry-001"
        assert data["status"] == "pending"

    def test_retry_nonexistent_job_returns_404(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post("/debug/assets/jobs/nonexistent-job/retry", headers=headers)
        
        assert response.status_code == 404

    def test_retry_completed_job_returns_404(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        create_job_in_db(db_session, "job-retry-completed", "completed")
        
        response = client.post("/debug/assets/jobs/job-retry-completed/retry", headers=headers)
        
        assert response.status_code == 404

    def test_non_admin_forbidden(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        
        create_job_in_db(db_session, "job-retry-forbidden", "failed")
        
        response = client.post("/debug/assets/jobs/job-retry-forbidden/retry", headers=headers)
        
        assert response.status_code == 403


class TestCancelAssetJobDebug:
    def test_admin_can_cancel_pending_job(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        create_job_in_db(db_session, "job-cancel-001", "pending")
        
        response = client.post("/debug/assets/jobs/job-cancel-001/cancel", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "job-cancel-001"
        assert data["status"] == "cancelled"

    def test_cancel_nonexistent_job_returns_404(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post("/debug/assets/jobs/nonexistent-job/cancel", headers=headers)
        
        assert response.status_code == 404

    def test_cancel_completed_job_returns_404(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        create_job_in_db(db_session, "job-cancel-completed", "completed")
        
        response = client.post("/debug/assets/jobs/job-cancel-completed/cancel", headers=headers)
        
        assert response.status_code == 404

    def test_non_admin_forbidden(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        
        create_job_in_db(db_session, "job-cancel-forbidden", "pending")
        
        response = client.post("/debug/assets/jobs/job-cancel-forbidden/cancel", headers=headers)
        
        assert response.status_code == 403


class TestJobDebugReadOnly:
    def test_get_job_endpoints_preserve_row_counts(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        create_job_in_db(db_session, "job-readonly-001", "pending")
        
        rows_before = count_job_rows(db_session)
        
        response = client.get("/debug/assets/jobs", headers=headers)
        assert response.status_code == 200
        
        response = client.get("/debug/assets/jobs/job-readonly-001", headers=headers)
        assert response.status_code == 200
        
        rows_after = count_job_rows(db_session)
        assert rows_before == rows_after

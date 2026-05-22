"""
Integration tests for admin operations API endpoints (health and metrics).
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel
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


class TestHealthEndpointAuthorization:
    def test_non_admin_gets_403_on_health(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/health", headers=user_headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_unauthenticated_gets_401_on_health(self, client):
        response = client.get("/admin/health")
        assert response.status_code == 401

    def test_admin_can_access_health(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200


class TestHealthEndpointResponse:
    def test_health_returns_correct_json_shape(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "db" in data
        assert "redis" in data
        assert "provider" in data
        assert "uptime_seconds" in data

        assert "status" in data["db"]
        assert "status" in data["redis"]
        assert "status" in data["provider"]
        assert isinstance(data["uptime_seconds"], int)

    def test_health_db_status_ok(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["db"]["status"] == "ok"

    def test_health_redis_status(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["redis"]["status"] in ("ok", "error", "disabled")

    def test_health_provider_status(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["provider"]["status"] in ("ok", "warning", "error")

    def test_health_uptime_positive(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["uptime_seconds"] >= 0


class TestMetricsEndpointAuthorization:
    def test_non_admin_gets_403_on_metrics(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/metrics", headers=user_headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_unauthenticated_gets_401_on_metrics(self, client):
        response = client.get("/admin/metrics")
        assert response.status_code == 401

    def test_admin_can_access_metrics(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200


class TestMetricsEndpointResponse:
    def test_metrics_returns_correct_json_shape(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "api_latency" in data
        assert "llm_calls" in data
        assert "validator" in data
        assert "turns" in data
        assert "rate_limit" in data
        assert "sessions" in data

    def test_metrics_api_latency_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        latency = data["api_latency"]
        assert "avg_ms" in latency
        assert "p50_ms" in latency
        assert "p95_ms" in latency
        assert "p99_ms" in latency
        assert "count" in latency

    def test_metrics_llm_calls_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        llm = data["llm_calls"]
        assert "total_count" in llm
        assert "success_count" in llm
        assert "failure_count" in llm
        assert "failure_rate" in llm

    def test_metrics_validator_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        validator = data["validator"]
        assert "rejection_count" in validator
        assert "validation_count" in validator

    def test_metrics_turns_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        turns = data["turns"]
        assert "success_count" in turns
        assert "failure_count" in turns

    def test_metrics_rate_limit_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        rate_limit = data["rate_limit"]
        assert "hit_count" in rate_limit

    def test_metrics_sessions_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        sessions = data["sessions"]
        assert "active_count" in sessions

    def test_metrics_returns_db_backed_counts(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data["llm_calls"]["total_count"], int)
        assert isinstance(data["llm_calls"]["success_count"], int)
        assert isinstance(data["llm_calls"]["failure_count"], int)
        assert isinstance(data["llm_calls"]["failure_rate"], float)
        assert isinstance(data["validator"]["validation_count"], int)
        assert isinstance(data["validator"]["rejection_count"], int)
        assert isinstance(data["turns"]["success_count"], int)
        assert isinstance(data["turns"]["failure_count"], int)
        assert isinstance(data["rate_limit"]["hit_count"], int)
        assert isinstance(data["sessions"]["active_count"], int)

    def test_metrics_includes_asset_jobs(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "asset_jobs" in data
        asset_jobs = data["asset_jobs"]
        for key in ("pending", "processing", "completed", "failed", "dead_lettered"):
            assert key in asset_jobs
            assert isinstance(asset_jobs[key], int)

    def test_metrics_counts_rate_limit_hits(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        _seed_rate_limit_events(db_engine, allowed=False, count=3)
        _seed_rate_limit_events(db_engine, allowed=True, count=5)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["rate_limit"]["hit_count"] == 3

    def test_metrics_counts_active_sessions(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        _seed_sessions(db_engine, status="active", count=2)
        _seed_sessions(db_engine, status="completed", count=1)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["sessions"]["active_count"] == 2

    def test_metrics_counts_turn_success_failure(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        _seed_turn_transactions(db_engine, status="committed", count=4, turn_no_offset=0)
        _seed_turn_transactions(db_engine, status="rolled_back", count=1, turn_no_offset=4)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["turns"]["success_count"] == 4
        assert data["turns"]["failure_count"] == 1

    def test_metrics_counts_validation_reports(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        _seed_validation_reports(db_engine, is_valid=True, count=3, turn_no_offset=900)
        _seed_validation_reports(db_engine, is_valid=False, count=2, turn_no_offset=901)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["validator"]["validation_count"] == 5
        assert data["validator"]["rejection_count"] == 2

    def test_metrics_counts_asset_jobs(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        _seed_asset_jobs(db_engine, status="completed", count=5)
        _seed_asset_jobs(db_engine, status="failed", count=1)
        _seed_asset_jobs(db_engine, status="pending", count=2)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["asset_jobs"]["completed"] == 5
        assert data["asset_jobs"]["failed"] == 1
        assert data["asset_jobs"]["pending"] == 2

    def test_metrics_requires_admin(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/metrics", headers=user_headers)
        assert response.status_code == 403


def _seed_rate_limit_events(db_engine, allowed: bool, count: int):
    from llm_rpg.storage.models import AssetRateLimitEventModel
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        for i in range(count):
            event = AssetRateLimitEventModel(
                event_id=uuid.uuid4().hex,
                user_id=None,
                session_id=None,
                provider_name="mock",
                bucket_key=f"test-bucket-{uuid.uuid4().hex[:8]}",
                limit_type="per_user",
                allowed=allowed,
                limit_value=10,
                current_value=11 if not allowed else 5,
            )
            db.add(event)
        db.commit()
    finally:
        db.close()


def _ensure_test_session(db):
    from llm_rpg.storage.models import SessionModel, UserModel, WorldModel
    existing = db.query(SessionModel).first()
    if existing:
        return existing.id
    user = db.query(UserModel).first()
    if not user:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        user = UserModel(
            id=uuid.uuid4().hex,
            username=f"test_session_owner_{uuid.uuid4().hex[:8]}",
            email=f"test_session_owner_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=pwd_context.hash("Password123!"),
            is_admin=False,
        )
        db.add(user)
        db.flush()
    world = db.query(WorldModel).first()
    if not world:
        world = WorldModel(
            id=uuid.uuid4().hex,
            code=f"test_world_{uuid.uuid4().hex[:8]}",
            name="Test World",
        )
        db.add(world)
        db.flush()
    session = SessionModel(
        id=uuid.uuid4().hex,
        user_id=user.id,
        world_id=world.id,
        status="active",
        started_at=datetime.utcnow(),
        last_played_at=datetime.utcnow(),
    )
    db.add(session)
    db.flush()
    return session.id


def _seed_sessions(db_engine, status: str, count: int):
    from llm_rpg.storage.models import SessionModel, UserModel, WorldModel
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        user = db.query(UserModel).first()
        if not user:
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            user = UserModel(
                id=uuid.uuid4().hex,
                username=f"session_owner_{uuid.uuid4().hex[:8]}",
                email=f"session_owner_{uuid.uuid4().hex[:8]}@example.com",
                password_hash=pwd_context.hash("Password123!"),
                is_admin=False,
            )
            db.add(user)
            db.flush()
        world = db.query(WorldModel).first()
        if not world:
            world = WorldModel(
                id=uuid.uuid4().hex,
                code=f"test_world_{uuid.uuid4().hex[:8]}",
                name="Test World",
            )
            db.add(world)
            db.flush()
        for i in range(count):
            session = SessionModel(
                id=uuid.uuid4().hex,
                user_id=user.id,
                world_id=world.id,
                status=status,
                started_at=datetime.utcnow(),
                last_played_at=datetime.utcnow(),
            )
            db.add(session)
        db.commit()
    finally:
        db.close()


def _seed_turn_transactions(db_engine, status: str, count: int, turn_no_offset: int = 0):
    from llm_rpg.storage.models import TurnTransactionModel
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        session_id = _ensure_test_session(db)
        for i in range(count):
            txn = TurnTransactionModel(
                session_id=session_id,
                turn_no=turn_no_offset + i + 1,
                idempotency_key=uuid.uuid4().hex,
                status=status,
                started_at=datetime.utcnow(),
                committed_at=datetime.utcnow() if status == "committed" else None,
                aborted_at=datetime.utcnow() if status == "rolled_back" else None,
            )
            db.add(txn)
        db.commit()
    finally:
        db.close()


def _seed_validation_reports(db_engine, is_valid: bool, count: int, turn_no_offset: int = 900):
    from llm_rpg.storage.models import ValidationReportModel, TurnTransactionModel
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        session_id = _ensure_test_session(db)
        turn_no = turn_no_offset
        txn = TurnTransactionModel(
            session_id=session_id,
            turn_no=turn_no,
            idempotency_key=uuid.uuid4().hex,
            status="committed",
            started_at=datetime.utcnow(),
            committed_at=datetime.utcnow(),
        )
        db.add(txn)
        db.flush()
        for i in range(count):
            report = ValidationReportModel(
                transaction_id=txn.id,
                session_id=session_id,
                turn_no=turn_no,
                scope="state_delta",
                is_valid=is_valid,
                created_at=datetime.utcnow(),
            )
            db.add(report)
        db.commit()
    finally:
        db.close()


def _seed_asset_jobs(db_engine, status: str, count: int):
    from llm_rpg.storage.models import AssetGenerationJobModel
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        for i in range(count):
            job = AssetGenerationJobModel(
                job_id=uuid.uuid4().hex,
                asset_type="portrait",
                status=status,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(job)
        db.commit()
    finally:
        db.close()

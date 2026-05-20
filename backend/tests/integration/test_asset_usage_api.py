"""Integration tests for Debug Asset Usage API endpoints."""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel, WorldModel, SessionModel, SystemSettingsModel,
    AssetUsageLogModel, AssetGenerationJobModel,
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


def create_session_in_db(db_engine, session_id, user_id):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        world = db.query(WorldModel).first()
        if not world:
            world = WorldModel(
                id=str(uuid.uuid4()),
                code="test-world",
                name="Test World",
            )
            db.add(world)
            db.commit()
            db.refresh(world)

        session = SessionModel(
            id=session_id,
            user_id=user_id,
            world_id=world.id,
            status="active",
        )
        db.add(session)
        db.commit()
        return session
    finally:
        db.close()


def create_usage_log_in_db(db_engine, **kwargs):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        log = AssetUsageLogModel(
            id=str(uuid.uuid4()),
            usage_id=kwargs.get("usage_id", str(uuid.uuid4())),
            job_id=kwargs.get("job_id"),
            asset_id=kwargs.get("asset_id"),
            session_id=kwargs.get("session_id"),
            user_id=kwargs.get("user_id"),
            provider_name=kwargs.get("provider_name", "mock"),
            asset_type=kwargs.get("asset_type", "portrait"),
            operation=kwargs.get("operation", "generate"),
            estimated_cost_usd=kwargs.get("estimated_cost_usd"),
            actual_cost_usd=kwargs.get("actual_cost_usd"),
            currency="USD",
            status=kwargs.get("status", "completed"),
            metadata_json=kwargs.get("metadata_json", {}),
            created_at=kwargs.get("created_at", datetime.now()),
        )
        db.add(log)
        db.commit()
        return log
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


@pytest.fixture
def admin_user_data():
    return {
        "username": f"admin_{uuid.uuid4().hex[:8]}",
        "email": f"admin_{uuid.uuid4().hex[:8]}@example.com",
        "password": "AdminPass123!",
    }


class TestListAssetUsage:
    def test_list_asset_usage_returns_paginated(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        for i in range(3):
            create_usage_log_in_db(
                db_engine,
                usage_id=f"usage-{i}",
                provider_name="mock",
                estimated_cost_usd=0.01 * (i + 1),
            )

        response = client.get(
            "/debug/assets/usage?limit=2&skip=0",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2

    def test_list_asset_usage_filters_by_session(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        create_usage_log_in_db(
            db_engine,
            usage_id="usage-session-a",
            session_id="session-a",
        )
        create_usage_log_in_db(
            db_engine,
            usage_id="usage-session-b",
            session_id="session-b",
        )

        response = client.get(
            "/debug/assets/usage?session_id=session-a",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["session_id"] == "session-a"

    def test_list_asset_usage_requires_admin(self, client, db_engine, admin_user_data):
        response = client.get("/debug/assets/usage")
        assert response.status_code == 401


class TestGetUsageSummary:
    def test_get_usage_summary_aggregates(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        for i in range(3):
            create_usage_log_in_db(
                db_engine,
                usage_id=f"usage-summary-{i}",
                estimated_cost_usd=0.01,
                actual_cost_usd=0.02,
            )

        response = client.get(
            "/debug/assets/usage/summary",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_estimated"] == 0.03
        assert data["total_actual"] == 0.06
        assert data["count"] == 3

    def test_get_usage_summary_filters_by_provider(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        create_usage_log_in_db(
            db_engine,
            usage_id="usage-p-mock",
            provider_name="mock",
            actual_cost_usd=0.01,
        )
        create_usage_log_in_db(
            db_engine,
            usage_id="usage-p-openai",
            provider_name="openai_image",
            actual_cost_usd=0.05,
        )

        response = client.get(
            "/debug/assets/usage/summary?provider_name=mock",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["total_actual"] == 0.01


class TestGetSessionAssetUsage:
    def test_get_session_asset_usage_returns_logs(self, client, db_engine, admin_user_data):
        admin_id = create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        create_session_in_db(db_engine, "session-usage-test", admin_id)

        for i in range(2):
            create_usage_log_in_db(
                db_engine,
                usage_id=f"usage-session-{i}",
                session_id="session-usage-test",
            )

        response = client.get(
            "/debug/sessions/session-usage-test/asset-usage",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_get_session_asset_usage_404_for_nonexistent_session(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/sessions/nonexistent-session/asset-usage",
            headers=headers,
        )

        assert response.status_code == 404


class TestListAssetProviders:
    def test_list_asset_providers_returns_capabilities(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/assets/providers",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        provider_names = [p["provider_name"] for p in data["providers"]]
        assert "mock" in provider_names

    def test_list_asset_providers_requires_admin(self, client):
        response = client.get("/debug/assets/providers")
        assert response.status_code == 401


class TestGetProviderHealth:
    def test_get_provider_health_returns_status(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/assets/providers/mock/health",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["provider_name"] == "mock"
        assert "configured" in data
        assert "enabled" in data

    def test_get_provider_health_unknown_provider(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/assets/providers/unknown_provider/health",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["provider_name"] == "unknown_provider"
        assert data["configured"] is False
        assert data["last_error"] is not None

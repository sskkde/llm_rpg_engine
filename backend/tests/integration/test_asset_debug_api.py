"""
Integration tests for asset debug API endpoints.

Tests that asset debug GET endpoints:
- Return proper 200/404/empty states for admin users
- Return 401 for unauthenticated requests
- Return 403 for non-admin authenticated requests
- Do NOT modify database state (read-only verification)
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel, WorldModel, SessionModel, AssetModel
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


def setup_test_session_with_assets(db: Session):
    """Create a test session with assets for testing."""
    world = WorldModel(
        id="test_world_assets",
        code="assets_world",
        name="Assets Test World",
        genre="xianxia",
        lore_summary="Test world for asset debug",
        status="active",
    )
    db.add(world)

    user = UserModel(
        id="test_user_assets",
        username="assets_test_user",
        email="assets@test.com",
        password_hash="hashed",
        is_admin=True,
    )
    db.add(user)

    session = SessionModel(
        id="test_session_assets",
        user_id="test_user_assets",
        world_id="test_world_assets",
        status="active",
    )
    db.add(session)

    asset1 = AssetModel(
        id="test_asset_1",
        asset_id="asset-debug-001",
        asset_type="portrait",
        status="completed",
        session_id="test_session_assets",
        owner_entity_id="npc_001",
        owner_entity_type="npc",
        provider_name="mock",
        cache_key="cache_key_001",
        result_url="https://example.com/portrait1.png",
        created_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db.add(asset1)

    asset2 = AssetModel(
        id="test_asset_2",
        asset_id="asset-debug-002",
        asset_type="scene",
        status="failed",
        session_id="test_session_assets",
        owner_entity_id="loc_001",
        owner_entity_type="location",
        provider_name="mock",
        error_message="Provider error",
        created_at=datetime(2024, 1, 1, 0, 1, 0),
    )
    db.add(asset2)

    asset3 = AssetModel(
        id="test_asset_3",
        asset_id="asset-debug-003",
        asset_type="portrait",
        status="processing",
        session_id="test_session_assets",
        owner_entity_id="npc_002",
        owner_entity_type="npc",
        provider_name="openai",
        created_at=datetime(2024, 1, 1, 0, 2, 0),
    )
    db.add(asset3)

    db.commit()

    return {
        "session_id": "test_session_assets",
        "world_id": "test_world_assets",
        "user_id": "test_user_assets",
        "asset_ids": ["asset-debug-001", "asset-debug-002", "asset-debug-003"],
    }


def count_asset_rows(db: Session) -> int:
    return db.query(func.count(AssetModel.id)).scalar()


class TestListSessionAssetsDebug:
    """Test GET /debug/sessions/{session_id}/assets endpoint."""

    def test_admin_can_list_session_assets(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_assets(db_session)

        rows_before = count_asset_rows(db_session)

        response = client.get(
            "/debug/sessions/test_session_assets/assets",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3

        asset_ids = [a["asset_id"] for a in data]
        assert "asset-debug-001" in asset_ids
        assert "asset-debug-002" in asset_ids
        assert "asset-debug-003" in asset_ids

        rows_after = count_asset_rows(db_session)
        assert rows_before == rows_after

    def test_admin_can_filter_by_asset_type(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_assets(db_session)

        response = client.get(
            "/debug/sessions/test_session_assets/assets?asset_type=portrait",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        for asset in data:
            assert asset["asset_type"] == "portrait"

    def test_admin_gets_empty_list_for_nonexistent_session(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/sessions/nonexistent_session/assets",
            headers=headers
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_admin_gets_empty_list_for_session_with_no_assets(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        world = WorldModel(
            id="test_world_empty",
            code="empty_world",
            name="Empty World",
            genre="xianxia",
            lore_summary="Empty",
            status="active",
        )
        db_session.add(world)

        user = UserModel(
            id="test_user_empty",
            username="empty_user",
            email="empty@test.com",
            password_hash="hashed",
            is_admin=True,
        )
        db_session.add(user)

        session = SessionModel(
            id="test_session_empty",
            user_id="test_user_empty",
            world_id="test_world_empty",
            status="active",
        )
        db_session.add(session)
        db_session.commit()

        response = client.get(
            "/debug/sessions/test_session_empty/assets",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_non_admin_forbidden_from_listing_assets(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_test_session_with_assets(db_session)

        response = client.get(
            "/debug/sessions/test_session_assets/assets",
            headers=headers
        )

        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()

    def test_unauthenticated_gets_401(self, client, db_session):
        setup_test_session_with_assets(db_session)

        response = client.get("/debug/sessions/test_session_assets/assets")

        assert response.status_code == 401


class TestGetAssetDebug:
    """Test GET /debug/assets/{asset_id} endpoint."""

    def test_admin_can_get_asset_detail(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_assets(db_session)

        rows_before = count_asset_rows(db_session)

        response = client.get(
            "/debug/assets/asset-debug-001",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["asset_id"] == "asset-debug-001"
        assert data["asset_type"] == "portrait"
        assert data["generation_status"] == "completed"
        assert data["provider"] == "mock"
        assert data["result_url"] == "https://example.com/portrait1.png"

        rows_after = count_asset_rows(db_session)
        assert rows_before == rows_after

    def test_admin_can_get_failed_asset_detail(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_assets(db_session)

        response = client.get(
            "/debug/assets/asset-debug-002",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["asset_id"] == "asset-debug-002"
        assert data["generation_status"] == "failed"
        assert data["error_message"] == "Provider error"

    def test_admin_gets_404_for_nonexistent_asset(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get(
            "/debug/assets/nonexistent-asset",
            headers=headers
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_non_admin_forbidden_from_asset_detail(self, client, db_engine, db_session, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)
        setup_test_session_with_assets(db_session)

        response = client.get(
            "/debug/assets/asset-debug-001",
            headers=headers
        )

        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, client, db_session):
        setup_test_session_with_assets(db_session)

        response = client.get("/debug/assets/asset-debug-001")

        assert response.status_code == 401


class TestAssetDebugReadOnly:
    """Verify asset debug endpoints are read-only."""

    def test_get_asset_endpoints_preserve_row_counts(self, client, db_engine, db_session, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        setup_test_session_with_assets(db_session)

        endpoints = [
            "/debug/sessions/test_session_assets/assets",
            "/debug/assets/asset-debug-001",
            "/debug/assets/asset-debug-002",
        ]

        for endpoint in endpoints:
            rows_before = count_asset_rows(db_session)

            response = client.get(endpoint, headers=headers)

            assert response.status_code in [200, 404], f"Endpoint {endpoint} returned unexpected status"

            rows_after = count_asset_rows(db_session)
            assert rows_before == rows_after, f"Endpoint {endpoint} modified database state"

"""
Integration tests for media endpoints.

Verifies that media generation endpoints are implemented (P6),
require authentication, and validate request schemas.
"""

import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.main import app
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel


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


class TestMediaEndpointsAuth:
    """Test that media endpoints require authentication."""

    def test_portrait_generate_requires_auth(self, client):
        response = client.post(
            "/media/portraits/generate",
            json={"npc_id": "test-npc-id", "style": "anime", "expression": "neutral"}
        )
        assert response.status_code == 401

    def test_scene_generate_requires_auth(self, client):
        response = client.post(
            "/media/scenes/generate",
            json={"location_id": "test-location-id", "time_of_day": "day"}
        )
        assert response.status_code == 401

    def test_bgm_generate_requires_auth(self, client):
        response = client.post(
            "/media/bgm/generate",
            json={"mood": "tense", "duration_seconds": 60}
        )
        assert response.status_code == 401


class TestMediaEndpointContract:
    """Test that media endpoints validate request schemas."""

    def test_portrait_generate_rejects_missing_npc_id(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        invalid_request = {
            "style": "anime",
            "expression": "happy"
        }
        response = client.post("/media/portraits/generate", json=invalid_request, headers=headers)
        assert response.status_code == 422

    def test_scene_generate_rejects_missing_location_id(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        invalid_request = {
            "time_of_day": "day"
        }
        response = client.post("/media/scenes/generate", json=invalid_request, headers=headers)
        assert response.status_code == 422

    def test_bgm_generate_rejects_missing_mood(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        invalid_request = {
            "duration_seconds": 60
        }
        response = client.post("/media/bgm/generate", json=invalid_request, headers=headers)
        assert response.status_code == 422

    def test_bgm_generate_rejects_invalid_duration(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        invalid_request = {
            "mood": "tense",
            "duration_seconds": 5
        }
        response = client.post("/media/bgm/generate", json=invalid_request, headers=headers)
        assert response.status_code == 422

    def test_bgm_generate_rejects_excessive_duration(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        invalid_request = {
            "mood": "tense",
            "duration_seconds": 500
        }
        response = client.post("/media/bgm/generate", json=invalid_request, headers=headers)
        assert response.status_code == 422


class TestMediaEndpointIsolation:
    """Test that media endpoints are isolated from game logic."""

    def test_media_does_not_affect_world_state(self, client):
        response = client.get("/world/state")
        assert response.status_code == 404

    def test_media_does_not_affect_docs(self, client):
        response = client.get("/docs")
        assert response.status_code == 200

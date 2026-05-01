"""
Integration tests for authentication and save functionality.
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import WorldModel
from llm_rpg.storage.repositories import WorldRepository
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
def sample_world_data():
    return {
        "code": f"test_world_{uuid.uuid4().hex[:8]}",
        "name": "Test World",
        "genre": "xianxia",
        "lore_summary": "A test world for integration tests",
        "status": "active",
    }


@pytest.fixture
def test_user_data():
    return {
        "username": f"testuser_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePass123!",
    }


@pytest.fixture
def second_user_data():
    return {
        "username": f"user2_{uuid.uuid4().hex[:8]}",
        "email": f"user2_{uuid.uuid4().hex[:8]}@example.com",
        "password": "AnotherPass123!",
    }


def create_world_in_db(db_engine, world_data):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        world_repo = WorldRepository(db)
        world = world_repo.create(world_data)
        db.commit()
        world_id = world.id
        return world_id
    finally:
        db.close()


@pytest.fixture
def auth_headers(client, test_user_data):
    response = client.post("/auth/register", json=test_user_data)
    assert response.status_code == 201, f"Registration failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user_auth_headers(client, second_user_data):
    response = client.post("/auth/register", json=second_user_data)
    assert response.status_code == 201, f"Registration failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuthRegistration:
    def test_register_user_success(self, client, test_user_data):
        response = client.post("/auth/register", json=test_user_data)
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["username"] == test_user_data["username"]
        assert data["user"]["email"] == test_user_data["email"]
        assert "password" not in data["user"]
        assert "password_hash" not in data["user"]

    def test_register_duplicate_username(self, client, test_user_data):
        response1 = client.post("/auth/register", json=test_user_data)
        assert response1.status_code == 201
        
        duplicate_data = test_user_data.copy()
        duplicate_data["email"] = f"other_{uuid.uuid4().hex[:8]}@example.com"
        response2 = client.post("/auth/register", json=duplicate_data)
        assert response2.status_code == 409
        assert "already registered" in response2.json()["detail"].lower()

    def test_register_duplicate_email(self, client, test_user_data):
        response1 = client.post("/auth/register", json=test_user_data)
        assert response1.status_code == 201
        
        duplicate_data = test_user_data.copy()
        duplicate_data["username"] = f"other_{uuid.uuid4().hex[:8]}"
        response2 = client.post("/auth/register", json=duplicate_data)
        assert response2.status_code == 409
        assert "already registered" in response2.json()["detail"].lower()

    def test_register_weak_password(self, client, test_user_data):
        weak_data = test_user_data.copy()
        weak_data["password"] = "123"
        response = client.post("/auth/register", json=weak_data)
        assert response.status_code == 422


class TestAuthLogin:
    def test_login_success(self, client, test_user_data):
        register_response = client.post("/auth/register", json=test_user_data)
        assert register_response.status_code == 201
        
        login_data = {
            "username": test_user_data["username"],
            "password": test_user_data["password"],
        }
        response = client.post("/auth/login", json=login_data)
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["username"] == test_user_data["username"]

    def test_login_invalid_password(self, client, test_user_data):
        client.post("/auth/register", json=test_user_data)
        
        login_data = {
            "username": test_user_data["username"],
            "password": "wrongpassword",
        }
        response = client.post("/auth/login", json=login_data)
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        login_data = {
            "username": "nonexistentuser12345",
            "password": "somepassword",
        }
        response = client.post("/auth/login", json=login_data)
        assert response.status_code == 401


class TestAuthMe:
    def test_get_current_user(self, client, test_user_data):
        register_response = client.post("/auth/register", json=test_user_data)
        token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = client.get("/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user_data["username"]
        assert data["email"] == test_user_data["email"]
        assert "password" not in data
        assert "password_hash" not in data
        assert "id" in data

    def test_get_me_no_token(self, client):
        response = client.get("/auth/me")
        assert response.status_code == 401

    def test_get_me_invalid_token(self, client):
        headers = {"Authorization": "Bearer invalid_token"}
        response = client.get("/auth/me", headers=headers)
        assert response.status_code == 401


class TestSaveSlots:
    def test_create_save_slot(self, client, auth_headers):
        slot_data = {
            "slot_number": 1,
            "name": "My First Save",
        }
        response = client.post("/saves", json=slot_data, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["slot_number"] == 1
        assert data["name"] == "My First Save"
        assert "id" in data
        assert "user_id" in data

    def test_create_duplicate_slot_number(self, client, auth_headers):
        slot_data = {"slot_number": 1, "name": "First Save"}
        response1 = client.post("/saves", json=slot_data, headers=auth_headers)
        assert response1.status_code == 201
        
        slot_data2 = {"slot_number": 1, "name": "Second Save"}
        response2 = client.post("/saves", json=slot_data2, headers=auth_headers)
        assert response2.status_code == 409

    def test_list_save_slots(self, client, auth_headers):
        client.post("/saves", json={"slot_number": 1, "name": "Slot 1"}, headers=auth_headers)
        client.post("/saves", json={"slot_number": 2, "name": "Slot 2"}, headers=auth_headers)
        
        response = client.get("/saves", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["slot_number"] == 1
        assert data[1]["slot_number"] == 2

    def test_get_save_slot_detail(self, client, auth_headers):
        create_response = client.post("/saves", json={"slot_number": 1, "name": "Detail Test"}, headers=auth_headers)
        slot_id = create_response.json()["id"]
        
        response = client.get(f"/saves/{slot_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == slot_id
        assert data["slot_number"] == 1
        assert data["name"] == "Detail Test"
        assert "sessions" in data

    def test_update_save_slot(self, client, auth_headers):
        create_response = client.post("/saves", json={"slot_number": 1, "name": "Original"}, headers=auth_headers)
        slot_id = create_response.json()["id"]
        
        update_data = {"name": "Updated Name"}
        response = client.put(f"/saves/{slot_id}", json=update_data, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"

    def test_delete_save_slot(self, client, auth_headers):
        create_response = client.post("/saves", json={"slot_number": 1, "name": "To Delete"}, headers=auth_headers)
        slot_id = create_response.json()["id"]
        
        response = client.delete(f"/saves/{slot_id}", headers=auth_headers)
        assert response.status_code == 204
        
        get_response = client.get(f"/saves/{slot_id}", headers=auth_headers)
        assert get_response.status_code == 404


class TestSaveSlotOwnership:
    def test_cannot_access_other_user_save_slot(self, client, auth_headers, second_user_auth_headers):
        create_response = client.post("/saves", json={"slot_number": 1, "name": "Private Save"}, headers=auth_headers)
        slot_id = create_response.json()["id"]
        
        response = client.get(f"/saves/{slot_id}", headers=second_user_auth_headers)
        assert response.status_code == 403
        assert "access denied" in response.json()["detail"].lower()

    def test_cannot_update_other_user_save_slot(self, client, auth_headers, second_user_auth_headers):
        create_response = client.post("/saves", json={"slot_number": 1, "name": "Private Save"}, headers=auth_headers)
        slot_id = create_response.json()["id"]
        
        response = client.put(f"/saves/{slot_id}", json={"name": "Hacked"}, headers=second_user_auth_headers)
        assert response.status_code == 403

    def test_cannot_delete_other_user_save_slot(self, client, auth_headers, second_user_auth_headers):
        create_response = client.post("/saves", json={"slot_number": 1, "name": "Private Save"}, headers=auth_headers)
        slot_id = create_response.json()["id"]
        
        response = client.delete(f"/saves/{slot_id}", headers=second_user_auth_headers)
        assert response.status_code == 403

    def test_users_can_have_same_slot_numbers(self, client, auth_headers, second_user_auth_headers):
        response1 = client.post("/saves", json={"slot_number": 1, "name": "User1 Save"}, headers=auth_headers)
        assert response1.status_code == 201
        
        response2 = client.post("/saves", json={"slot_number": 1, "name": "User2 Save"}, headers=second_user_auth_headers)
        assert response2.status_code == 201


class TestSessions:
    def test_list_sessions(self, client, auth_headers, db_engine, sample_world_data):
        world_id = create_world_in_db(db_engine, sample_world_data)
        
        client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
        
        response = client.get("/sessions", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_get_session_snapshot(self, client, auth_headers, db_engine, sample_world_data):
        world_id = create_world_in_db(db_engine, sample_world_data)
        
        save_response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
        session_id = save_response.json()["session_id"]
        
        response = client.get(f"/sessions/{session_id}/snapshot", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert data["world_id"] == world_id
        assert "session_state" in data
        assert "player_state" in data

    def test_load_session(self, client, auth_headers, db_engine, sample_world_data):
        world_id = create_world_in_db(db_engine, sample_world_data)
        
        save_response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
        session_id = save_response.json()["session_id"]
        
        response = client.post(f"/sessions/{session_id}/load", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert data["world_id"] == world_id


class TestSessionOwnership:
    def test_cannot_access_other_user_session_snapshot(self, client, auth_headers, second_user_auth_headers, db_engine, sample_world_data):
        world_id = create_world_in_db(db_engine, sample_world_data)
        
        save_response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
        session_id = save_response.json()["session_id"]
        
        response = client.get(f"/sessions/{session_id}/snapshot", headers=second_user_auth_headers)
        assert response.status_code in [401, 403]

    def test_cannot_load_other_user_session(self, client, auth_headers, second_user_auth_headers, db_engine, sample_world_data):
        world_id = create_world_in_db(db_engine, sample_world_data)
        
        save_response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
        session_id = save_response.json()["session_id"]
        
        response = client.post(f"/sessions/{session_id}/load", headers=second_user_auth_headers)
        assert response.status_code in [401, 403]


class TestUnauthorizedAccess:
    def test_cannot_list_saves_without_auth(self, client):
        response = client.get("/saves")
        assert response.status_code in [401, 403]

    def test_cannot_create_save_without_auth(self, client):
        response = client.post("/saves", json={"slot_number": 1, "name": "Test"})
        assert response.status_code in [401, 403]

    def test_cannot_list_sessions_without_auth(self, client):
        response = client.get("/sessions")
        assert response.status_code in [401, 403]

    def test_cannot_access_snapshot_without_auth(self, client):
        response = client.get("/sessions/123/snapshot")
        assert response.status_code in [401, 403]


class TestManualSave:
    def test_manual_save_creates_session(self, client, auth_headers, db_engine, sample_world_data):
        world_id = create_world_in_db(db_engine, sample_world_data)
        
        response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert "save_slot_id" in data
        assert data["message"] == "Game saved successfully"

    def test_manual_save_invalid_world(self, client, auth_headers):
        response = client.post("/saves/manual-save", json={"world_id": "invalid-world-id"}, headers=auth_headers)
        assert response.status_code == 404


class TestNotFound:
    def test_get_nonexistent_save_slot(self, client, auth_headers):
        response = client.get(f"/saves/{uuid.uuid4()}", headers=auth_headers)
        assert response.status_code == 404

    def test_get_nonexistent_session_snapshot(self, client, auth_headers):
        response = client.get(f"/sessions/{uuid.uuid4()}/snapshot", headers=auth_headers)
        assert response.status_code == 404

    def test_load_nonexistent_session(self, client, auth_headers):
        response = client.post(f"/sessions/{uuid.uuid4()}/load", headers=auth_headers)
        assert response.status_code == 404

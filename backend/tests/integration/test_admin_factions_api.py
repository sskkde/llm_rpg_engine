"""
Integration tests for Admin Factions API endpoints.
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel, WorldModel, FactionModel
from llm_rpg.storage.repositories import UserRepository, WorldRepository
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


def create_test_world(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        world_repo = WorldRepository(db)
        world = world_repo.create({
            "code": f"test_world_{uuid.uuid4().hex[:8]}",
            "name": "Test World",
            "genre": "fantasy",
            "status": "active",
        })
        db.commit()
        return world.id
    finally:
        db.close()


class TestAdminFactionsAuth:
    def test_non_admin_forbidden_from_factions(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        
        admin_headers = get_auth_header(client, admin_user_data)
        user_headers = get_auth_header(client, regular_user_data)
        
        admin_response = client.get("/admin/factions", headers=admin_headers)
        assert admin_response.status_code == 200
        
        user_response = client.get("/admin/factions", headers=user_headers)
        assert user_response.status_code == 403
        assert user_response.json()["detail"] == "Admin access required"
    
    def test_unauthenticated_user_gets_401(self, client):
        response = client.get("/admin/factions")
        assert response.status_code == 401


class TestAdminFactionsCRUD:
    def test_list_factions_empty(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/admin/factions", headers=headers)
        assert response.status_code == 200
        assert response.json() == []
    
    def test_create_faction(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_test",
            "world_id": world_id,
            "name": "Test Faction",
            "ideology": {"alignment": "neutral"},
            "goals": [{"goal_id": "g1", "description": "Test goal", "priority": 10}],
            "relationships": [],
            "visibility": "public",
            "status": "active",
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data["logical_id"] == "faction_test"
        assert data["name"] == "Test Faction"
        assert data["world_id"] == world_id
    
    def test_create_faction_duplicate_logical_id(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        response1 = client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_dup",
            "world_id": world_id,
            "name": "First Faction",
        })
        assert response1.status_code == 201
        
        response2 = client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_dup",
            "world_id": world_id,
            "name": "Second Faction",
        })
        assert response2.status_code == 409
    
    def test_get_faction(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_get",
            "world_id": world_id,
            "name": "Faction to Get",
        })
        faction_id = create_response.json()["id"]
        
        response = client.get(f"/admin/factions/{faction_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["name"] == "Faction to Get"
    
    def test_get_faction_not_found(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/admin/factions/nonexistent", headers=headers)
        assert response.status_code == 404
    
    def test_update_faction(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_update",
            "world_id": world_id,
            "name": "Original Name",
        })
        faction_id = create_response.json()["id"]
        
        response = client.patch(f"/admin/factions/{faction_id}", headers=headers, json={
            "name": "Updated Name",
            "status": "inactive",
        })
        
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"
        assert response.json()["status"] == "inactive"
    
    def test_update_faction_cannot_change_logical_id(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_nochange",
            "world_id": world_id,
            "name": "Test Faction",
        })
        faction_id = create_response.json()["id"]
        
        response = client.patch(f"/admin/factions/{faction_id}", headers=headers, json={
            "logical_id": "new_logical_id",
        })
        
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert any("logical_id cannot be changed" in str(err) for err in detail)
    
    def test_delete_faction(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_delete",
            "world_id": world_id,
            "name": "Faction to Delete",
        })
        faction_id = create_response.json()["id"]
        
        delete_response = client.delete(f"/admin/factions/{faction_id}", headers=headers)
        assert delete_response.status_code == 204
        
        get_response = client.get(f"/admin/factions/{faction_id}", headers=headers)
        assert get_response.status_code == 404
    
    def test_delete_faction_not_found(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.delete("/admin/factions/nonexistent", headers=headers)
        assert response.status_code == 404
    
    def test_list_factions_by_world(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id1 = create_test_world(db_engine)
        world_id2 = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_w1",
            "world_id": world_id1,
            "name": "World 1 Faction",
        })
        client.post("/admin/factions", headers=headers, json={
            "logical_id": "faction_w2",
            "world_id": world_id2,
            "name": "World 2 Faction",
        })
        
        response = client.get(f"/admin/factions?world_id={world_id1}", headers=headers)
        assert response.status_code == 200
        factions = response.json()
        assert len(factions) == 1
        assert factions[0]["name"] == "World 1 Faction"

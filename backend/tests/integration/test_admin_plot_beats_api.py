"""
Integration tests for Admin Plot Beats API endpoints.
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel, WorldModel, PlotBeatModel
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


class TestAdminPlotBeatsAuth:
    def test_non_admin_forbidden_from_plot_beats(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        
        admin_headers = get_auth_header(client, admin_user_data)
        user_headers = get_auth_header(client, regular_user_data)
        
        admin_response = client.get("/admin/plot-beats", headers=admin_headers)
        assert admin_response.status_code == 200
        
        user_response = client.get("/admin/plot-beats", headers=user_headers)
        assert user_response.status_code == 403
        assert user_response.json()["detail"] == "Admin access required"
    
    def test_unauthenticated_user_gets_401(self, client):
        response = client.get("/admin/plot-beats")
        assert response.status_code == 401


class TestAdminPlotBeatsCRUD:
    def test_list_plot_beats_empty(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/admin/plot-beats", headers=headers)
        assert response.status_code == 200
        assert response.json() == []
    
    def test_create_plot_beat(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_test",
            "world_id": world_id,
            "title": "Test Plot Beat",
            "conditions": [{"type": "location_is", "params": {"location_id": "loc_1"}}],
            "effects": [{"type": "emit_event", "params": {"event": "test_event"}}],
            "priority": 50,
            "visibility": "conditional",
            "status": "pending",
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data["logical_id"] == "beat_test"
        assert data["title"] == "Test Plot Beat"
        assert data["world_id"] == world_id
        assert len(data["conditions"]) == 1
        assert len(data["effects"]) == 1
    
    def test_create_plot_beat_duplicate_logical_id(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        response1 = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_dup",
            "world_id": world_id,
            "title": "First Beat",
        })
        assert response1.status_code == 201
        
        response2 = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_dup",
            "world_id": world_id,
            "title": "Second Beat",
        })
        assert response2.status_code == 409
    
    def test_get_plot_beat(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_get",
            "world_id": world_id,
            "title": "Beat to Get",
        })
        beat_id = create_response.json()["id"]
        
        response = client.get(f"/admin/plot-beats/{beat_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["title"] == "Beat to Get"
    
    def test_get_plot_beat_not_found(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/admin/plot-beats/nonexistent", headers=headers)
        assert response.status_code == 404
    
    def test_update_plot_beat(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_update",
            "world_id": world_id,
            "title": "Original Title",
            "priority": 10,
        })
        beat_id = create_response.json()["id"]
        
        response = client.patch(f"/admin/plot-beats/{beat_id}", headers=headers, json={
            "title": "Updated Title",
            "priority": 90,
            "status": "active",
        })
        
        assert response.status_code == 200
        assert response.json()["title"] == "Updated Title"
        assert response.json()["priority"] == 90
        assert response.json()["status"] == "active"
    
    def test_update_plot_beat_cannot_change_logical_id(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_nochange",
            "world_id": world_id,
            "title": "Test Beat",
        })
        beat_id = create_response.json()["id"]
        
        response = client.patch(f"/admin/plot-beats/{beat_id}", headers=headers, json={
            "logical_id": "new_logical_id",
        })
        
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert any("logical_id cannot be changed" in str(err) for err in detail)
    
    def test_delete_plot_beat(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_delete",
            "world_id": world_id,
            "title": "Beat to Delete",
        })
        beat_id = create_response.json()["id"]
        
        delete_response = client.delete(f"/admin/plot-beats/{beat_id}", headers=headers)
        assert delete_response.status_code == 204
        
        get_response = client.get(f"/admin/plot-beats/{beat_id}", headers=headers)
        assert get_response.status_code == 404
    
    def test_delete_plot_beat_not_found(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.delete("/admin/plot-beats/nonexistent", headers=headers)
        assert response.status_code == 404
    
    def test_list_plot_beats_by_world(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id1 = create_test_world(db_engine)
        world_id2 = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_w1",
            "world_id": world_id1,
            "title": "World 1 Beat",
        })
        client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_w2",
            "world_id": world_id2,
            "title": "World 2 Beat",
        })
        
        response = client.get(f"/admin/plot-beats?world_id={world_id1}", headers=headers)
        assert response.status_code == 200
        beats = response.json()
        assert len(beats) == 1
        assert beats[0]["title"] == "World 1 Beat"
    
    def test_update_plot_beat_conditions_and_effects(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        world_id = create_test_world(db_engine)
        headers = get_auth_header(client, admin_user_data)
        
        create_response = client.post("/admin/plot-beats", headers=headers, json={
            "logical_id": "beat_cond_eff",
            "world_id": world_id,
            "title": "Beat with Conditions",
        })
        beat_id = create_response.json()["id"]
        
        response = client.patch(f"/admin/plot-beats/{beat_id}", headers=headers, json={
            "conditions": [{"type": "npc_present", "params": {"npc_id": "npc_1"}}],
            "effects": [{"type": "set_state", "params": {"key": "flag", "value": True}}],
        })
        
        assert response.status_code == 200
        assert len(response.json()["conditions"]) == 1
        assert len(response.json()["effects"]) == 1

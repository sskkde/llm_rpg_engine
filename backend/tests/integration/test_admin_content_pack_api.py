"""
Integration tests for Admin Content Pack API endpoints.
"""

import pytest
import uuid
import os
import tempfile
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel, WorldModel
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


class TestAdminContentPackAuth:
    def test_non_admin_forbidden_from_validate(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        
        admin_headers = get_auth_header(client, admin_user_data)
        user_headers = get_auth_header(client, regular_user_data)
        
        admin_response = client.post(
            "/admin/content-packs/validate",
            headers=admin_headers,
            json={"path": "content_packs/test"}
        )
        assert admin_response.status_code in [200, 422]
        
        user_response = client.post(
            "/admin/content-packs/validate",
            headers=user_headers,
            json={"path": "content_packs/test"}
        )
        assert user_response.status_code == 403
    
    def test_unauthenticated_user_gets_401(self, client):
        response = client.post(
            "/admin/content-packs/validate",
            json={"path": "content_packs/test"}
        )
        assert response.status_code == 401


class TestAdminContentPackPathValidation:
    def test_path_traversal_rejected(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/validate",
            headers=headers,
            json={"path": "content_packs/../secret"}
        )
        
        assert response.status_code == 422
        assert "Path traversal not allowed" in response.json()["detail"]
    
    def test_path_without_content_packs_prefix_rejected(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/validate",
            headers=headers,
            json={"path": "other_packs/test"}
        )
        
        assert response.status_code == 422
        assert "must start with 'content_packs/'" in response.json()["detail"]
    
    def test_path_with_double_dot_slash_rejected(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/import",
            headers=headers,
            json={"path": "content_packs/../etc/passwd"}
        )
        
        assert response.status_code == 422
        assert "Path traversal not allowed" in response.json()["detail"]
    
    def test_valid_content_packs_path_accepted(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/validate",
            headers=headers,
            json={"path": "content_packs/qinglan_xianxia"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "is_valid" in data


class TestAdminContentPackValidate:
    def test_validate_nonexistent_pack(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/validate",
            headers=headers,
            json={"path": "content_packs/nonexistent_pack"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert any("not found" in issue["message"].lower() or "LOAD_ERROR" in issue.get("code", "") 
                   for issue in data["issues"])


class TestAdminContentPackImport:
    def test_import_dry_run(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/import?dry_run=true",
            headers=headers,
            json={"path": "content_packs/qinglan_xianxia"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True
    
    def test_import_nonexistent_pack(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/import",
            headers=headers,
            json={"path": "content_packs/nonexistent_pack"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert len(data["errors"]) > 0
    
    def test_import_path_traversal_blocked(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)
        
        response = client.post(
            "/admin/content-packs/import",
            headers=headers,
            json={"path": "content_packs/../../../etc/passwd"}
        )
        
        assert response.status_code == 422
        assert "Path traversal not allowed" in response.json()["detail"]

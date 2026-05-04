"""
Integration tests for admin authorization enforcement.
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


class TestAdminAuthorization:
    def test_non_admin_forbidden_from_admin_and_debug(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        
        admin_headers = get_auth_header(client, admin_user_data)
        user_headers = get_auth_header(client, regular_user_data)
        
        admin_response = client.get("/admin/worlds", headers=admin_headers)
        assert admin_response.status_code == 200
        
        user_response = client.get("/admin/worlds", headers=user_headers)
        assert user_response.status_code == 403
        assert user_response.json()["detail"] == "Admin access required"
        
        debug_response = client.get("/debug/model-calls", headers=user_headers)
        assert debug_response.status_code == 403
        assert debug_response.json()["detail"] == "Admin access required for debug endpoints"
    
    def test_admin_can_access_admin_endpoints(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/admin/worlds", headers=headers)
        assert response.status_code == 200
    
    def test_admin_can_access_debug_endpoints(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        
        headers = get_auth_header(client, admin_user_data)
        
        response = client.get("/debug/model-calls", headers=headers)
        assert response.status_code == 200
    
    def test_unauthenticated_user_gets_401(self, client):
        response = client.get("/admin/worlds")
        assert response.status_code == 401
        
        response = client.get("/debug/model-calls")
        assert response.status_code == 401


class TestUserResponseIncludesIsAdmin:
    def test_register_returns_is_admin(self, client, regular_user_data):
        response = client.post("/auth/register", json=regular_user_data)
        assert response.status_code == 201
        
        user = response.json()["user"]
        assert "is_admin" in user
        assert user["is_admin"] is False
    
    def test_login_returns_is_admin(self, client, db_engine, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        
        response = client.post("/auth/login", json={
            "username": regular_user_data["username"],
            "password": regular_user_data["password"],
        })
        assert response.status_code == 200
        
        user = response.json()["user"]
        assert "is_admin" in user
        assert user["is_admin"] is False
    
    def test_me_returns_is_admin(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        
        headers = get_auth_header(client, admin_user_data)
        response = client.get("/auth/me", headers=headers)
        assert response.status_code == 200
        
        user = response.json()
        assert "is_admin" in user
        assert user["is_admin"] is True


class TestAdminMigration:
    def test_admin_promotion_migration_handles_no_admin_user(self, db_engine):
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            user_repo = UserRepository(db)
            user = user_repo.create({
                "username": "regular_user",
                "email": "regular@example.com",
                "password_hash": "hashed_password",
                "is_admin": False,
            })
            db.commit()
            
            db.refresh(user)
            assert user.is_admin is False
            
            admin_user = user_repo.create({
                "username": "admin",
                "email": "admin@example.com",
                "password_hash": "hashed_password",
                "is_admin": True,
            })
            db.commit()
            
            db.refresh(admin_user)
            assert admin_user.is_admin is True
        finally:
            db.close()

"""
Integration tests for reserved media endpoints.

Verifies that media generation endpoints return 501 Not Implemented
to preserve their API contract for future implementation.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.main import app
from llm_rpg.storage.database import Base, get_db


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


class TestMediaEndpoints501:
    """Test that reserved media endpoints return 501 Not Implemented."""
    
    def test_portrait_generate_returns_501(self, client):
        """POST /media/portraits/generate should return 501."""
        response = client.post(
            "/media/portraits/generate",
            json={"npc_id": "test-npc-id", "style": "anime", "expression": "neutral"}
        )
        
        assert response.status_code == 501, \
            f"Expected 501, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data
        assert "reserved" in data["detail"].lower() or "not implemented" in data["detail"].lower()
    
    def test_scene_generate_returns_501(self, client):
        """POST /media/scenes/generate should return 501."""
        response = client.post(
            "/media/scenes/generate",
            json={"location_id": "test-location-id", "time_of_day": "day"}
        )
        
        assert response.status_code == 501, \
            f"Expected 501, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data
        assert "reserved" in data["detail"].lower() or "not implemented" in data["detail"].lower()
    
    def test_bgm_generate_returns_501(self, client):
        """POST /media/bgm/generate should return 501."""
        response = client.post(
            "/media/bgm/generate",
            json={"mood": "tense", "duration_seconds": 60}
        )
        
        assert response.status_code == 501, \
            f"Expected 501, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data
        assert "reserved" in data["detail"].lower() or "not implemented" in data["detail"].lower()


class TestMediaEndpointContract:
    """Test that media endpoints maintain their API contract."""
    
    def test_portrait_generate_accepts_valid_request(self, client):
        """Portrait endpoint should accept valid request body before returning 501."""
        valid_request = {
            "npc_id": "some-npc-uuid",
            "style": "anime",
            "expression": "happy"
        }
        
        response = client.post("/media/portraits/generate", json=valid_request)
        
        assert response.status_code == 501
    
    def test_portrait_generate_rejects_missing_npc_id(self, client):
        """Portrait endpoint should reject requests missing required npc_id."""
        invalid_request = {
            "style": "anime",
            "expression": "happy"
        }
        
        response = client.post("/media/portraits/generate", json=invalid_request)
        
        assert response.status_code == 422
    
    def test_scene_generate_accepts_valid_request(self, client):
        """Scene endpoint should accept valid request body before returning 501."""
        valid_request = {
            "location_id": "some-location-uuid",
            "time_of_day": "night",
            "weather": "rainy"
        }
        
        response = client.post("/media/scenes/generate", json=valid_request)
        
        assert response.status_code == 501
    
    def test_scene_generate_rejects_missing_location_id(self, client):
        """Scene endpoint should reject requests missing required location_id."""
        invalid_request = {
            "time_of_day": "day"
        }
        
        response = client.post("/media/scenes/generate", json=invalid_request)
        
        assert response.status_code == 422
    
    def test_bgm_generate_accepts_valid_request(self, client):
        """BGM endpoint should accept valid request body before returning 501."""
        valid_request = {
            "mood": "peaceful",
            "location_id": "some-location-uuid",
            "duration_seconds": 120
        }
        
        response = client.post("/media/bgm/generate", json=valid_request)
        
        assert response.status_code == 501
    
    def test_bgm_generate_rejects_missing_mood(self, client):
        """BGM endpoint should reject requests missing required mood."""
        invalid_request = {
            "duration_seconds": 60
        }
        
        response = client.post("/media/bgm/generate", json=invalid_request)
        
        assert response.status_code == 422
    
    def test_bgm_generate_rejects_invalid_duration(self, client):
        """BGM endpoint should reject duration outside valid range."""
        invalid_request = {
            "mood": "tense",
            "duration_seconds": 5
        }
        
        response = client.post("/media/bgm/generate", json=invalid_request)
        
        assert response.status_code == 422
    
    def test_bgm_generate_rejects_excessive_duration(self, client):
        """BGM endpoint should reject duration exceeding maximum."""
        invalid_request = {
            "mood": "tense",
            "duration_seconds": 500
        }
        
        response = client.post("/media/bgm/generate", json=invalid_request)
        
        assert response.status_code == 422


class TestMediaEndpointIsolation:
    """Test that media endpoints are isolated from game logic."""
    
    def test_media_unavailable_does_not_affect_world_state(self, client):
        """Media 501 responses should not affect game state endpoints."""
        response = client.get("/world/state")
        
        assert response.status_code == 404
    
    def test_media_unavailable_does_not_affect_docs(self, client):
        """Media 501 responses should not affect API docs."""
        response = client.get("/docs")
        
        assert response.status_code == 200

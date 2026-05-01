"""
Basic health check tests for LLM RPG Engine API.

These tests verify that the FastAPI application is properly configured
and responding to requests.
"""

import pytest
from fastapi.testclient import TestClient


class TestHealthCheck:
    def test_app_imports(self):
        from llm_rpg.main import app
        assert app is not None
        assert app.title == "LLM RPG Engine"
    
    def test_context_builder_import(self):
        from llm_rpg.core.context_builder import ContextBuilder
        assert ContextBuilder.__name__ == "ContextBuilder"
    
    def test_client_can_connect(self, client: TestClient):
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_openapi_schema_available(self, client: TestClient):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "LLM RPG Engine"
        assert "paths" in data


class TestSessionEndpoints:
    def test_create_save(self, client: TestClient):
        response = client.post("/dev/saves")
        assert response.status_code == 200
        
        session_id = response.json()
        assert isinstance(session_id, str)
        assert len(session_id) > 0
    
    def test_list_saves(self, client: TestClient):
        create_response = client.post("/dev/saves")
        assert create_response.status_code == 200
        session_id = create_response.json()
        
        response = client.get("/dev/saves")
        assert response.status_code == 200
        
        sessions = response.json()
        assert isinstance(sessions, list)
        assert session_id in sessions
    
    def test_get_snapshot(self, client: TestClient):
        create_response = client.post("/dev/saves")
        assert create_response.status_code == 200
        session_id = create_response.json()
        
        response = client.get(f"/dev/sessions/{session_id}/snapshot")
        assert response.status_code == 200
        
        data = response.json()
        assert "player_state" in data
        assert "world_state" in data
        assert "scene_state" in data
    
    def test_get_snapshot_not_found(self, client: TestClient):
        response = client.get("/dev/sessions/non-existent-id/snapshot")
        assert response.status_code == 404
        assert "detail" in response.json()
    
    def test_perform_turn(self, client: TestClient):
        create_response = client.post("/dev/saves")
        assert create_response.status_code == 200
        session_id = create_response.json()
        
        response = client.post(
            f"/dev/sessions/{session_id}/turn",
            json={"action": "观察四周"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "narrative" in data
        assert "recommended_actions" in data
        assert "state" in data
        assert isinstance(data["recommended_actions"], list)
    
    def test_get_logs(self, client: TestClient):
        create_response = client.post("/dev/saves")
        assert create_response.status_code == 200
        session_id = create_response.json()

        other_create_response = client.post("/dev/saves")
        assert other_create_response.status_code == 200
        other_session_id = other_create_response.json()

        turn_response = client.post(
            f"/dev/sessions/{session_id}/turn",
            json={"action": "观察四周"}
        )
        assert turn_response.status_code == 200
        
        response = client.get(f"/dev/sessions/{session_id}/logs")
        assert response.status_code == 200
        
        logs = response.json()
        assert isinstance(logs, list)
        assert len(logs) > 0

        other_response = client.get(f"/dev/sessions/{other_session_id}/logs")
        assert other_response.status_code == 200
        assert other_response.json() == []

"""Integration tests for combat API."""

import pytest
import uuid

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
def test_world(db_session: Session):
    repo = WorldRepository(db_session)
    world_data = {
        "code": f"test_world_{uuid.uuid4().hex[:8]}",
        "name": "Test World",
        "genre": "fantasy",
        "lore_summary": "A world for testing",
        "status": "active",
    }
    return repo.create(world_data)


@pytest.fixture
def test_user(client: TestClient):
    user_data = {
        "username": f"testuser_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePass123!",
    }
    response = client.post("/auth/register", json=user_data)
    if response.status_code == 201:
        return response.json()

    login_response = client.post(
        "/auth/login",
        data={"username": user_data["username"], "password": user_data["password"]}
    )
    return login_response.json()


@pytest.fixture
def auth_headers(test_user: dict):
    return {"Authorization": f"Bearer {test_user['access_token']}"}


@pytest.fixture
def test_game_session(client: TestClient, auth_headers: dict, test_world: WorldModel):
    save_slot_response = client.post(
        "/saves",
        headers=auth_headers,
        json={"slot_number": 1, "name": "Test Save Slot"}
    )

    assert save_slot_response.status_code == 201, f"Failed to create save slot: {save_slot_response.text}"
    save_slot = save_slot_response.json()

    manual_save_response = client.post(
        "/saves/manual-save",
        headers=auth_headers,
        json={
            "slot_id": save_slot["id"],
            "world_id": test_world.id
        }
    )

    assert manual_save_response.status_code == 201, f"Failed to create session: {manual_save_response.text}"
    return manual_save_response.json()


@pytest.fixture(autouse=True)
def reset_combat_manager():
    import llm_rpg.core.combat as combat_module
    combat_module._combat_manager = None
    yield
    combat_module._combat_manager = None


class TestCombatStart:
    def test_start_combat_creates_session_and_round(self, client: TestClient, auth_headers: dict, test_game_session: dict):
        response = client.post(
            "/combat/start",
            headers=auth_headers,
            json={
                "session_id": test_game_session["session_id"],
                "location_id": "loc_test",
                "participants": [
                    {
                        "actor_id": "player",
                        "actor_type": "player",
                        "name": "Player",
                        "hp": 100,
                        "max_hp": 100,
                        "initiative": 10
                    },
                    {
                        "actor_id": "enemy1",
                        "actor_type": "npc",
                        "name": "Enemy 1",
                        "hp": 50,
                        "max_hp": 50,
                        "initiative": 5
                    }
                ],
                "narration_context": "Test combat"
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert "combat_id" in data
        assert data["session_id"] == test_game_session["session_id"]
        assert data["status"] == "active"
        assert data["current_round_no"] == 1
        assert len(data["participants"]) == 2
        assert data["message"] == "Combat started successfully"

    def test_start_combat_unauthorized(self, client: TestClient, test_game_session: dict):
        response = client.post(
            "/combat/start",
            json={
                "session_id": test_game_session["session_id"],
                "participants": [{"actor_id": "player", "actor_type": "player", "name": "Player", "hp": 100, "max_hp": 100, "initiative": 10}]
            }
        )
        assert response.status_code == 401

    def test_start_combat_invalid_session(self, client: TestClient, auth_headers: dict):
        response = client.post(
            "/combat/start",
            headers=auth_headers,
            json={
                "session_id": "invalid_session_id",
                "participants": [{"actor_id": "player", "actor_type": "player", "name": "Player", "hp": 100, "max_hp": 100, "initiative": 10}]
            }
        )
        assert response.status_code == 404


class TestCombatTurn:
    def test_submit_valid_action(self, client: TestClient, auth_headers: dict, test_game_session: dict):
        start_response = client.post(
            "/combat/start",
            headers=auth_headers,
            json={
                "session_id": test_game_session["session_id"],
                "participants": [
                    {"actor_id": "player", "actor_type": "player", "name": "Player", "hp": 100, "max_hp": 100, "initiative": 10},
                    {"actor_id": "enemy1", "actor_type": "npc", "name": "Enemy", "hp": 50, "max_hp": 50, "initiative": 5}
                ]
            }
        )
        combat_id = start_response.json()["combat_id"]

        response = client.post(
            f"/combat/{combat_id}/turn",
            headers=auth_headers,
            params={"actor_id": "player"},
            json={"action_type": "attack", "target_id": "enemy1"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "action_id" in data
        assert data["combat_id"] == combat_id
        assert "resolution" in data
        assert data["combat_status"] == "active"

    def test_submit_invalid_action_returns_400(self, client: TestClient, auth_headers: dict, test_game_session: dict):
        start_response = client.post(
            "/combat/start",
            headers=auth_headers,
            json={
                "session_id": test_game_session["session_id"],
                "participants": [
                    {"actor_id": "player", "actor_type": "player", "name": "Player", "hp": 100, "max_hp": 100, "initiative": 10},
                    {"actor_id": "enemy1", "actor_type": "npc", "name": "Enemy", "hp": 50, "max_hp": 50, "initiative": 5}
                ]
            }
        )
        combat_id = start_response.json()["combat_id"]

        response = client.post(
            f"/combat/{combat_id}/turn",
            headers=auth_headers,
            params={"actor_id": "player"},
            json={"action_type": "attack"}
        )

        assert response.status_code == 400
        error_detail = response.json()["detail"].lower()
        assert "target" in error_detail

        db_response = client.get(f"/combat/{combat_id}", headers=auth_headers)
        combat_data = db_response.json()
        current_round = combat_data.get("current_round", {})
        actions = current_round.get("actions", [])
        assert len(actions) == 0, "No action should be committed for invalid action"

    def test_submit_action_invalid_type(self, client: TestClient, auth_headers: dict, test_game_session: dict):
        start_response = client.post(
            "/combat/start",
            headers=auth_headers,
            json={
                "session_id": test_game_session["session_id"],
                "participants": [{"actor_id": "player", "actor_type": "player", "name": "Player", "hp": 100, "max_hp": 100, "initiative": 10}]
            }
        )
        combat_id = start_response.json()["combat_id"]

        response = client.post(
            f"/combat/{combat_id}/turn",
            headers=auth_headers,
            params={"actor_id": "player"},
            json={"action_type": "invalid_action"}
        )

        assert response.status_code == 400

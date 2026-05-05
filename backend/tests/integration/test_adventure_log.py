import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.models import Base
from llm_rpg.main import app
from llm_rpg.storage.database import get_db


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
    from fastapi.testclient import TestClient
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user_data():
    return {
        "username": f"testuser_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePass123!",
    }


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
def auth_headers(client, test_user_data):
    response = client.post("/auth/register", json=test_user_data)
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_world_in_db(db_engine, world_data):
    from llm_rpg.storage.repositories import WorldRepository
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        world_repo = WorldRepository(db)
        world = world_repo.create(world_data)
        db.commit()
        return world.id
    finally:
        db.close()


def create_session(client, auth_headers, db_engine, sample_world_data):
    world_id = create_world_in_db(db_engine, sample_world_data)
    response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["session_id"], world_id


class TestAdventureLogAPI:
    def test_new_session_log_has_single_initial_scene(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        
        entry = data[0]
        assert entry["turn_no"] == 0
        assert entry["event_type"] == "initial_scene"
        assert "山门广场晨雾未散" in entry["narration"]
        assert entry["action"] is None
        assert entry["recommended_actions"] == []

    def test_adventure_log_idempotent(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        response1 = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert response1.status_code == 200
        count1 = len(response1.json())
        
        response2 = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert response2.status_code == 200
        count2 = len(response2.json())
        
        assert count1 == count2 == 1

    def test_adventure_log_rejects_other_user(self, client, db_engine, sample_world_data):
        user1_data = {
            "username": f"user1_{uuid.uuid4().hex[:8]}",
            "email": f"user1_{uuid.uuid4().hex[:8]}@example.com",
            "password": "SecurePass123!",
        }
        user2_data = {
            "username": f"user2_{uuid.uuid4().hex[:8]}",
            "email": f"user2_{uuid.uuid4().hex[:8]}@example.com",
            "password": "SecurePass123!",
        }
        
        response1 = client.post("/auth/register", json=user1_data)
        assert response1.status_code == 201
        token1 = response1.json()["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}
        
        response2 = client.post("/auth/register", json=user2_data)
        assert response2.status_code == 201
        token2 = response2.json()["access_token"]
        headers2 = {"Authorization": f"Bearer {token2}"}
        
        session_id, _ = create_session(client, headers1, db_engine, sample_world_data)
        
        response = client.get(f"/sessions/{session_id}/adventure-log", headers=headers2)
        
        assert response.status_code in [401, 403]


class TestAdventureLogPersistence:
    def test_non_streaming_turn_is_persisted(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        turn_response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers,
        )
        assert turn_response.status_code == 200
        
        log_response = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert log_response.status_code == 200
        data = log_response.json()
        
        assert len(data) == 2
        
        initial_scene = data[0]
        assert initial_scene["turn_no"] == 0
        assert initial_scene["event_type"] == "initial_scene"
        
        player_turn = data[1]
        assert player_turn["turn_no"] == 1
        assert player_turn["event_type"] == "player_turn"
        assert player_turn["action"] == "观察四周"
        assert len(player_turn["narration"]) > 0
        assert player_turn["recommended_actions"] == []

    def test_multiple_turns_persisted_in_order(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        actions = ["观察四周", "向东走", "与NPC对话"]
        for action in actions:
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers,
            )
            assert response.status_code == 200
        
        log_response = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert log_response.status_code == 200
        data = log_response.json()
        
        assert len(data) == 4
        
        turn_numbers = [entry["turn_no"] for entry in data]
        assert turn_numbers == [0, 1, 2, 3]
        
        assert data[0]["event_type"] == "initial_scene"
        for i, action in enumerate(actions, start=1):
            assert data[i]["event_type"] == "player_turn"
            assert data[i]["action"] == action

    def test_failed_turn_does_not_create_player_log(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        log_before = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert log_before.status_code == 200
        count_before = len(log_before.json())
        
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": ""},
            headers=auth_headers,
        )
        
        if response.status_code != 200:
            log_after = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
            assert log_after.status_code == 200
            count_after = len(log_after.json())
            assert count_after == count_before

    def test_streaming_mock_turn_is_persisted(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)
        
        with client.stream(
            "POST",
            f"/streaming/sessions/{session_id}/turn/mock",
            json={"action": "观察四周"},
            headers=auth_headers,
        ) as response:
            assert response.status_code == 200
            
            events = []
            event_type = None
            for line in response.iter_lines():
                if line:
                    if isinstance(line, bytes):
                        line = line.decode("utf-8")
                    if line.startswith("event:"):
                        event_type = line[7:]
                    elif line.startswith("data:"):
                        import json
                        data = json.loads(line[5:])
                        events.append({"event": event_type, "data": data})
            
            event_types = [e["event"] for e in events]
            assert "turn_completed" in event_types
        
        log_response = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert log_response.status_code == 200
        data = log_response.json()
        
        assert len(data) == 2
        
        initial_scene = data[0]
        assert initial_scene["turn_no"] == 0
        assert initial_scene["event_type"] == "initial_scene"
        
        player_turn = data[1]
        assert player_turn["turn_no"] == 1
        assert player_turn["event_type"] == "player_turn"
        assert player_turn["action"] == "观察四周"
        assert len(player_turn["narration"]) > 0
        assert player_turn["recommended_actions"] == []

    def test_streaming_error_does_not_create_player_log(self, client, auth_headers, db_engine, sample_world_data):
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        from sqlalchemy.orm import sessionmaker
        from llm_rpg.storage.repositories import SystemSettingsRepository
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            settings_repo = SystemSettingsRepository(db)
            settings_repo.update_singleton({
                "provider_mode": "custom",
                "custom_base_url": None,
            })
        finally:
            db.close()

        log_before = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert log_before.status_code == 200
        count_before = len(log_before.json())

        with client.stream(
            "POST",
            f"/streaming/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=auth_headers,
        ) as response:
            events = []
            event_type = None
            for line in response.iter_lines():
                if line:
                    if isinstance(line, bytes):
                        line = line.decode("utf-8")
                    if line.startswith("event:"):
                        event_type = line[7:]
                    elif line.startswith("data:"):
                        import json
                        data = json.loads(line[5:])
                        events.append({"event": event_type, "data": data})

        event_types = [e["event"] for e in events]
        assert "turn_error" in event_types

        log_after = client.get(f"/sessions/{session_id}/adventure-log", headers=auth_headers)
        assert log_after.status_code == 200
        count_after = len(log_after.json())
        assert count_after == count_before

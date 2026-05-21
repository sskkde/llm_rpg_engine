import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.main import app
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    WorldModel,
    LocationModel,
    SessionModel,
    SessionStateModel,
    SessionNPCStateModel,
    SessionInventoryItemModel,
    NPCTemplateModel,
    ItemTemplateModel,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    LocationRepository,
    SessionRepository,
    SessionStateRepository,
    SessionNPCStateRepository,
    SessionInventoryItemRepository,
    NPCTemplateRepository,
    ItemTemplateRepository,
)

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def engine():
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
def client(engine):
    def override_get_db():
        connection = engine.connect()
        session = sessionmaker(bind=connection)()
        try:
            yield session
        finally:
            session.close()
            connection.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_world(engine, code=None):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = WorldRepository(db)
        world = repo.create({
            "code": code or f"test_world_{uuid.uuid4().hex[:8]}",
            "name": "Test World",
            "genre": "xianxia",
            "status": "active",
        })
        return world.id
    finally:
        db.close()


def _create_user_and_token(client):
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    password = "SecurePass123!"
    resp = client.post("/auth/register", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 201, f"Registration failed: {resp.text}"
    token = resp.json()["access_token"]
    user_id = resp.json()["user"]["id"]
    return token, user_id


def _create_session(engine, user_id, world_id):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = SessionRepository(db)
        session = repo.create({
            "user_id": user_id,
            "world_id": world_id,
            "status": "active",
        })
        return session.id
    finally:
        db.close()


def _create_location(engine, world_id, code, name, tags=None, access_rules=None, description=None):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = LocationRepository(db)
        location = repo.create({
            "world_id": world_id,
            "code": code,
            "name": name,
            "tags": tags or [],
            "access_rules": access_rules or {},
            "description": description or f"A location called {name}.",
        })
        return location.id
    finally:
        db.close()


def _set_session_state(engine, session_id, current_location_id):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = SessionStateRepository(db)
        repo.create_or_update({
            "session_id": session_id,
            "current_location_id": current_location_id,
            "active_mode": "exploration",
        })
    finally:
        db.close()


def _create_npc_template(engine, world_id, code, name):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = NPCTemplateRepository(db)
        template = repo.create({
            "world_id": world_id,
            "code": code,
            "name": name,
        })
        return template.id
    finally:
        db.close()


def _create_npc_state(engine, session_id, npc_template_id, current_location_id):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = SessionNPCStateRepository(db)
        state = repo.create({
            "session_id": session_id,
            "npc_template_id": npc_template_id,
            "current_location_id": current_location_id,
        })
        return state.id
    finally:
        db.close()


def _create_item_template(engine, world_id, code, name, item_type="misc"):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = ItemTemplateRepository(db)
        template = repo.create({
            "world_id": world_id,
            "code": code,
            "name": name,
            "item_type": item_type,
        })
        return template.id
    finally:
        db.close()


def _create_inventory_item(engine, session_id, template_id, owner_type, owner_ref_id, quantity=1):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = SessionInventoryItemRepository(db)
        item = repo.create({
            "session_id": session_id,
            "item_template_id": template_id,
            "owner_type": owner_type,
            "owner_ref_id": owner_ref_id,
            "quantity": quantity,
        })
        return item.id
    finally:
        db.close()


class TestListLocations:
    def test_get_locations_returns_known_location_list(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        loc_square = _create_location(engine, world_id, "square", "广场")
        loc_hall = _create_location(engine, world_id, "hall", "大殿")
        loc_cave = _create_location(engine, world_id, "cave", "洞穴", tags=["hidden"])

        _set_session_state(engine, session_id, loc_square)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/locations", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        names = [loc["name"] for loc in data]
        assert "广场" in names
        assert "大殿" in names
        assert "洞穴" not in names

        for loc in data:
            if loc["name"] == "广场":
                assert loc["is_current"] is True
            else:
                assert loc["is_current"] is False

    def test_get_locations_filter_by_accessible(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        loc_square = _create_location(engine, world_id, "square", "广场",
                                      access_rules={"always_accessible": True})
        loc_hall = _create_location(engine, world_id, "hall", "大殿",
                                    access_rules={"always_accessible": True})
        loc_sealed = _create_location(engine, world_id, "sealed", "封印之地",
                                      access_rules={"item_required": "key"})

        _set_session_state(engine, session_id, loc_square)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/locations?accessible=true", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        names = [loc["name"] for loc in data]
        assert "广场" in names
        assert "大殿" in names
        assert "封印之地" not in names


class TestGetCurrentLocation:
    def test_get_current_location_returns_detail_with_npcs(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        loc_square = _create_location(engine, world_id, "square", "广场")
        _set_session_state(engine, session_id, loc_square)

        npc_tmpl_id = _create_npc_template(engine, world_id, "elder", "老者")
        _create_npc_state(engine, session_id, npc_tmpl_id, loc_square)

        item_tmpl_id = _create_item_template(engine, world_id, "herb", "灵草")
        _create_inventory_item(engine, session_id, item_tmpl_id, "location", loc_square)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/locations/current", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "广场"
        assert data["is_current"] is True
        assert len(data["npcs_present"]) == 1
        assert data["npcs_present"][0]["name"] == "老者"
        assert len(data["items_present"]) == 1
        assert data["items_present"][0]["name"] == "灵草"

    def test_get_current_location_with_connections(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        loc_a = _create_location(engine, world_id, "loc_a", "A",
                                 access_rules={"always_accessible": True})
        loc_b = _create_location(engine, world_id, "loc_b", "B",
                                 access_rules={"always_accessible": True})

        _set_session_state(engine, session_id, loc_a)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/locations/current", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert loc_b in data["connections"]


class TestGetLocationDetail:
    def test_get_location_by_id_returns_correct_data(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        loc_square = _create_location(engine, world_id, "square", "广场",
                                      description="一个宽阔的广场")
        _set_session_state(engine, session_id, loc_square)

        npc_tmpl = _create_npc_template(engine, world_id, "guard", "守卫")
        _create_npc_state(engine, session_id, npc_tmpl, loc_square)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/locations/{loc_square}", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "广场"
        assert data["description"] == "一个宽阔的广场"
        assert data["is_current"] is True
        assert len(data["npcs_present"]) == 1
        assert data["npcs_present"][0]["name"] == "守卫"

    def test_get_location_404_for_unknown_location(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        loc_square = _create_location(engine, world_id, "square", "广场")
        _set_session_state(engine, session_id, loc_square)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(
            f"/player/sessions/{session_id}/locations/nonexistent-id",
            headers=headers,
        )

        assert resp.status_code == 404

    def test_get_location_404_for_hidden_location(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        loc_square = _create_location(engine, world_id, "square", "广场")
        loc_secret = _create_location(engine, world_id, "secret_room", "密室",
                                      tags=["secret"])
        _set_session_state(engine, session_id, loc_square)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/locations/{loc_secret}", headers=headers)

        assert resp.status_code == 404

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
    SessionModel,
    SessionInventoryItemModel,
    ItemTemplateModel,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    SessionRepository,
    SessionInventoryItemRepository,
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


def _create_world(db_engine, code=None):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        repo = WorldRepository(db)
        world = repo.create({
            "code": code or f"test_world_{uuid.uuid4().hex[:8]}",
            "name": "Test World",
            "genre": "xianxia",
            "status": "active",
        })
        return world.id, world.code
    finally:
        db.close()


def _create_user_and_token(client):
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePass123!"
    resp = client.post("/auth/register", json={
        "username": username,
        "email": email,
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


def _create_item_template(engine, world_id, code, name, item_type, rarity="common", effects=None, description=None):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = ItemTemplateRepository(db)
        template = repo.create({
            "world_id": world_id,
            "code": code,
            "name": name,
            "item_type": item_type,
            "rarity": rarity,
            "effects_json": effects or {},
            "description": description or f"A {name} item.",
        })
        return template.id
    finally:
        db.close()


def _create_inventory_item(engine, session_id, template_id, quantity=1, durability=None, bound=False):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        repo = SessionInventoryItemRepository(db)
        item = repo.create({
            "session_id": session_id,
            "item_template_id": template_id,
            "owner_type": "player",
            "quantity": quantity,
            "durability": durability,
            "bound_flag": bound,
        })
        return item.id
    finally:
        db.close()


class TestListInventory:
    def test_inventory_returns_list(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        tmpl_id = _create_item_template(engine, world_id, "hp_potion", "回血丹", "consumable", "common",
                                        {"effect": "restore_hp"})
        _create_inventory_item(engine, session_id, tmpl_id, quantity=3)

        tmpl_id2 = _create_item_template(engine, world_id, "wood_sword", "木剑", "equipment", "common",
                                         {"atk": "+2"})
        _create_inventory_item(engine, session_id, tmpl_id2, quantity=1)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/inventory", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = [item["name"] for item in data]
        assert "回血丹" in names
        assert "木剑" in names

    def test_inventory_with_category_filter(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        tmpl_consumable = _create_item_template(engine, world_id, "hp_potion2", "回血丹", "consumable")
        _create_inventory_item(engine, session_id, tmpl_consumable, quantity=5)
        tmpl_equipment = _create_item_template(engine, world_id, "iron_sword", "铁剑", "equipment", "rare")
        _create_inventory_item(engine, session_id, tmpl_equipment, quantity=1)

        headers = {"Authorization": f"Bearer {token}"}
        resp_all = client.get(f"/player/sessions/{session_id}/inventory", headers=headers)
        assert resp_all.status_code == 200
        assert len(resp_all.json()) == 2

        resp_consumable = client.get(
            f"/player/sessions/{session_id}/inventory?category=consumable", headers=headers)
        assert resp_consumable.status_code == 200
        data = resp_consumable.json()
        assert len(data) == 1
        assert data[0]["name"] == "回血丹"
        assert data[0]["item_type"] == "consumable"

        resp_equipment = client.get(
            f"/player/sessions/{session_id}/inventory?category=equipment", headers=headers)
        assert resp_equipment.status_code == 200
        data2 = resp_equipment.json()
        assert len(data2) == 1
        assert data2[0]["name"] == "铁剑"
        assert data2[0]["rarity"] == "rare"

    def test_empty_inventory_returns_empty_list(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/inventory", headers=headers)

        assert resp.status_code == 200
        assert resp.json() == []


class TestGetInventoryItem:
    def test_item_detail_returns_correct_fields(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        tmpl_id = _create_item_template(engine, world_id, "fire_sword", "烈焰剑", "equipment", "legendary",
                                        {"atk": "+15", "fire": True}, "一把燃烧的剑")
        inv_id = _create_inventory_item(engine, session_id, tmpl_id, quantity=1, durability=100, bound=True)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/inventory/{inv_id}", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == inv_id
        assert data["name"] == "烈焰剑"
        assert data["quantity"] == 1
        assert data["rarity"] == "legendary"
        assert data["item_type"] == "equipment"
        assert data["durability"] == 100
        assert data["bound_flag"] is True
        assert data["effects"] == {"atk": "+15", "fire": True}
        assert data["description"] == "一把燃烧的剑"

    def test_item_detail_404_for_unknown_item(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(
            f"/player/sessions/{session_id}/inventory/nonexistent-id",
            headers=headers,
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_item_detail_404_wrong_session(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_a = _create_session(engine, user_id, world_id)
        session_b = _create_session(engine, user_id, world_id)

        tmpl_id = _create_item_template(engine, world_id, "dagger", "匕首", "equipment")
        inv_id = _create_inventory_item(engine, session_a, tmpl_id)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_b}/inventory/{inv_id}", headers=headers)

        assert resp.status_code == 404


class TestInventoryStats:
    def test_stats_returns_summary(self, client, engine):
        token, user_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_id = _create_session(engine, user_id, world_id)

        tmpl_consumable = _create_item_template(engine, world_id, "mana_potion", "回蓝药", "consumable")
        _create_inventory_item(engine, session_id, tmpl_consumable, quantity=10)
        tmpl_equipment = _create_item_template(engine, world_id, "staff", "法杖", "equipment", "epic")
        _create_inventory_item(engine, session_id, tmpl_equipment, quantity=1)
        tmpl_key = _create_item_template(engine, world_id, "gate_key", "石门钥匙", "key_item", "rare")
        _create_inventory_item(engine, session_id, tmpl_key, quantity=1)

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/player/sessions/{session_id}/inventory/stats", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_items"] == 12
        assert data["unique_items"] == 3
        assert data["categories"]["consumable"] == 10
        assert data["categories"]["equipment"] == 1
        assert data["categories"]["key_item"] == 1
        assert data["categories"]["quest_item"] == 0
        assert data["categories"]["other"] == 0
        assert data["total_weight"] == 0.0


class TestAuthAndAccess:
    def test_unauthenticated_returns_401(self, client, engine):
        world_id, _ = _create_world(engine)
        token, user_id = _create_user_and_token(client)
        session_id = _create_session(engine, user_id, world_id)

        resp = client.get(f"/player/sessions/{session_id}/inventory")
        assert resp.status_code == 401

    def test_cross_user_access_denied(self, client, engine):
        token_user1, user1_id = _create_user_and_token(client)
        world_id, _ = _create_world(engine)
        session_id = _create_session(engine, user1_id, world_id)

        token_user2, _ = _create_user_and_token(client)
        headers = {"Authorization": f"Bearer {token_user2}"}

        resp = client.get(f"/player/sessions/{session_id}/inventory", headers=headers)
        assert resp.status_code == 403

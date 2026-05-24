"""
Integration tests for Player API endpoints.

Tests the 4 player API endpoints end-to-end through the FastAPI test client:
- GET /player/sessions/{session_id}/quests
- GET /player/sessions/{session_id}/inventory
- GET /player/sessions/{session_id}/relationships
- GET /player/sessions/{session_id}/locations

Each endpoint is tested for:
- Happy path: returns HTTP 200 with correct JSON shape
- Empty state: returns empty array/zero-total when no data
- Error state: returns appropriate error for invalid session ID
- Auth: returns 401 without token, 403 for wrong user
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel,
    WorldModel,
    SessionModel,
    SessionStateModel,
    QuestTemplateModel,
    QuestStepModel,
    SessionQuestStateModel,
    ItemTemplateModel,
    SessionInventoryItemModel,
    NPCTemplateModel,
    SessionNPCStateModel,
    NPCRelationshipMemoryModel,
    LocationModel,
)
from llm_rpg.storage.repositories import (
    UserRepository,
    WorldRepository,
    SessionRepository,
    SessionStateRepository,
    QuestTemplateRepository,
    QuestStepRepository,
    SessionQuestStateRepository,
    ItemTemplateRepository,
    SessionInventoryItemRepository,
    NPCTemplateRepository,
    SessionNPCStateRepository,
    LocationRepository,
)
from llm_rpg.main import app


TEST_DATABASE_URL = "sqlite:///:memory:"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =============================================================================
# Fixtures
# =============================================================================

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


# =============================================================================
# Helpers
# =============================================================================

def _new_db(db_engine) -> Session:
    return sessionmaker(bind=db_engine)()


def _make_user(db: Session, username: str, is_admin: bool = False) -> UserModel:
    return UserRepository(db).create({
        "username": username,
        "email": f"{username}@test.local",
        "password_hash": pwd_context.hash("testpass123"),
        "is_admin": is_admin,
    })


def _make_world(db: Session, code: str, name: str) -> WorldModel:
    return WorldRepository(db).create({"code": code, "name": name, "status": "active"})


def _make_session(db: Session, user_id: str, world_id: str) -> SessionModel:
    return SessionRepository(db).create({
        "user_id": user_id,
        "world_id": world_id,
        "status": "active",
    })


def _make_session_state(db: Session, session_id: str, current_location_id: str) -> SessionStateModel:
    return SessionStateRepository(db).create_or_update({
        "session_id": session_id,
        "current_location_id": current_location_id,
        "active_mode": "exploration",
    })


def _make_location(db: Session, world_id: str, code: str, name: str,
                   tags=None, access_rules=None, description=None) -> LocationModel:
    return LocationRepository(db).create({
        "world_id": world_id,
        "code": code,
        "name": name,
        "tags": tags or [],
        "access_rules": access_rules or {},
        "description": description or f"A location called {name}.",
    })


def _make_quest_template(db: Session, world_id: str, code: str, name: str,
                         quest_type: str = "main", visibility: str = "visible",
                         summary: str = None) -> QuestTemplateModel:
    return QuestTemplateRepository(db).create({
        "world_id": world_id,
        "code": code,
        "name": name,
        "quest_type": quest_type,
        "visibility": visibility,
        "summary": summary,
    })


def _make_quest_step(db: Session, quest_template_id: str, step_no: int,
                     objective: str) -> QuestStepModel:
    return QuestStepRepository(db).create({
        "quest_template_id": quest_template_id,
        "step_no": step_no,
        "objective": objective,
    })


def _make_quest_state(db: Session, session_id: str, quest_template_id: str,
                      status: str = "active", current_step_no: int = 1,
                      progress_json: dict = None,
                      player_visibility: str = "discovered") -> SessionQuestStateModel:
    return SessionQuestStateRepository(db).create({
        "session_id": session_id,
        "quest_template_id": quest_template_id,
        "current_step_no": current_step_no,
        "status": status,
        "progress_json": progress_json or {},
        "player_visibility": player_visibility,
    })


def _make_item_template(db: Session, world_id: str, code: str, name: str,
                        item_type: str = "consumable", rarity: str = "common",
                        effects_json: dict = None, description: str = None) -> ItemTemplateModel:
    return ItemTemplateRepository(db).create({
        "world_id": world_id,
        "code": code,
        "name": name,
        "item_type": item_type,
        "rarity": rarity,
        "effects_json": effects_json or {},
        "description": description or f"A {name} item.",
    })


def _make_inventory_item(db: Session, session_id: str, item_template_id: str,
                         owner_type: str = "player", owner_ref_id: str = None,
                         quantity: int = 1, durability: int = None,
                         bound_flag: bool = False) -> SessionInventoryItemModel:
    return SessionInventoryItemRepository(db).create({
        "session_id": session_id,
        "item_template_id": item_template_id,
        "owner_type": owner_type,
        "owner_ref_id": owner_ref_id,
        "quantity": quantity,
        "durability": durability,
        "bound_flag": bound_flag,
    })


def _make_npc_template(db: Session, world_id: str, code: str, name: str,
                       role_type: str = "npc", public_identity: str = None) -> NPCTemplateModel:
    return NPCTemplateRepository(db).create({
        "world_id": world_id,
        "code": code,
        "name": name,
        "role_type": role_type,
        "public_identity": public_identity or "A mysterious figure",
    })


def _make_npc_state(db: Session, session_id: str, npc_template_id: str,
                    trust_score: int = 50, suspicion_score: int = 0,
                    current_location_id: str = None,
                    status_flags: dict = None) -> SessionNPCStateModel:
    return SessionNPCStateRepository(db).create({
        "session_id": session_id,
        "npc_template_id": npc_template_id,
        "trust_score": trust_score,
        "suspicion_score": suspicion_score,
        "current_location_id": current_location_id,
        "status_flags": status_flags or {},
    })


def _make_relationship_memory(db: Session, session_id: str, npc_id: str,
                              target_id: str, turn: int,
                              content: str) -> NPCRelationshipMemoryModel:
    return NPCRelationshipMemoryModel(
        id=f"rel_mem_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        npc_id=npc_id,
        target_id=target_id,
        content=content,
        created_turn=turn,
    )


def _get_token(client: TestClient, username: str, password: str = "testpass123") -> str:
    resp = client.post("/auth/login", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["access_token"]


# =============================================================================
# Integration Tests: Player Quests
# =============================================================================

class TestPlayerQuestsIntegration:
    """Integration tests for GET /player/sessions/{session_id}/quests"""

    def test_quests_happy_path_returns_200_with_data(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Quest World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            qt = _make_quest_template(db, world.id, "q1", "寻仙之路",
                                      summary="踏上修仙之旅")
            _make_quest_step(db, qt.id, 1, "找到灵根")
            _make_quest_step(db, qt.id, 2, "通过试炼")
            _make_quest_state(db, session.id, qt.id, "active", 2,
                              progress_json={"step_1": True})
            db.commit()

            session_id = session.id
            qt_id = qt.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/quests",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        quest = data[0]
        assert quest["quest_id"] == qt_id
        assert quest["title"] == "寻仙之路"
        assert quest["description"] == "踏上修仙之旅"
        assert quest["stage"] == 2
        assert quest["status"] == "active"
        assert len(quest["objectives"]) == 2
        assert quest["objectives"][0]["completed"] is True
        assert quest["objectives"][1]["completed"] is False

    def test_quests_empty_state_returns_empty_list(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Empty Quest World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            db.commit()

            session_id = session.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/quests",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_quests_invalid_session_returns_404(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            db.commit()
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            "/player/sessions/nonexistent-session-id/quests",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_quests_unauthenticated_returns_401(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Auth World")
            db.commit()
            session = _make_session(db, user.id, world.id)
            db.commit()
            session_id = session.id
        finally:
            db.close()

        resp = client.get(f"/player/sessions/{session_id}/quests")
        assert resp.status_code == 401

    def test_quests_cross_user_returns_403(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user_a = _make_user(db, f"ua_{uuid.uuid4().hex[:6]}")
            user_b = _make_user(db, f"ub_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Cross World")
            db.commit()

            session_a = _make_session(db, user_a.id, world.id)
            db.commit()

            session_a_id = session_a.id
            token_b = _get_token(client, user_b.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_a_id}/quests",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 403


# =============================================================================
# Integration Tests: Player Inventory
# =============================================================================

class TestPlayerInventoryIntegration:
    """Integration tests for GET /player/sessions/{session_id}/inventory"""

    def test_inventory_happy_path_returns_200_with_items(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Inv World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            tmpl = _make_item_template(db, world.id, "sword", "灵剑",
                                       item_type="equipment", rarity="rare",
                                       effects_json={"atk": "+10"})
            _make_inventory_item(db, session.id, tmpl.id, quantity=1, durability=100)
            db.commit()

            session_id = session.id
            tmpl_id = tmpl.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/inventory",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert item["name"] == "灵剑"
        assert item["quantity"] == 1
        assert item["rarity"] == "rare"
        assert item["item_type"] == "equipment"
        assert item["effects"] == {"atk": "+10"}

    def test_inventory_empty_state_returns_empty_list(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Empty Inv World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            db.commit()

            session_id = session.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/inventory",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_inventory_invalid_session_returns_404(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            db.commit()
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            "/player/sessions/nonexistent-session-id/inventory",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_inventory_unauthenticated_returns_401(self, client, db_engine):
        resp = client.get("/player/sessions/some-session/inventory")
        assert resp.status_code == 401

    def test_inventory_cross_user_returns_403(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user_a = _make_user(db, f"ua_{uuid.uuid4().hex[:6]}")
            user_b = _make_user(db, f"ub_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Cross Inv World")
            db.commit()

            session_a = _make_session(db, user_a.id, world.id)
            db.commit()

            session_a_id = session_a.id
            token_b = _get_token(client, user_b.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_a_id}/inventory",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 403


# =============================================================================
# Integration Tests: Player Relationships
# =============================================================================

class TestPlayerRelationshipsIntegration:
    """Integration tests for GET /player/sessions/{session_id}/relationships"""

    def test_relationships_happy_path_returns_200_with_data(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Rel World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            npc = _make_npc_template(db, world.id, "elder", "长老",
                                     public_identity="村中智者")
            _make_npc_state(db, session.id, npc.id, trust_score=75,
                            suspicion_score=10,
                            status_flags={"respect_score": 80, "fear_score": 5})
            db.add(_make_relationship_memory(db, session.id, npc.id, "player", 3, "长老传授功法"))
            db.commit()

            session_id = session.id
            npc_id = npc.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert data["total"] == 1
        assert len(data["relationships"]) == 1
        rel = data["relationships"][0]
        assert rel["npc_id"] == npc_id
        assert rel["npc_name"] == "长老"
        assert rel["trust_score"] == 75
        assert rel["respect_score"] == 80
        assert rel["fear_score"] == 5

    def test_relationships_empty_state_returns_zero_total(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Empty Rel World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            db.commit()

            session_id = session.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["relationships"] == []

    def test_relationships_invalid_session_returns_404(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            db.commit()
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            "/player/sessions/nonexistent-session-id/relationships",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_relationships_unauthenticated_returns_401(self, client, db_engine):
        resp = client.get("/player/sessions/some-session/relationships")
        assert resp.status_code == 401

    def test_relationships_cross_user_returns_403(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user_a = _make_user(db, f"ua_{uuid.uuid4().hex[:6]}")
            user_b = _make_user(db, f"ub_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Cross Rel World")
            db.commit()

            session_a = _make_session(db, user_a.id, world.id)
            db.commit()

            session_a_id = session_a.id
            token_b = _get_token(client, user_b.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_a_id}/relationships",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 403


# =============================================================================
# Integration Tests: Player Locations
# =============================================================================

class TestPlayerLocationsIntegration:
    """Integration tests for GET /player/sessions/{session_id}/locations"""

    def test_locations_happy_path_returns_200_with_data(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Loc World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            loc_square = _make_location(db, world.id, "square", "广场",
                                        description="一个宽阔的广场")
            loc_hall = _make_location(db, world.id, "hall", "大殿",
                                      description="庄严的大殿")
            _make_session_state(db, session.id, loc_square.id)
            db.commit()

            session_id = session.id
            loc_square_id = loc_square.id
            loc_hall_id = loc_hall.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/locations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        loc_ids = {loc["location_id"] for loc in data}
        assert loc_square_id in loc_ids
        assert loc_hall_id in loc_ids

        # Verify current location is marked
        square_loc = next(l for l in data if l["location_id"] == loc_square_id)
        assert square_loc["is_current"] is True
        assert square_loc["name"] == "广场"

    def test_locations_empty_state_returns_empty_list(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Empty Loc World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            # No locations created, no session state set
            db.commit()

            session_id = session.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/locations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_locations_invalid_session_returns_404(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            db.commit()
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            "/player/sessions/nonexistent-session-id/locations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_locations_unauthenticated_returns_401(self, client, db_engine):
        resp = client.get("/player/sessions/some-session/locations")
        assert resp.status_code == 401

    def test_locations_cross_user_returns_403(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user_a = _make_user(db, f"ua_{uuid.uuid4().hex[:6]}")
            user_b = _make_user(db, f"ub_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Cross Loc World")
            db.commit()

            session_a = _make_session(db, user_a.id, world.id)
            db.commit()

            session_a_id = session_a.id
            token_b = _get_token(client, user_b.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_a_id}/locations",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 403

    def test_locations_hidden_locations_excluded(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"w_{uuid.uuid4().hex[:6]}", "Hidden World")
            db.commit()

            session = _make_session(db, user.id, world.id)
            loc_square = _make_location(db, world.id, "square", "广场")
            loc_secret = _make_location(db, world.id, "secret", "密室",
                                        tags=["hidden"])
            _make_session_state(db, session.id, loc_square.id)
            db.commit()

            session_id = session.id
            token = _get_token(client, user.username)
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/locations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        names = [loc["name"] for loc in data]
        assert "广场" in names
        assert "密室" not in names


# =============================================================================
# Integration Tests: Cross-Endpoint Session Consistency
# =============================================================================

class TestPlayerAPISessionConsistency:
    """Verify all 4 endpoints use the same session ownership check."""

    def test_all_endpoints_reject_invalid_session(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
            db.commit()
            token = _get_token(client, user.username)
        finally:
            db.close()

        headers = {"Authorization": f"Bearer {token}"}
        fake_session = "nonexistent-session-id"

        resp_quests = client.get(f"/player/sessions/{fake_session}/quests", headers=headers)
        resp_inv = client.get(f"/player/sessions/{fake_session}/inventory", headers=headers)
        resp_rel = client.get(f"/player/sessions/{fake_session}/relationships", headers=headers)
        resp_loc = client.get(f"/player/sessions/{fake_session}/locations", headers=headers)

        assert resp_quests.status_code == 404
        assert resp_inv.status_code == 404
        assert resp_rel.status_code == 404
        assert resp_loc.status_code == 404

    def test_all_endpoints_reject_unauthenticated(self, client, db_engine):
        fake_session = "some-session-id"

        resp_quests = client.get(f"/player/sessions/{fake_session}/quests")
        resp_inv = client.get(f"/player/sessions/{fake_session}/inventory")
        resp_rel = client.get(f"/player/sessions/{fake_session}/relationships")
        resp_loc = client.get(f"/player/sessions/{fake_session}/locations")

        assert resp_quests.status_code == 401
        assert resp_inv.status_code == 401
        assert resp_rel.status_code == 401
        assert resp_loc.status_code == 401

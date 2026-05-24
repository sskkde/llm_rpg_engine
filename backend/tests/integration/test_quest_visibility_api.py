"""
Integration tests for quest visibility API.

Tests:
- Hidden quest not returned by Player API list_quests endpoint
- Discovered quest returned by Player API
- Hidden quest returns 404 on detail endpoint
- Completed quest auto-promoted to discovered
- reveal_quest sets player_visibility and revealed_at
- Admin/debug API can see hidden quests
"""

import pytest
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel,
    WorldModel,
    SessionModel,
    QuestTemplateModel,
    QuestStepModel,
    SessionQuestStateModel,
)
from llm_rpg.storage.repositories import (
    UserRepository,
    WorldRepository,
    SessionRepository,
    QuestTemplateRepository,
    QuestStepRepository,
    SessionQuestStateRepository,
)
from llm_rpg.services.quest_journal_service import QuestJournalService
from llm_rpg.main import app
from passlib.context import CryptContext


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


def _make_quest_template(
    db: Session, world_id: str, code: str, name: str, visibility: str = "visible"
) -> QuestTemplateModel:
    return QuestTemplateRepository(db).create({
        "world_id": world_id,
        "code": code,
        "name": name,
        "quest_type": "main",
        "visibility": visibility,
    })


def _make_quest_step(db: Session, quest_template_id: str, step_no: int, objective: str) -> QuestStepModel:
    return QuestStepRepository(db).create({
        "quest_template_id": quest_template_id,
        "step_no": step_no,
        "objective": objective,
    })


def _make_quest_state(
    db: Session,
    session_id: str,
    quest_template_id: str,
    status: str = "active",
    player_visibility: str = "hidden",
    current_step_no: int = 1,
) -> SessionQuestStateModel:
    return SessionQuestStateRepository(db).create({
        "session_id": session_id,
        "quest_template_id": quest_template_id,
        "current_step_no": current_step_no,
        "status": status,
        "progress_json": {},
        "player_visibility": player_visibility,
    })


def _get_token(client: TestClient, username: str, password: str = "testpass123") -> str:
    resp = client.post("/auth/login", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["access_token"]


# =============================================================================
# Tests: Hidden Quest Not Returned
# =============================================================================

class TestHiddenQuestNotReturned:
    """Test that hidden quests are not returned by Player API."""

    def test_hidden_quest_not_in_list(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "hidden_quest", "Hidden Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="hidden")
            db.commit()

            token = _get_token(client, user.username)
            session_id = session.id
            quest_id = quest.id
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/quests",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        quest_ids = [q["quest_id"] for q in data]
        assert quest_id not in quest_ids

    def test_hidden_quest_returns_404_on_detail(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "hidden_quest", "Hidden Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="hidden")
            db.commit()

            token = _get_token(client, user.username)
            session_id = session.id
            quest_id = quest.id
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/quests/{quest_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 404


# =============================================================================
# Tests: Discovered Quest Returned
# =============================================================================

class TestDiscoveredQuestReturned:
    """Test that discovered quests are returned by Player API."""

    def test_discovered_quest_in_list(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "discovered_quest", "Discovered Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="discovered")
            db.commit()

            token = _get_token(client, user.username)
            session_id = session.id
            quest_id = quest.id
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/quests",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        quest_ids = [q["quest_id"] for q in data]
        assert quest_id in quest_ids

    def test_discovered_quest_detail_returns_200(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "discovered_quest", "Discovered Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="discovered")
            db.commit()

            token = _get_token(client, user.username)
            session_id = session.id
            quest_id = quest.id
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/quests/{quest_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["quest_id"] == quest_id
        assert data["title"] == "Discovered Quest"

    def test_archived_quest_in_list(self, client, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "archived_quest", "Archived Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="archived")
            db.commit()

            token = _get_token(client, user.username)
            session_id = session.id
            quest_id = quest.id
        finally:
            db.close()

        resp = client.get(
            f"/player/sessions/{session_id}/quests",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        quest_ids = [q["quest_id"] for q in data]
        assert quest_id in quest_ids


# =============================================================================
# Tests: Completed Quest Auto-Promoted
# =============================================================================

class TestCompletedQuestAutoPromoted:
    """Test that completed quests are auto-promoted to discovered."""

    def test_completed_quest_visible_after_reveal(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "completed_quest", "Completed Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            quest_state = _make_quest_state(
                db, session.id, quest.id,
                status="completed",
                player_visibility="hidden",
            )
            db.commit()

            service = QuestJournalService(db)
            result = service.reveal_quest(session.id, quest.id)

            assert result.player_visibility == "discovered"
            assert result.revealed_at is not None
        finally:
            db.close()

    def test_failed_quest_visible_after_reveal(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "failed_quest", "Failed Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            quest_state = _make_quest_state(
                db, session.id, quest.id,
                status="failed",
                player_visibility="hidden",
            )
            db.commit()

            service = QuestJournalService(db)
            result = service.reveal_quest(session.id, quest.id)

            assert result.player_visibility == "discovered"
            assert result.revealed_at is not None
        finally:
            db.close()


# =============================================================================
# Tests: reveal_quest Sets Fields
# =============================================================================

class TestRevealQuestSetsFields:
    """Test that reveal_quest sets player_visibility and revealed_at."""

    def test_reveal_sets_visibility_to_discovered(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "reveal_quest", "Reveal Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="hidden")
            db.commit()

            service = QuestJournalService(db)
            result = service.reveal_quest(session.id, quest.id)

            assert result.player_visibility == "discovered"
        finally:
            db.close()

    def test_reveal_sets_revealed_at(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "reveal_quest", "Reveal Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="hidden")
            db.commit()

            before = datetime.now(timezone.utc)
            service = QuestJournalService(db)
            result = service.reveal_quest(session.id, quest.id)
            after = datetime.now(timezone.utc)

            assert result.revealed_at is not None
            revealed_at = result.revealed_at
            if revealed_at.tzinfo is None:
                revealed_at = revealed_at.replace(tzinfo=timezone.utc)
            assert before <= revealed_at <= after
        finally:
            db.close()

    def test_reveal_sets_source_event_id(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "reveal_quest", "Reveal Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="hidden")
            db.commit()

            service = QuestJournalService(db)
            result = service.reveal_quest(
                session.id, quest.id, source_event_id="event-123"
            )

            assert result.reveal_source_event_id == "event-123"
        finally:
            db.close()

    def test_reveal_sets_initial_step(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "reveal_quest", "Reveal Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="hidden")
            db.commit()

            service = QuestJournalService(db)
            result = service.reveal_quest(session.id, quest.id, initial_step=3)

            assert result.last_revealed_step_no == 3
        finally:
            db.close()

    def test_reveal_is_idempotent(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "reveal_quest", "Reveal Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="hidden")
            db.commit()

            service = QuestJournalService(db)
            result1 = service.reveal_quest(session.id, quest.id)
            revealed_at_1 = result1.revealed_at

            result2 = service.reveal_quest(session.id, quest.id)

            assert result2.player_visibility == "discovered"
            assert result2.revealed_at == revealed_at_1
        finally:
            db.close()


# =============================================================================
# Tests: Admin/Debug Can See Hidden
# =============================================================================

class TestAdminCanSeeHidden:
    """Test that admin/debug can see hidden quests via service."""

    def test_service_get_all_includes_hidden(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest1 = _make_quest_template(db, world.id, "hidden_quest", "Hidden Quest")
            quest2 = _make_quest_template(db, world.id, "visible_quest", "Visible Quest")
            _make_quest_step(db, quest1.id, 1, "First step")
            _make_quest_step(db, quest2.id, 1, "First step")
            _make_quest_state(db, session.id, quest1.id, player_visibility="hidden")
            _make_quest_state(db, session.id, quest2.id, player_visibility="discovered")
            db.commit()

            repo = SessionQuestStateRepository(db)
            all_states = repo.get_by_session(session.id)

            quest_ids = [qs.quest_template_id for qs in all_states]
            assert quest1.id in quest_ids
            assert quest2.id in quest_ids
        finally:
            db.close()

    def test_service_list_visible_excludes_hidden(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest1 = _make_quest_template(db, world.id, "hidden_quest", "Hidden Quest")
            quest2 = _make_quest_template(db, world.id, "visible_quest", "Visible Quest")
            _make_quest_step(db, quest1.id, 1, "First step")
            _make_quest_step(db, quest2.id, 1, "First step")
            _make_quest_state(db, session.id, quest1.id, player_visibility="hidden")
            _make_quest_state(db, session.id, quest2.id, player_visibility="discovered")
            db.commit()

            service = QuestJournalService(db)
            visible = service.list_visible_quests(session.id)

            quest_ids = [qs.quest_template_id for qs in visible]
            assert quest1.id not in quest_ids
            assert quest2.id in quest_ids
        finally:
            db.close()


# =============================================================================
# Tests: Hide Quest
# =============================================================================

class TestHideQuest:
    """Test that hide_quest sets player_visibility to hidden."""

    def test_hide_sets_visibility_to_hidden(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest = _make_quest_template(db, world.id, "hide_quest", "Hide Quest")
            _make_quest_step(db, quest.id, 1, "First step")
            _make_quest_state(db, session.id, quest.id, player_visibility="discovered")
            db.commit()

            service = QuestJournalService(db)
            result = service.hide_quest(session.id, quest.id)

            assert result.player_visibility == "hidden"
        finally:
            db.close()

    def test_hide_raises_for_nonexistent(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            db.commit()

            service = QuestJournalService(db)
            with pytest.raises(ValueError, match="Quest state not found"):
                service.hide_quest(session.id, "nonexistent-quest")
        finally:
            db.close()


# =============================================================================
# Tests: Visibility Status Filter
# =============================================================================

class TestVisibilityStatusFilter:
    """Test filtering by status in list_visible_quests."""

    def test_filter_by_active_status(self, db_engine):
        db = _new_db(db_engine)
        try:
            user = _make_user(db, f"quest_user_{uuid.uuid4().hex[:6]}")
            world = _make_world(db, f"quest_world_{uuid.uuid4().hex[:6]}", "Quest World")
            session = _make_session(db, user.id, world.id)
            quest1 = _make_quest_template(db, world.id, "active_quest", "Active Quest")
            quest2 = _make_quest_template(db, world.id, "completed_quest", "Completed Quest")
            _make_quest_step(db, quest1.id, 1, "First step")
            _make_quest_step(db, quest2.id, 1, "First step")
            _make_quest_state(
                db, session.id, quest1.id,
                status="active",
                player_visibility="discovered"
            )
            _make_quest_state(
                db, session.id, quest2.id,
                status="completed",
                player_visibility="discovered"
            )
            db.commit()

            service = QuestJournalService(db)
            active = service.list_visible_quests(session.id, status="active")

            quest_ids = [qs.quest_template_id for qs in active]
            assert quest1.id in quest_ids
            assert quest2.id not in quest_ids
        finally:
            db.close()

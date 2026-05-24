"""Unit tests for QuestJournalService."""

import pytest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from llm_rpg.storage.models import Base, SessionQuestStateModel
from llm_rpg.storage.repositories import SessionQuestStateRepository
from llm_rpg.services.quest_journal_service import QuestJournalService


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def quest_state_repo(db_session):
    return SessionQuestStateRepository(db_session)


@pytest.fixture
def service(db_session):
    return QuestJournalService(db_session)


def _create_quest_state(repo, db_session, **overrides):
    data = {
        "id": f"qs-{overrides.get('quest_template_id', 'test')}",
        "session_id": "session-1",
        "quest_template_id": "quest-1",
        "current_step_no": 1,
        "progress_json": {},
        "status": "active",
        "player_visibility": "hidden",
    }
    data.update(overrides)
    quest_state = repo.create(data)
    db_session.commit()
    return quest_state


class TestRevealQuest:
    def test_reveal_quest_sets_discovered(self, service, quest_state_repo, db_session):
        _create_quest_state(quest_state_repo, db_session, quest_template_id="quest-reveal-1")

        result = service.reveal_quest("session-1", "quest-reveal-1")

        assert result.player_visibility == "discovered"
        assert result.revealed_at is not None

    def test_reveal_quest_sets_source_event_id(self, service, quest_state_repo, db_session):
        _create_quest_state(quest_state_repo, db_session, quest_template_id="quest-event-1")

        result = service.reveal_quest(
            "session-1",
            "quest-event-1",
            source_event_id="event-123",
        )

        assert result.reveal_source_event_id == "event-123"

    def test_reveal_quest_sets_initial_step(self, service, quest_state_repo, db_session):
        _create_quest_state(quest_state_repo, db_session, quest_template_id="quest-step-1")

        result = service.reveal_quest(
            "session-1",
            "quest-step-1",
            initial_step=3,
        )

        assert result.last_revealed_step_no == 3

    def test_reveal_quest_idempotent(self, service, quest_state_repo, db_session):
        _create_quest_state(quest_state_repo, db_session, quest_template_id="quest-idem-1")

        result1 = service.reveal_quest("session-1", "quest-idem-1")
        revealed_at_1 = result1.revealed_at

        result2 = service.reveal_quest("session-1", "quest-idem-1")

        assert result2.player_visibility == "discovered"
        assert result2.revealed_at == revealed_at_1

    def test_reveal_quest_raises_for_nonexistent(self, service):
        with pytest.raises(ValueError, match="Quest state not found"):
            service.reveal_quest("session-1", "nonexistent-quest")

    def test_reveal_quest_auto_promotes_completed(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-completed-1",
            status="completed",
            player_visibility="hidden",
        )

        result = service.reveal_quest("session-1", "quest-completed-1")

        assert result.player_visibility == "discovered"
        assert result.revealed_at is not None

    def test_reveal_quest_auto_promotes_failed(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-failed-1",
            status="failed",
            player_visibility="hidden",
        )

        result = service.reveal_quest("session-1", "quest-failed-1")

        assert result.player_visibility == "discovered"
        assert result.revealed_at is not None


class TestRevealObjective:
    def test_reveal_objective_updates_step(self, service, quest_state_repo, db_session):
        _create_quest_state(quest_state_repo, db_session, quest_template_id="quest-obj-1")

        result = service.reveal_objective("session-1", "quest-obj-1", step_no=2)

        assert result.last_revealed_step_no == 2
        assert result.player_visibility == "discovered"

    def test_reveal_objective_takes_max(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-obj-max",
            last_revealed_step_no=3,
        )

        result = service.reveal_objective("session-1", "quest-obj-max", step_no=2)

        assert result.last_revealed_step_no == 3

        result2 = service.reveal_objective("session-1", "quest-obj-max", step_no=5)
        assert result2.last_revealed_step_no == 5

    def test_reveal_objective_ensures_discovered(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-obj-hidden",
            player_visibility="hidden",
        )

        result = service.reveal_objective("session-1", "quest-obj-hidden", step_no=1)

        assert result.player_visibility == "discovered"
        assert result.revealed_at is not None

    def test_reveal_objective_sets_source_event(self, service, quest_state_repo, db_session):
        _create_quest_state(quest_state_repo, db_session, quest_template_id="quest-obj-event")

        result = service.reveal_objective(
            "session-1",
            "quest-obj-event",
            step_no=1,
            source_event_id="event-456",
        )

        assert result.reveal_source_event_id == "event-456"

    def test_reveal_objective_raises_for_nonexistent(self, service):
        with pytest.raises(ValueError, match="Quest state not found"):
            service.reveal_objective("session-1", "nonexistent-quest", step_no=1)


class TestListVisibleQuests:
    def test_list_visible_excludes_hidden(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-visible-1",
            player_visibility="discovered",
        )
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-hidden-1",
            player_visibility="hidden",
        )

        result = service.list_visible_quests("session-1")

        assert len(result) == 1
        assert result[0].quest_template_id == "quest-visible-1"

    def test_list_visible_with_status_filter(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-active-1",
            player_visibility="discovered",
            status="active",
        )
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-completed-1",
            player_visibility="discovered",
            status="completed",
        )

        result = service.list_visible_quests("session-1", status="active")

        assert len(result) == 1
        assert result[0].status == "active"

    def test_list_visible_empty_when_none(self, service):
        result = service.list_visible_quests("nonexistent-session")
        assert result == []

    def test_list_visible_includes_archived(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-archived-1",
            player_visibility="archived",
        )

        result = service.list_visible_quests("session-1")

        assert len(result) == 1
        assert result[0].quest_template_id == "quest-archived-1"


class TestGetVisibleQuestDetail:
    def test_get_visible_returns_quest(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-detail-1",
            player_visibility="discovered",
        )

        result = service.get_visible_quest_detail("session-1", "quest-detail-1")

        assert result is not None
        assert result.quest_template_id == "quest-detail-1"

    def test_get_visible_returns_none_for_hidden(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-detail-hidden",
            player_visibility="hidden",
        )

        result = service.get_visible_quest_detail("session-1", "quest-detail-hidden")

        assert result is None

    def test_get_visible_returns_none_for_nonexistent(self, service):
        result = service.get_visible_quest_detail("session-1", "nonexistent-quest")
        assert result is None


class TestHideQuest:
    def test_hide_quest_sets_hidden(self, service, quest_state_repo, db_session):
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-hide-1",
            player_visibility="discovered",
        )

        result = service.hide_quest("session-1", "quest-hide-1")

        assert result.player_visibility == "hidden"

    def test_hide_quest_raises_for_nonexistent(self, service):
        with pytest.raises(ValueError, match="Quest state not found"):
            service.hide_quest("session-1", "nonexistent-quest")


class TestAutoPromoteCompletedFailed:
    def test_completed_quest_always_visible_after_reveal(self, service, quest_state_repo, db_session):
        quest = _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-auto-1",
            status="completed",
            player_visibility="hidden",
        )
        assert quest.player_visibility == "hidden"

        result = service.reveal_quest("session-1", "quest-auto-1")

        assert result.player_visibility == "discovered"

    def test_failed_quest_always_visible_after_reveal(self, service, quest_state_repo, db_session):
        quest = _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-auto-2",
            status="failed",
            player_visibility="hidden",
        )
        assert quest.player_visibility == "hidden"

        result = service.reveal_quest("session-1", "quest-auto-2")

        assert result.player_visibility == "discovered"

    def test_completed_quest_keeps_existing_revealed_at(self, service, quest_state_repo, db_session):
        existing_revealed = datetime(2024, 1, 1, 12, 0, 0)
        _create_quest_state(
            quest_state_repo,
            db_session,
            quest_template_id="quest-auto-3",
            status="completed",
            player_visibility="hidden",
            revealed_at=existing_revealed,
        )

        result = service.reveal_quest("session-1", "quest-auto-3")

        assert result.revealed_at == existing_revealed

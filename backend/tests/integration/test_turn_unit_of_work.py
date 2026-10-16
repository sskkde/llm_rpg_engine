"""Session-scoped managed turn transaction contract tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from llm_rpg.core.turn_allocation import TurnAllocationError, commit_turn
from llm_rpg.core.turn_unit_of_work import TurnUnitOfWork, TurnUnitOfWorkError, is_managed
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import EventLogModel
from llm_rpg.storage.repositories import EventLogRepository


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'turn-uow.sqlite'}", poolclass=NullPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def test_managed_repository_writes_are_invisible_until_explicit_commit(session_factory):
    db = session_factory()
    repo = EventLogRepository(db)
    try:
        with TurnUnitOfWork(db):
            assert is_managed(db)
            repo.create({"session_id": "uow-session", "turn_no": 1, "event_type": "player_turn"})
            repo.create({"session_id": "uow-session", "turn_no": 1, "event_type": "world_event"})
            observer = session_factory()
            try:
                count_before = observer.query(EventLogModel).filter_by(session_id="uow-session").count()
            finally:
                observer.close()
            print(f"second_session_before_commit={count_before}")
            assert count_before == 0
            db.commit()
        assert not is_managed(db)
        observer = session_factory()
        try:
            count_after = observer.query(EventLogModel).filter_by(session_id="uow-session").count()
        finally:
            observer.close()
        assert count_after == 2
    finally:
        db.close()


def test_exception_rolls_back_all_managed_writes_and_restores_marker(session_factory):
    db = session_factory()
    db.info["turn_uow"] = False
    try:
        with pytest.raises(RuntimeError, match="injected"):
            with TurnUnitOfWork(db):
                assert is_managed(db)
                EventLogRepository(db).create({
                    "session_id": "rollback-session", "turn_no": 1, "event_type": "player_turn"
                })
                EventLogRepository(db).create({
                    "session_id": "rollback-session", "turn_no": 1, "event_type": "world_event"
                })
                raise RuntimeError("injected")
        assert db.info["turn_uow"] is False
        observer = session_factory()
        try:
            assert observer.query(EventLogModel).filter_by(session_id="rollback-session").count() == 0
        finally:
            observer.close()
    finally:
        db.close()


def test_repository_outside_managed_scope_still_commits_immediately(session_factory):
    db = session_factory()
    try:
        EventLogRepository(db).create({
            "session_id": "legacy-session", "turn_no": 1, "event_type": "player_turn"
        })
        observer = session_factory()
        try:
            assert observer.query(EventLogModel).filter_by(session_id="legacy-session").count() == 1
        finally:
            observer.close()
    finally:
        db.close()


def test_uow_rejects_preexisting_pending_game_effect(session_factory):
    db = session_factory()
    try:
        db.add(EventLogModel(session_id="dirty-session", turn_no=1, event_type="player_turn"))
        with pytest.raises(TurnUnitOfWorkError, match="pending Session changes"):
            with TurnUnitOfWork(db):
                pytest.fail("must not enter")
        assert not is_managed(db)
        db.rollback()
    finally:
        db.close()


def test_managed_commit_turn_conflict_does_not_return_competitor(session_factory):
    db = session_factory()
    try:
        EventLogRepository(db).create({
            "session_id": "conflict-session", "turn_no": 1, "event_type": "player_turn",
            "structured_action": {"idempotency_key": "other-request"},
        })
        with pytest.raises(TurnAllocationError, match="already owned by another event"):
            with TurnUnitOfWork(db):
                commit_turn(db, "conflict-session", 1, "player_turn", idempotency_key="this-request")
    finally:
        db.close()

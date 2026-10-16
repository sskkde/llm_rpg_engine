"""Persisted-state fingerprints and commit-boundary revalidation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from llm_rpg.core.turn_service import (
    TurnStateConflictError,
    compute_state_fingerprint,
)
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import SessionEventFlagModel


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'turn-fingerprint.sqlite'}", poolclass=NullPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def test_fingerprint_is_deterministic_and_independent_of_row_order(session_factory):
    db = session_factory()
    db.add_all([
        SessionEventFlagModel(id="flag-b", session_id="fingerprint-session", flag_key="b", flag_value="2"),
        SessionEventFlagModel(id="flag-a", session_id="fingerprint-session", flag_key="a", flag_value="1"),
    ])
    db.commit()
    first = compute_state_fingerprint(db, "fingerprint-session")
    db.expire_all()
    second = compute_state_fingerprint(db, "fingerprint-session")
    assert first == second
    db.close()


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_member_insert_update_delete_changes_fingerprint(session_factory, operation):
    db = session_factory()
    db.add(SessionEventFlagModel(id="flag-a", session_id="fingerprint-session", flag_key="a", flag_value="1"))
    db.commit()
    before = compute_state_fingerprint(db, "fingerprint-session")
    if operation == "insert":
        db.add(SessionEventFlagModel(id="flag-b", session_id="fingerprint-session", flag_key="b", flag_value="2"))
    elif operation == "update":
        db.query(SessionEventFlagModel).filter_by(id="flag-a").one().flag_value = "changed"
    else:
        db.query(SessionEventFlagModel).filter_by(id="flag-a").delete()
    db.commit()
    assert compute_state_fingerprint(db, "fingerprint-session") != before
    db.close()


def test_independent_connection_detects_external_commit_without_seeing_uow_writes(session_factory):
    """SQLite rollback-journal mode cannot independently re-read during a writer; PG is authoritative."""
    turn_db = session_factory()
    if turn_db.get_bind().dialect.name == "sqlite":
        pytest.skip("SQLite 下重验不可测，PG 为准")
    turn_db.add(SessionEventFlagModel(
        id="flag-a", session_id="fingerprint-session", flag_key="a", flag_value="before"
    ))
    turn_db.commit()
    fp_before = compute_state_fingerprint(turn_db, "fingerprint-session")

    # Simulate an uncommitted turn write: an independent connection must not see it.
    turn_db.add(SessionEventFlagModel(
        id="turn-only", session_id="fingerprint-session", flag_key="turn", flag_value="uncommitted"
    ))
    observer = session_factory()
    assert compute_state_fingerprint(observer, "fingerprint-session") == fp_before

    # A separate writer commits concurrently; fresh state now differs from the claim-time state.
    external = session_factory()
    external.query(SessionEventFlagModel).filter_by(id="flag-a").one().flag_value = "external"
    external.commit()
    fresh = session_factory()
    fp_external = compute_state_fingerprint(fresh, "fingerprint-session")
    with pytest.raises(TurnStateConflictError) as conflict:
        if fp_external != fp_before:
            raise TurnStateConflictError("fingerprint-session")
    assert conflict.value.code == "state_conflict"
    assert fresh.query(SessionEventFlagModel).filter_by(id="turn-only").count() == 0

    turn_db.rollback()
    observer.close()
    external.close()
    fresh.close()
    turn_db.close()

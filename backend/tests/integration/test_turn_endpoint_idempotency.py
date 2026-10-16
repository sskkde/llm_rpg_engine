"""Endpoint-level idempotency contracts for REST and SSE turn routes."""

from datetime import datetime, timedelta
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.api.auth import get_current_active_user
from llm_rpg.main import app
from llm_rpg.core.turn_claim import compute_request_fingerprint
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    ChapterModel, EventLogModel, LocationModel, NPCTemplateModel, QuestTemplateModel,
    SaveSlotModel, SessionModel, TurnTransactionModel, UserModel, WorldModel,
)


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    session = sessionmaker(bind=db_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded_session(db):
    user = UserModel(id="idempotency_user", username="idem", email="idem@example.com", password_hash="hashed", is_admin=True)
    world = WorldModel(id="idempotency_world", code="idem-world", name="测试世界", genre="xianxia", status="active")
    chapter = ChapterModel(id="idempotency_chapter", world_id=world.id, chapter_no=1, name="第一章")
    locations = [
        LocationModel(id="idempotency_square", world_id=world.id, chapter_id=chapter.id, code="square", name="广场", access_rules={"always_accessible": True}),
        LocationModel(id="idempotency_hall", world_id=world.id, chapter_id=chapter.id, code="hall", name="试炼堂", access_rules={"always_accessible": True}),
    ]
    npc = NPCTemplateModel(id="idempotency_npc", world_id=world.id, code="guide", name="向导", role_type="guide", hidden_identity="secret")
    quest = QuestTemplateModel(id="idempotency_quest", world_id=world.id, code="trial", name="试炼", quest_type="main", visibility="visible")
    slot = SaveSlotModel(id="idempotency_slot", user_id=user.id, slot_number=1, name="测试存档")
    session = SessionModel(id="idempotency_session", user_id=user.id, save_slot_id=slot.id, world_id=world.id, current_chapter_id=chapter.id, status="active")
    db.add_all([user, world, chapter, *locations, npc, quest, slot, session])
    db.commit()
    return session


@pytest.fixture
def client(db_engine, seeded_session, monkeypatch):
    SessionLocal = sessionmaker(bind=db_engine)
    from llm_rpg.api import streaming
    monkeypatch.setattr(streaming, "SessionLocal", SessionLocal)
    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()
    def override_current_user():
        return UserModel(id=seeded_session.user_id, username="idem", email="idem@example.com", is_admin=True)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _turn_events(db: Session, session_id: str) -> int:
    return db.query(EventLogModel).filter_by(
        session_id=session_id, event_type="player_turn"
    ).count()


def test_rest_same_key_replays_one_turn(client, db, seeded_session):
    endpoint = f"/game/sessions/{seeded_session.id}/turn"
    request = {"action": "观察四周", "idempotency_key": "rest-repeat"}

    first = client.post(endpoint, json=request)
    second = client.post(endpoint, json=request)

    assert first.status_code == second.status_code == 200
    first_body, second_body = first.json(), second.json()
    assert first_body["turn_index"] == second_body["turn_index"] == 1
    assert first_body["idempotency_key"] == second_body["idempotency_key"] == "rest-repeat"
    assert _turn_events(db, seeded_session.id) == 1
    assert db.query(TurnTransactionModel).filter_by(session_id=seeded_session.id).count() == 1


def test_rest_without_key_returns_service_uuid(client, seeded_session):
    response = client.post(
        f"/game/sessions/{seeded_session.id}/turn", json={"action": "观察四周"}
    )
    assert response.status_code == 200
    assert str(uuid.UUID(response.json()["idempotency_key"])) == response.json()["idempotency_key"]


def test_rest_fingerprint_conflict_has_no_second_turn(client, db, seeded_session):
    endpoint = f"/game/sessions/{seeded_session.id}/turn"
    first = client.post(endpoint, json={
        "action": "观察四周", "idempotency_key": "fingerprint-conflict",
        "request_fingerprint": "canonical-a",
    })
    before = _turn_events(db, seeded_session.id)
    conflict = client.post(endpoint, json={
        "action": "前往试炼堂", "idempotency_key": "fingerprint-conflict",
        "request_fingerprint": "canonical-b",
    })
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "fingerprint_conflict"
    assert _turn_events(db, seeded_session.id) == before == 1


def test_active_claim_is_fast_rest_conflict(client, db, seeded_session):
    db.add(TurnTransactionModel(
        session_id=seeded_session.id,
        turn_no=1,
        idempotency_key="active-other",
        request_fingerprint="active-fingerprint",
        lease_expires_at=datetime.utcnow() + timedelta(minutes=1),
        fencing_generation=1,
        status="pending",
        started_at=datetime.utcnow(),
    ))
    db.commit()
    response = client.post(
        f"/game/sessions/{seeded_session.id}/turn",
        json={"action": "观察四周", "idempotency_key": "different-key"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "turn_in_progress"
    assert _turn_events(db, seeded_session.id) == 0


def test_same_key_isolated_between_sessions(client, db, seeded_session):
    slot = SaveSlotModel(
        id="endpoint_slot_second", user_id=seeded_session.user_id,
        slot_number=2, name="第二存档",
    )
    other = SessionModel(
        id="endpoint_session_second", user_id=seeded_session.user_id,
        save_slot_id=slot.id, world_id=seeded_session.world_id,
        current_chapter_id=seeded_session.current_chapter_id, status="active",
    )
    db.add_all([slot, other])
    db.commit()
    payload = {"action": "观察四周", "idempotency_key": "shared-key"}

    first = client.post(f"/game/sessions/{seeded_session.id}/turn", json=payload)
    second = client.post(f"/game/sessions/{other.id}/turn", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["turn_index"] == second.json()["turn_index"] == 1
    assert _turn_events(db, seeded_session.id) == _turn_events(db, other.id) == 1


def test_sse_same_key_retry_header_and_conflict_error_event(client, db, seeded_session):
    endpoint = f"/streaming/sessions/{seeded_session.id}/turn/mock"
    with client.stream("POST", endpoint, json={
        "action": "观察四周", "idempotency_key": "sse-repeat"
    }) as response:
        first_body = "".join(response.iter_text())
        assert response.status_code == 200
        assert response.headers["X-Idempotency-Key"] == "sse-repeat"
    with client.stream("POST", endpoint, json={
        "action": "观察四周", "idempotency_key": "sse-repeat"
    }) as response:
        replay_body = "".join(response.iter_text())
        assert response.status_code == 200
        assert response.headers["X-Idempotency-Key"] == "sse-repeat"
    assert "event: turn_completed" in first_body
    assert "event: turn_completed" in replay_body
    assert _turn_events(db, seeded_session.id) == 1

    with client.stream("POST", endpoint, json={
        "action": "另一个动作", "idempotency_key": "sse-repeat"
    }) as response:
        conflict_body = "".join(response.iter_text())
        assert response.status_code == 200
        assert response.headers["X-Idempotency-Key"] == "sse-repeat"
    assert 'event: error' in conflict_body
    assert '"code": "fingerprint_conflict"' in conflict_body
    assert _turn_events(db, seeded_session.id) == 1


def test_sse_and_rest_default_fingerprint_share_service_contract(client, db, seeded_session):
    key = "rest-sse-same-request"
    action = "观察四周"
    rest = client.post(f"/game/sessions/{seeded_session.id}/turn", json={
        "action": action, "idempotency_key": key,
    })
    with client.stream(
        "POST", f"/streaming/sessions/{seeded_session.id}/turn/mock", json={
            "action": action, "idempotency_key": key,
        }
    ) as response:
        stream_body = "".join(response.iter_text())
        assert response.headers["X-Idempotency-Key"] == key
    assert rest.status_code == 200
    assert "event: turn_completed" in stream_body
    claim = db.query(TurnTransactionModel).filter_by(
        session_id=seeded_session.id, idempotency_key=key
    ).one()
    assert claim.request_fingerprint == compute_request_fingerprint(action, None)
    assert _turn_events(db, seeded_session.id) == 1


def test_committed_claim_without_snapshot_maps_recovery_incomplete(client, db, seeded_session):
    action = "观察四周"
    db.add(TurnTransactionModel(
        session_id=seeded_session.id,
        turn_no=1,
        idempotency_key="missing-snapshot",
        request_fingerprint=compute_request_fingerprint(action, None),
        fencing_generation=1,
        status="committed",
        started_at=datetime.utcnow(),
    ))
    db.commit()
    response = client.post(f"/game/sessions/{seeded_session.id}/turn", json={
        "action": action, "idempotency_key": "missing-snapshot",
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "recovery_incomplete"
    assert _turn_events(db, seeded_session.id) == 0

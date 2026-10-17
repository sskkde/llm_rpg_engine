"""Phase-3 visibility boundaries and snapshot rewind guards."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict

import pytest
from sqlalchemy.orm import sessionmaker

from llm_rpg.api.auth import get_current_active_user
from llm_rpg.core import time_simulation_rules as rules
from llm_rpg.core import turn_service
from llm_rpg.core.instance_snapshot_service import (
    SnapshotRewindRefusedError,
    apply_snapshot,
    create_baseline_snapshot,
    restore_snapshot,
)
from llm_rpg.core.time_simulation import PHASE3_NAMESPACE
from llm_rpg.main import app
from llm_rpg.storage.database import get_db
from llm_rpg.storage.models import (
    EventLogModel,
    InstanceSnapshotModel,
    PlaythroughInstanceModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    UserModel,
)

from .time_slice_fixtures import (
    TimeSliceSession,
    intent_stage_result,
    patch_intent_stage,
    run_turn,
    time_slice,  # noqa: F401 - re-exported so pytest can resolve the fixture
)


HIDDEN_FACT_MARKERS = (
    rules.LOCATION_TRIAL_PEAK,
    rules.NPC_A_CODE,
    rules.NPC_B_CODE,
    rules.TOKEN_ITEM_CODE,
    "item_acquired",
    "item_take_failed",
    "item_use_failed",
    "npc_arrived",
    "npc_travel_started",
)


@pytest.fixture
def phase3_client(time_slice: TimeSliceSession, monkeypatch):
    """Route the app and SSE worker to the fixture's isolated SQLite database."""
    from fastapi.testclient import TestClient

    from llm_rpg.api import streaming

    session = time_slice.db.query(SessionModel).filter_by(
        id=time_slice.session_id
    ).one()
    current_user = UserModel(
        id=session.user_id,
        username="phase3-test-user",
        email="phase3-test-user@test.invalid",
        password_hash="x",
        is_admin=False,
    )
    session_factory = sessionmaker(bind=time_slice.db.get_bind(), expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: current_user
    monkeypatch.setattr(streaming, "SessionLocal", session_factory)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def _second_session(time_slice: TimeSliceSession) -> str:
    suffix = uuid.uuid4().hex
    source = time_slice.db.query(SessionModel).filter_by(
        id=time_slice.session_id
    ).one()
    session = SessionModel(
        id=f"session-{suffix}",
        user_id=source.user_id,
        world_id=time_slice.world_id,
        status="active",
    )
    time_slice.db.add(session)
    time_slice.db.commit()
    return session.id


def _assert_no_hidden_facts(value) -> None:
    serialized = json.dumps(value, ensure_ascii=False, default=str).lower()
    for marker in HIDDEN_FACT_MARKERS:
        token_pattern = rf"(?<![a-z0-9_]){re.escape(marker.lower())}(?![a-z0-9_])"
        assert re.search(token_pattern, serialized) is None, (
            f"unexpected hidden fact: {marker}"
        )


def _normalized_engine_facts(time_slice: TimeSliceSession):
    timeline = []
    for event in time_slice.game_events():
        marker = (event.result_json or {}).get(PHASE3_NAMESPACE)
        if not marker:
            continue
        timeline.append({
            "turn_no": event.turn_no,
            "event_type": event.event_type,
            "actor_id": event.actor_id,
            "visibility_scope": event.visibility_scope,
            "step_key": marker.get("step_key"),
            "logical_tick": marker.get("logical_tick"),
            "sequence": marker.get("sequence"),
        })

    token = time_slice.token_owner()
    if token.owner_type == "npc":
        token_owner = next(
            f"npc:{code}"
            for code in (rules.NPC_A_CODE, rules.NPC_B_CODE)
            if time_slice.npc_row(code).id == token.owner_ref_id
        )
    elif token.owner_type == "location":
        token_owner = f"location:{time_slice.location_code(token.owner_ref_id)}"
    else:
        token_owner = f"{token.owner_type}:{token.owner_ref_id}"

    return {
        "timeline": timeline,
        "logical_tick": time_slice.run_state().logical_tick,
        "player_location": time_slice.player_location_code(),
        "npc_locations": {
            code: time_slice.npc_location_code(code)
            for code in (rules.NPC_A_CODE, rules.NPC_B_CODE)
        },
        "token_owner": token_owner,
        "step_statuses": time_slice.step_statuses(),
    }


def _sensitive_snapshot_rows(db, session_id: str):
    result = {}
    for model in (
        SessionNPCStateModel,
        SessionInventoryItemModel,
        SessionStateModel,
    ):
        rows = db.query(model).filter_by(session_id=session_id).order_by(model.id).all()
        result[model.__tablename__] = [
            tuple((column.name, getattr(row, column.name)) for column in model.__table__.columns)
            for row in rows
        ]
    return result


def test_rest_sse_outputs_and_replay_hide_offstage_facts_and_share_engine_effects(
    time_slice: TimeSliceSession, phase3_client, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    service = turn_service.execute_turn_service
    progress_events = []

    def rest_service(**kwargs):
        return service(**kwargs, use_mock=True)

    from llm_rpg.api import game, streaming

    monkeypatch.setattr(game, "execute_turn_service", rest_service)

    def sse_service(**kwargs):
        callback = kwargs.get("progress_callback")
        assert callback is not None

        def collect(event):
            progress_events.append(asdict(event))
            callback(event)

        kwargs["progress_callback"] = collect
        return service(**kwargs)

    monkeypatch.setattr(streaming, "execute_turn_service", sse_service)

    rest_response = phase3_client.post(
        f"/game/sessions/{time_slice.session_id}/turn",
        json={"action": "原地等待片刻", "idempotency_key": "visibility-rest"},
    )
    assert rest_response.status_code == 200, rest_response.text
    rest_body = rest_response.json()
    _assert_no_hidden_facts({
        "narration": rest_body["narration"],
        "recommended_actions": rest_body["recommended_actions"],
    })

    time_slice.db.expire_all()
    player_turn = time_slice.db.query(EventLogModel).filter_by(
        session_id=time_slice.session_id,
        turn_no=1,
        event_type="player_turn",
    ).one()
    _assert_no_hidden_facts(player_turn.result_json)

    replay_response = phase3_client.post(
        f"/game/sessions/{time_slice.session_id}/replay",
        json={"start_turn": 1},
    )
    assert replay_response.status_code == 200, replay_response.text
    replay_body = replay_response.json()
    replay_world = replay_body["reconstructed_state"]["world_state"]
    assert all(not key.startswith("__") for key in replay_world["global_flags"])
    assert PHASE3_NAMESPACE not in json.dumps(replay_body, ensure_ascii=False)
    _assert_no_hidden_facts(replay_body)

    second_id = _second_session(time_slice)
    sse_response = phase3_client.post(
        f"/streaming/sessions/{second_id}/turn/mock",
        json={"action": "原地等待片刻", "idempotency_key": "visibility-sse"},
    )
    assert sse_response.status_code == 200, sse_response.text
    sse_body = sse_response.text
    _assert_no_hidden_facts(sse_body)
    _assert_no_hidden_facts(progress_events)
    assert progress_events

    first = _normalized_engine_facts(time_slice)
    second = TimeSliceSession(
        time_slice.db, {**time_slice.ids, "session_id": second_id}
    )
    time_slice.db.expire_all()
    assert _normalized_engine_facts(second) == first


def test_noncurrent_phase3_location_hides_dynamic_contents_but_current_remains_visible(
    time_slice: TimeSliceSession, phase3_client, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("inspect"))
    run_turn(time_slice, "观察四周")

    peak_id = time_slice.location_id(rules.LOCATION_TRIAL_PEAK)
    state = time_slice.session_state()
    state.current_location_id = peak_id
    time_slice.db.commit()

    current_response = phase3_client.get(
        f"/player/sessions/{time_slice.session_id}/locations/{peak_id}"
    )
    assert current_response.status_code == 200
    current = current_response.json()
    assert current["is_current"] is True
    assert [npc["npc_id"] for npc in current["npcs_present"]] == [
        time_slice.npc_ids[rules.NPC_B_CODE]
    ]
    assert [item["item_id"] for item in current["items_present"]] == [
        time_slice.item_ids[rules.TOKEN_ITEM_CODE]
    ]

    state.current_location_id = time_slice.location_id(rules.LOCATION_MOUNTAIN_GATE)
    time_slice.db.commit()
    noncurrent_response = phase3_client.get(
        f"/player/sessions/{time_slice.session_id}/locations/{peak_id}"
    )
    assert noncurrent_response.status_code == 200
    noncurrent = noncurrent_response.json()
    assert noncurrent["is_current"] is False
    assert noncurrent["npcs_present"] == []
    assert noncurrent["items_present"] == []


def test_npc_owned_phase3_token_is_hidden_from_inventory_detail_but_player_item_is_readable(
    time_slice: TimeSliceSession, phase3_client, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")
    token = time_slice.token_owner()
    assert token.owner_type == "npc"

    hidden_response = phase3_client.get(
        f"/player/sessions/{time_slice.session_id}/inventory/{token.id}"
    )
    assert hidden_response.status_code == 404

    player_item = SessionInventoryItemModel(
        id=f"player-item-{uuid.uuid4().hex}",
        session_id=time_slice.session_id,
        item_template_id=token.item_template_id,
        owner_type="player",
        owner_ref_id=None,
        quantity=1,
    )
    time_slice.db.add(player_item)
    time_slice.db.commit()

    player_response = phase3_client.get(
        f"/player/sessions/{time_slice.session_id}/inventory/{player_item.id}"
    )
    assert player_response.status_code == 200
    assert player_response.json()["id"] == player_item.id


def test_phase3_snapshot_apply_and_readonly_restore_refuse_without_writes(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")

    playthrough = PlaythroughInstanceModel(
        id=f"pi-{uuid.uuid4().hex}",
        world_id=time_slice.world_id,
        root_session_id=time_slice.session_id,
        instance_status="active",
    )
    time_slice.db.add(playthrough)
    time_slice.db.commit()
    snapshot = create_baseline_snapshot(
        time_slice.db,
        playthrough_instance_id=playthrough.id,
        session_id=time_slice.session_id,
    )
    snapshot_count = time_slice.db.query(InstanceSnapshotModel).filter_by(
        playthrough_instance_id=playthrough.id
    ).count()
    before = _sensitive_snapshot_rows(time_slice.db, time_slice.session_id)

    monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
    with pytest.raises(SnapshotRewindRefusedError):
        apply_snapshot(time_slice.db, snapshot.id)
    time_slice.db.expire_all()
    assert _sensitive_snapshot_rows(time_slice.db, time_slice.session_id) == before
    assert time_slice.db.query(InstanceSnapshotModel).filter_by(
        playthrough_instance_id=playthrough.id
    ).count() == snapshot_count

    monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
    with pytest.raises(SnapshotRewindRefusedError):
        restore_snapshot(time_slice.db, snapshot.id)
    time_slice.db.expire_all()
    assert _sensitive_snapshot_rows(time_slice.db, time_slice.session_id) == before
    assert time_slice.db.query(InstanceSnapshotModel).filter_by(
        playthrough_instance_id=playthrough.id
    ).count() == snapshot_count

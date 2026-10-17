"""Service-level content_v1 traces across formal turns and service reloads."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.content.runtime_models import CurrentPlanState
from llm_rpg.core.content_publish_service import publish_content_pack_version
from llm_rpg.core.content_runtime import (
    CONTENT_NAMESPACE,
    load_content_runtime_context,
)
from llm_rpg.core.playthrough_instance_service import create_content_v1_instance
from llm_rpg.core.turn_service import execute_turn_service
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    GameEventModel,
    LocationModel,
    MemoryFactModel,
    NPCRelationshipMemoryModel,
    NPCPrivateMemoryModel,
    NPCTemplateModel,
    PlaythroughInstanceModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    StoryPackageVersionModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_MISTY_FORD = _REPO_ROOT / "content_packs" / "misty_ford"
_TRIAL_MICRO = _REPO_ROOT / "content_packs" / "trial_micro_config"


@pytest.fixture
def content_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db, factory
    finally:
        db.close()
        engine.dispose()


def _user(db) -> UserModel:
    token = uuid.uuid4().hex[:12]
    user = UserModel(username=f"content-turn-{token}", is_admin=False)
    db.add(user)
    db.flush()
    return user


def _version(db, pack_dir: Path) -> str:
    return publish_content_pack_version(db, pack_dir=pack_dir).version_id


def _instance(db, version_id: str, *, user_id: str | None = None) -> dict:
    return create_content_v1_instance(
        db,
        user_id=user_id or _user(db).id,
        version_id=version_id,
    )


def _inspect_turn(db, session_id: str, *, action: str = "inspect"):
    return execute_turn_service(
        db=db,
        session_id=session_id,
        player_input=action,
        use_mock=True,
    )


def _content_trace(db, session_id: str) -> list[tuple[int, str, dict]]:
    rows = db.query(GameEventModel).filter_by(session_id=session_id).all()
    content_rows = [
        row for row in rows
        if isinstance(row.result_json, dict) and isinstance(row.result_json.get("engine_meta"), dict)
    ]
    content_rows.sort(key=lambda row: row.result_json["engine_meta"]["sequence"])
    return [
        (
            row.result_json["engine_meta"]["logical_tick"],
            row.event_type,
            row.public_payload_json or row.private_payload_json or {},
        )
        for row in content_rows
    ]


def _npc_by_code(db, session_id: str, code: str) -> SessionNPCStateModel:
    for row in db.query(SessionNPCStateModel).filter_by(session_id=session_id).all():
        template = db.get(NPCTemplateModel, row.npc_template_id)
        if template and template.code == code:
            return row
    raise AssertionError(f"missing NPC state for {code}")


def test_trial_micro_config_uses_content_rules_and_interrupts_at_tick_seven(content_db):
    db, _ = content_db
    version_id = _version(db, _TRIAL_MICRO)
    created = _instance(db, version_id)
    session_id = created["session_id"]

    first = _inspect_turn(db, session_id)
    second = _inspect_turn(db, session_id)
    third = _inspect_turn(db, session_id)
    # The fixed combat-category duration is five ticks; starting at the actual
    # interrupted cursor (7) proves the continuation does not skip tick 8/9.
    fourth = _inspect_turn(db, session_id, action="attack npc_a")

    assert load_content_runtime_context(db, session_id=session_id).run_state.logical_tick == 12
    assert [
        first.time_advance_result["actual_elapsed_minutes"],
        second.time_advance_result["actual_elapsed_minutes"],
        third.time_advance_result["actual_elapsed_minutes"],
        fourth.time_advance_result["actual_elapsed_minutes"],
    ] == [3, 3, 1, 5]
    assert third.time_advance_result["planned_elapsed_minutes"] == 3
    assert third.time_advance_result["interrupted"] is True

    trace = _content_trace(db, session_id)
    tick_five = [event_type for tick, event_type, _ in trace if tick == 5]
    required_tick_five = ["npc_arrived", "item_acquired", "item_take_failed"]
    matched = 0
    for event_type in tick_five:
        if matched < len(required_tick_five) and event_type == required_tick_five[matched]:
            matched += 1
    assert matched == len(required_tick_five), tick_five
    assert tick_five.count("plan_blocked") == 1
    tick_seven = [(event_type, payload) for tick, event_type, payload in trace if tick == 7]
    assert tick_seven and tick_seven[0][0] == "world_interrupt"
    assert tick_seven[0][1]["kind"] == "trial_bell"
    assert any(tick == 8 and event_type == "npc_travel_started" for tick, event_type, _ in trace)
    assert any(tick == 9 and event_type == "npc_arrived" for tick, event_type, _ in trace)
    token = db.query(SessionInventoryItemModel).filter_by(
        session_id=session_id, instance_key="trial_token"
    ).one()
    npc_a = _npc_by_code(db, session_id, "npc_a")
    assert token.owner_type == "character"
    assert token.owner_ref_id == npc_a.id


def test_misty_ford_route_override_is_session_scoped_and_survives_service_reload(content_db):
    db, factory = content_db
    version_id = _version(db, _MISTY_FORD)
    first = _instance(db, version_id)
    second = _instance(db, version_id)
    session_id = first["session_id"]
    other_session_id = second["session_id"]

    _inspect_turn(db, session_id)
    _inspect_turn(db, session_id)
    first_state = load_content_runtime_context(db, session_id=session_id).run_state
    other_state = load_content_runtime_context(db, session_id=other_session_id).run_state
    assert first_state.logical_tick == 6
    assert other_state.logical_tick == 0
    assert first_state.route_overrides["east_bank->west_bank"] is False
    assert other_state.route_overrides == {}

    db.close()
    restarted_db = factory()
    try:
        reloaded = load_content_runtime_context(restarted_db, session_id=session_id)
        ferryman = _npc_by_code(restarted_db, session_id, "ferryman")
        plan = reloaded.state.npc_current_plans["ferryman"]
        assert isinstance(plan, CurrentPlanState)
        assert plan.action == "wait"
        assert plan.expected_end_tick == 9
        assert ferryman.current_location_id == restarted_db.query(LocationModel).filter_by(
            world_id=reloaded.binding.world_id, code="east_bank"
        ).one().id
        from llm_rpg.core.turn_service import _content_recommended_actions
        recommendations = _content_recommended_actions(restarted_db, reloaded)
        assert not any("西岸" in action or "west_bank" in action for action in recommendations)

        _inspect_turn(restarted_db, session_id)
        _inspect_turn(restarted_db, session_id)
        final_context = load_content_runtime_context(restarted_db, session_id=session_id)
        assert final_context.state.logical_tick == 12
        assert final_context.state.npc_positions["ferryman"] == "west_bank"
        assert final_context.state.npc_current_plans["ferryman"].status == "achieved"
        assert final_context.state.route_is_open("east_bank", "west_bank") is True
        trace = _content_trace(restarted_db, session_id)
        assert any(tick == 4 and event_type == "route_changed" for tick, event_type, _ in trace)
        assert any(tick == 5 and event_type == "npc_travel_failed" for tick, event_type, _ in trace)
        assert any(tick == 9 and event_type == "route_changed" for tick, event_type, _ in trace)
        assert any(tick == 12 and event_type == "npc_arrived" for tick, event_type, _ in trace)
    finally:
        restarted_db.close()


def test_content_engine_events_use_durable_ids_for_event_time_cognition(content_db, monkeypatch):
    from llm_rpg.core import turn_service

    monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
    original_apply = turn_service.apply_content_advance

    def check_apply_contract(db, *, session_id, context, advance_result, write_cognition):
        route_event = next(
            (event for event in advance_result.events if event.event_type == "route_changed"),
            None,
        )
        if route_event is not None:
            event_ids = db.info.get("content_event_ids", {})
            tick_positions = db.info.get("content_tick_positions", {})
            events_by_seq = {event.seq: event for event in advance_result.events}
            assert set(event_ids) == set(events_by_seq)
            assert all(
                spec.event_seq in events_by_seq
                and spec.source_step_code == events_by_seq[spec.event_seq].step_code
                and spec.tick == events_by_seq[spec.event_seq].tick
                for spec in advance_result.cognition
            )
            assert event_ids[route_event.seq]
            assert tick_positions[route_event.tick]["npc_positions"]["ferryman"] == "east_bank"
            assert write_cognition is True
        return original_apply(
            db,
            session_id=session_id,
            context=context,
            advance_result=advance_result,
            write_cognition=write_cognition,
        )

    monkeypatch.setattr(turn_service, "apply_content_advance", check_apply_contract)
    db, _ = content_db
    version_id = _version(db, _MISTY_FORD)
    created = _instance(db, version_id)
    session_id = created["session_id"]
    _inspect_turn(db, session_id)
    _inspect_turn(db, session_id)

    trace_rows = db.query(GameEventModel).filter_by(session_id=session_id).all()
    route_changed = next(
        row for row in trace_rows
        if row.event_type == "route_changed"
        and isinstance(row.public_payload_json, dict)
        and row.public_payload_json.get("from") == "east_bank"
    )
    assert route_changed.id
    memories = db.query(NPCPrivateMemoryModel).filter_by(session_id=session_id).all()
    ferry_template = db.query(NPCTemplateModel).filter_by(
        world_id=db.get(SessionModel, session_id).world_id,
        code="ferryman",
    ).one()
    herbalist_template = db.query(NPCTemplateModel).filter_by(
        world_id=ferry_template.world_id,
        code="herbalist",
    ).one()
    ferry_memories = [m for m in memories if m.npc_template_id == ferry_template.id]
    herbalist_memories = [m for m in memories if m.npc_template_id == herbalist_template.id]
    assert any(route_changed.id in (m.source_event_ids_json or []) for m in ferry_memories)
    assert not any(route_changed.id in (m.source_event_ids_json or []) for m in herbalist_memories)


def test_next_formal_turn_retrieves_only_same_session_major_npc_memory(content_db, monkeypatch):
    from llm_rpg.core import turn_service

    db, _ = content_db
    version_id = _version(db, _MISTY_FORD)
    created = _instance(db, version_id)
    session_id = created["session_id"]
    ferry_template = db.query(NPCTemplateModel).filter_by(
        world_id=db.get(SessionModel, session_id).world_id,
        code="ferryman",
    ).one()
    ferry_template.is_major_npc = True
    db.flush()
    monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
    _inspect_turn(db, session_id)
    _inspect_turn(db, session_id)

    captured: list[tuple[str, dict]] = []
    original = turn_service._build_npc_context

    def capture_context(**kwargs):
        result = original(**kwargs)
        captured.append((kwargs["npc_id"], result))
        return result

    monkeypatch.setattr(turn_service, "_build_npc_context", capture_context)
    _inspect_turn(db, session_id)

    ferryman = _npc_by_code(db, session_id, "ferryman")
    ferry_contexts = [context for npc_id, context in captured if npc_id == ferryman.id]
    assert ferry_contexts
    retrieved = ferry_contexts[-1].get("retrieved_private_memories", [])
    assert any("bridge" in item.get("text", "").lower() or "桥" in item.get("text", "") for item in retrieved)
    assert all(item.get("source_event_ids") for item in retrieved)
    assert not any("route_overrides" in str(item) or CONTENT_NAMESPACE in str(item) for item in retrieved)


def test_two_named_content_items_keep_distinct_instance_keys(content_db):
    db, _ = content_db
    version_id = _version(db, _MISTY_FORD)
    created = _instance(db, version_id)
    session_id = created["session_id"]

    items = db.query(SessionInventoryItemModel).filter_by(session_id=session_id).all()
    keys = {row.instance_key for row in items}
    assert {"lantern", "herb_bundle"}.issubset(keys)
    assert len(keys) == len(items)
    assert len({row.id for row in items}) == len(items)


def test_content_turn_returns_actual_interrupt_time_without_exposing_engine_state(content_db):
    from llm_rpg.core.projections import project_content_public_context

    db, _ = content_db
    version_id = _version(db, _TRIAL_MICRO)
    created = _instance(db, version_id)
    session_id = created["session_id"]
    _inspect_turn(db, session_id)
    _inspect_turn(db, session_id)
    interrupted = _inspect_turn(db, session_id)

    safe = project_content_public_context({
        "global_flags": {CONTENT_NAMESPACE: {"route_overrides": {"x->y": False}}},
        "route_overrides": {"x->y": False},
        "pending_steps": ["secret"],
        "visible_npcs": [
            {"npc_id": "visible", "name": "Seen", "hidden_identity": "hidden", "hidden_plan_state": {"x": 1}},
            {"npc_id": "hidden", "name": "Unseen", "owner_ref_id": "private"},
        ],
        "status_flags": {"mood": "calm", "short_memory_summary": "private"},
    }, visible_npc_ids={"visible"})
    encoded = str(safe)
    assert "route_overrides" not in encoded
    assert "pending_steps" not in encoded
    assert "hidden_identity" not in encoded
    assert "Unseen" not in encoded
    assert "short_memory_summary" not in encoded
    assert "calm" in encoded
    assert interrupted.time_advance_result["actual_elapsed_minutes"] == 1
    assert interrupted.time_advance_result["interrupted"] is True
    assert "__content_simulation" not in str(interrupted.model_dump() if hasattr(interrupted, "model_dump") else interrupted)


def test_content_manual_save_and_instantiate_are_version_bound(content_db, monkeypatch):
    from llm_rpg.api.sessions import PlayerInstantiateRequest, instantiate_story_package

    db, _ = content_db
    monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
    user = _user(db)
    version_id = _version(db, _MISTY_FORD)
    version = db.get(StoryPackageVersionModel, version_id)
    assert version is not None

    response = instantiate_story_package(
        PlayerInstantiateRequest(
            story_package_id=version.story_package_id,
            version_id=version_id,
            runtime_mode="content_v1",
        ),
        current_user=user,
        db=db,
    )
    assert response.version_id == version_id
    session = db.get(SessionModel, response.session_id)
    assert session is not None
    assert session.story_package_version_id == version_id
    assert session.playthrough_instance_id
    instance = db.get(PlaythroughInstanceModel, session.playthrough_instance_id)
    assert instance is not None
    assert instance.story_package_version_id == version_id

    # The service-level manual-save path must use the same factory, not a bare Session.
    from llm_rpg.api.saves import ManualSaveRequest, create_manual_save

    manual = create_manual_save(
        ManualSaveRequest(world_id=version.world_id),
        current_user=user,
        db=db,
    )
    manual_session = db.get(SessionModel, manual.session_id)
    assert manual_session is not None
    assert manual_session.story_package_version_id == version_id
    assert manual_session.playthrough_instance_id
    assert manual_session.save_slot_id == manual.save_slot_id
    assert db.query(SessionStateModel).filter_by(session_id=manual.session_id).one().global_flags_json.get(CONTENT_NAMESPACE)


def test_rest_and_sse_channels_share_content_turn_service_side_effects(content_db):
    """The transport adapters must leave the same durable content event trace."""
    db, _ = content_db
    version_id = _version(db, _TRIAL_MICRO)
    first = _instance(db, version_id)
    second = _instance(db, version_id)

    rest_result = _inspect_turn(db, first["session_id"])
    sse_events: list[dict] = []
    sse_result = execute_turn_service(
        db=db,
        session_id=second["session_id"],
        player_input="inspect",
        use_mock=True,
        turn_event_callback=sse_events.append,
    )

    assert rest_result.time_advance_result["actual_elapsed_minutes"] == sse_result.time_advance_result["actual_elapsed_minutes"]
    assert _content_trace(db, first["session_id"]) == _content_trace(db, second["session_id"])
    assert db.query(TurnTransactionModel).filter_by(session_id=first["session_id"]).count() == 1
    assert db.query(TurnTransactionModel).filter_by(session_id=second["session_id"]).count() == 1


def test_content_player_subresources_share_visibility_whitelist(content_db):
    from fastapi import HTTPException

    from llm_rpg.api.player_inventory import get_inventory_item
    from llm_rpg.api.player_locations import get_current_location, get_location_detail
    from llm_rpg.api.player_relationships import (
        get_relationship_detail,
        list_relationships,
        relationship_summary,
    )

    db, _ = content_db
    user = _user(db)
    version_id = _version(db, _MISTY_FORD)
    created = _instance(db, version_id, user_id=user.id)
    session_id = created["session_id"]
    ferryman = _npc_by_code(db, session_id, "ferryman")
    herbalist = _npc_by_code(db, session_id, "herbalist")
    ferryman.status_flags = {
        "alive": True,
        "mood": "calm",
        "secret_plan": "keep private",
        "unlisted_status": "not public",
    }
    ferryman.short_memory_summary = "private summary"
    db.add(NPCRelationshipMemoryModel(
        id=f"relationship-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        npc_id=ferryman.npc_template_id,
        target_id="player",
        content="private conversation history",
        impact_json={"secret": True},
        created_turn=1,
    ))
    db.flush()

    current = get_current_location(session_id, current_user=user, db=db)
    assert [npc.npc_id for npc in current.npcs_present] == [ferryman.npc_template_id]
    assert current.npcs_present[0].mood is None
    assert current.npcs_present[0].status_flags == {"alive": True, "mood": "calm"}

    # A DB end-state location/owner change without a player-visible engine event
    # must not be treated as evidence that the player perceived the moved entity.
    original_herbalist_location = herbalist.current_location_id
    herbalist.current_location_id = current.location_id
    hidden_item = db.query(SessionInventoryItemModel).filter_by(
        session_id=session_id, instance_key="lantern"
    ).one()
    original_item_owner = hidden_item.owner_ref_id
    hidden_item.owner_ref_id = current.location_id
    db.flush()
    unobserved_move = get_current_location(session_id, current_user=user, db=db)
    assert herbalist.npc_template_id not in {
        npc.npc_id for npc in unobserved_move.npcs_present
    }
    assert all(item.item_id != hidden_item.item_template_id for item in unobserved_move.items_present)
    herbalist.current_location_id = original_herbalist_location
    hidden_item.owner_ref_id = original_item_owner
    db.flush()

    watch_house = db.query(LocationModel).filter_by(
        world_id=created["world_id"], code="watch_house"
    ).one()
    assert watch_house.access_rules["always_accessible"] is True
    remote = get_location_detail(
        session_id, watch_house.id, current_user=user, db=db
    )
    assert remote.npcs_present == []
    assert remote.items_present == []

    # FastAPI route functions are called directly here, so the Query-defaulted
    # parameters must be supplied explicitly.
    relationships = list_relationships(
        session_id, sort="trust", current_user=user, db=db
    )
    assert [item.npc_id for item in relationships.relationships] == [ferryman.npc_template_id]
    summary = relationship_summary(session_id, current_user=user, db=db)
    assert summary.total_npcs == 1
    detail = get_relationship_detail(
        session_id, ferryman.npc_template_id, current_user=user, db=db
    )
    assert detail.status_flags == {"alive": True, "mood": "calm"}
    assert detail.interaction_history == []
    with pytest.raises(HTTPException) as hidden_relationship:
        get_relationship_detail(
            session_id, herbalist.npc_template_id, current_user=user, db=db
        )
    assert hidden_relationship.value.status_code == 404

    hidden_item = db.query(SessionInventoryItemModel).filter_by(
        session_id=session_id, owner_type="location"
    ).one()
    with pytest.raises(HTTPException) as hidden_inventory:
        get_inventory_item(
            session_id, hidden_item.id, current_user=user, db=db
        )
    assert hidden_inventory.value.status_code == 404


def test_content_replay_npc_count_uses_public_whitelist_and_legacy_total(content_db):
    from llm_rpg.api.game import ReplayRequest, replay_turns

    db, _ = content_db
    user = _user(db)
    version_id = _version(db, _MISTY_FORD)
    content_session = _instance(db, version_id, user_id=user.id)
    content_replay = replay_turns(
        content_session["session_id"],
        ReplayRequest(),
        current_user=user,
        db=db,
    )
    assert content_replay.reconstructed_state["npc_count"] == 1

    legacy_token = uuid.uuid4().hex[:8]
    legacy_world = WorldModel(
        id=f"legacy-world-{legacy_token}",
        code=f"legacy-{legacy_token}",
        name="Legacy replay world",
        genre="fantasy",
        status="active",
    )
    legacy_location = LocationModel(
        id=f"legacy-location-{legacy_token}",
        world_id=legacy_world.id,
        code="start",
        name="Start",
    )
    legacy_session = SessionModel(
        id=f"legacy-session-{legacy_token}",
        user_id=user.id,
        world_id=legacy_world.id,
        status="active",
    )
    legacy_npcs = [
        NPCTemplateModel(
            id=f"legacy-npc-template-{legacy_token}-{index}",
            world_id=legacy_world.id,
            code=f"legacy_npc_{index}",
            name=f"Legacy NPC {index}",
            initial_location_id=legacy_location.id,
        )
        for index in range(2)
    ]
    db.add_all([legacy_world, legacy_location, legacy_session, *legacy_npcs])
    db.flush()
    db.add(SessionStateModel(
        id=f"legacy-state-{legacy_token}",
        session_id=legacy_session.id,
        current_location_id=legacy_location.id,
        global_flags_json={},
    ))
    db.add_all([
        SessionNPCStateModel(
            id=f"legacy-npc-state-{legacy_token}-{index}",
            session_id=legacy_session.id,
            npc_template_id=npc.id,
            current_location_id=legacy_location.id,
            status_flags={"alive": True},
        )
        for index, npc in enumerate(legacy_npcs)
    ])
    db.flush()

    legacy_replay = replay_turns(
        legacy_session.id,
        ReplayRequest(),
        current_user=user,
        db=db,
    )
    assert legacy_replay.reconstructed_state["npc_count"] == 2

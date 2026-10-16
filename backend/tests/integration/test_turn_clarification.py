"""W0 red-light coverage: an explicitly ambiguous input must be a zero-time turn.

Production gap this file exposes (`.omo/plans/phase1-turn-foundation-completion.md`
sections 2.2 and W4): an input that *deterministically* parses to ``move`` without a
target is an explicit request for clarification, but the production path
(`llm_rpg.core.turn_service.execute_turn_service`) still treats it as an ordinary
turn -- it advances world time by the movement category default, settles scheduled
events at the adjudicated time, writes game events / state deltas / necessary
cognition, and (on a first turn) unconditionally initializes session story state.

The counter-example is a guard: ``unknown`` / unrecognized input must keep the
existing fallback behaviour and never be reclassified as clarification.

Trigger choice is verified by code, not guessed: `_parse_player_input("去")` returns
``("move", None)`` (see `_parse_player_input` move-keyword branch), and the
input-intent LLM stage is inert under ``use_mock=True`` because the mock provider
never yields an accepted `InputIntentProposal`, so the deterministic parser decides.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from llm_rpg.core import turn_service
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    GameEventModel,
    LocationModel,
    MemoryFactModel,
    MemorySummaryModel,
    NPCBeliefModel,
    NPCPrivateMemoryModel,
    NPCMemoryScopeModel,
    NPCRelationshipMemoryModel,
    NPCTemplateModel,
    QuestTemplateModel,
    SaveSlotModel,
    ScheduledEventModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionStateModel,
    StateDeltaModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)

# Deterministic clarification trigger: `_parse_player_input` sees the move keyword
# "去", strips everything after it, and returns ("move", None) -- a move with no target.
CLARIFY_INPUT = "去"

# Deterministic non-clarification input: no keyword matches, so the parser returns
# ("action", None) and time keeps the existing "unknown" category rule.
UNKNOWN_INPUT = "unknown"

# Rows that a clarification turn must never add: game events and state deltas are the
# observable "game action" writes, the memory tables are necessary cognition.
NON_CLARIFICATION_MODELS = (
    GameEventModel,
    StateDeltaModel,
    MemorySummaryModel,
    MemoryFactModel,
    NPCBeliefModel,
    NPCPrivateMemoryModel,
    NPCRelationshipMemoryModel,
    NPCMemoryScopeModel,
)


@pytest.fixture
def seeded_session(tmp_path):
    """Fresh SQLite session with one world, one location and one NPC template."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'turn-clarification.sqlite'}", poolclass=NullPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    suffix = uuid.uuid4().hex
    user = UserModel(
        id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid",
        password_hash="x", is_admin=False,
    )
    world = WorldModel(
        id=f"w-{suffix}", code=f"w-{suffix}", name="测试世界", genre="xianxia", status="active",
    )
    db.add_all([user, world])
    db.flush()
    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="测试章")
    location = LocationModel(
        id=f"l-{suffix}", world_id=world.id, chapter_id=chapter.id, code="square",
        name="广场", access_rules={"always_accessible": True},
    )
    npc = NPCTemplateModel(
        id=f"n-{suffix}", world_id=world.id, code="guide", name="向导", role_type="guide",
    )
    quest = QuestTemplateModel(
        id=f"q-{suffix}", world_id=world.id, code="quest", name="任务",
        quest_type="main", visibility="visible",
    )
    slot = SaveSlotModel(id=f"s-{suffix}", user_id=user.id, slot_number=1, name="测试存档")
    session = SessionModel(
        id=f"session-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id,
        current_chapter_id=chapter.id, status="active",
    )
    db.add_all([chapter, location, npc, quest, slot, session])
    db.commit()
    try:
        yield db, session.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _current_time(db, session_id):
    row = db.query(SessionStateModel).filter_by(session_id=session_id).one_or_none()
    return None if row is None else row.current_time


def _counts(db, session_id, models=NON_CLARIFICATION_MODELS):
    return {
        model.__tablename__: db.query(model).filter_by(session_id=session_id).count()
        for model in models
    }


def _new_rows(before, after):
    return {table: count - before[table] for table, count in after.items() if count != before[table]}


def _player_turn_rows(db, session_id):
    return db.query(EventLogModel).filter_by(
        session_id=session_id, event_type="player_turn"
    ).count()


def test_move_without_target_is_zero_time_clarification(seeded_session):
    """An explicit "move with no target" must commit a zero-time clarification turn."""
    db, session_id = seeded_session

    # A warm-up turn establishes the persisted world time and a baseline of rows.
    warm_up = turn_service.execute_turn_service(
        db, session_id, "观察四周", idempotency_key="warm-up", use_mock=True
    )
    before_time = _current_time(db, session_id)
    before_rows = _counts(db, session_id)
    before_player_turns = _player_turn_rows(db, session_id)
    assert before_time is not None, "warm-up turn must persist world time"

    # The trigger must be the deterministic parser's move-without-target result.
    assert turn_service._parse_player_input(CLARIFY_INPUT) == ("move", None)

    # A pending scheduled event is due as soon as any turn settles: a zero-time
    # clarification turn must never fire it.
    db.add(ScheduledEventModel(
        id=f"scheduled-{uuid.uuid4().hex}", session_id=session_id,
        event_template_id=None, trigger_conditions_json={}, status="pending",
    ))
    db.commit()
    scheduled_id = db.query(ScheduledEventModel).filter_by(session_id=session_id).one().id

    result = turn_service.execute_turn_service(
        db, session_id, CLARIFY_INPUT, idempotency_key="clarify-move-no-target", use_mock=True
    )

    # (3) the turn number still increases: the input and its clarification audit persist
    assert result.turn_no == warm_up.turn_no + 1, (
        f"clarification must still allocate the next turn: warm-up={warm_up.turn_no} "
        f"clarification={result.turn_no}"
    )

    # (2) zero game actions
    assert result.actions_committed == 0, (
        f"clarification commits no game action, got actions_committed={result.actions_committed}"
    )

    # (1) world time must not move
    after_time = _current_time(db, session_id)
    assert after_time == before_time, (
        "zero-time clarification must not advance world time: "
        f"before={before_time!r} after={after_time!r} "
        f"time_advance_result={result.time_advance_result!r}"
    )

    # (5) the adjudicated time advance is zero, not the movement-category default
    assert result.time_advance_result["accepted_elapsed_minutes"] == 0, (
        f"clarification must adjudicate zero elapsed minutes, got {result.time_advance_result!r}"
    )

    # (4) no game event, state delta, scheduled event or memory row for this turn
    new_rows = _new_rows(before_rows, _counts(db, session_id))
    assert not new_rows, (
        "clarification turn must not write game events, state deltas, scheduled "
        f"events or memory rows, got new rows: {new_rows}"
    )
    assert db.query(ScheduledEventModel).filter_by(id=scheduled_id).one().status == "pending", (
        "clarification turn must not settle pending scheduled events"
    )
    assert _player_turn_rows(db, session_id) == before_player_turns + 1, (
        "the clarification turn itself must remain recoverable as a persisted player_turn"
    )


def test_unknown_input_is_not_clarification(seeded_session):
    """Unrecognized input keeps the existing fallback time rule, never zero time."""
    db, session_id = seeded_session

    warm_up = turn_service.execute_turn_service(
        db, session_id, "观察四周", idempotency_key="warm-up", use_mock=True
    )
    before_time = _current_time(db, session_id)

    assert turn_service._parse_player_input(UNKNOWN_INPUT) == ("action", None)

    result = turn_service.execute_turn_service(
        db, session_id, UNKNOWN_INPUT, idempotency_key="unknown-input", use_mock=True
    )

    assert result.turn_no == warm_up.turn_no + 1
    after_time = _current_time(db, session_id)
    assert after_time != before_time, (
        "unrecognized input must keep advancing world time under the existing rule, "
        f"never the zero-time clarification rule: before={before_time!r} after={after_time!r} "
        f"time_advance_result={result.time_advance_result!r}"
    )
    # `_resolve_elapsed_minutes` falls back to 10 for the "action" intent and the
    # "unknown" category range (5, 15) accepts it unchanged.
    assert result.time_advance_result["accepted_elapsed_minutes"] == 10, (
        f"unrecognized input keeps the existing unknown-category timing, got {result.time_advance_result!r}"
    )


def test_clarification_same_key_recovery_is_read_only(seeded_session):
    """Retrying a clarification with the same key must recover without a second write."""
    db, session_id = seeded_session

    turn_service.execute_turn_service(
        db, session_id, "观察四周", idempotency_key="warm-up", use_mock=True
    )
    before_time = _current_time(db, session_id)
    before_rows = _counts(db, session_id)

    first = turn_service.execute_turn_service(
        db, session_id, CLARIFY_INPUT, idempotency_key="clarify-same-key", use_mock=True
    )
    mid_rows = _counts(db, session_id)
    mid_time = _current_time(db, session_id)

    second = turn_service.execute_turn_service(
        db, session_id, CLARIFY_INPUT, idempotency_key="clarify-same-key", use_mock=True
    )
    after_rows = _counts(db, session_id)

    assert second.turn_no == first.turn_no, (
        f"same-key recovery must reuse the turn: first={first.turn_no} second={second.turn_no}"
    )
    assert _new_rows(mid_rows, after_rows) == {}, (
        f"same-key recovery must not write again, got new rows: {_new_rows(mid_rows, after_rows)}"
    )
    assert db.query(TurnTransactionModel).filter_by(
        session_id=session_id, turn_no=first.turn_no
    ).count() == 1

    assert mid_time == before_time, (
        "zero-time clarification must not advance world time on the first attempt: "
        f"before={before_time!r} after={mid_time!r} "
        f"time_advance_result={first.time_advance_result!r}"
    )
    assert _current_time(db, session_id) == before_time, (
        "same-key recovery must leave world time unchanged: "
        f"before={before_time!r} after={_current_time(db, session_id)!r}"
    )


def test_first_turn_clarification_does_not_seed_state(seeded_session):
    """A first-turn clarification must not initialize runtime state or seed memories."""
    db, session_id = seeded_session

    assert _current_time(db, session_id) is None, "fixture must start without session state"
    assert db.query(SessionPlayerStateModel).filter_by(session_id=session_id).count() == 0
    assert _player_turn_rows(db, session_id) == 0

    result = turn_service.execute_turn_service(
        db, session_id, CLARIFY_INPUT, idempotency_key="first-turn-clarify", use_mock=True
    )

    assert result.turn_no == 1, f"first turn must still be numbered, got {result.turn_no}"
    assert result.actions_committed == 0
    assert _player_turn_rows(db, session_id) == 1, (
        "the first-turn clarification must still persist its input for idempotent recovery"
    )

    assert db.query(SessionStateModel).filter_by(session_id=session_id).count() == 0, (
        "first-turn clarification must not initialize session story state"
    )
    assert db.query(SessionPlayerStateModel).filter_by(session_id=session_id).count() == 0, (
        "first-turn clarification must not initialize player runtime state"
    )
    assert db.query(SessionNPCStateModel).filter_by(session_id=session_id).count() == 0, (
        "first-turn clarification must not initialize NPC runtime state"
    )
    seeded_memories = _counts(db, session_id)
    assert not any(seeded_memories.values()), (
        f"first-turn clarification must not seed memories, got rows: {seeded_memories}"
    )
    assert result.time_advance_result["accepted_elapsed_minutes"] == 0, (
        f"first-turn clarification must adjudicate zero elapsed minutes, got {result.time_advance_result!r}"
    )

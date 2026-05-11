"""
Unit tests for EventLog and EventStore.

Tests cover:
- Ordered append of events
- Reading events by turn index
- Empty log behavior
- Unique event IDs
- Multiple events to same transaction
- Reading by event type
- Transaction commit/rollback
"""

import pytest
from datetime import datetime

from llm_rpg.core.event_log import EventStore, EventLog
from llm_rpg.models.events import (
    EventType,
    GameEvent,
    PlayerInputEvent,
    SceneEvent,
    NPCActionEvent,
    WorldTime,
    TurnTransaction,
    TransactionStatus,
)


def make_event(
    event_id: str,
    event_type: EventType,
    turn_index: int,
    **kwargs,
) -> GameEvent:
    if event_type == EventType.PLAYER_INPUT:
        return PlayerInputEvent(
            event_id=event_id,
            event_type=event_type,
            turn_index=turn_index,
            raw_input=kwargs.get("raw_input", "test"),
            actor_id=kwargs.get("actor_id", "player"),
        )
    elif event_type == EventType.SCENE_EVENT:
        return SceneEvent(
            event_id=event_id,
            event_type=event_type,
            turn_index=turn_index,
            scene_id=kwargs.get("scene_id", "scene_1"),
            trigger=kwargs.get("trigger", "test"),
            summary=kwargs.get("summary", "test event"),
        )
    elif event_type == EventType.NPC_ACTION:
        return NPCActionEvent(
            event_id=event_id,
            event_type=event_type,
            turn_index=turn_index,
            npc_id=kwargs.get("npc_id", "npc_1"),
            action_type=kwargs.get("action_type", "talk"),
            summary=kwargs.get("summary", "test action"),
        )
    else:
        return GameEvent(
            event_id=event_id,
            event_type=event_type,
            turn_index=turn_index,
        )


def make_world_time() -> WorldTime:
    return WorldTime(
        calendar="修仙历",
        season="春",
        day=1,
        period="辰时",
    )


class TestEventStore:
    """Tests for EventStore class."""

    def test_initialization(self):
        store = EventStore()
        assert store is not None
        assert len(store._events) == 0
        assert len(store._transactions) == 0

    def test_create_transaction(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="look around",
            world_time_before=world_time,
        )
        
        assert txn is not None
        assert txn.transaction_id.startswith("turn_")
        assert txn.session_id == "sess_1"
        assert txn.game_id == "game_1"
        assert txn.turn_index == 1
        assert txn.player_input == "look around"
        assert txn.status == TransactionStatus.PENDING

    def test_add_event_creates_ordered_events(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event1 = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        event2 = make_event("evt_2", EventType.SCENE_EVENT, turn_index=1)
        event3 = make_event("evt_3", EventType.NPC_ACTION, turn_index=1)
        
        store.add_event(txn, event1)
        store.add_event(txn, event2)
        store.add_event(txn, event3)
        
        events = store.get_events_by_turn(1)
        assert len(events) == 3
        assert events[0].event_id == "evt_1"
        assert events[1].event_id == "evt_2"
        assert events[2].event_id == "evt_3"

    def test_get_events_by_turn_returns_in_order(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn1 = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        txn2 = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=2,
            player_input="test",
            world_time_before=world_time,
        )
        
        event1 = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        event2 = make_event("evt_2", EventType.SCENE_EVENT, turn_index=2)
        event3 = make_event("evt_3", EventType.NPC_ACTION, turn_index=1)
        
        store.add_event(txn1, event1)
        store.add_event(txn2, event2)
        store.add_event(txn1, event3)
        
        turn1_events = store.get_events_by_turn(1)
        assert len(turn1_events) == 2
        assert turn1_events[0].event_id == "evt_1"
        assert turn1_events[1].event_id == "evt_3"
        
        turn2_events = store.get_events_by_turn(2)
        assert len(turn2_events) == 1
        assert turn2_events[0].event_id == "evt_2"

    def test_empty_event_log_returns_empty_list(self):
        store = EventStore()
        
        events = store.get_events_by_turn(1)
        assert events == []
        
        events = store.get_events_by_type(EventType.PLAYER_INPUT)
        assert events == []

    def test_events_have_unique_ids(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event1 = make_event("evt_unique_1", EventType.PLAYER_INPUT, turn_index=1)
        event2 = make_event("evt_unique_2", EventType.SCENE_EVENT, turn_index=1)
        
        store.add_event(txn, event1)
        store.add_event(txn, event2)
        
        assert event1.event_id != event2.event_id
        assert store.get_event("evt_unique_1") is not None
        assert store.get_event("evt_unique_2") is not None

    def test_multiple_events_to_same_transaction(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        for i in range(5):
            event = make_event(f"evt_{i}", EventType.PLAYER_INPUT, turn_index=1)
            store.add_event(txn, event)
        
        assert len(txn.event_ids) == 5
        assert len(store.get_events_by_turn(1)) == 5

    def test_get_events_by_type(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event1 = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        event2 = make_event("evt_2", EventType.PLAYER_INPUT, turn_index=1)
        event3 = make_event("evt_3", EventType.SCENE_EVENT, turn_index=1)
        
        store.add_event(txn, event1)
        store.add_event(txn, event2)
        store.add_event(txn, event3)
        
        player_events = store.get_events_by_type(EventType.PLAYER_INPUT)
        assert len(player_events) == 2
        
        scene_events = store.get_events_by_type(EventType.SCENE_EVENT)
        assert len(scene_events) == 1

    def test_commit_transaction(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        store.add_event(txn, event)
        
        store.commit_transaction(txn)
        
        assert txn.status == TransactionStatus.COMMITTED
        assert txn.committed_at is not None

    def test_rollback_transaction_removes_events(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        store.add_event(txn, event)
        
        assert store.get_event("evt_1") is not None
        
        store.rollback_transaction(txn)
        
        assert txn.status == TransactionStatus.ROLLED_BACK
        assert store.get_event("evt_1") is None

    def test_get_events_by_actor(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event1 = make_event(
            "evt_1",
            EventType.PLAYER_INPUT,
            turn_index=1,
            actor_id="player_1",
        )
        event2 = make_event(
            "evt_2",
            EventType.NPC_ACTION,
            turn_index=1,
            npc_id="npc_1",
        )
        
        store.add_event(txn, event1)
        store.add_event(txn, event2)
        
        player_events = store.get_events_by_actor("player_1")
        assert len(player_events) == 1
        
        npc_events = store.get_events_by_actor("npc_1")
        assert len(npc_events) == 1

    def test_get_events_in_range(self):
        store = EventStore()
        world_time = make_world_time()
        
        for turn in [1, 2, 3, 4, 5]:
            txn = store.create_transaction(
                session_id="sess_1",
                game_id="game_1",
                turn_index=turn,
                player_input="test",
                world_time_before=world_time,
            )
            event = make_event(f"evt_{turn}", EventType.PLAYER_INPUT, turn_index=turn)
            store.add_event(txn, event)
        
        events = store.get_events_in_range(2, 4)
        assert len(events) == 3

    def test_get_recent_events(self):
        store = EventStore()
        world_time = make_world_time()
        
        for turn in [1, 2, 3, 4, 5]:
            txn = store.create_transaction(
                session_id="sess_1",
                game_id="game_1",
                turn_index=turn,
                player_input="test",
                world_time_before=world_time,
            )
            event = make_event(f"evt_{turn}", EventType.PLAYER_INPUT, turn_index=turn)
            store.add_event(txn, event)
        
        recent = store.get_recent_events(limit=3)
        assert len(recent) == 3

    def test_clear(self):
        store = EventStore()
        world_time = make_world_time()
        
        txn = store.create_transaction(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        event = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        store.add_event(txn, event)
        
        store.clear()
        
        assert len(store._events) == 0
        assert len(store._transactions) == 0


class TestEventLog:
    """Tests for EventLog class."""

    def test_initialization(self):
        log = EventLog()
        assert log is not None

    def test_start_turn(self):
        log = EventLog()
        world_time = make_world_time()
        
        txn = log.start_turn(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="look around",
            world_time_before=world_time,
        )
        
        assert txn is not None
        assert txn.turn_index == 1

    def test_record_event(self):
        log = EventLog()
        world_time = make_world_time()
        
        txn = log.start_turn(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        log.record_event(txn, event)
        
        assert log.get_event("evt_1") is not None

    def test_commit_turn(self):
        log = EventLog()
        world_time = make_world_time()
        
        txn = log.start_turn(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        log.record_event(txn, event)
        log.commit_turn(txn)
        
        assert txn.status == TransactionStatus.COMMITTED

    def test_abort_turn(self):
        log = EventLog()
        world_time = make_world_time()
        
        txn = log.start_turn(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        log.record_event(txn, event)
        log.abort_turn(txn)
        
        assert txn.status == TransactionStatus.ROLLED_BACK
        assert log.get_event("evt_1") is None

    def test_get_turn_events(self):
        log = EventLog()
        world_time = make_world_time()
        
        txn = log.start_turn(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        
        event1 = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        event2 = make_event("evt_2", EventType.SCENE_EVENT, turn_index=1)
        log.record_event(txn, event1)
        log.record_event(txn, event2)
        
        events = log.get_turn_events(1)
        assert len(events) == 2

    def test_query_events(self):
        log = EventLog()
        world_time = make_world_time()
        
        for turn in [1, 2, 3]:
            txn = log.start_turn(
                session_id="sess_1",
                game_id="game_1",
                turn_index=turn,
                player_input="test",
                world_time_before=world_time,
            )
            event = make_event(f"evt_{turn}", EventType.PLAYER_INPUT, turn_index=turn)
            log.record_event(txn, event)
        
        events = log.query_events(turn_range=(1, 2))
        assert len(events) == 2

    def test_get_session_events(self):
        log = EventLog()
        world_time = make_world_time()
        
        txn = log.start_turn(
            session_id="sess_1",
            game_id="game_1",
            turn_index=1,
            player_input="test",
            world_time_before=world_time,
        )
        event = make_event("evt_1", EventType.PLAYER_INPUT, turn_index=1)
        log.record_event(txn, event)
        
        events = log.get_session_events("sess_1")
        assert len(events) == 1
        
        events = log.get_session_events("nonexistent")
        assert len(events) == 0

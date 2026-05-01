import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..models.events import (
    AnyGameEvent,
    EventType,
    GameEvent,
    TurnTransaction,
    TransactionStatus,
)


class EventStore:
    
    def __init__(self):
        self._events: Dict[str, GameEvent] = {}
        self._transactions: Dict[str, TurnTransaction] = {}
        self._events_by_turn: Dict[int, List[str]] = {}
        self._events_by_type: Dict[EventType, List[str]] = {}
        self._events_by_actor: Dict[str, List[str]] = {}
    
    def create_transaction(
        self,
        session_id: str,
        game_id: str,
        turn_index: int,
        player_input: str,
        world_time_before: Any,
    ) -> TurnTransaction:
        transaction_id = f"turn_{turn_index:06d}_{uuid.uuid4().hex[:8]}"
        transaction = TurnTransaction(
            transaction_id=transaction_id,
            session_id=session_id,
            game_id=game_id,
            turn_index=turn_index,
            world_time_before=world_time_before,
            player_input=player_input,
        )
        self._transactions[transaction_id] = transaction
        return transaction
    
    def add_event(
        self,
        transaction: TurnTransaction,
        event: GameEvent,
    ) -> GameEvent:
        self._events[event.event_id] = event
        
        transaction.add_event(event.event_id)
        
        turn = event.turn_index
        if turn not in self._events_by_turn:
            self._events_by_turn[turn] = []
        self._events_by_turn[turn].append(event.event_id)
        
        event_type = event.event_type
        if event_type not in self._events_by_type:
            self._events_by_type[event_type] = []
        self._events_by_type[event_type].append(event.event_id)
        
        if hasattr(event, 'actor_id'):
            actor_id = event.actor_id
            if actor_id not in self._events_by_actor:
                self._events_by_actor[actor_id] = []
            self._events_by_actor[actor_id].append(event.event_id)
        elif hasattr(event, 'npc_id'):
            npc_id = event.npc_id
            if npc_id not in self._events_by_actor:
                self._events_by_actor[npc_id] = []
            self._events_by_actor[npc_id].append(event.event_id)
        
        return event
    
    def commit_transaction(self, transaction: TurnTransaction) -> None:
        transaction.commit()
    
    def rollback_transaction(self, transaction: TurnTransaction) -> None:
        for event_id in transaction.event_ids:
            if event_id in self._events:
                del self._events[event_id]
        
        transaction.rollback()
    
    def get_event(self, event_id: str) -> Optional[GameEvent]:
        return self._events.get(event_id)
    
    def get_transaction(self, transaction_id: str) -> Optional[TurnTransaction]:
        return self._transactions.get(transaction_id)
    
    def get_events_by_turn(self, turn_index: int) -> List[GameEvent]:
        event_ids = self._events_by_turn.get(turn_index, [])
        return [self._events[eid] for eid in event_ids if eid in self._events]
    
    def get_events_by_type(self, event_type: EventType) -> List[GameEvent]:
        event_ids = self._events_by_type.get(event_type, [])
        return [self._events[eid] for eid in event_ids if eid in self._events]
    
    def get_events_by_actor(self, actor_id: str) -> List[GameEvent]:
        event_ids = self._events_by_actor.get(actor_id, [])
        return [self._events[eid] for eid in event_ids if eid in self._events]
    
    def get_events_in_range(
        self,
        start_turn: int,
        end_turn: int,
    ) -> List[GameEvent]:
        result = []
        for turn in range(start_turn, end_turn + 1):
            result.extend(self.get_events_by_turn(turn))
        return result
    
    def get_recent_events(self, limit: int = 10) -> List[GameEvent]:
        all_events = sorted(
            self._events.values(),
            key=lambda e: e.timestamp,
            reverse=True,
        )
        return all_events[:limit]

    def get_events_by_session(self, session_id: str, limit: int = 100) -> List[GameEvent]:
        event_ids = [
            event_id
            for transaction in self._transactions.values()
            if transaction.session_id == session_id
            for event_id in transaction.event_ids
        ]
        events = [self._events[event_id] for event_id in event_ids if event_id in self._events]
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]
    
    def clear(self) -> None:
        self._events.clear()
        self._transactions.clear()
        self._events_by_turn.clear()
        self._events_by_type.clear()
        self._events_by_actor.clear()


class EventLog:
    
    def __init__(self):
        self._store = EventStore()
        self._event_counter = 0
    
    def _generate_event_id(self, event_type: str) -> str:
        self._event_counter += 1
        return f"evt_{event_type}_{self._event_counter:06d}"
    
    def start_turn(
        self,
        session_id: str,
        game_id: str,
        turn_index: int,
        player_input: str,
        world_time_before: Any,
    ) -> TurnTransaction:
        return self._store.create_transaction(
            session_id=session_id,
            game_id=game_id,
            turn_index=turn_index,
            player_input=player_input,
            world_time_before=world_time_before,
        )
    
    def record_event(
        self,
        transaction: TurnTransaction,
        event: GameEvent,
    ) -> GameEvent:
        return self._store.add_event(transaction, event)
    
    def commit_turn(self, transaction: TurnTransaction) -> None:
        self._store.commit_transaction(transaction)
    
    def abort_turn(self, transaction: TurnTransaction) -> None:
        self._store.rollback_transaction(transaction)
    
    def get_event(self, event_id: str) -> Optional[GameEvent]:
        return self._store.get_event(event_id)
    
    def get_turn_events(self, turn_index: int) -> List[GameEvent]:
        return self._store.get_events_by_turn(turn_index)
    
    def get_recent_events(self, limit: int = 10) -> List[GameEvent]:
        return self._store.get_recent_events(limit)

    def get_session_events(self, session_id: str, limit: int = 100) -> List[GameEvent]:
        return self._store.get_events_by_session(session_id, limit)
    
    def get_events_by_type(self, event_type: EventType) -> List[GameEvent]:
        return self._store.get_events_by_type(event_type)
    
    def get_actor_events(self, actor_id: str) -> List[GameEvent]:
        return self._store.get_events_by_actor(actor_id)
    
    def query_events(
        self,
        turn_range: Optional[tuple] = None,
        event_types: Optional[List[EventType]] = None,
        actor_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[GameEvent]:
        if turn_range:
            events = self._store.get_events_in_range(turn_range[0], turn_range[1])
        else:
            events = list(self._store._events.values())
        
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        
        if actor_id:
            actor_events = set(self._store.get_events_by_actor(actor_id))
            events = [e for e in events if e in actor_events]
        
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

"""
ScheduledEventProcessor - Processes scheduled events at world time.

This processor:
- Queries pending scheduled_events from the database
- Checks trigger_conditions against current world state
- Fires events when conditions are met
- Creates game_event records for triggered events
- Integrates with WorldEngine for time-based processing
"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy.orm import Session

from ..storage.models import (
    ScheduledEventModel,
    GameEventModel,
    TurnTransactionModel,
    EventTemplateModel,
)
from ..storage.repositories import (
    ScheduledEventRepository,
    GameEventRepository,
    TurnTransactionRepository,
)
from ..models.events import WorldTime


class ScheduledEventProcessor:
    """
    Processor for scheduled events that fire based on world time.
    
    Key responsibilities:
    - Query pending scheduled events for a session
    - Evaluate trigger_conditions against current world state
    - Fire events when conditions are satisfied
    - Create game_event records for audit trail
    - Mark scheduled events as triggered
    
    Integration points:
    - Called by WorldEngine after time advancement
    - Uses ScheduledEventRepository for data access
    - Creates GameEventModel records for triggered events
    """
    
    def __init__(self, db: Session) -> None:
        self.db: Session = db
        self._scheduled_event_repo: ScheduledEventRepository | None = None
        self._game_event_repo: GameEventRepository | None = None
        self._transaction_repo: TurnTransactionRepository | None = None
    
    @property
    def scheduled_event_repo(self) -> ScheduledEventRepository:
        if self._scheduled_event_repo is None:
            self._scheduled_event_repo = ScheduledEventRepository(self.db)
        return self._scheduled_event_repo
    
    @property
    def game_event_repo(self) -> GameEventRepository:
        if self._game_event_repo is None:
            self._game_event_repo = GameEventRepository(self.db)
        return self._game_event_repo
    
    @property
    def transaction_repo(self) -> TurnTransactionRepository:
        if self._transaction_repo is None:
            self._transaction_repo = TurnTransactionRepository(self.db)
        return self._transaction_repo
    
    def process_scheduled_events(
        self,
        session_id: str,
        world_time: WorldTime,
        current_turn: int,
        world_state: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        fired_events: list[dict[str, Any]] = []
        
        pending_events = self.scheduled_event_repo.get_pending(session_id)
        
        for scheduled_event in pending_events:
            if self._should_fire_event(
                scheduled_event=scheduled_event,
                world_time=world_time,
                world_state=world_state,
            ):
                fired_event = self._fire_scheduled_event(
                    scheduled_event=scheduled_event,
                    current_turn=current_turn,
                )
                if fired_event:
                    fired_events.append(fired_event)
        
        return fired_events
    
    def _should_fire_event(
        self,
        scheduled_event: ScheduledEventModel,
        world_time: WorldTime,
        world_state: dict[str, Any] | None = None,
    ) -> bool:
        raw_conditions = scheduled_event.trigger_conditions_json
        trigger_conditions: dict[str, Any] = raw_conditions if raw_conditions else {}
        
        if not self._check_time_conditions(trigger_conditions, world_time):
            return False
        
        if not self._check_state_conditions(trigger_conditions, world_state):
            return False
        
        return True
    
    def _check_time_conditions(
        self,
        trigger_conditions: dict[str, Any],
        world_time: WorldTime,
    ) -> bool:
        time_conditions = trigger_conditions.get("world_time", {})
        
        if not time_conditions:
            return True
        
        if "season" in time_conditions:
            if world_time.season != time_conditions["season"]:
                return False
        
        if "day" in time_conditions:
            day_condition = time_conditions["day"]
            if isinstance(day_condition, int):
                if world_time.day != day_condition:
                    return False
            elif isinstance(day_condition, dict):
                if "min" in day_condition and world_time.day < day_condition["min"]:
                    return False
                if "max" in day_condition and world_time.day > day_condition["max"]:
                    return False
        
        if "period" in time_conditions:
            period_condition = time_conditions["period"]
            if isinstance(period_condition, str):
                if world_time.period != period_condition:
                    return False
            elif isinstance(period_condition, list):
                if world_time.period not in period_condition:
                    return False
        
        periods = [
            "子时", "丑时", "寅时", "卯时", "辰时", "巳时",
            "午时", "未时", "申时", "酉时", "戌时", "亥时"
        ]
        
        if "period_after" in time_conditions:
            try:
                current_idx = periods.index(world_time.period)
                after_idx = periods.index(time_conditions["period_after"])
                if current_idx <= after_idx:
                    return False
            except ValueError:
                pass
        
        if "period_before" in time_conditions:
            try:
                current_idx = periods.index(world_time.period)
                before_idx = periods.index(time_conditions["period_before"])
                if current_idx >= before_idx:
                    return False
            except ValueError:
                pass
        
        return True
    
    def _check_state_conditions(
        self,
        trigger_conditions: dict[str, Any],
        world_state: dict[str, Any] | None = None,
    ) -> bool:
        state_conditions = trigger_conditions.get("world_state", {})
        
        if not state_conditions:
            return True
        
        if world_state is None:
            return False
        
        if "global_flags" in state_conditions:
            flag_conditions = state_conditions["global_flags"]
            current_flags = world_state.get("global_flags", {})
            
            for flag_name, expected_value in flag_conditions.items():
                if current_flags.get(flag_name) != expected_value:
                    return False
        
        if "player_location" in state_conditions:
            expected_location = state_conditions["player_location"]
            current_location = world_state.get("player_location")
            if current_location != expected_location:
                return False
        
        if "quest_status" in state_conditions:
            quest_conditions = state_conditions["quest_status"]
            quest_states = world_state.get("quest_states", {})
            
            for quest_id, expected_status in quest_conditions.items():
                if quest_states.get(quest_id, {}).get("status") != expected_status:
                    return False
        
        return True
    
    def _fire_scheduled_event(
        self,
        scheduled_event: ScheduledEventModel,
        current_turn: int,
    ) -> dict[str, Any] | None:
        try:
            event_template = None
            raw_template_id = scheduled_event.event_template_id
            template_id: str | None = str(raw_template_id) if raw_template_id else None
            if template_id:
                event_template = self.db.query(EventTemplateModel).filter(
                    EventTemplateModel.id == template_id
                ).first()
            
            event_type = "scheduled_event"
            effects: dict[str, Any] = {}
            
            if event_template:
                raw_event_type = event_template.event_type
                event_type = str(raw_event_type) if raw_event_type else event_type
                raw_effects = event_template.effects
                if raw_effects:
                    effects = cast(dict[str, Any], raw_effects)
            
            raw_session_id = scheduled_event.session_id
            if not raw_session_id:
                return None
            session_id = str(raw_session_id)
            
            transaction = self._get_or_create_system_transaction(
                session_id=session_id,
                turn_no=current_turn,
            )
            
            if transaction is None:
                return None
            
            raw_trigger_conditions = scheduled_event.trigger_conditions_json
            trigger_conditions = raw_trigger_conditions if raw_trigger_conditions else {}
            
            game_event = GameEventModel(
                transaction_id=transaction.id,
                session_id=session_id,
                turn_no=current_turn,
                event_type=str(event_type),
                actor_id="world",
                target_ids_json=[],
                visibility_scope="player_visible",
                public_payload_json={
                    "scheduled_event_id": scheduled_event.id,
                    "event_template_id": template_id,
                    "effects": effects,
                },
                private_payload_json={
                    "trigger_conditions": trigger_conditions,
                },
                result_json={
                    "fired_at": datetime.now().isoformat(),
                },
                occurred_at=datetime.now(),
            )
            
            self.db.add(game_event)
            
            scheduled_event.status = "triggered"
            
            self.db.commit()
            self.db.refresh(game_event)
            
            return {
                "game_event_id": game_event.id,
                "scheduled_event_id": scheduled_event.id,
                "event_type": str(event_type),
                "effects": effects,
                "turn_no": current_turn,
            }
            
        except Exception:
            self.db.rollback()
            return None
    
    def _get_or_create_system_transaction(
        self,
        session_id: str,
        turn_no: int,
    ) -> TurnTransactionModel | None:
        existing = self.transaction_repo.get_by_session_and_turn(session_id, turn_no)
        if existing:
            return existing
        
        try:
            transaction = TurnTransactionModel(
                session_id=session_id,
                turn_no=turn_no,
                idempotency_key=f"scheduled_event_{session_id}_{turn_no}",
                status="committed",
                started_at=datetime.now(),
                committed_at=datetime.now(),
            )
            
            self.db.add(transaction)
            self.db.commit()
            self.db.refresh(transaction)
            
            return transaction
            
        except Exception:
            self.db.rollback()
            return None
    
    def schedule_event(
        self,
        session_id: str,
        event_template_id: str | None,
        trigger_conditions: dict[str, Any],
    ) -> ScheduledEventModel:
        scheduled_event = ScheduledEventModel(
            session_id=session_id,
            event_template_id=event_template_id,
            trigger_conditions_json=trigger_conditions,
            status="pending",
        )
        
        self.db.add(scheduled_event)
        self.db.commit()
        self.db.refresh(scheduled_event)
        
        return scheduled_event
    
    def cancel_scheduled_event(
        self,
        event_id: str,
    ) -> bool:
        event = self.scheduled_event_repo.get_by_id(event_id)
        
        if event is None:
            return False
        
        current_status = event.status
        if current_status != "pending":
            return False
        
        event.status = "cancelled"
        self.db.commit()
        
        return True
    
    def get_pending_events(
        self,
        session_id: str,
    ) -> list[ScheduledEventModel]:
        return self.scheduled_event_repo.get_pending(session_id)

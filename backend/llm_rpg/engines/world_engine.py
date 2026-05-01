from typing import Any, Dict, List, Optional

from ..models.states import CanonicalState, WorldState
from ..models.events import WorldTime, WorldTickEvent
from ..core.canonical_state import CanonicalStateManager
from ..core.event_log import EventLog


class WorldEngine:
    
    def __init__(
        self,
        state_manager: CanonicalStateManager,
        event_log: EventLog,
    ):
        self._state_manager = state_manager
        self._event_log = event_log
    
    def advance_time(
        self,
        game_id: str,
        time_delta: int = 1,
    ) -> WorldTickEvent:
        state = self._state_manager.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        world_state = state.world_state
        old_time = world_state.current_time
        
        new_period = self._advance_period(old_time.period, time_delta)
        new_day = old_time.day
        new_season = old_time.season
        
        if new_period == "子时" and old_time.period != "子时":
            new_day += 1
            if new_day > 30:
                new_day = 1
                new_season = self._advance_season(old_time.season)
        
        new_time = WorldTime(
            calendar=old_time.calendar,
            season=new_season,
            day=new_day,
            period=new_period,
        )
        
        world_state.current_time = new_time
        
        event = WorldTickEvent(
            event_id=f"evt_world_tick_{game_id}_{new_time}",
            turn_index=state.player_state.flags.get("turn_index", 0),
            time_before=old_time,
            time_after=new_time,
            summary=f"时间从 {old_time} 推进到 {new_time}",
        )
        
        return event
    
    def _advance_period(self, current_period: str, delta: int) -> str:
        periods = [
            "子时", "丑时", "寅时", "卯时", "辰时", "巳时",
            "午时", "未时", "申时", "酉时", "戌时", "亥时"
        ]
        
        try:
            current_index = periods.index(current_period)
            new_index = (current_index + delta) % len(periods)
            return periods[new_index]
        except ValueError:
            return current_period
    
    def _advance_season(self, current_season: str) -> str:
        seasons = ["春", "夏", "秋", "冬"]
        try:
            current_index = seasons.index(current_season)
            next_index = (current_index + 1) % len(seasons)
            return seasons[next_index]
        except ValueError:
            return current_season
    
    def check_world_events(
        self,
        game_id: str,
    ) -> List[Dict[str, Any]]:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return []
        
        events = []
        
        world_state = state.world_state
        if world_state.current_time.period in ["子时", "丑时", "寅时"]:
            events.append({
                "type": "time_based",
                "description": "深夜时分，妖气加重",
                "effects": {"danger_level": 0.1},
            })
        
        return events
    
    def update_global_flags(
        self,
        game_id: str,
        flags: Dict[str, Any],
    ) -> None:
        state = self._state_manager.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        state.world_state.global_flags.update(flags)
    
    def get_weather(self, game_id: str) -> str:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return "晴"
        
        return state.world_state.weather
    
    def set_weather(self, game_id: str, weather: str) -> None:
        state = self._state_manager.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        state.world_state.weather = weather
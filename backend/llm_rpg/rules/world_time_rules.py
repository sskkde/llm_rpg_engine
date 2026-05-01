"""
World Time Rules

Manages world time advancement and time-based effects.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class TimeEffect:
    """Represents a time-based effect."""
    effect_type: str
    target_id: str
    magnitude: float
    duration: int
    description: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "effect_type": self.effect_type,
            "target_id": self.target_id,
            "magnitude": self.magnitude,
            "duration": self.duration,
            "description": self.description,
        }


class WorldTimeRules:
    """
    Manages world time advancement and effects.
    
    Rules:
    - Time advances based on actions
    - Different periods have different effects
    - NPCs have schedules based on time
    - Events trigger at specific times
    """
    
    PERIODS = [
        "子时", "丑时", "寅时", "卯时", "辰时", "巳时",
        "午时", "未时", "申时", "酉时", "戌时", "亥时",
    ]
    
    SEASONS = ["春", "夏", "秋", "冬"]
    
    def __init__(self):
        self._period_effects = {
            "子时": [{"type": "visibility", "value": -0.5, "target": "all"}],
            "午时": [{"type": "fatigue", "value": 0.2, "target": "player"}],
        }
        self._season_effects = {
            "冬": [{"type": "movement_cost", "value": 1.5, "target": "all"}],
        }
        self._action_time_costs = {
            "move": 1,
            "talk": 1,
            "combat": 2,
            "rest": 3,
            "craft": 4,
        }
    
    def advance_time(
        self,
        current_time: Dict[str, Any],
        periods_to_advance: int = 1
    ) -> Dict[str, Any]:
        """
        Advance world time.
        
        Args:
            current_time: Current world time
            periods_to_advance: Number of periods to advance
            
        Returns:
            New world time
        """
        new_time = current_time.copy()
        
        current_period_index = self.PERIODS.index(current_time.get("period", "子时"))
        current_day = current_time.get("day", 1)
        current_season_index = self.SEASONS.index(current_time.get("season", "春"))
        
        new_period_index = (current_period_index + periods_to_advance) % 12
        days_passed = (current_period_index + periods_to_advance) // 12
        
        new_day = current_day + days_passed
        new_season_index = (current_season_index + (new_day - 1) // 90) % 4
        
        new_time["period"] = self.PERIODS[new_period_index]
        new_time["day"] = new_day
        new_time["season"] = self.SEASONS[new_season_index]
        
        return new_time
    
    def calculate_effects(
        self,
        world_time: Dict[str, Any]
    ) -> List[TimeEffect]:
        """
        Calculate effects for the current time.
        
        Args:
            world_time: Current world time
            
        Returns:
            List of time effects
        """
        effects = []
        
        period = world_time.get("period", "")
        if period in self._period_effects:
            for effect_data in self._period_effects[period]:
                effects.append(TimeEffect(
                    effect_type=effect_data["type"],
                    target_id=effect_data["target"],
                    magnitude=effect_data["value"],
                    duration=1,
                    description=f"{period} effect: {effect_data['type']}",
                ))
        
        season = world_time.get("season", "")
        if season in self._season_effects:
            for effect_data in self._season_effects[season]:
                effects.append(TimeEffect(
                    effect_type=effect_data["type"],
                    target_id=effect_data["target"],
                    magnitude=effect_data["value"],
                    duration=1,
                    description=f"{season} effect: {effect_data['type']}",
                ))
        
        return effects
    
    def get_action_time_cost(self, action_type: str) -> int:
        """Get time cost for an action."""
        return self._action_time_costs.get(action_type, 1)
    
    def set_action_time_cost(self, action_type: str, cost: int) -> None:
        """Set time cost for an action."""
        self._action_time_costs[action_type] = cost
    
    def add_period_effect(self, period: str, effect: Dict[str, Any]) -> None:
        """Add an effect for a specific period."""
        if period not in self._period_effects:
            self._period_effects[period] = []
        self._period_effects[period].append(effect)
    
    def add_season_effect(self, season: str, effect: Dict[str, Any]) -> None:
        """Add an effect for a specific season."""
        if season not in self._season_effects:
            self._season_effects[season] = []
        self._season_effects[season].append(effect)
    
    def is_night_time(self, world_time: Dict[str, Any]) -> bool:
        """Check if it's night time."""
        period = world_time.get("period", "")
        night_periods = ["子时", "丑时", "寅时", "亥时"]
        return period in night_periods
    
    def is_day_time(self, world_time: Dict[str, Any]) -> bool:
        """Check if it's day time."""
        return not self.is_night_time(world_time)
    
    def get_time_description(self, world_time: Dict[str, Any]) -> str:
        """Get human-readable time description."""
        calendar = world_time.get("calendar", "")
        season = world_time.get("season", "")
        day = world_time.get("day", 1)
        period = world_time.get("period", "")
        
        return f"{calendar} {season} 第{day}日 {period}"

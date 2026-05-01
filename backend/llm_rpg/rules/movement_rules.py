"""
Movement Rules

Validates movement actions and calculates movement costs.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class MovementCost:
    """Represents the cost of a movement."""
    base_cost: int
    terrain_modifier: float
    fatigue_cost: float
    time_cost: int
    valid: bool
    reason: str
    
    def total_cost(self) -> float:
        """Calculate total movement cost."""
        return self.base_cost * self.terrain_modifier + self.fatigue_cost
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_cost": self.base_cost,
            "terrain_modifier": self.terrain_modifier,
            "fatigue_cost": self.fatigue_cost,
            "time_cost": self.time_cost,
            "total_cost": self.total_cost(),
            "valid": self.valid,
            "reason": self.reason,
        }


class MovementRules:
    """
    Validates movement actions and calculates costs.
    
    Rules:
    - Cannot move while in combat
    - Cannot move to blocked locations
    - Cannot move without required items
    - Movement costs depend on terrain and player state
    """
    
    def __init__(self):
        self._terrain_costs = {
            "plains": 1.0,
            "forest": 1.5,
            "mountain": 2.0,
            "water": 3.0,
            "urban": 0.8,
            "dungeon": 1.2,
        }
        self._blocked_locations: set = set()
        self._required_items: Dict[str, List[str]] = {}
    
    def validate_movement(
        self,
        player_location: str,
        target_location: str,
        game_state: Dict[str, Any]
    ) -> MovementCost:
        """
        Validate and calculate cost for a movement.
        
        Args:
            player_location: Current player location
            target_location: Target location
            game_state: Current game state
            
        Returns:
            MovementCost with validation result
        """
        if target_location in self._blocked_locations:
            return MovementCost(
                base_cost=0,
                terrain_modifier=1.0,
                fatigue_cost=0.0,
                time_cost=0,
                valid=False,
                reason="Target location is blocked",
            )
        
        if target_location == player_location:
            return MovementCost(
                base_cost=0,
                terrain_modifier=1.0,
                fatigue_cost=0.0,
                time_cost=0,
                valid=False,
                reason="Already at target location",
            )
        
        current_mode = game_state.get("current_mode", "exploration")
        if current_mode == "combat":
            return MovementCost(
                base_cost=0,
                terrain_modifier=1.0,
                fatigue_cost=0.0,
                time_cost=0,
                valid=False,
                reason="Cannot move while in combat",
            )
        
        if target_location in self._required_items:
            inventory = game_state.get("inventory", [])
            required = self._required_items[target_location]
            missing = [item for item in required if item not in inventory]
            if missing:
                return MovementCost(
                    base_cost=0,
                    terrain_modifier=1.0,
                    fatigue_cost=0.0,
                    time_cost=0,
                    valid=False,
                    reason=f"Missing required items: {', '.join(missing)}",
                )
        
        terrain = game_state.get("locations", {}).get(target_location, {}).get("terrain", "plains")
        terrain_modifier = self._terrain_costs.get(terrain, 1.0)
        
        player_fatigue = game_state.get("player_fatigue", 0.0)
        fatigue_cost = player_fatigue * 0.5
        
        base_cost = 10
        time_cost = int(base_cost * terrain_modifier)
        
        return MovementCost(
            base_cost=base_cost,
            terrain_modifier=terrain_modifier,
            fatigue_cost=fatigue_cost,
            time_cost=time_cost,
            valid=True,
            reason="Movement valid",
        )
    
    def can_move_to(
        self,
        from_location: str,
        to_location: str,
        game_state: Dict[str, Any]
    ) -> bool:
        """Check if movement is possible."""
        cost = self.validate_movement(from_location, to_location, game_state)
        return cost.valid
    
    def get_valid_destinations(
        self,
        current_location: str,
        game_state: Dict[str, Any]
    ) -> List[str]:
        """Get list of valid destinations from current location."""
        all_locations = game_state.get("locations", {}).keys()
        valid = []
        
        for location in all_locations:
            if location != current_location:
                if self.can_move_to(current_location, location, game_state):
                    valid.append(location)
        
        return valid
    
    def block_location(self, location_id: str) -> None:
        """Block a location from movement."""
        self._blocked_locations.add(location_id)
    
    def unblock_location(self, location_id: str) -> None:
        """Unblock a location."""
        if location_id in self._blocked_locations:
            self._blocked_locations.remove(location_id)
    
    def set_required_items(self, location_id: str, items: List[str]) -> None:
        """Set required items to enter a location."""
        self._required_items[location_id] = items
    
    def set_terrain_cost(self, terrain_type: str, cost_multiplier: float) -> None:
        """Set cost multiplier for a terrain type."""
        self._terrain_costs[terrain_type] = cost_multiplier

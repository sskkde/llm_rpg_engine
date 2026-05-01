"""
Combat Rules

Validates combat actions and calculates combat outcomes.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class CombatActionType(str, Enum):
    """Types of combat actions."""
    ATTACK = "attack"
    DEFEND = "defend"
    USE_SKILL = "use_skill"
    USE_ITEM = "use_item"
    FLEE = "flee"


class CombatOutcomeType(str, Enum):
    """Types of combat outcomes."""
    HIT = "hit"
    MISS = "miss"
    CRITICAL = "critical"
    BLOCKED = "blocked"
    DODGED = "dodged"


@dataclass
class CombatOutcome:
    """Represents the outcome of a combat action."""
    action_type: CombatActionType
    outcome_type: CombatOutcomeType
    damage: int
    attacker_id: str
    target_id: str
    valid: bool
    reason: str
    effects: List[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "outcome_type": self.outcome_type.value,
            "damage": self.damage,
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "valid": self.valid,
            "reason": self.reason,
            "effects": self.effects,
        }


class CombatRules:
    """
    Validates combat actions and calculates outcomes.
    
    Rules:
    - Must be in combat mode to perform combat actions
    - Must have valid target
    - Must have required resources ( stamina, items)
    - Damage calculation based on stats and modifiers
    """
    
    def __init__(self):
        self._base_damage = {
            CombatActionType.ATTACK: 10,
            CombatActionType.USE_SKILL: 15,
        }
        self._defense_reduction = 0.5
        self._critical_chance = 0.1
        self._critical_multiplier = 2.0
        self._flee_chance = 0.3
    
    def validate_action(
        self,
        action_type: CombatActionType,
        attacker_id: str,
        target_id: Optional[str],
        game_state: Dict[str, Any]
    ) -> CombatOutcome:
        """
        Validate and execute a combat action.
        
        Args:
            action_type: Type of combat action
            attacker_id: ID of the attacker
            target_id: ID of the target (None for flee/defend)
            game_state: Current game state
            
        Returns:
            CombatOutcome with validation and result
        """
        current_mode = game_state.get("current_mode", "exploration")
        if current_mode != "combat":
            return CombatOutcome(
                action_type=action_type,
                outcome_type=CombatOutcomeType.MISS,
                damage=0,
                attacker_id=attacker_id,
                target_id=target_id or "",
                valid=False,
                reason="Not in combat mode",
                effects=[],
            )
        
        if action_type in [CombatActionType.ATTACK, CombatActionType.USE_SKILL]:
            if not target_id:
                return CombatOutcome(
                    action_type=action_type,
                    outcome_type=CombatOutcomeType.MISS,
                    damage=0,
                    attacker_id=attacker_id,
                    target_id="",
                    valid=False,
                    reason="Target required for attack",
                    effects=[],
                )
            
            combat_state = game_state.get("combat_state", {})
            participants = combat_state.get("participants", [])
            if target_id not in participants:
                return CombatOutcome(
                    action_type=action_type,
                    outcome_type=CombatOutcomeType.MISS,
                    damage=0,
                    attacker_id=attacker_id,
                    target_id=target_id,
                    valid=False,
                    reason="Target not in combat",
                    effects=[],
                )
        
        if action_type == CombatActionType.USE_ITEM:
            inventory = game_state.get("inventory", [])
            has_usable_item = any(item.get("usable_in_combat") for item in inventory)
            if not has_usable_item:
                return CombatOutcome(
                    action_type=action_type,
                    outcome_type=CombatOutcomeType.MISS,
                    damage=0,
                    attacker_id=attacker_id,
                    target_id=target_id or "",
                    valid=False,
                    reason="No usable items in inventory",
                    effects=[],
                )
        
        return self._calculate_outcome(action_type, attacker_id, target_id, game_state)
    
    def _calculate_outcome(
        self,
        action_type: CombatActionType,
        attacker_id: str,
        target_id: Optional[str],
        game_state: Dict[str, Any]
    ) -> CombatOutcome:
        """Calculate combat outcome."""
        import random
        
        if action_type == CombatActionType.FLEE:
            success = random.random() < self._flee_chance
            return CombatOutcome(
                action_type=action_type,
                outcome_type=CombatOutcomeType.HIT if success else CombatOutcomeType.MISS,
                damage=0,
                attacker_id=attacker_id,
                target_id="",
                valid=True,
                reason="Flee successful" if success else "Flee failed",
                effects=[{"type": "flee", "success": success}],
            )
        
        if action_type == CombatActionType.DEFEND:
            return CombatOutcome(
                action_type=action_type,
                outcome_type=CombatOutcomeType.BLOCKED,
                damage=0,
                attacker_id=attacker_id,
                target_id="",
                valid=True,
                reason="Defending",
                effects=[{"type": "defense_boost", "value": self._defense_reduction}],
            )
        
        base_damage = self._base_damage.get(action_type, 5)
        
        is_critical = random.random() < self._critical_chance
        if is_critical:
            damage = int(base_damage * self._critical_multiplier)
            outcome_type = CombatOutcomeType.CRITICAL
        else:
            damage = base_damage
            outcome_type = CombatOutcomeType.HIT
        
        return CombatOutcome(
            action_type=action_type,
            outcome_type=outcome_type,
            damage=damage,
            attacker_id=attacker_id,
            target_id=target_id or "",
            valid=True,
            reason=f"{'Critical hit' if is_critical else 'Hit'} for {damage} damage",
            effects=[{"type": "damage", "value": damage}],
        )
    
    def can_perform_action(
        self,
        action_type: CombatActionType,
        game_state: Dict[str, Any]
    ) -> bool:
        """Check if an action can be performed."""
        current_mode = game_state.get("current_mode", "exploration")
        if current_mode != "combat":
            return False
        
        if action_type == CombatActionType.USE_ITEM:
            inventory = game_state.get("inventory", [])
            return any(item.get("usable_in_combat") for item in inventory)
        
        return True
    
    def set_base_damage(self, action_type: CombatActionType, damage: int) -> None:
        """Set base damage for an action type."""
        self._base_damage[action_type] = damage
    
    def set_critical_chance(self, chance: float) -> None:
        """Set critical hit chance (0.0 to 1.0)."""
        self._critical_chance = max(0.0, min(1.0, chance))
    
    def set_flee_chance(self, chance: float) -> None:
        """Set flee success chance (0.0 to 1.0)."""
        self._flee_chance = max(0.0, min(1.0, chance))

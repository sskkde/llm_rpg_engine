"""
Dialogue Rules

Validates dialogue actions and manages dialogue state.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class DialogueState(str, Enum):
    """Dialogue conversation states."""
    INACTIVE = "inactive"
    ACTIVE = "active"
    WAITING_FOR_RESPONSE = "waiting_for_response"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


class DialogueActionType(str, Enum):
    """Types of dialogue actions."""
    GREET = "greet"
    ASK = "ask"
    TELL = "tell"
    THREATEN = "threaten"
    PERSUADE = "persuade"
    END = "end"


@dataclass
class DialogueContext:
    """Context for a dialogue interaction."""
    npc_id: str
    npc_mood: str
    npc_trust: float
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    available_topics: List[str] = field(default_factory=list)
    blocked_topics: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "npc_id": self.npc_id,
            "npc_mood": self.npc_mood,
            "npc_trust": self.npc_trust,
            "conversation_history_length": len(self.conversation_history),
            "available_topics": self.available_topics,
            "blocked_topics": self.blocked_topics,
        }


class DialogueRules:
    """
    Validates dialogue actions and manages state.
    
    Rules:
    - Must be in dialogue mode to perform dialogue actions
    - NPC mood affects available dialogue options
    - Trust level affects information revealed
    - Some topics may be blocked based on state
    """
    
    def __init__(self):
        self._mood_requirements = {
            DialogueActionType.THREATEN: ["hostile", "angry"],
            DialogueActionType.PERSUADE: ["neutral", "friendly", "curious"],
        }
        self._trust_thresholds = {
            DialogueActionType.ASK: 0.3,
            DialogueActionType.TELL: 0.5,
            DialogueActionType.PERSUADE: 0.7,
        }
    
    def validate_action(
        self,
        action_type: DialogueActionType,
        target_npc: str,
        game_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate a dialogue action.
        
        Args:
            action_type: Type of dialogue action
            target_npc: ID of the target NPC
            game_state: Current game state
            
        Returns:
            Validation result
        """
        current_mode = game_state.get("current_mode", "exploration")
        if current_mode != "dialogue":
            return {
                "valid": False,
                "reason": "Not in dialogue mode",
                "action_type": action_type.value,
                "target_npc": target_npc,
            }
        
        npc_states = game_state.get("npc_states", {})
        npc = npc_states.get(target_npc)
        if not npc:
            return {
                "valid": False,
                "reason": f"NPC not found: {target_npc}",
                "action_type": action_type.value,
                "target_npc": target_npc,
            }
        
        npc_mood = npc.get("mood", "neutral")
        npc_trust = npc.get("trust_toward_player", 0.5)
        
        if action_type in self._mood_requirements:
            required_moods = self._mood_requirements[action_type]
            if npc_mood not in required_moods:
                return {
                    "valid": False,
                    "reason": f"NPC mood '{npc_mood}' not suitable for {action_type.value}",
                    "action_type": action_type.value,
                    "target_npc": target_npc,
                    "npc_mood": npc_mood,
                    "required_moods": required_moods,
                }
        
        if action_type in self._trust_thresholds:
            required_trust = self._trust_thresholds[action_type]
            if npc_trust < required_trust:
                return {
                    "valid": False,
                    "reason": f"NPC trust ({npc_trust:.2f}) below threshold ({required_trust:.2f})",
                    "action_type": action_type.value,
                    "target_npc": target_npc,
                    "npc_trust": npc_trust,
                    "required_trust": required_trust,
                }
        
        if action_type == DialogueActionType.END:
            return {
                "valid": True,
                "reason": "Dialogue ended",
                "action_type": action_type.value,
                "target_npc": target_npc,
                "ends_dialogue": True,
            }
        
        return {
            "valid": True,
            "reason": "Action valid",
            "action_type": action_type.value,
            "target_npc": target_npc,
            "npc_mood": npc_mood,
            "npc_trust": npc_trust,
        }
    
    def can_talk_to(self, npc_id: str, game_state: Dict[str, Any]) -> bool:
        """Check if player can talk to an NPC."""
        npc_states = game_state.get("npc_states", {})
        npc = npc_states.get(npc_id)
        if not npc:
            return False
        
        npc_status = npc.get("status", "alive")
        if npc_status != "alive":
            return False
        
        player_location = game_state.get("player_location", "")
        npc_location = npc.get("location_id", "")
        
        return player_location == npc_location
    
    def get_available_actions(
        self,
        npc_id: str,
        game_state: Dict[str, Any]
    ) -> List[DialogueActionType]:
        """Get available dialogue actions for an NPC."""
        actions = []
        
        for action_type in DialogueActionType:
            result = self.validate_action(action_type, npc_id, game_state)
            if result.get("valid"):
                actions.append(action_type)
        
        return actions
    
    def build_dialogue_context(
        self,
        npc_id: str,
        game_state: Dict[str, Any]
    ) -> DialogueContext:
        """Build dialogue context for an NPC."""
        npc_states = game_state.get("npc_states", {})
        npc = npc_states.get(npc_id, {})
        
        return DialogueContext(
            npc_id=npc_id,
            npc_mood=npc.get("mood", "neutral"),
            npc_trust=npc.get("trust_toward_player", 0.5),
            available_topics=npc.get("available_topics", []),
            blocked_topics=npc.get("blocked_topics", []),
        )
    
    def set_mood_requirement(
        self,
        action_type: DialogueActionType,
        moods: List[str]
    ) -> None:
        """Set required moods for a dialogue action."""
        self._mood_requirements[action_type] = moods
    
    def set_trust_threshold(
        self,
        action_type: DialogueActionType,
        threshold: float
    ) -> None:
        """Set trust threshold for a dialogue action."""
        self._trust_thresholds[action_type] = threshold

from typing import Any, Dict, List, Optional

from ..models.states import CanonicalState, NPCState
from ..models.memories import NPCMemoryScope
from ..models.common import ProposedAction
from ..models.perspectives import NPCPerspective

from ..core.canonical_state import CanonicalStateManager
from ..core.npc_memory import NPCMemoryManager
from ..core.perspective import PerspectiveService
from ..core.context_builder import ContextBuilder


class NPCEngine:
    
    def __init__(
        self,
        state_manager: CanonicalStateManager,
        memory_manager: NPCMemoryManager,
        perspective_service: PerspectiveService,
        context_builder: ContextBuilder,
    ):
        self._state_manager = state_manager
        self._memory_manager = memory_manager
        self._perspective = perspective_service
        self._context_builder = context_builder
    
    def generate_npc_action(
        self,
        npc_id: str,
        game_id: str,
        turn_index: int,
    ) -> Optional[ProposedAction]:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return None
        
        npc_state = state.npc_states.get(npc_id)
        if npc_state is None:
            return None
        
        if npc_state.status != "alive":
            return None
        
        scope = self._memory_manager.get_scope(npc_id)
        if scope is None:
            return None
        
        context = self._context_builder.build_npc_context(
            npc_id=npc_id,
            game_id=game_id,
            turn_id=str(turn_index),
            state=state,
            npc_scope=scope,
        )
        
        action = self._decide_action(npc_id, npc_state, scope, context)
        
        return action
    
    def _decide_action(
        self,
        npc_id: str,
        npc_state: NPCState,
        scope: NPCMemoryScope,
        context: Any,
    ) -> ProposedAction:
        if npc_state.current_goal_ids:
            goal_id = npc_state.current_goal_ids[0]
            return ProposedAction(
                action_id=f"npc_{npc_id}_goal_{goal_id}",
                actor_id=npc_id,
                action_type="pursue_goal",
                summary=f"{npc_state.name} 继续追求目标",
                priority=0.7,
            )
        
        return ProposedAction(
            action_id=f"npc_{npc_id}_idle",
            actor_id=npc_id,
            action_type="idle",
            summary=f"{npc_state.name} 等待着",
            priority=0.3,
        )
    
    def update_npc_state(
        self,
        npc_id: str,
        game_id: str,
        new_mood: Optional[str] = None,
        new_action: Optional[str] = None,
        new_location: Optional[str] = None,
    ) -> None:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return
        
        npc_state = state.npc_states.get(npc_id)
        if npc_state is None:
            return
        
        if new_mood:
            npc_state.mood = new_mood
        if new_action:
            npc_state.current_action = new_action
        if new_location:
            npc_state.location_id = new_location
    
    def record_npc_perception(
        self,
        npc_id: str,
        event_summary: str,
        turn_index: int,
        importance: float = 0.5,
    ) -> None:
        self._memory_manager.add_perceived_event(
            npc_id=npc_id,
            turn=turn_index,
            summary=event_summary,
            importance=importance,
        )
    
    def update_npc_beliefs(
        self,
        npc_id: str,
        content: str,
        belief_type: str = "fact",
        confidence: float = 0.5,
        truth_status: str = "unknown",
        turn_index: int = 0,
    ) -> None:
        self._memory_manager.add_belief(
            npc_id=npc_id,
            content=content,
            belief_type=belief_type,
            confidence=confidence,
            truth_status=truth_status,
            current_turn=turn_index,
        )
    
    def get_npc_context_for_player(
        self,
        npc_id: str,
        game_id: str,
        turn_index: int,
    ) -> Dict[str, Any]:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return {}
        
        npc_state = state.npc_states.get(npc_id)
        if npc_state is None:
            return {}
        
        return {
            "name": npc_state.name,
            "location_id": npc_state.location_id,
            "mood": npc_state.mood,
            "current_action": npc_state.current_action,
        }
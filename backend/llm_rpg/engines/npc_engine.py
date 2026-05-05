from typing import Any, Dict, List, Optional

from ..models.states import CanonicalState, NPCState
from ..models.memories import NPCMemoryScope
from ..models.common import ProposedAction, ContextPack
from ..models.perspectives import NPCPerspective
from ..models.proposals import NPCActionProposal, ProposalType, ProposalSource

from ..core.canonical_state import CanonicalStateManager
from ..core.npc_memory import NPCMemoryManager
from ..core.perspective import PerspectiveService
from ..core.context_builder import ContextBuilder
from ..llm.proposal_pipeline import ProposalPipeline


class NPCEngine:
    
    def __init__(
        self,
        state_manager: CanonicalStateManager,
        memory_manager: NPCMemoryManager,
        perspective_service: PerspectiveService,
        context_builder: ContextBuilder,
        proposal_pipeline: Optional[ProposalPipeline] = None,
    ):
        self._state_manager = state_manager
        self._memory_manager = memory_manager
        self._perspective = perspective_service
        self._context_builder = context_builder
        self._proposal_pipeline = proposal_pipeline
    
    def generate_npc_action(
        self,
        npc_id: str,
        game_id: str,
        turn_index: int,
    ) -> Optional[ProposedAction]:
        """
        Generate NPC action using the proposal pipeline.
        
        This method builds NPC context with perspective filtering, then uses
        the ProposalPipeline to generate an NPCActionProposal. Valid proposals
        are converted to ProposedAction. Falls back to goal/idle behavior if
        pipeline is unavailable or fails.
        
        The NPC prompt sees only perspective-filtered state - no other NPC
        private memories, no narrator-only hidden facts.
        """
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
        
        # Try to use proposal pipeline if available
        if self._proposal_pipeline is not None:
            proposal = self._generate_proposal_via_pipeline(
                npc_id=npc_id,
                game_id=game_id,
                turn_index=turn_index,
                context=context,
            )
            
            if proposal is not None:
                return self._convert_proposal_to_action(proposal, npc_state)
        
        # Fallback to deterministic goal/idle behavior
        return self._decide_action_fallback(npc_id, npc_state, scope, context)
    
    def _generate_proposal_via_pipeline(
        self,
        npc_id: str,
        game_id: str,
        turn_index: int,
        context: ContextPack,
    ) -> Optional[NPCActionProposal]:
        """
        Generate NPCActionProposal via the proposal pipeline.
        
        Uses synchronous wrapper since NPCEngine methods are synchronous.
        The pipeline handles LLM call, parsing, repair, and fallback.
        """
        import asyncio
        
        try:
            # Try to get running event loop (if in async context)
            loop = asyncio.get_running_loop()
            # We're in an async context, create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self._proposal_pipeline.generate_npc_action(
                        npc_id=npc_id,
                        npc_context=context.content,
                        session_id=game_id,
                        turn_no=turn_index,
                    )
                )
                return future.result(timeout=30.0)
        except RuntimeError:
            # No running event loop, use asyncio.run directly
            return asyncio.run(
                self._proposal_pipeline.generate_npc_action(
                    npc_id=npc_id,
                    npc_context=context.content,
                    session_id=game_id,
                    turn_no=turn_index,
                )
            )
    
    def _convert_proposal_to_action(
        self,
        proposal: NPCActionProposal,
        npc_state: NPCState,
    ) -> ProposedAction:
        """
        Convert a valid NPCActionProposal to ProposedAction.
        
        Maps proposal fields to ProposedAction contract:
        - action_type -> action_type
        - target -> target_ids
        - summary -> summary
        - visible_motivation -> intention
        - hidden_motivation -> hidden_motivation
        - state_deltas -> state_delta_candidates
        - confidence -> priority
        - visibility -> visible_to_player
        """
        target_ids = []
        if proposal.target:
            target_ids = [proposal.target]
        
        visible_to_player = proposal.visibility == "player_visible"
        
        # Convert state deltas
        state_delta_candidates = [
            {
                "path": delta.path,
                "operation": delta.operation,
                "value": delta.value,
                "reason": delta.reason,
            }
            for delta in proposal.state_deltas
        ]
        
        return ProposedAction(
            action_id=proposal.audit.proposal_id,
            actor_id=proposal.npc_id,
            action_type=proposal.action_type,
            target_ids=target_ids,
            summary=proposal.summary,
            intention=proposal.visible_motivation,
            visible_to_player=visible_to_player,
            hidden_motivation=proposal.hidden_motivation,
            state_delta_candidates=state_delta_candidates,
            priority=proposal.confidence,
        )
    
    def _decide_action_fallback(
        self,
        npc_id: str,
        npc_state: NPCState,
        scope: NPCMemoryScope,
        context: Any,
    ) -> ProposedAction:
        """
        Deterministic fallback when proposal pipeline is unavailable or fails.
        
        Preserves original goal/idle behavior:
        - If NPC has current goals, pursue the first one
        - Otherwise, idle
        """
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
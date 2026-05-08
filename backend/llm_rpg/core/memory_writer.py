import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..models.events import GameEvent, MemoryWriteEvent, MemoryTarget
from ..models.memories import Memory, MemoryType
from ..models.summaries import Summary
from ..models.states import CanonicalState

from .event_log import EventLog
from .npc_memory import NPCMemoryManager
from .summary import SummaryManager

if TYPE_CHECKING:
    from ..storage.repositories import (
        MemorySummaryRepository,
        MemoryFactRepository,
        NPCBeliefRepository,
        NPCRelationshipMemoryRepository,
    )


class MemoryWriter:
    
    def __init__(
        self,
        event_log: EventLog,
        npc_memory_manager: NPCMemoryManager,
        summary_manager: SummaryManager,
        memory_summary_repo: Optional["MemorySummaryRepository"] = None,
        memory_fact_repo: Optional["MemoryFactRepository"] = None,
        npc_belief_repo: Optional["NPCBeliefRepository"] = None,
        npc_relationship_repo: Optional["NPCRelationshipMemoryRepository"] = None,
        session_id: Optional[str] = None,
    ):
        """
        Initialize MemoryWriter with optional repository dependencies.
        
        When repositories are provided, the writer persists memories to DB.
        The in-memory managers (SummaryManager, NPCMemoryManager) are retained
        for backward compatibility and performance.
        
        Args:
            event_log: Event log for event sourcing
            npc_memory_manager: NPC memory manager for in-memory operations
            summary_manager: Summary manager for in-memory operations
            memory_summary_repo: Repository for memory_summaries table
            memory_fact_repo: Repository for memory_facts table
            npc_belief_repo: Repository for npc_beliefs table
            npc_relationship_repo: Repository for npc_relationship_memories table
            session_id: Session ID for DB operations (required if repos are provided)
        """
        self._event_log = event_log
        self._npc_memory = npc_memory_manager
        self._summary_manager = summary_manager
        
        # Repository dependencies (optional - if None, operates in memory-only mode)
        self._memory_summary_repo = memory_summary_repo
        self._memory_fact_repo = memory_fact_repo
        self._npc_belief_repo = npc_belief_repo
        self._npc_relationship_repo = npc_relationship_repo
        self._session_id = session_id
    
    def _is_db_backed(self) -> bool:
        return all([
            self._memory_summary_repo is not None,
            self._memory_fact_repo is not None,
            self._npc_belief_repo is not None,
            self._npc_relationship_repo is not None,
            self._session_id is not None,
        ])
    
    def _persist_summary_to_db(
        self,
        summary: Summary,
        scope_type: str,
        scope_ref_id: Optional[str] = None,
        importance_score: float = 0.5,
    ) -> None:
        if not self._is_db_backed():
            return
        
        from ..storage.models import generate_uuid
        
        self._memory_summary_repo.create({
            "id": summary.summary_id,
            "session_id": self._session_id,
            "scope_type": scope_type,
            "scope_ref_id": scope_ref_id,
            "summary_text": summary.content,
            "source_turn_range": {"start": summary.start_turn, "end": summary.end_turn},
            "importance_score": importance_score,
        })
    
    def _persist_fact_to_db(
        self,
        fact_id: str,
        fact_type: str,
        subject_ref: str,
        fact_key: str,
        fact_value: str,
        confidence: float = 1.0,
        source_event_id: Optional[str] = None,
    ) -> None:
        if not self._is_db_backed():
            return
        
        self._memory_fact_repo.create({
            "id": fact_id,
            "session_id": self._session_id,
            "fact_type": fact_type,
            "subject_ref": subject_ref,
            "fact_key": fact_key,
            "fact_value": fact_value,
            "confidence": confidence,
            "source_event_id": source_event_id,
        })
    
    def _persist_npc_belief_to_db(
        self,
        npc_id: str,
        content: str,
        belief_type: str = "fact",
        confidence: float = 0.5,
        truth_status: str = "unknown",
        source_event_id: Optional[str] = None,
        current_turn: int = 0,
    ) -> None:
        if not self._is_db_backed():
            return
        
        from ..storage.models import generate_uuid
        
        self._npc_belief_repo.create({
            "id": generate_uuid(),
            "session_id": self._session_id,
            "npc_id": npc_id,
            "belief_type": belief_type,
            "content": content,
            "confidence": confidence,
            "truth_status": truth_status,
            "source_event_id": source_event_id,
            "created_turn": current_turn,
            "last_updated_turn": current_turn,
        })
    
    def _persist_relationship_memory_to_db(
        self,
        npc_id: str,
        target_id: str,
        content: str,
        impact: Dict[str, int],
        source_event_id: Optional[str] = None,
        current_turn: int = 0,
    ) -> None:
        if not self._is_db_backed():
            return
        
        from ..storage.models import generate_uuid
        
        self._npc_relationship_repo.create({
            "id": generate_uuid(),
            "session_id": self._session_id,
            "npc_id": npc_id,
            "target_id": target_id,
            "content": content,
            "impact_json": impact,
            "source_event_id": source_event_id,
            "created_turn": current_turn,
        })
    
    def write_event_memories(
        self,
        event: GameEvent,
        state: CanonicalState,
        current_turn: int,
    ) -> List[Memory]:
        memories = []
        
        if hasattr(event, 'actor_id') and event.actor_id != "player":
            memory = self._npc_memory.add_memory(
                npc_id=event.actor_id,
                content=event.summary if hasattr(event, 'summary') else str(event),
                memory_type=MemoryType.EPISODIC,
                source_event_ids=[event.event_id],
                importance=event.metadata.get("importance", 0.5),
                current_turn=current_turn,
            )
            memories.append(memory)
        
        if hasattr(event, 'visible_to_player') and event.visible_to_player:
            for npc_id in state.current_scene_state.active_actor_ids:
                if npc_id != "player" and npc_id != getattr(event, 'actor_id', None):
                    memory = self._npc_memory.add_memory(
                        npc_id=npc_id,
                        content=event.summary if hasattr(event, 'summary') else str(event),
                        memory_type=MemoryType.EPISODIC,
                        source_event_ids=[event.event_id],
                        importance=event.metadata.get("importance", 0.5) * 0.8,
                        current_turn=current_turn,
                    )
                    memories.append(memory)
        
        return memories
    
    def write_state_change_memories(
        self,
        delta_path: str,
        old_value: Any,
        new_value: Any,
        state: CanonicalState,
        current_turn: int,
    ) -> List[Memory]:
        memories = []
        
        if "mood" in delta_path:
            parts = delta_path.split(".")
            if len(parts) >= 3 and parts[0] == "npcs":
                npc_id = parts[1]
                memory = self._npc_memory.add_memory(
                    npc_id=npc_id,
                    content=f"情绪从 {old_value} 变为 {new_value}",
                    memory_type=MemoryType.SEMANTIC,
                    importance=0.6,
                    emotional_weight=0.3,
                    current_turn=current_turn,
                )
                memories.append(memory)
        
        return memories
    
    def write_relationship_memories(
        self,
        source_id: str,
        target_id: str,
        event: GameEvent,
        impact: Dict[str, int],
        current_turn: int,
    ) -> None:
        content = event.summary if hasattr(event, 'summary') else str(event)
        
        self._npc_memory.add_relationship_memory(
            npc_id=source_id,
            target_id=target_id,
            content=content,
            impact=impact,
            source_event_ids=[event.event_id],
        )
        
        self._persist_relationship_memory_to_db(
            npc_id=source_id,
            target_id=target_id,
            content=content,
            impact=impact,
            source_event_id=event.event_id,
            current_turn=current_turn,
        )
    
    def write_npc_belief_update(
        self,
        npc_id: str,
        observed_event: GameEvent,
        current_turn: int,
        belief_type: str = "fact",
        confidence: float = 0.8,
    ) -> None:
        content = observed_event.summary if hasattr(observed_event, 'summary') else str(observed_event)
        
        self._npc_memory.add_belief(
            npc_id=npc_id,
            content=content,
            belief_type=belief_type,
            confidence=confidence,
            truth_status="unknown",
            source_event_ids=[observed_event.event_id],
            current_turn=current_turn,
        )
        
        self._persist_npc_belief_to_db(
            npc_id=npc_id,
            content=content,
            belief_type=belief_type,
            confidence=confidence,
            truth_status="unknown",
            source_event_id=observed_event.event_id,
            current_turn=current_turn,
        )
    
    def write_turn_summary(
        self,
        turn_index: int,
        events: List[GameEvent],
        state: CanonicalState,
    ) -> Summary:
        event_summaries = []
        for event in events:
            if hasattr(event, 'summary'):
                event_summaries.append(event.summary)
        
        content = f"回合 {turn_index}: " + "; ".join(event_summaries)
        
        summary = self._summary_manager.create_world_chronicle(
            start_turn=turn_index,
            end_turn=turn_index,
            content=content,
            location_ids=[state.current_scene_state.location_id],
            key_event_ids=[e.event_id for e in events],
            objective_facts=event_summaries,
        )
        
        self._persist_summary_to_db(
            summary=summary,
            scope_type="world",
            scope_ref_id=None,
            importance_score=0.5,
        )
        
        return summary
    
    def write_scene_summary(
        self,
        scene_id: str,
        start_turn: int,
        end_turn: int,
        events: List[GameEvent],
        state: CanonicalState,
    ) -> Summary:
        event_summaries = []
        for event in events:
            if hasattr(event, 'summary'):
                event_summaries.append(event.summary)
        
        content = f"场景 {scene_id} (回合 {start_turn}-{end_turn}): " + "; ".join(event_summaries)
        
        summary = self._summary_manager.create_scene_summary(
            scene_id=scene_id,
            start_turn=start_turn,
            end_turn=end_turn,
            content=content,
            key_event_ids=[e.event_id for e in events],
        )
        
        self._persist_summary_to_db(
            summary=summary,
            scope_type="scene",
            scope_ref_id=scene_id,
            importance_score=0.4,
        )
        
        return summary
    
    def write_npc_subjective_summary(
        self,
        npc_id: str,
        start_turn: int,
        end_turn: int,
        events: List[GameEvent],
        state: CanonicalState,
    ) -> Summary:
        event_summaries = []
        for event in events:
            if hasattr(event, 'summary'):
                event_summaries.append(event.summary)
        
        content = f"NPC {npc_id} 的主观记忆 (回合 {start_turn}-{end_turn}): " + "; ".join(event_summaries)
        
        summary = self._summary_manager.create_npc_subjective_summary(
            npc_id=npc_id,
            start_turn=start_turn,
            end_turn=end_turn,
            subjective_summary=content,
        )
        
        self._persist_summary_to_db(
            summary=summary,
            scope_type="npc",
            scope_ref_id=npc_id,
            importance_score=0.6,
        )
        
        return summary
    
    def write_memory_event(
        self,
        transaction_id: str,
        turn_index: int,
        memories: List[Memory],
    ) -> MemoryWriteEvent:
        targets = []
        for memory in memories:
            targets.append(MemoryTarget(
                owner_type=memory.owner_type,
                owner_id=memory.owner_id,
                memory_id=memory.memory_id,
                memory_type=memory.memory_type,
            ))
        
        event = MemoryWriteEvent(
            event_id=f"evt_memory_{uuid.uuid4().hex[:8]}",
            turn_index=turn_index,
            memory_targets=targets,
        )
        
        return event
    
    def process_turn(
        self,
        turn_index: int,
        events: List[GameEvent],
        state: CanonicalState,
    ) -> Dict[str, Any]:
        all_memories = []
        
        for event in events:
            memories = self.write_event_memories(event, state, turn_index)
            all_memories.extend(memories)
        
        summary = self.write_turn_summary(turn_index, events, state)
        
        for npc_id in state.current_scene_state.active_actor_ids:
            if npc_id != "player":
                self.write_npc_subjective_summary(
                    npc_id=npc_id,
                    start_turn=turn_index,
                    end_turn=turn_index,
                    events=events,
                    state=state,
                )
        
        return {
            "memories_created": len(all_memories),
            "summary_created": summary.summary_id,
            "memory_ids": [m.memory_id for m in all_memories],
        }
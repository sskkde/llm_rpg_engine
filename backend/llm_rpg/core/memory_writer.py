import uuid
from typing import Any, Dict, List, Optional

from ..models.events import GameEvent, MemoryWriteEvent, MemoryTarget
from ..models.memories import Memory, MemoryType
from ..models.summaries import Summary
from ..models.states import CanonicalState

from .event_log import EventLog
from .npc_memory import NPCMemoryManager
from .summary import SummaryManager


class MemoryWriter:
    
    def __init__(
        self,
        event_log: EventLog,
        npc_memory_manager: NPCMemoryManager,
        summary_manager: SummaryManager,
    ):
        self._event_log = event_log
        self._npc_memory = npc_memory_manager
        self._summary_manager = summary_manager
    
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
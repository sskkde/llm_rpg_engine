import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..models.memories import (
    Memory,
    MemoryType,
    MemorySourceType,
    NPCProfile,
    Belief,
    NPCBeliefState,
    NPCPrivateMemory,
    RelationshipMemoryEntry,
    NPCRelationshipMemory,
    PerceivedEvent,
    NPCRecentContext,
    Secret,
    NPCSecrets,
    NPCKnowledgeState,
    NPCGoal,
    NPCGoals,
    ForgetCurve,
    NPCMemoryScope,
)

if TYPE_CHECKING:
    from ..storage.repositories import (
        NPCMemoryScopeRepository,
        NPCBeliefRepository,
        NPCPrivateMemoryRepository,
        NPCSecretRepository,
        NPCRelationshipMemoryRepository,
    )


class NPCMemoryManager:
    
    def __init__(
        self,
        scope_repo: Optional["NPCMemoryScopeRepository"] = None,
        belief_repo: Optional["NPCBeliefRepository"] = None,
        memory_repo: Optional["NPCPrivateMemoryRepository"] = None,
        secret_repo: Optional["NPCSecretRepository"] = None,
        relationship_repo: Optional["NPCRelationshipMemoryRepository"] = None,
        session_id: Optional[str] = None,
    ):
        """
        Initialize NPCMemoryManager with optional repository dependencies.
        
        When repositories are provided, the manager becomes DB-backed with DB as
        the authoritative source. The in-memory cache (_scopes, _memories) is
        retained for performance.
        
        Args:
            scope_repo: Repository for NPC memory scopes
            belief_repo: Repository for NPC beliefs
            memory_repo: Repository for NPC private memories
            secret_repo: Repository for NPC secrets
            relationship_repo: Repository for NPC relationship memories
            session_id: Session ID for DB operations (required if repos are provided)
        """
        self._scopes: Dict[str, NPCMemoryScope] = {}
        self._memories: Dict[str, Memory] = {}
        
        # Repository dependencies (optional - if None, operates in memory-only mode)
        self._scope_repo = scope_repo
        self._belief_repo = belief_repo
        self._memory_repo = memory_repo
        self._secret_repo = secret_repo
        self._relationship_repo = relationship_repo
        self._session_id = session_id
    
    def _is_db_backed(self) -> bool:
        """Check if the manager has DB repositories configured."""
        return all([
            self._scope_repo is not None,
            self._belief_repo is not None,
            self._memory_repo is not None,
            self._secret_repo is not None,
            self._relationship_repo is not None,
            self._session_id is not None,
        ])
    
    def create_npc_scope(
        self,
        npc_id: str,
        profile: NPCProfile,
        initial_goals: List[NPCGoal] = None,
    ) -> NPCMemoryScope:
        scope = NPCMemoryScope(
            npc_id=npc_id,
            profile=profile,
            belief_state=NPCBeliefState(npc_id=npc_id),
            recent_context=NPCRecentContext(npc_id=npc_id),
            secrets=NPCSecrets(npc_id=npc_id),
            knowledge_state=NPCKnowledgeState(npc_id=npc_id),
            goals=NPCGoals(npc_id=npc_id, goals=initial_goals or []),
        )
        
        if self._is_db_backed():
            from ..storage.models import generate_uuid
            self._scope_repo.create_or_update({
                "id": generate_uuid(),
                "session_id": self._session_id,
                "npc_id": npc_id,
                "profile_json": profile.model_dump() if hasattr(profile, 'model_dump') else profile.dict(),
                "forget_curve_json": scope.forget_curve.model_dump() if hasattr(scope.forget_curve, 'model_dump') else scope.forget_curve.dict(),
            })
        
        self._scopes[npc_id] = scope
        return scope
    
    def get_scope(self, npc_id: str) -> Optional[NPCMemoryScope]:
        scope = self._scopes.get(npc_id)
        if scope is None and self._is_db_backed():
            scope = self._load_scope_from_db(npc_id)
        return scope
    
    def _load_scope_from_db(self, npc_id: str) -> Optional[NPCMemoryScope]:
        if not self._is_db_backed():
            return None
        
        scope_model = self._scope_repo.get_by_session_and_npc(self._session_id, npc_id)
        if scope_model is None:
            return None
        
        profile_data = scope_model.profile_json or {}
        profile = NPCProfile(**profile_data) if profile_data else NPCProfile()
        
        forget_curve_data = scope_model.forget_curve_json or {}
        forget_curve = ForgetCurve(**forget_curve_data) if forget_curve_data else ForgetCurve()
        
        belief_models = self._belief_repo.get_by_npc(self._session_id, npc_id)
        beliefs = []
        for bm in belief_models:
            beliefs.append(Belief(
                belief_id=bm.id,
                content=bm.content,
                belief_type=bm.belief_type,
                confidence=bm.confidence,
                truth_status=bm.truth_status,
                source=MemorySourceType.DIRECT_OBSERVATION,
                source_event_ids=[bm.source_event_id] if bm.source_event_id else [],
                last_updated_turn=bm.last_updated_turn,
            ))
        
        memory_models = self._memory_repo.get_by_npc(self._session_id, npc_id)
        private_memories = []
        for mm in memory_models:
            private_memories.append(NPCPrivateMemory(
                memory_id=mm.id,
                owner_id=npc_id,
                memory_type=MemoryType(mm.memory_type),
                content=mm.content,
                source_event_ids=mm.source_event_ids_json or [],
                emotional_weight=mm.emotional_weight,
                importance=mm.importance,
                confidence=mm.confidence,
                current_strength=mm.current_strength,
                created_turn=mm.created_turn,
                last_accessed_turn=mm.last_accessed_turn,
                recall_count=mm.recall_count,
            ))
        
        secret_models = self._secret_repo.get_by_npc(self._session_id, npc_id)
        secrets = []
        for sm in secret_models:
            secrets.append(Secret(
                secret_id=sm.id,
                content=sm.content,
                willingness_to_reveal=sm.willingness_to_reveal,
                reveal_conditions=sm.reveal_conditions_json or [],
            ))
        
        relationship_models = self._relationship_repo.get_by_npc(self._session_id, npc_id)
        relationship_memories = []
        current_target = None
        current_rm = None
        for rm in relationship_models:
            if current_target != rm.target_id:
                if current_rm is not None:
                    relationship_memories.append(current_rm)
                current_target = rm.target_id
                current_rm = NPCRelationshipMemory(
                    owner_id=npc_id,
                    target_id=rm.target_id,
                )
            if current_rm is not None:
                current_rm.relationship_memory.append(RelationshipMemoryEntry(
                    content=rm.content,
                    impact=rm.impact_json or {},
                    source_event_ids=[rm.source_event_id] if rm.source_event_id else [],
                ))
        if current_rm is not None:
            relationship_memories.append(current_rm)
        
        scope = NPCMemoryScope(
            npc_id=npc_id,
            profile=profile,
            belief_state=NPCBeliefState(npc_id=npc_id, beliefs=beliefs),
            recent_context=NPCRecentContext(npc_id=npc_id),
            secrets=NPCSecrets(npc_id=npc_id, secrets=secrets),
            knowledge_state=NPCKnowledgeState(npc_id=npc_id),
            goals=NPCGoals(npc_id=npc_id, goals=[]),
            private_memories=private_memories,
            relationship_memories=relationship_memories,
            forget_curve=forget_curve,
        )
        
        self._scopes[npc_id] = scope
        return scope
    
    def add_memory(
        self,
        npc_id: str,
        content: str,
        memory_type: MemoryType = MemoryType.EPISODIC,
        source_event_ids: List[str] = None,
        entities: List[str] = None,
        importance: float = 0.5,
        emotional_weight: float = 0.0,
        confidence: float = 1.0,
        current_turn: int = 0,
    ) -> Memory:
        memory_id = f"mem_{npc_id}_{uuid.uuid4().hex[:8]}"
        memory = Memory(
            memory_id=memory_id,
            owner_type="npc",
            owner_id=npc_id,
            memory_type=memory_type,
            content=content,
            source_event_ids=source_event_ids or [],
            entities=entities or [],
            importance=importance,
            emotional_weight=emotional_weight,
            confidence=confidence,
            created_turn=current_turn,
            last_accessed_turn=current_turn,
        )
        
        if self._is_db_backed():
            from ..storage.models import generate_uuid
            self._memory_repo.create({
                "id": generate_uuid(),
                "session_id": self._session_id,
                "npc_id": npc_id,
                "memory_type": memory_type.value,
                "content": content,
                "source_event_ids_json": source_event_ids or [],
                "entities_json": entities or [],
                "importance": importance,
                "emotional_weight": emotional_weight,
                "confidence": confidence,
                "current_strength": 1.0,
                "created_turn": current_turn,
                "last_accessed_turn": current_turn,
                "recall_count": 0,
            })
        
        self._memories[memory_id] = memory
        
        scope = self._scopes.get(npc_id)
        if scope:
            private_memory = NPCPrivateMemory(
                memory_id=memory_id,
                owner_id=npc_id,
                memory_type=memory_type,
                content=content,
                source_event_ids=source_event_ids or [],
                emotional_weight=emotional_weight,
                importance=importance,
                confidence=confidence,
                created_turn=current_turn,
                last_accessed_turn=current_turn,
            )
            scope.private_memories.append(private_memory)
        
        return memory
    
    def add_belief(
        self,
        npc_id: str,
        content: str,
        belief_type: str = "fact",
        confidence: float = 0.5,
        truth_status: str = "unknown",
        source: MemorySourceType = MemorySourceType.DIRECT_OBSERVATION,
        source_event_ids: List[str] = None,
        current_turn: int = 0,
    ) -> Belief:
        belief_id = f"belief_{npc_id}_{uuid.uuid4().hex[:8]}"
        belief = Belief(
            belief_id=belief_id,
            content=content,
            belief_type=belief_type,
            confidence=confidence,
            truth_status=truth_status,
            source=source,
            source_event_ids=source_event_ids or [],
            last_updated_turn=current_turn,
        )
        
        if self._is_db_backed():
            from ..storage.models import generate_uuid
            source_event_id = source_event_ids[0] if source_event_ids else None
            self._belief_repo.create({
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
        
        scope = self._scopes.get(npc_id)
        if scope:
            scope.belief_state.beliefs.append(belief)
        
        return belief
    
    def add_perceived_event(
        self,
        npc_id: str,
        turn: int,
        summary: str,
        perception_type: str = "direct_observation",
        importance: float = 0.5,
    ) -> None:
        scope = self._scopes.get(npc_id)
        if scope:
            event = PerceivedEvent(
                turn=turn,
                summary=summary,
                perception_type=perception_type,
                importance=importance,
            )
            scope.recent_context.recent_perceived_events.append(event)
            
            max_recent = 20
            if len(scope.recent_context.recent_perceived_events) > max_recent:
                scope.recent_context.recent_perceived_events = \
                    scope.recent_context.recent_perceived_events[-max_recent:]
    
    def add_secret(
        self,
        npc_id: str,
        content: str,
        willingness_to_reveal: float = 0.1,
        reveal_conditions: List[str] = None,
    ) -> Secret:
        secret_id = f"secret_{npc_id}_{uuid.uuid4().hex[:8]}"
        secret = Secret(
            secret_id=secret_id,
            content=content,
            willingness_to_reveal=willingness_to_reveal,
            reveal_conditions=reveal_conditions or [],
        )
        
        if self._is_db_backed():
            from ..storage.models import generate_uuid
            self._secret_repo.create({
                "id": generate_uuid(),
                "session_id": self._session_id,
                "npc_id": npc_id,
                "content": content,
                "willingness_to_reveal": willingness_to_reveal,
                "reveal_conditions_json": reveal_conditions or [],
                "status": "hidden",
            })
        
        scope = self._scopes.get(npc_id)
        if scope:
            scope.secrets.secrets.append(secret)
        
        return secret
    
    def add_relationship_memory(
        self,
        npc_id: str,
        target_id: str,
        content: str,
        impact: Dict[str, int],
        source_event_ids: List[str] = None,
    ) -> None:
        scope = self._scopes.get(npc_id)
        if scope:
            entry = RelationshipMemoryEntry(
                content=content,
                impact=impact,
                source_event_ids=source_event_ids or [],
            )
            
            existing = None
            for rm in scope.relationship_memories:
                if rm.target_id == target_id:
                    existing = rm
                    break
            
            if existing is None:
                existing = NPCRelationshipMemory(
                    owner_id=npc_id,
                    target_id=target_id,
                )
                scope.relationship_memories.append(existing)
            
            existing.relationship_memory.append(entry)
    
    def update_knowledge(
        self,
        npc_id: str,
        known_facts: List[str] = None,
        known_rumors: List[str] = None,
        known_secrets: List[str] = None,
        forbidden_knowledge: List[str] = None,
    ) -> None:
        scope = self._scopes.get(npc_id)
        if scope:
            if known_facts:
                scope.knowledge_state.known_facts.extend(known_facts)
            if known_rumors:
                scope.knowledge_state.known_rumors.extend(known_rumors)
            if known_secrets:
                scope.knowledge_state.known_secrets.extend(known_secrets)
            if forbidden_knowledge:
                scope.knowledge_state.forbidden_knowledge.extend(forbidden_knowledge)
    
    def add_goal(
        self,
        npc_id: str,
        description: str,
        priority: float = 0.5,
        related_entities: List[str] = None,
    ) -> NPCGoal:
        goal_id = f"goal_{npc_id}_{uuid.uuid4().hex[:8]}"
        goal = NPCGoal(
            goal_id=goal_id,
            description=description,
            priority=priority,
            related_entities=related_entities or [],
        )
        
        scope = self._scopes.get(npc_id)
        if scope:
            scope.goals.goals.append(goal)
        
        return goal
    
    def compute_memory_strength(self, memory: Memory, current_turn: int) -> float:
        scope = self._scopes.get(memory.owner_id)
        if scope is None:
            return memory.current_strength
        
        curve = scope.forget_curve
        
        time_passed = current_turn - memory.last_accessed_turn
        time_decay = curve.time_decay * time_passed
        
        strength = (
            memory.importance
            + memory.emotional_weight * 0.3
            + curve.relationship_impact * 0.2
            + curve.plot_relevance * 0.2
            + curve.recall_reinforcement * (memory.recall_count * 0.1)
            - time_decay
        )
        
        return max(0.0, min(1.0, strength))
    
    def get_memories_for_context(
        self,
        npc_id: str,
        current_turn: int,
        limit: int = 10,
        min_strength: float = 0.3,
    ) -> List[Memory]:
        scope = self._scopes.get(npc_id)
        if scope is None:
            return []
        
        relevant_memories = []
        for memory in scope.private_memories:
            strength = self.compute_memory_strength(
                Memory(
                    memory_id=memory.memory_id,
                    owner_type="npc",
                    owner_id=npc_id,
                    memory_type=memory.memory_type,
                    content=memory.content,
                    source_event_ids=memory.source_event_ids,
                    importance=memory.importance,
                    emotional_weight=memory.emotional_weight,
                    confidence=memory.confidence,
                    current_strength=memory.current_strength,
                    created_turn=memory.created_turn,
                    last_accessed_turn=memory.last_accessed_turn,
                    recall_count=memory.recall_count,
                ),
                current_turn,
            )
            
            if strength >= min_strength:
                relevant_memories.append((memory, strength))
        
        relevant_memories.sort(key=lambda x: x[1], reverse=True)
        
        result = []
        for memory, strength in relevant_memories[:limit]:
            memory.last_accessed_turn = current_turn
            memory.recall_count += 1
            memory.current_strength = strength
            
            result.append(Memory(
                memory_id=memory.memory_id,
                owner_type="npc",
                owner_id=npc_id,
                memory_type=memory.memory_type,
                content=memory.content,
                source_event_ids=memory.source_event_ids,
                importance=memory.importance,
                emotional_weight=memory.emotional_weight,
                confidence=memory.confidence,
                current_strength=strength,
                created_turn=memory.created_turn,
                last_accessed_turn=current_turn,
                recall_count=memory.recall_count,
            ))
        
        return result
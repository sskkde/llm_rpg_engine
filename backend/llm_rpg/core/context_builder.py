from datetime import datetime
from typing import Any, Dict, List, Optional

from ..models.common import ContextPack, MemoryQuery, TimeRange
from ..models.states import CanonicalState, CurrentSceneState, NPCState
from ..models.perspectives import (
    Perspective,
    WorldPerspective,
    PlayerPerspective,
    NPCPerspective,
    NarratorPerspective,
)
from ..models.memories import NPCMemoryScope
from ..models.lore import LoreEntry, LoreView
from ..models.summaries import Summary
from ..models.events import GameEvent

from .retrieval import RetrievalSystem
from .perspective import PerspectiveService
from .perception import PerceptionResolver
from .projections import (
    PlayerVisibleProjectionBuilder,
    NPCVisibleProjectionBuilder,
    NarratorProjectionBuilder,
)


def _retrieve_memories_for_narration_context(
    db,
    session_id: str,
    current_location_id: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant memories for narration context.
    
    CRITICAL: Only retrieves world/session/scene memories, NEVER NPC subjective memories.
    """
    from ..storage.repositories import MemorySummaryRepository
    
    memory_repo = MemorySummaryRepository(db)
    
    summaries = []
    
    # Get world-level chronicles
    world_summaries = memory_repo.get_by_scope(
        session_id=session_id,
        scope_type="world",
    )
    summaries.extend(world_summaries[:limit])
    
    # Get scene-level summaries for current location
    if current_location_id:
        scene_summaries = memory_repo.get_by_scope(
            session_id=session_id,
            scope_type="scene",
            scope_ref_id=current_location_id,
        )
        summaries.extend(scene_summaries[:limit])
    
    # Sort by importance and return as dicts
    sorted_summaries = sorted(
        summaries,
        key=lambda s: s.importance_score,
        reverse=True,
    )[:limit]
    
    return [
        {
            "summary_text": s.summary_text,
            "importance": s.importance_score,
        }
        for s in sorted_summaries
    ]


def _retrieve_memories_for_npc_context(
    db,
    session_id: str,
    npc_id: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant memories for NPC context.
    
    Includes NPC subjective memories scoped by NPC ID.
    """
    from ..storage.repositories import (
        MemorySummaryRepository,
        MemoryFactRepository,
        NPCBeliefRepository,
        NPCPrivateMemoryRepository,
        NPCSecretRepository,
        NPCRelationshipMemoryRepository,
    )
    
    memory_repo = MemorySummaryRepository(db)
    fact_repo = MemoryFactRepository(db)
    belief_repo = NPCBeliefRepository(db)
    private_memory_repo = NPCPrivateMemoryRepository(db)
    secret_repo = NPCSecretRepository(db)
    relationship_repo = NPCRelationshipMemoryRepository(db)
    
    summaries = []
    
    # Get NPC subjective memories
    npc_summaries = memory_repo.get_by_scope(
        session_id=session_id,
        scope_type="npc",
        scope_ref_id=npc_id,
    )
    summaries.extend(npc_summaries[:limit])
    
    # Get NPC belief facts
    npc_beliefs = fact_repo.get_by_subject(session_id, npc_id)
    
    # Sort by importance and return as dicts
    sorted_summaries = sorted(
        summaries,
        key=lambda s: s.importance_score,
        reverse=True,
    )[:limit]
    
    result = [
        {
            "summary_text": s.summary_text,
            "importance": s.importance_score,
        }
        for s in sorted_summaries
    ]
    
    # Add belief facts
    for fact in npc_beliefs[:limit]:
        result.append({
            "memory_kind": "fact",
            "fact_type": fact.fact_type,
            "fact_value": fact.fact_value,
            "confidence": fact.confidence,
        })
    
    db_beliefs = sorted(
        belief_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda belief: (belief.confidence, belief.last_updated_turn, belief.created_turn),
        reverse=True,
    )[:limit]
    for belief in db_beliefs:
        result.append({
            "memory_kind": "npc_belief",
            "belief_id": belief.id,
            "belief_type": belief.belief_type,
            "content": belief.content,
            "confidence": belief.confidence,
            "truth_status": belief.truth_status,
            "source_event_id": belief.source_event_id,
            "created_turn": belief.created_turn,
            "last_updated_turn": belief.last_updated_turn,
        })
    
    db_private_memories = sorted(
        private_memory_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda memory: (memory.importance, memory.current_strength, memory.created_turn),
        reverse=True,
    )[:limit]
    for memory in db_private_memories:
        result.append({
            "memory_kind": "npc_private_memory",
            "memory_id": memory.id,
            "memory_type": memory.memory_type,
            "content": memory.content,
            "source_event_ids": memory.source_event_ids_json or [],
            "entities": memory.entities_json or [],
            "importance": memory.importance,
            "emotional_weight": memory.emotional_weight,
            "confidence": memory.confidence,
            "current_strength": memory.current_strength,
            "created_turn": memory.created_turn,
            "last_accessed_turn": memory.last_accessed_turn,
            "recall_count": memory.recall_count,
        })
    
    db_secrets = sorted(
        secret_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda secret: (secret.willingness_to_reveal, secret.created_at),
        reverse=True,
    )[:limit]
    for secret in db_secrets:
        result.append({
            "memory_kind": "npc_secret",
            "secret_id": secret.id,
            "content": secret.content,
            "willingness_to_reveal": secret.willingness_to_reveal,
            "reveal_conditions": secret.reveal_conditions_json or [],
            "status": secret.status,
            "created_at": secret.created_at.isoformat() if isinstance(secret.created_at, datetime) else None,
        })
    
    db_relationship_memories = sorted(
        relationship_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda memory: memory.created_turn,
        reverse=True,
    )[:limit]
    for memory in db_relationship_memories:
        result.append({
            "memory_kind": "npc_relationship_memory",
            "memory_id": memory.id,
            "target_id": memory.target_id,
            "content": memory.content,
            "impact": memory.impact_json or {},
            "source_event_id": memory.source_event_id,
            "created_turn": memory.created_turn,
        })
    
    return result


class ContextBuilder:
    """
    Builds context packs for different perspectives.

    Ensures proper perspective filtering so that:
    - NPC contexts receive only allowed facts, beliefs, rumors, and secrets
    - NarratorPerspective uses PlayerVisibleProjection only
    - Hidden lore never appears in contexts until reveal condition is satisfied
    """

    def __init__(
        self,
        retrieval_system: RetrievalSystem,
        perspective_service: PerspectiveService,
        perception_resolver: PerceptionResolver | None = None,
        player_projection_builder: PlayerVisibleProjectionBuilder | None = None,
        npc_projection_builder: NPCVisibleProjectionBuilder | None = None,
        narrator_projection_builder: NarratorProjectionBuilder | None = None,
    ):
        self._retrieval = retrieval_system
        self._perspective = perspective_service
        
        # New perception system (optional, for gradual migration)
        self._perception_resolver = perception_resolver
        self._player_projection = player_projection_builder
        self._npc_projection = npc_projection_builder
        self._narrator_projection = narrator_projection_builder
        
        # Flag to determine whether to use new projection system
        self._use_projection_system = (
            perception_resolver is not None
            and player_projection_builder is not None
            and npc_projection_builder is not None
            and narrator_projection_builder is not None
        )

    def build_world_context(
        self,
        game_id: str,
        turn_id: str,
        state: CanonicalState,
        recent_events: List[GameEvent] = None,
        relevant_lore: List[LoreEntry] = None,
    ) -> ContextPack:
        """
        Build context for the world engine.

        World perspective sees everything including hidden information.
        """
        content = {
            "world_state": state.world_state.model_dump(),
            "player_state": state.player_state.model_dump(),
            "scene_state": state.current_scene_state.model_dump(),
            "location_states": {k: v.model_dump() for k, v in state.location_states.items()},
            "npc_states": {k: v.model_dump() for k, v in state.npc_states.items()},
            "quest_states": {k: v.model_dump() for k, v in state.quest_states.items()},
            "faction_states": {k: v.model_dump() for k, v in state.faction_states.items()},
        }

        if recent_events:
            content["recent_events"] = [e.model_dump() for e in recent_events]

        if relevant_lore:
            content["relevant_lore"] = [l.model_dump() for l in relevant_lore]

        return ContextPack(
            context_id=f"world_{game_id}_{turn_id}",
            context_type="world",
            content=content,
        )

    def build_npc_context(
        self,
        npc_id: str,
        game_id: str,
        turn_id: str,
        state: CanonicalState,
        npc_scope: NPCMemoryScope,
        recent_events: List[GameEvent] = None,
        relevant_lore: List[LoreEntry] = None,
    ) -> ContextPack:
        """
        Build context for an NPC decision.

        NPC contexts receive only allowed facts, beliefs, rumors, and secrets.
        Hidden lore and forbidden knowledge are NEVER included.
        """
        npc_state = state.npc_states.get(npc_id)
        scene_state = state.current_scene_state

        known_facts = npc_scope.knowledge_state.known_facts
        known_rumors = npc_scope.knowledge_state.known_rumors
        known_secrets = npc_scope.knowledge_state.known_secrets
        forbidden_knowledge = npc_scope.knowledge_state.forbidden_knowledge

        # Get visible entities (NPCs/locations in current scene)
        visible_entity_ids = []
        if scene_state:
            visible_entity_ids = list(scene_state.active_actor_ids)

        # Use hybrid retrieval with perspective filtering
        npc_perspective = self._perspective.build_npc_perspective(
            perspective_id=f"npc_{npc_id}",
            npc_id=npc_id,
            known_facts=known_facts,
            believed_rumors=known_rumors,
            secrets=known_secrets,
            forbidden_knowledge=forbidden_knowledge,
        )

        relevant_memories = self._retrieval.hybrid_retrieve(
            query=MemoryQuery(
                owner_id=npc_id,
                owner_type="npc",
                limit=10,
                importance_threshold=0.3,
            ),
            perspective=npc_perspective,
            visible_entity_ids=visible_entity_ids,
            current_state={"current_turn": getattr(state.world_state, 'current_turn', 0)},
        )

        # Filter lore for NPC perspective
        filtered_lore = []
        if relevant_lore:
            lore_views = self._perspective.filter_lore_for_perspective(
                relevant_lore, npc_perspective
            )
            filtered_lore = [lv.model_dump() for lv in lore_views]

        # Filter events for NPC perspective
        filtered_events = []
        if recent_events:
            if self._use_projection_system:
                context = {
                    "npc_location_id": npc_state.location_id if npc_state else "unknown",
                    "current_turn": getattr(state.world_state, 'current_turn', 0),
                }
                filtered_events = self._npc_projection.build_projection(
                    events=recent_events,
                    perspective=npc_perspective,
                    context=context,
                )
            else:
                filtered_events = self._perspective.filter_events_for_perspective(
                    recent_events, npc_perspective
                )
                filtered_events = [e.model_dump() for e in filtered_events]

        # Build beliefs list (only those the NPC actually holds)
        beliefs = []
        for belief in npc_scope.belief_state.beliefs:
            beliefs.append({
                "content": belief.content,
                "type": belief.belief_type,
                "confidence": belief.confidence,
                "truth_status": belief.truth_status,
            })

        content = {
            "profile": npc_scope.profile.model_dump(),
            "current_state": npc_state.model_dump() if npc_state else None,
            "visible_scene": scene_state.model_dump() if scene_state else None,
            "known_facts": known_facts,
            "known_rumors": known_rumors,
            "forbidden_knowledge": forbidden_knowledge,
            "goals": [g.model_dump() for g in npc_scope.goals.goals],
            "recent_memories": [r.model_dump() for r in relevant_memories],
            "relationship_memories": [rm.model_dump() for rm in npc_scope.relationship_memories],
            "beliefs": beliefs,
        }

        if filtered_events:
            content["recent_events"] = filtered_events

        if filtered_lore:
            content["relevant_lore"] = filtered_lore

        # Add secrets separately - NPC knows them but won't reveal without conditions
        if npc_scope.secrets.secrets:
            content["secrets"] = [
                {
                    "secret_id": s.secret_id,
                    "content": s.content,
                    "willingness": s.willingness_to_reveal,
                    "conditions": s.reveal_conditions,
                }
                for s in npc_scope.secrets.secrets
            ]

        content["constraints"] = [
            f"不得泄露以下信息: {', '.join(forbidden_knowledge)}",
            "行动必须符合当前可见环境",
            "决策必须基于已知事实和信念",
        ]

        return ContextPack(
            context_id=f"npc_{npc_id}_{game_id}_{turn_id}",
            context_type="npc_decision",
            owner_id=npc_id,
            content=content,
            included_memory_ids=[r.memory_id for r in relevant_memories],
        )

    def build_player_visible_context(
        self,
        game_id: str,
        turn_id: str,
        state: CanonicalState,
        player_perspective: PlayerPerspective,
        recent_events: List[GameEvent] = None,
    ) -> ContextPack:
        """
        Build context showing only what the player can see.

        This is the canonical player-visible state used for both
        player contexts and narrator contexts.
        """
        scene_state = state.current_scene_state
        player_state = state.player_state

        visible_events = []
        if recent_events:
            if self._use_projection_system:
                context = {
                    "player_location_id": player_state.location_id,
                    "current_turn": getattr(state.world_state, 'current_turn', 0),
                }
                visible_events_dicts = self._player_projection.build_projection(
                    events=recent_events,
                    perspective=player_perspective,
                    context=context,
                )
                visible_events = visible_events_dicts
            else:
                visible_events = self._perspective.filter_events_for_perspective(
                    recent_events, player_perspective
                )
                visible_events = [e.model_dump() for e in visible_events]

        visible_npc_states = {}
        if scene_state:
            for npc_id, npc_state in state.npc_states.items():
                if npc_id in scene_state.active_actor_ids:
                    visible_npc_states[npc_id] = {
                        "name": npc_state.name,
                        "location_id": npc_state.location_id,
                        "mood": npc_state.mood,
                        "current_action": npc_state.current_action,
                    }

        content = {
            "player_state": player_state.model_dump(),
            "visible_scene": scene_state.model_dump() if scene_state else None,
            "visible_npc_states": visible_npc_states,
            "known_facts": player_perspective.known_facts,
            "known_rumors": player_perspective.known_rumors,
            "visible_events": visible_events,
            "available_actions": scene_state.available_actions if scene_state else [],
        }

        return ContextPack(
            context_id=f"player_visible_{game_id}_{turn_id}",
            context_type="player_visible",
            owner_id="player",
            content=content,
        )

    def build_narration_context(
        self,
        game_id: str,
        turn_id: str,
        state: CanonicalState,
        player_perspective: PlayerPerspective,
        narrator_perspective: NarratorPerspective,
        recent_events: List[GameEvent] = None,
        scene_tone: str = "neutral",
        writing_style: str = "default",
    ) -> ContextPack:
        """
        Build context for the narration engine.

        CRITICAL: NarratorPerspective uses PlayerVisibleProjection only.
        Hidden lore facts known only to WorldPerspective are NEVER passed
        to the narrator context.

        The narrator should only narrate what the player can perceive.
        """
        player_visible_context = self.build_player_visible_context(
            game_id=game_id,
            turn_id=turn_id,
            state=state,
            player_perspective=player_perspective,
            recent_events=recent_events,
        )

        lore_entries = []
        filtered_lore_views = self._perspective.filter_lore_for_perspective(
            lore_entries, player_perspective
        )

        if self._use_projection_system and recent_events:
            context = {
                "player_location_id": state.player_state.location_id,
                "current_turn": getattr(state.world_state, 'current_turn', 0),
                "player_perspective": player_perspective,
            }
            narration_events = self._narrator_projection.build_projection(
                events=recent_events,
                perspective=narrator_perspective,
                context=context,
            )
            player_visible_context.content["visible_events"] = narration_events

        content = {
            "player_visible_context": player_visible_context.content,
            "scene_tone": scene_tone,
            "writing_style": writing_style,
            "narrator_tone": narrator_perspective.tone,
            "narrator_pacing": narrator_perspective.pacing,
            "style_requirements": narrator_perspective.style_requirements,
            "forbidden_info": narrator_perspective.forbidden_info,
            "allowed_hints": narrator_perspective.allowed_hints,
            "lore_context": [lv.model_dump() for lv in filtered_lore_views],
        }

        return ContextPack(
            context_id=f"narration_{game_id}_{turn_id}",
            context_type="narration",
            content=content,
        )

    def build_lore_context(
        self,
        game_id: str,
        turn_id: str,
        perspective: Perspective,
        lore_entries: List[LoreEntry],
        query: str = "",
    ) -> ContextPack:
        """
        Build lore context filtered for a specific perspective.

        Hidden lore facts known only to WorldPerspective never appear
        in NPC/player/narrator contexts until reveal condition is satisfied.
        """
        lore_views = self._perspective.filter_lore_for_perspective(
            lore_entries, perspective
        )

        content = {
            "lore_views": [lv.model_dump() for lv in lore_views],
            "perspective_id": perspective.perspective_id,
            "perspective_type": perspective.perspective_type.value,
            "query": query,
        }

        return ContextPack(
            context_id=f"lore_{game_id}_{turn_id}",
            context_type="lore",
            content=content,
        )

    # ========================================================================
    # P2 NPCContextBuilder Strengthening — new methods
    # ========================================================================

    def get_npc_perspective_facts(
        self,
        npc_id: str,
        state: CanonicalState,
        npc_scope: NPCMemoryScope,
    ) -> Dict[str, Any]:
        """
        Return facts visible to an NPC through their knowledge scope.

        NEVER returns omniscient canonical state data. Only facts within the
        NPC's knowledge_state.known_facts and directly perceivable scene info.
        """
        knowledge = npc_scope.knowledge_state
        scene_state = state.current_scene_state
        npc_state = state.npc_states.get(npc_id)

        # Known facts (filtered: exclude anything in forbidden_knowledge)
        forbidden_set = set(knowledge.forbidden_knowledge)
        safe_known_facts = [
            f for f in knowledge.known_facts
            if f not in forbidden_set
        ]

        # Visible scene facts — only what the NPC can directly perceive
        visible_scene = {}
        if scene_state and npc_state:
            npc_location = npc_state.location_id
            scene_location = scene_state.location_id

            if npc_location == scene_location:
                visible_scene = {
                    "scene_id": scene_state.scene_id,
                    "location_id": scene_state.location_id,
                    "active_actor_ids": scene_state.active_actor_ids,
                    "visible_object_ids": scene_state.visible_object_ids,
                    "scene_phase": scene_state.scene_phase,
                    "danger_level": scene_state.danger_level,
                }

        # Visible NPC states — only NPCs in the same scene that the NPC can perceive
        visible_npc_states: Dict[str, Dict[str, Any]] = {}
        if scene_state and npc_state and npc_state.location_id == scene_state.location_id:
            active_ids = set(scene_state.active_actor_ids)
            # NPC can see other active actors in the scene (but not their inner state)
            for other_id, other_state in state.npc_states.items():
                if other_id == npc_id:
                    continue
                if other_id in active_ids or other_state.location_id == scene_state.location_id:
                    visible_npc_states[other_id] = {
                        "name": other_state.name,
                        "location_id": other_state.location_id,
                        "mood": other_state.mood,
                        "current_action": other_state.current_action,
                        "status": other_state.status,
                    }

        # Private memories — the NPC's own secrets (not mixed with known_facts)
        private_memory_ids = [pm.memory_id for pm in npc_scope.private_memories]

        return {
            "known_facts": safe_known_facts,
            "known_rumors": knowledge.known_rumors,
            "known_secrets": knowledge.known_secrets,
            "forbidden_knowledge": knowledge.forbidden_knowledge,
            "visible_scene": visible_scene,
            "visible_npc_states": visible_npc_states,
            "private_memory_ids": private_memory_ids,
        }

    def get_npc_available_actions(
        self,
        npc_id: str,
        npc_scope: NPCMemoryScope,
        npc_state: NPCState,
        scene_state: CurrentSceneState,
    ) -> List[str]:
        """
        Return action types available to an NPC based on state and location.

        Actions depend on:
        - NPC status (dead NPCs have no actions)
        - Location match with scene (remote NPCs have limited actions)
        - Scene's available_actions
        - NPC mood and scene phase (combat → hostile actions)
        """
        # Dead NPCs cannot act
        if npc_state.status == "dead":
            return []

        # Base actions for alive NPCs
        base_actions = ["observe", "idle"]

        # Location-dependent actions
        npc_location = npc_state.location_id
        scene_location = scene_state.location_id

        in_scene = (npc_location == scene_location)

        if in_scene:
            # NPC is in the current scene — full interaction possible
            base_actions.extend(["talk", "act", "move"])

            # Scene-specific available actions (only available when in scene)
            scene_actions = set(scene_state.available_actions)
            for action in scene_actions:
                if action not in base_actions:
                    base_actions.append(action)
        else:
            # NPC is elsewhere — only limited actions
            base_actions.append("move")

        # Condition-dependent actions
        if npc_state.mood == "hostile" or scene_state.scene_phase == "combat":
            for combat_action in ["attack", "flee", "defend"]:
                if combat_action not in base_actions:
                    base_actions.append(combat_action)

        if npc_state.physical_state and npc_state.physical_state.injured:
            if "flee" not in base_actions:
                base_actions.append("flee")
            if "hide" not in base_actions:
                base_actions.append("hide")

        return base_actions

    def build_npc_decision_context(
        self,
        npc_id: str,
        game_id: str,
        turn_id: str,
        state: CanonicalState,
        npc_scope: NPCMemoryScope,
        recent_events: List[GameEvent] = None,
        relevant_lore: List[LoreEntry] = None,
    ) -> ContextPack:
        """
        Build a complete decision context for NPC actions.

        Includes:
        - Visible scene facts (perspective-filtered)
        - NPC known facts, beliefs, private memories
        - NPC goals and forbidden knowledge flags
        - Available actions based on state/location
        - Constraints preventing use of forbidden knowledge

        CRITICAL: Never includes omniscient canonical state data.
        NPC decisions must be based on what the NPC actually knows.
        """
        npc_state = state.npc_states.get(npc_id)
        scene_state = state.current_scene_state

        # Get perspective-filtered facts
        perspective_facts = self.get_npc_perspective_facts(
            npc_id, state, npc_scope
        )

        # Get available actions
        available_actions: List[str] = []
        if npc_state and scene_state:
            available_actions = self.get_npc_available_actions(
                npc_id, npc_scope, npc_state, scene_state
            )

        # Build NPC perspective for event/lore filtering
        known_facts = npc_scope.knowledge_state.known_facts
        known_rumors = npc_scope.knowledge_state.known_rumors
        known_secrets = npc_scope.knowledge_state.known_secrets
        forbidden_knowledge = npc_scope.knowledge_state.forbidden_knowledge

        npc_perspective = self._perspective.build_npc_perspective(
            perspective_id=f"npc_{npc_id}",
            npc_id=npc_id,
            known_facts=known_facts,
            believed_rumors=known_rumors,
            secrets=known_secrets,
            forbidden_knowledge=forbidden_knowledge,
        )

        # Filter recent events through NPC perspective
        filtered_events: List[Dict[str, Any]] = []
        if recent_events and npc_state:
            if self._use_projection_system:
                context = {
                    "npc_location_id": npc_state.location_id,
                    "current_turn": getattr(state.world_state, 'current_turn', 0),
                }
                filtered_events = self._npc_projection.build_projection(
                    events=recent_events,
                    perspective=npc_perspective,
                    context=context,
                )
            else:
                filtered = self._perspective.filter_events_for_perspective(
                    recent_events, npc_perspective
                )
                filtered_events = [e.model_dump() for e in filtered]

        # Filter lore through NPC perspective
        filtered_lore: List[Dict[str, Any]] = []
        if relevant_lore:
            lore_views = self._perspective.filter_lore_for_perspective(
                relevant_lore, npc_perspective
            )
            filtered_lore = [lv.model_dump() for lv in lore_views]

        # Build beliefs list
        beliefs = []
        for belief in npc_scope.belief_state.beliefs:
            beliefs.append({
                "content": belief.content,
                "type": belief.belief_type,
                "confidence": belief.confidence,
                "truth_status": belief.truth_status,
            })

        # Build private memories list
        private_memories = []
        for pm in npc_scope.private_memories:
            private_memories.append({
                "memory_id": pm.memory_id,
                "memory_type": pm.memory_type,
                "content": pm.content,
                "emotional_weight": pm.emotional_weight,
                "importance": pm.importance,
                "confidence": pm.confidence,
                "current_strength": pm.current_strength,
                "created_turn": pm.created_turn,
                "last_accessed_turn": pm.last_accessed_turn,
                "recall_count": pm.recall_count,
            })

        # Build goals list
        goals = []
        for goal in npc_scope.goals.goals:
            goals.append({
                "goal_id": goal.goal_id,
                "description": goal.description,
                "priority": goal.priority,
                "status": goal.status,
                "related_entities": goal.related_entities,
            })

        # Build relationship memories
        relationship_memories = []
        for rm in npc_scope.relationship_memories:
            entries = []
            for entry in rm.relationship_memory:
                entries.append({
                    "content": entry.content,
                    "impact": entry.impact,
                    "current_strength": entry.current_strength,
                })
            relationship_memories.append({
                "owner_id": rm.owner_id,
                "target_id": rm.target_id,
                "entries": entries,
            })

        # Forbidden knowledge flags — LLM needs to know what not to use
        forbidden_flags = list(npc_scope.knowledge_state.forbidden_knowledge)

        # Build constraints
        constraints = [
            "不得泄露或以任何方式使用 forbidden knowledge 中列出的信息",
            "行动必须基于已知事实（known_facts）和信念（beliefs），不得使用超出知识范围的信息",
            "决策必须符合当前可见环境和 NPC 角色设定",
            "私有记忆（private_memories）中的信息不得直接透露",
        ]
        if forbidden_flags:
            flags_str = ", ".join(forbidden_flags)
            constraints.append(
                f"严禁在行动中使用以下禁止知识: {flags_str}"
            )

        content: Dict[str, Any] = {
            "profile": npc_scope.profile.model_dump(),
            "current_state": npc_state.model_dump() if npc_state else None,
            "visible_scene_facts": perspective_facts.get("visible_scene", {}),
            "visible_npc_states": perspective_facts.get("visible_npc_states", {}),
            "known_facts": perspective_facts.get("known_facts", []),
            "known_rumors": perspective_facts.get("known_rumors", []),
            "known_secrets": perspective_facts.get("known_secrets", []),
            "beliefs": beliefs,
            "private_memories": private_memories,
            "goals": goals,
            "relationship_memories": relationship_memories,
            "forbidden_knowledge_flags": forbidden_flags,
            "available_actions": available_actions,
            "constraints": constraints,
        }

        if filtered_events:
            content["recent_events"] = filtered_events

        if filtered_lore:
            content["relevant_lore"] = filtered_lore

        # Secrets — NPC's own secrets (for internal decision context, not for output)
        if npc_scope.secrets.secrets:
            content["secrets"] = [
                {
                    "secret_id": s.secret_id,
                    "content": s.content,
                    "willingness": s.willingness_to_reveal,
                    "conditions": s.reveal_conditions,
                }
                for s in npc_scope.secrets.secrets
            ]

        return ContextPack(
            context_id=f"npc_decision_{npc_id}_{game_id}_{turn_id}",
            context_type="npc_decision",
            owner_id=npc_id,
            content=content,
        )

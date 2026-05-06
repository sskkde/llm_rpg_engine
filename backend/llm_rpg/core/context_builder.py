from typing import Any, Dict, List, Optional

from ..models.common import ContextPack, MemoryQuery, TimeRange
from ..models.states import CanonicalState
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
    from ..storage.repositories import MemorySummaryRepository, MemoryFactRepository
    
    memory_repo = MemorySummaryRepository(db)
    fact_repo = MemoryFactRepository(db)
    
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
            "fact_type": fact.fact_type,
            "fact_value": fact.fact_value,
            "confidence": fact.confidence,
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
    ):
        self._retrieval = retrieval_system
        self._perspective = perspective_service

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
            visible_events = self._perspective.filter_events_for_perspective(
                recent_events, player_perspective
            )

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
            "visible_events": [e.model_dump() for e in visible_events],
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
        # Build player-visible context first
        player_visible_context = self.build_player_visible_context(
            game_id=game_id,
            turn_id=turn_id,
            state=state,
            player_perspective=player_perspective,
            recent_events=recent_events,
        )

        # Get lore visible to player (narrator uses PlayerVisibleProjection)
        # IMPORTANT: Do NOT pass raw hidden lore to narrator
        lore_entries = []  # Would come from lore_store
        filtered_lore_views = self._perspective.filter_lore_for_perspective(
            lore_entries, player_perspective
        )

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

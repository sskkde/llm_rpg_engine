"""
Bridge between DB NPC state/templates and engine NPCState/NPCMemoryScope.

This module provides idempotent functions to build runtime NPC state objects
from persisted database models. It ensures NPCs have both NPCState and
NPCMemoryScope available for action generation.

Key functions:
- build_npc_state_from_db: Creates NPCState + minimal NPCMemoryScope from DB
- get_active_npcs_at_location: Returns all visible NPCs at a location
"""

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models.states import NPCState, PhysicalState, MentalState
from ..models.memories import (
    NPCProfile,
    NPCBeliefState,
    NPCRecentContext,
    NPCSecrets,
    NPCKnowledgeState,
    NPCGoals,
    NPCMemoryScope,
)
from ..storage.models import (
    SessionNPCStateModel,
    NPCTemplateModel,
    LocationModel,
)


@dataclass
class NPCStateWithScope:
    """Container for NPC state and memory scope."""
    npc_state: NPCState
    memory_scope: NPCMemoryScope
    hidden_identity: Optional[str] = None  # Not exposed to player-visible output


def build_npc_state_from_db(
    db: Session,
    session_id: str,
    npc_template_id: str,
) -> Optional[NPCStateWithScope]:
    """
    Build NPCState and minimal NPCMemoryScope from database models.
    
    This is an idempotent bridge that:
    1. Reads SessionNPCStateModel for runtime state (location, mood, trust, suspicion)
    2. Reads NPCTemplateModel for static data (name, personality, goals)
    3. Creates minimal NPCMemoryScope if not exists
    4. Returns NPCStateWithScope with both state and scope
    
    Args:
        db: Database session
        session_id: Game session ID
        npc_template_id: NPC template ID
        
    Returns:
        NPCStateWithScope if NPC exists, None otherwise
    """
    # Get session NPC state
    session_npc = db.query(SessionNPCStateModel).filter(
        SessionNPCStateModel.session_id == session_id,
        SessionNPCStateModel.npc_template_id == npc_template_id,
    ).first()
    
    if session_npc is None:
        return None
    
    # Get NPC template
    npc_template = db.query(NPCTemplateModel).filter(
        NPCTemplateModel.id == npc_template_id,
    ).first()
    
    if npc_template is None:
        return None
    
    # Build NPCState from session state + template
    npc_state = _build_npc_state(session_npc, npc_template)
    
    # Build minimal NPCMemoryScope
    memory_scope = _build_minimal_memory_scope(npc_template, session_npc)
    
    return NPCStateWithScope(
        npc_state=npc_state,
        memory_scope=memory_scope,
        hidden_identity=npc_template.hidden_identity,
    )


def get_active_npcs_at_location(
    db: Session,
    session_id: str,
    location_id: str,
) -> List[NPCStateWithScope]:
    """
    Get all NPCs currently at a specific location.
    
    Filters NPCs by current_location_id and excludes those with hidden
    identities from player-visible output (hidden_identity is stored
    in NPCStateWithScope but not exposed in narration).
    
    Args:
        db: Database session
        session_id: Game session ID
        location_id: Location ID to filter by
        
    Returns:
        List of NPCStateWithScope for NPCs at the location
    """
    # Query session NPC states at location
    session_npcs = db.query(SessionNPCStateModel).filter(
        SessionNPCStateModel.session_id == session_id,
        SessionNPCStateModel.current_location_id == location_id,
    ).all()
    
    results = []
    for session_npc in session_npcs:
        npc_with_scope = build_npc_state_from_db(
            db=db,
            session_id=session_id,
            npc_template_id=session_npc.npc_template_id,
        )
        if npc_with_scope is not None:
            results.append(npc_with_scope)
    
    return results


def _build_npc_state(
    session_npc: SessionNPCStateModel,
    npc_template: NPCTemplateModel,
) -> NPCState:
    """
    Build NPCState from session state and template.
    
    Maps database fields to runtime NPCState:
    - name, npc_id from template
    - location_id from session_npc.current_location_id
    - mood derived from trust/suspicion scores
    - trust/suspicion from session_npc scores
    """
    # Derive mood from trust and suspicion scores
    mood = _derive_mood(session_npc.trust_score, session_npc.suspicion_score)
    
    # Build physical and mental states
    physical_state = PhysicalState(
        hp=100,
        max_hp=100,
        injured=False,
        fatigue=0.0,
    )
    
    mental_state = MentalState(
        fear=0.0,
        trust_toward_player=session_npc.trust_score / 100.0,
        suspicion_toward_player=session_npc.suspicion_score / 100.0,
        mood=mood,
    )
    
    # Parse goals from template (stored as JSON list)
    goal_ids = []
    if npc_template.goals and isinstance(npc_template.goals, list):
        for i, goal in enumerate(npc_template.goals):
            if isinstance(goal, dict) and "id" in goal:
                goal_ids.append(goal["id"])
            elif isinstance(goal, str):
                goal_ids.append(f"goal_{npc_template.id}_{i}")
    
    return NPCState(
        entity_id=f"npc_{session_npc.id}",
        entity_type="npc",
        npc_id=npc_template.id,
        name=npc_template.name,
        status="alive",
        location_id=session_npc.current_location_id or "",
        mood=mood,
        current_goal_ids=goal_ids,
        current_action=None,
        physical_state=physical_state,
        mental_state=mental_state,
    )


def _build_minimal_memory_scope(
    npc_template: NPCTemplateModel,
    session_npc: SessionNPCStateModel,
) -> NPCMemoryScope:
    """
    Build minimal NPCMemoryScope from template and session state.
    
    Creates a functional but minimal scope with:
    - Basic profile (id, name, role, personality)
    - Empty belief state (populated during gameplay)
    - Empty recent context
    - Secrets from hidden_identity if present
    - Empty knowledge state
    - Goals from template
    """
    # Build profile
    personality = []
    if npc_template.personality:
        # Parse personality from text (could be comma-separated or newline-separated)
        if isinstance(npc_template.personality, str):
            personality = [
                p.strip() 
                for p in npc_template.personality.replace("\n", ",").split(",")
                if p.strip()
            ]
    
    profile = NPCProfile(
        npc_id=npc_template.id,
        name=npc_template.name,
        role=npc_template.role_type or "",
        true_identity=npc_template.hidden_identity,
        personality=personality,
        speech_style={"style": npc_template.speech_style} if npc_template.speech_style else {},
        core_goals=[],
    )
    
    # Parse goals from template
    goals = []
    if npc_template.goals and isinstance(npc_template.goals, list):
        for i, goal in enumerate(npc_template.goals):
            if isinstance(goal, dict):
                from ..models.memories import NPCGoal
                goals.append(NPCGoal(
                    goal_id=goal.get("id", f"goal_{npc_template.id}_{i}"),
                    description=goal.get("description", str(goal)),
                    priority=goal.get("priority", 0.5),
                    status="active",
                    related_entities=goal.get("related_entities", []),
                ))
    
    # Build secrets from hidden_identity
    secrets_list = []
    if npc_template.hidden_identity:
        from ..models.memories import Secret
        secrets_list.append(Secret(
            secret_id=f"secret_{npc_template.id}_identity",
            content=npc_template.hidden_identity,
            willingness_to_reveal=0.1,
            reveal_conditions=["trust > 80", "story_revealed"],
            known_by=[],
        ))
    
    return NPCMemoryScope(
        npc_id=npc_template.id,
        profile=profile,
        belief_state=NPCBeliefState(npc_id=npc_template.id),
        private_memories=[],
        relationship_memories=[],
        recent_context=NPCRecentContext(npc_id=npc_template.id),
        secrets=NPCSecrets(
            npc_id=npc_template.id,
            secrets=secrets_list,
        ),
        knowledge_state=NPCKnowledgeState(npc_id=npc_template.id),
        goals=NPCGoals(
            npc_id=npc_template.id,
            goals=goals,
        ),
    )


def _derive_mood(trust_score: int, suspicion_score: int) -> str:
    """
    Derive mood string from trust and suspicion scores.
    
    Trust: 0-100 (higher = more trusting)
    Suspicion: 0-100 (higher = more suspicious)
    
    Returns mood string suitable for NPCState.mood
    """
    if suspicion_score >= 70:
        return "suspicious"
    elif trust_score >= 80:
        return "friendly"
    elif trust_score >= 60:
        return "warm"
    elif suspicion_score >= 40:
        return "wary"
    elif trust_score >= 40:
        return "neutral"
    else:
        return "cold"

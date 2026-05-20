"""NPC Portrait Prompt Builder — mood→expression mapping and context assembly.

Provides rich context for portrait generation prompts, including NPC name, mood,
personality, appearance, location, and recent narration.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from llm_rpg.core.npc_state_bridge import _derive_mood


MOOD_TO_EXPRESSION = {
    "suspicious": "thoughtful",
    "friendly": "happy",
    "warm": "happy",
    "wary": "surprised",
    "neutral": "neutral",
    "cold": "angry",
}


class PortraitContext(BaseModel):
    """Context for building NPC portrait prompts."""
    npc_id: str = ""
    npc_name: str = ""
    role_type: str = ""
    mood: str = "neutral"
    expression: str = "neutral"
    personality: str = ""
    appearance: str = ""
    location_name: str = ""
    location_tags: list[str] = []
    trust_score: int = 50
    suspicion_score: int = 0
    recent_narration_summary: str = ""
    combat_state: str = ""
    chapter_theme: str = ""


def map_mood_to_expression(mood: str) -> str:
    """Map mood string to PortraitExpression value string.

    Args:
        mood: Mood string from _derive_mood().

    Returns:
        Expression string (PortraitExpression value). Returns "neutral" for unknown moods.
    """
    return MOOD_TO_EXPRESSION.get(mood, "neutral")


def build_portrait_context(
    session_id: str,
    npc_id: str,
    db: Session,
) -> PortraitContext:
    """Build portrait context from database entities.

    Fetches NPC template, session NPC state, location, and recent narration.
    Handles all missing data gracefully with defaults.

    Args:
        session_id: Session ID.
        npc_id: NPC template ID.
        db: SQLAlchemy session.

    Returns:
        PortraitContext with filled fields (defaults for missing data).
    """
    from llm_rpg.storage.repositories import (
        NPCTemplateRepository,
        SessionNPCStateRepository,
        SessionStateRepository,
        SessionRepository,
        LocationRepository,
        EventLogRepository,
        ChapterRepository,
    )

    context = PortraitContext(npc_id=npc_id)

    npc_repo = NPCTemplateRepository(db)
    npc_template = npc_repo.get_by_id(npc_id)
    if npc_template:
        context.npc_name = npc_template.name or ""
        context.role_type = npc_template.role_type or ""
        context.personality = npc_template.personality or ""
        context.appearance = npc_template.appearance or ""

    npc_state_repo = SessionNPCStateRepository(db)
    npc_state = npc_state_repo.get_by_session_and_npc(session_id, npc_id)
    if npc_state:
        trust = npc_state.trust_score if npc_state.trust_score is not None else 50
        suspicion = npc_state.suspicion_score if npc_state.suspicion_score is not None else 0
        context.trust_score = trust
        context.suspicion_score = suspicion
        context.mood = _derive_mood(trust, suspicion)
        context.expression = map_mood_to_expression(context.mood)

    session_state_repo = SessionStateRepository(db)
    session_state = session_state_repo.get_by_session(session_id)
    if session_state and session_state.current_location_id:
        location_repo = LocationRepository(db)
        location = location_repo.get_by_id(session_state.current_location_id)
        if location:
            context.location_name = location.name or ""
            context.location_tags = location.tags or []

    # Fetch chapter theme from session's current chapter
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if session and session.current_chapter_id:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(session.current_chapter_id)
        if chapter:
            # Use summary as theme, fallback to name
            context.chapter_theme = chapter.summary or chapter.name or ""

    # Determine combat state from session_state.active_mode
    if session_state and session_state.active_mode:
        if session_state.active_mode == "combat":
            context.combat_state = "in_combat"
        else:
            context.combat_state = "exploration"

    event_log_repo = EventLogRepository(db)
    recent_events = event_log_repo.get_recent(session_id, limit=3)
    if recent_events:
        narrations = []
        for event in recent_events:
            if event.narrative_text:
                narrations.append(event.narrative_text)
        if narrations:
            context.recent_narration_summary = " ".join(narrations)[-500:]

    return context


def build_portrait_prompt(context: PortraitContext) -> str:
    """Build portrait prompt string from context.

    Assembles a prompt with NPC name, role, appearance, personality, and expression.
    Only includes fields that have values (skip empty ones).

    Args:
        context: PortraitContext with NPC data.

    Returns:
        Prompt string for portrait generation. Never raises exceptions.
    """
    parts = []

    if context.npc_name:
        parts.append(f"A portrait of {context.npc_name}")
        if context.role_type:
            parts[-1] += f", a {context.role_type}"
    else:
        parts.append("A portrait")

    if context.appearance:
        parts.append(f"Appearance: {context.appearance}")

    if context.personality:
        personality_excerpt = context.personality[:200]
        parts.append(f"Personality: {personality_excerpt}")

    if context.expression and context.expression != "neutral":
        parts.append(f"Expression: {context.expression}")
    elif context.mood:
        parts.append(f"Mood: {context.mood}")

    if context.location_name:
        parts.append(f"Location: {context.location_name}")

    if context.recent_narration_summary:
        summary = context.recent_narration_summary
        if len(summary) > 400:
            summary = summary[:400] + "..."
        parts.append(f"Recent context: {summary}")

    if context.combat_state and context.combat_state != "exploration":
        parts.append(f"Current situation: {context.combat_state}")

    if context.chapter_theme:
        parts.append(f"Story theme: {context.chapter_theme}")

    return ". ".join(parts) + "."

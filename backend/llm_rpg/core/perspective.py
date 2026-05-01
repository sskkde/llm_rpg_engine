from typing import Any, Dict, List, Optional

from ..models.perspectives import (
    Perspective,
    PerspectiveType,
    WorldPerspective,
    PlayerPerspective,
    NPCPerspective,
    FactionPerspective,
    NarratorPerspective,
    VisibilityResult,
    VisibilityLevel,
    FilteredContent,
)
from ..models.states import CanonicalState
from ..models.events import GameEvent
from ..models.lore import LoreEntry, LoreView


class PerspectiveService:
    
    def __init__(self):
        self._perspectives: Dict[str, Perspective] = {}
    
    def register_perspective(self, perspective: Perspective) -> None:
        self._perspectives[perspective.perspective_id] = perspective
    
    def get_perspective(self, perspective_id: str) -> Optional[Perspective]:
        return self._perspectives.get(perspective_id)
    
    def build_world_perspective(self, perspective_id: str = "world") -> WorldPerspective:
        perspective = WorldPerspective(
            perspective_id=perspective_id,
            owner_id="world",
        )
        self._perspectives[perspective_id] = perspective
        return perspective
    
    def build_player_perspective(
        self,
        perspective_id: str,
        player_id: str,
        known_facts: List[str] = None,
        known_rumors: List[str] = None,
        visible_scene_ids: List[str] = None,
        discovered_locations: List[str] = None,
    ) -> PlayerPerspective:
        perspective = PlayerPerspective(
            perspective_id=perspective_id,
            owner_id=player_id,
            known_facts=known_facts or [],
            known_rumors=known_rumors or [],
            visible_scene_ids=visible_scene_ids or [],
            discovered_locations=discovered_locations or [],
        )
        self._perspectives[perspective_id] = perspective
        return perspective
    
    def build_npc_perspective(
        self,
        perspective_id: str,
        npc_id: str,
        known_facts: List[str] = None,
        believed_rumors: List[str] = None,
        private_knowledge: List[str] = None,
        secrets: List[str] = None,
        forbidden_knowledge: List[str] = None,
    ) -> NPCPerspective:
        perspective = NPCPerspective(
            perspective_id=perspective_id,
            owner_id=npc_id,
            npc_id=npc_id,
            known_facts=known_facts or [],
            believed_rumors=believed_rumors or [],
            private_knowledge=private_knowledge or [],
            secrets=secrets or [],
            forbidden_knowledge=forbidden_knowledge or [],
        )
        self._perspectives[perspective_id] = perspective
        return perspective
    
    def build_faction_perspective(
        self,
        perspective_id: str,
        faction_id: str,
        collective_knowledge: List[str] = None,
        strategic_concerns: List[str] = None,
        active_plans: List[str] = None,
    ) -> FactionPerspective:
        perspective = FactionPerspective(
            perspective_id=perspective_id,
            owner_id=faction_id,
            faction_id=faction_id,
            collective_knowledge=collective_knowledge or [],
            strategic_concerns=strategic_concerns or [],
            active_plans=active_plans or [],
        )
        self._perspectives[perspective_id] = perspective
        return perspective
    
    def build_narrator_perspective(
        self,
        perspective_id: str,
        base_perspective_id: str,
        style_requirements: Dict[str, Any] = None,
        tone: str = "neutral",
        pacing: str = "normal",
        forbidden_info: List[str] = None,
        allowed_hints: List[str] = None,
    ) -> NarratorPerspective:
        perspective = NarratorPerspective(
            perspective_id=perspective_id,
            owner_id="narrator",
            base_perspective_id=base_perspective_id,
            style_requirements=style_requirements or {},
            tone=tone,
            pacing=pacing,
            forbidden_info=forbidden_info or [],
            allowed_hints=allowed_hints or [],
        )
        self._perspectives[perspective_id] = perspective
        return perspective
    
    def check_visibility(
        self,
        content: Any,
        perspective: Perspective,
        content_id: Optional[str] = None,
    ) -> VisibilityResult:
        if isinstance(perspective, WorldPerspective):
            return VisibilityResult(
                is_visible=True,
                visibility_level=VisibilityLevel.FULL,
                content=content,
                reason="World perspective sees everything",
            )
        
        if isinstance(perspective, PlayerPerspective):
            if content_id and content_id in perspective.known_facts:
                return VisibilityResult(
                    is_visible=True,
                    visibility_level=VisibilityLevel.FULL,
                    content=content,
                    reason="Known fact",
                )
            if content_id and content_id in perspective.known_rumors:
                return VisibilityResult(
                    is_visible=True,
                    visibility_level=VisibilityLevel.RUMOR,
                    content=content,
                    reason="Known rumor",
                )
            return VisibilityResult(
                is_visible=False,
                visibility_level=VisibilityLevel.HIDDEN,
                reason="Not in player perspective",
            )
        
        if isinstance(perspective, NPCPerspective):
            if content_id and content_id in perspective.known_facts:
                return VisibilityResult(
                    is_visible=True,
                    visibility_level=VisibilityLevel.FULL,
                    content=content,
                    reason="Known fact",
                )
            if content_id and content_id in perspective.believed_rumors:
                return VisibilityResult(
                    is_visible=True,
                    visibility_level=VisibilityLevel.RUMOR,
                    content=content,
                    reason="Believed rumor",
                )
            if content_id and content_id in perspective.secrets:
                return VisibilityResult(
                    is_visible=True,
                    visibility_level=VisibilityLevel.FULL,
                    content=content,
                    reason="Known secret",
                )
            if content_id and content_id in perspective.forbidden_knowledge:
                return VisibilityResult(
                    is_visible=False,
                    visibility_level=VisibilityLevel.HIDDEN,
                    reason="Forbidden knowledge",
                )
            return VisibilityResult(
                is_visible=False,
                visibility_level=VisibilityLevel.HIDDEN,
                reason="Not in NPC perspective",
            )
        
        return VisibilityResult(
            is_visible=False,
            visibility_level=VisibilityLevel.HIDDEN,
            reason="Unknown perspective type",
        )
    
    def filter_events_for_perspective(
        self,
        events: List[GameEvent],
        perspective: Perspective,
    ) -> List[GameEvent]:
        if isinstance(perspective, WorldPerspective):
            return events
        
        filtered = []
        for event in events:
            result = self.check_visibility(event, perspective, event.event_id)
            if result.is_visible:
                filtered.append(event)
        
        return filtered
    
    def filter_lore_for_perspective(
        self,
        lore_entries: List[LoreEntry],
        perspective: Perspective,
    ) -> List[LoreView]:
        filtered = []
        
        for entry in lore_entries:
            if isinstance(perspective, WorldPerspective):
                filtered.append(LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=entry.canonical_content,
                    visibility_level="full",
                    perspective_id=perspective.perspective_id,
                ))
            elif isinstance(perspective, PlayerPerspective):
                if entry.lore_id in perspective.known_facts:
                    filtered.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=entry.canonical_content,
                        visibility_level="full",
                        perspective_id=perspective.perspective_id,
                    ))
                elif entry.lore_id in perspective.known_rumors:
                    rumor_content = entry.rumor_versions[0] if entry.rumor_versions else entry.public_content
                    filtered.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=rumor_content or "",
                        visibility_level="rumor",
                        perspective_id=perspective.perspective_id,
                        is_rumor=True,
                        confidence=0.5,
                    ))
            elif isinstance(perspective, NPCPerspective):
                if entry.lore_id in perspective.known_facts:
                    filtered.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=entry.canonical_content,
                        visibility_level="full",
                        perspective_id=perspective.perspective_id,
                    ))
                elif entry.lore_id in perspective.believed_rumors:
                    rumor_content = entry.rumor_versions[0] if entry.rumor_versions else entry.public_content
                    filtered.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=rumor_content or "",
                        visibility_level="rumor",
                        perspective_id=perspective.perspective_id,
                        is_rumor=True,
                        confidence=0.5,
                    ))
        
        return filtered
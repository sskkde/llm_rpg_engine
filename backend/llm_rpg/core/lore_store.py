from typing import Any, Dict, List, Optional

from ..models.lore import (
    LoreEntry,
    LoreCategory,
    LoreView,
    WorldLore,
    CultivationSystemLore,
    LocationLore,
    CharacterLore,
    FactionLore,
    ItemLore,
    MonsterLore,
    HistoryLore,
    MainPlotLore,
    RuleLore,
    RumorLore,
)
from ..models.perspectives import Perspective, PlayerPerspective, NPCPerspective


class LoreStore:
    
    def __init__(self):
        self._entries: Dict[str, LoreEntry] = {}
        self._by_category: Dict[LoreCategory, List[str]] = {}
        self._by_tag: Dict[str, List[str]] = {}
        self._by_entity: Dict[str, List[str]] = {}
    
    def add_entry(self, entry: LoreEntry) -> None:
        self._entries[entry.lore_id] = entry
        
        if entry.category not in self._by_category:
            self._by_category[entry.category] = []
        self._by_category[entry.category].append(entry.lore_id)
        
        for tag in entry.tags:
            if tag not in self._by_tag:
                self._by_tag[tag] = []
            self._by_tag[tag].append(entry.lore_id)
        
        if hasattr(entry, 'character_id') and entry.character_id:
            if entry.character_id not in self._by_entity:
                self._by_entity[entry.character_id] = []
            self._by_entity[entry.character_id].append(entry.lore_id)
        
        if hasattr(entry, 'location_id') and entry.location_id:
            if entry.location_id not in self._by_entity:
                self._by_entity[entry.location_id] = []
            self._by_entity[entry.location_id].append(entry.lore_id)
        
        if hasattr(entry, 'faction_id') and entry.faction_id:
            if entry.faction_id not in self._by_entity:
                self._by_entity[entry.faction_id] = []
            self._by_entity[entry.faction_id].append(entry.lore_id)
    
    def get_entry(self, lore_id: str) -> Optional[LoreEntry]:
        return self._entries.get(lore_id)
    
    def get_entries_by_category(self, category: LoreCategory) -> List[LoreEntry]:
        ids = self._by_category.get(category, [])
        return [self._entries[lid] for lid in ids if lid in self._entries]
    
    def get_entries_by_tag(self, tag: str) -> List[LoreEntry]:
        ids = self._by_tag.get(tag, [])
        return [self._entries[lid] for lid in ids if lid in self._entries]
    
    def get_entries_by_entity(self, entity_id: str) -> List[LoreEntry]:
        ids = self._by_entity.get(entity_id, [])
        return [self._entries[lid] for lid in ids if lid in self._entries]
    
    def search_entries(self, query: str) -> List[LoreEntry]:
        query_lower = query.lower()
        results = []
        
        for entry in self._entries.values():
            if (query_lower in entry.title.lower() or
                query_lower in entry.canonical_content.lower() or
                any(query_lower in tag.lower() for tag in entry.tags)):
                results.append(entry)
        
        return results
    
    def get_view_for_perspective(
        self,
        lore_id: str,
        perspective: Perspective,
    ) -> Optional[LoreView]:
        entry = self._entries.get(lore_id)
        if entry is None:
            return None
        
        if isinstance(perspective, PlayerPerspective):
            if lore_id in perspective.known_facts:
                return LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=entry.canonical_content,
                    visibility_level="full",
                    perspective_id=perspective.perspective_id,
                )
            elif lore_id in perspective.known_rumors:
                rumor_content = entry.rumor_versions[0] if entry.rumor_versions else entry.public_content
                return LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=rumor_content or "",
                    visibility_level="rumor",
                    perspective_id=perspective.perspective_id,
                    is_rumor=True,
                    confidence=0.5,
                )
            elif entry.public_content:
                return LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=entry.public_content,
                    visibility_level="partial",
                    perspective_id=perspective.perspective_id,
                )
            return None
        
        elif isinstance(perspective, NPCPerspective):
            if lore_id in perspective.known_facts:
                return LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=entry.canonical_content,
                    visibility_level="full",
                    perspective_id=perspective.perspective_id,
                )
            elif lore_id in perspective.believed_rumors:
                rumor_content = entry.rumor_versions[0] if entry.rumor_versions else entry.public_content
                return LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=rumor_content or "",
                    visibility_level="rumor",
                    perspective_id=perspective.perspective_id,
                    is_rumor=True,
                    confidence=0.5,
                )
            elif entry.public_content:
                return LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=entry.public_content,
                    visibility_level="partial",
                    perspective_id=perspective.perspective_id,
                )
            return None
        
        return LoreView(
            lore_id=entry.lore_id,
            title=entry.title,
            category=entry.category,
            content=entry.canonical_content,
            visibility_level="full",
            perspective_id=perspective.perspective_id,
        )
    
    def get_views_for_perspective(
        self,
        perspective: Perspective,
        category: Optional[LoreCategory] = None,
        tags: Optional[List[str]] = None,
        entity_id: Optional[str] = None,
    ) -> List[LoreView]:
        if category:
            entries = self.get_entries_by_category(category)
        elif tags:
            entries = []
            for tag in tags:
                entries.extend(self.get_entries_by_tag(tag))
        elif entity_id:
            entries = self.get_entries_by_entity(entity_id)
        else:
            entries = list(self._entries.values())
        
        views = []
        for entry in entries:
            view = self.get_view_for_perspective(entry.lore_id, perspective)
            if view:
                views.append(view)
        
        return views
    
    def check_reveal_conditions(
        self,
        lore_id: str,
        game_state: Dict[str, Any],
    ) -> bool:
        entry = self._entries.get(lore_id)
        if entry is None:
            return False
        
        for condition in entry.hidden_from_player_until:
            if self._evaluate_condition(condition, game_state):
                return True
        
        return False
    
    def _evaluate_condition(self, condition: str, game_state: Dict[str, Any]) -> bool:
        return False
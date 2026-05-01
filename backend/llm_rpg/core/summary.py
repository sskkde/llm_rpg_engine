from typing import Any, Dict, List, Optional

from ..models.summaries import (
    Summary,
    SummaryType,
    WorldChronicle,
    SceneSummary,
    SessionSummary,
    NPCSubjectiveSummary,
    FactionSummary,
    PlayerJourneySummary,
    EmotionalImpression,
)
from ..models.events import GameEvent, WorldTime


class SummaryManager:
    
    def __init__(self):
        self._summaries: Dict[str, Summary] = {}
        self._by_type: Dict[SummaryType, List[str]] = {}
        self._by_owner: Dict[str, List[str]] = {}
        self._by_turn_range: Dict[int, List[str]] = {}
    
    def add_summary(self, summary: Summary) -> None:
        self._summaries[summary.summary_id] = summary
        
        if summary.summary_type not in self._by_type:
            self._by_type[summary.summary_type] = []
        self._by_type[summary.summary_type].append(summary.summary_id)
        
        owner_key = f"{summary.owner_type}:{summary.owner_id}" if summary.owner_type and summary.owner_id else None
        if owner_key:
            if owner_key not in self._by_owner:
                self._by_owner[owner_key] = []
            self._by_owner[owner_key].append(summary.summary_id)
        
        for turn in range(summary.start_turn, summary.end_turn + 1):
            if turn not in self._by_turn_range:
                self._by_turn_range[turn] = []
            self._by_turn_range[turn].append(summary.summary_id)
    
    def get_summary(self, summary_id: str) -> Optional[Summary]:
        return self._summaries.get(summary_id)
    
    def get_summaries_by_type(self, summary_type: SummaryType) -> List[Summary]:
        ids = self._by_type.get(summary_type, [])
        return [self._summaries[sid] for sid in ids if sid in self._summaries]
    
    def get_summaries_by_owner(self, owner_type: str, owner_id: str) -> List[Summary]:
        owner_key = f"{owner_type}:{owner_id}"
        ids = self._by_owner.get(owner_key, [])
        return [self._summaries[sid] for sid in ids if sid in self._summaries]
    
    def get_summaries_for_turn(self, turn: int) -> List[Summary]:
        ids = self._by_turn_range.get(turn, [])
        return [self._summaries[sid] for sid in ids if sid in self._summaries]
    
    def create_world_chronicle(
        self,
        start_turn: int,
        end_turn: int,
        content: str,
        location_ids: List[str] = None,
        key_event_ids: List[str] = None,
        objective_facts: List[str] = None,
        time_range: Dict[str, Any] = None,
    ) -> WorldChronicle:
        summary_id = f"chronicle_{start_turn}_{end_turn}"
        chronicle = WorldChronicle(
            summary_id=summary_id,
            start_turn=start_turn,
            end_turn=end_turn,
            content=content,
            location_ids=location_ids or [],
            key_event_ids=key_event_ids or [],
            objective_facts=objective_facts or [],
            time_range=time_range,
        )
        self.add_summary(chronicle)
        return chronicle
    
    def create_scene_summary(
        self,
        scene_id: str,
        start_turn: int,
        end_turn: int,
        content: str,
        open_threads: List[str] = None,
        scene_phase: str = "exploration",
        key_event_ids: List[str] = None,
    ) -> SceneSummary:
        summary_id = f"scene_{scene_id}_{start_turn}_{end_turn}"
        summary = SceneSummary(
            summary_id=summary_id,
            scene_id=scene_id,
            start_turn=start_turn,
            end_turn=end_turn,
            content=content,
            open_threads=open_threads or [],
            scene_phase=scene_phase,
            key_event_ids=key_event_ids or [],
        )
        self.add_summary(summary)
        return summary
    
    def create_session_summary(
        self,
        session_id: str,
        start_turn: int,
        end_turn: int,
        content: str,
        player_actions: List[str] = None,
        major_events: List[str] = None,
        key_event_ids: List[str] = None,
    ) -> SessionSummary:
        summary_id = f"session_{session_id}_{start_turn}_{end_turn}"
        summary = SessionSummary(
            summary_id=summary_id,
            session_id=session_id,
            start_turn=start_turn,
            end_turn=end_turn,
            content=content,
            player_actions=player_actions or [],
            major_events=major_events or [],
            key_event_ids=key_event_ids or [],
        )
        self.add_summary(summary)
        return summary
    
    def create_npc_subjective_summary(
        self,
        npc_id: str,
        start_turn: int,
        end_turn: int,
        subjective_summary: str,
        emotional_impression: EmotionalImpression = None,
        memory_strength: float = 1.0,
        distortion_level: float = 0.0,
        key_event_ids: List[str] = None,
    ) -> NPCSubjectiveSummary:
        summary_id = f"npc_{npc_id}_{start_turn}_{end_turn}"
        summary = NPCSubjectiveSummary(
            summary_id=summary_id,
            npc_id=npc_id,
            owner_type="npc",
            owner_id=npc_id,
            start_turn=start_turn,
            end_turn=end_turn,
            content=subjective_summary,
            subjective_summary=subjective_summary,
            emotional_impression=emotional_impression or EmotionalImpression(),
            memory_strength=memory_strength,
            distortion_level=distortion_level,
            key_event_ids=key_event_ids or [],
        )
        self.add_summary(summary)
        return summary
    
    def create_faction_summary(
        self,
        faction_id: str,
        start_turn: int,
        end_turn: int,
        content: str,
        known_events: List[str] = None,
        strategic_concerns: List[str] = None,
        key_event_ids: List[str] = None,
    ) -> FactionSummary:
        summary_id = f"faction_{faction_id}_{start_turn}_{end_turn}"
        summary = FactionSummary(
            summary_id=summary_id,
            faction_id=faction_id,
            owner_type="faction",
            owner_id=faction_id,
            start_turn=start_turn,
            end_turn=end_turn,
            content=content,
            known_events=known_events or [],
            strategic_concerns=strategic_concerns or [],
            key_event_ids=key_event_ids or [],
        )
        self.add_summary(summary)
        return summary
    
    def create_player_journey_summary(
        self,
        player_id: str,
        chapter: str,
        start_turn: int,
        end_turn: int,
        content: str,
        known_clues: List[str] = None,
        unresolved_questions: List[str] = None,
        key_event_ids: List[str] = None,
    ) -> PlayerJourneySummary:
        summary_id = f"journey_{player_id}_{start_turn}_{end_turn}"
        summary = PlayerJourneySummary(
            summary_id=summary_id,
            player_id=player_id,
            owner_type="player",
            owner_id=player_id,
            chapter=chapter,
            start_turn=start_turn,
            end_turn=end_turn,
            content=content,
            known_clues=known_clues or [],
            unresolved_questions=unresolved_questions or [],
            key_event_ids=key_event_ids or [],
        )
        self.add_summary(summary)
        return summary
    
    def get_recent_summaries(
        self,
        limit: int = 10,
        summary_type: Optional[SummaryType] = None,
    ) -> List[Summary]:
        if summary_type:
            summaries = self.get_summaries_by_type(summary_type)
        else:
            summaries = list(self._summaries.values())
        
        summaries.sort(key=lambda s: s.end_turn, reverse=True)
        return summaries[:limit]
    
    def get_relevant_summaries(
        self,
        current_turn: int,
        lookback_turns: int = 10,
        summary_type: Optional[SummaryType] = None,
    ) -> List[Summary]:
        start_turn = max(0, current_turn - lookback_turns)
        
        relevant = []
        for turn in range(start_turn, current_turn + 1):
            summaries = self.get_summaries_for_turn(turn)
            for summary in summaries:
                if summary_type is None or summary.summary_type == summary_type:
                    if summary not in relevant:
                        relevant.append(summary)
        
        relevant.sort(key=lambda s: s.end_turn, reverse=True)
        return relevant
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from ..models.states import CanonicalState, WorldState
from ..models.events import WorldTime, WorldTickEvent
from ..models.proposals import (
    WorldTickProposal,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    ValidationStatus,
    create_fallback_world_tick,
)
from ..core.canonical_state import CanonicalStateManager
from ..core.event_log import EventLog


class WorldEngine:
    """
    World engine for managing global world state and time advancement.
    
    Key principles:
    - Deterministic time advancement is authoritative (always applied)
    - LLM outputs are proposals only (candidates, not direct mutations)
    - World proposals passed to validator/commit logic
    - Existing check_world_events remains as fallback
    """
    
    def __init__(
        self,
        state_manager: CanonicalStateManager,
        event_log: EventLog,
        proposal_pipeline: Optional[Any] = None,  # ProposalPipeline (avoid circular import)
    ):
        self._state_manager = state_manager
        self._event_log = event_log
        self._proposal_pipeline = proposal_pipeline
        self._audit_log: List[Dict[str, Any]] = []
        # Thread pool for async-to-sync bridge
        self._executor = ThreadPoolExecutor(max_workers=1)
    
    def advance_time(
        self,
        game_id: str,
        time_delta: int = 1,
    ) -> WorldTickEvent:
        state = self._state_manager.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        world_state = state.world_state
        old_time = world_state.current_time
        
        new_period = self._advance_period(old_time.period, time_delta)
        new_day = old_time.day
        new_season = old_time.season
        
        if new_period == "子时" and old_time.period != "子时":
            new_day += 1
            if new_day > 30:
                new_day = 1
                new_season = self._advance_season(old_time.season)
        
        new_time = WorldTime(
            calendar=old_time.calendar,
            season=new_season,
            day=new_day,
            period=new_period,
        )
        
        world_state.current_time = new_time
        
        event = WorldTickEvent(
            event_id=f"evt_world_tick_{game_id}_{new_time}",
            turn_index=state.player_state.flags.get("turn_index", 0),
            time_before=old_time,
            time_after=new_time,
            summary=f"时间从 {old_time} 推进到 {new_time}",
        )
        
        return event
    
    def _advance_period(self, current_period: str, delta: int) -> str:
        periods = [
            "子时", "丑时", "寅时", "卯时", "辰时", "巳时",
            "午时", "未时", "申时", "酉时", "戌时", "亥时"
        ]
        
        try:
            current_index = periods.index(current_period)
            new_index = (current_index + delta) % len(periods)
            return periods[new_index]
        except ValueError:
            return current_period
    
    def _advance_season(self, current_season: str) -> str:
        seasons = ["春", "夏", "秋", "冬"]
        try:
            current_index = seasons.index(current_season)
            next_index = (current_index + 1) % len(seasons)
            return seasons[next_index]
        except ValueError:
            return current_season
    
    def check_world_events(
        self,
        game_id: str,
    ) -> List[Dict[str, Any]]:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return []
        
        events = []
        
        world_state = state.world_state
        if world_state.current_time.period in ["子时", "丑时", "寅时"]:
            events.append({
                "type": "time_based",
                "description": "深夜时分，妖气加重",
                "effects": {"danger_level": 0.1},
            })
        
        return events
    
    def update_global_flags(
        self,
        game_id: str,
        flags: Dict[str, Any],
    ) -> None:
        state = self._state_manager.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        state.world_state.global_flags.update(flags)
    
    def get_weather(self, game_id: str) -> str:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return "晴"
        
        return state.world_state.weather
    
    def set_weather(self, game_id: str, weather: str) -> None:
        state = self._state_manager.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        state.world_state.weather = weather
    
    def generate_world_candidates(
        self,
        game_id: str,
        current_turn: int,
    ) -> WorldTickProposal:
        """
        Generate world tick proposal for global/offscreen evolution.
        
        This method:
        1. Uses ProposalPipeline for LLM-driven world proposals
        2. Returns candidates only (no direct state mutation)
        3. Falls back to deterministic check_world_events on failure
        
        The proposal includes:
        - World event candidates
        - Faction/location/quest/NPC schedule delta candidates
        - Countdown pressure indicators
        
        Args:
            game_id: Game identifier
            current_turn: Current turn number for audit
            
        Returns:
            WorldTickProposal with candidates (never mutates state)
        """
        if self._proposal_pipeline is None:
            return self._create_fallback_proposal(
                reason="ProposalPipeline not configured",
                current_turn=current_turn,
            )
        
        state = self._state_manager.get_state(game_id)
        if state is None:
            return self._create_fallback_proposal(
                reason=f"State not found: {game_id}",
                current_turn=current_turn,
            )
        
        world_context = self._build_world_context(state, current_turn)
        
        try:
            proposal = self._generate_proposal_via_pipeline(
                world_context=world_context,
                session_id=game_id,
                turn_no=current_turn,
            )
            
            self._audit_log.append({
                "audit_id": f"world_proposal_{uuid.uuid4().hex[:8]}",
                "timestamp": datetime.now().isoformat(),
                "type": "world_proposal_success",
                "source": "proposal_pipeline",
                "is_fallback": proposal.is_fallback,
                "confidence": proposal.confidence,
                "events_count": len(proposal.candidate_events),
                "deltas_count": len(proposal.state_deltas),
            })
            
            return proposal
            
        except Exception as e:
            self._audit_log.append({
                "audit_id": f"world_proposal_error_{uuid.uuid4().hex[:8]}",
                "timestamp": datetime.now().isoformat(),
                "type": "world_proposal_error",
                "source": "fallback",
                "error": str(e),
            })
            
            return self._create_fallback_proposal(
                reason=str(e),
                current_turn=current_turn,
                state=state,
            )
    
    def _build_world_context(
        self,
        state: CanonicalState,
        current_turn: int,
    ) -> Dict[str, Any]:
        """
        Build world context for LLM proposal generation.
        
        Includes only world-visible information (no player-hidden secrets).
        """
        world_state = state.world_state
        
        return {
            "current_turn": current_turn,
            "time": {
                "calendar": world_state.current_time.calendar,
                "season": world_state.current_time.season,
                "day": world_state.current_time.day,
                "period": world_state.current_time.period,
            },
            "weather": world_state.weather,
            "global_flags": world_state.global_flags,
            "active_quests": [
                quest_id for quest_id, quest in state.quest_states.items()
                if quest.status == "active"
            ] if hasattr(state, 'quest_states') else [],
            "npc_count": len(state.npc_states),
            "location_count": len(world_state.location_states) if hasattr(world_state, 'location_states') else 0,
        }
    
    def _generate_proposal_via_pipeline(
        self,
        world_context: Dict[str, Any],
        session_id: str,
        turn_no: int,
    ) -> WorldTickProposal:
        """Generate proposal using ProposalPipeline (async-to-sync bridge)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = self._executor.submit(
                    asyncio.run,
                    self._proposal_pipeline.generate_world_tick(
                        world_context=world_context,
                        session_id=session_id,
                        turn_no=turn_no,
                    )
                )
                return future.result(timeout=30.0)
            else:
                return loop.run_until_complete(
                    self._proposal_pipeline.generate_world_tick(
                        world_context=world_context,
                        session_id=session_id,
                        turn_no=turn_no,
                    )
                )
        except RuntimeError:
            return asyncio.run(
                self._proposal_pipeline.generate_world_tick(
                    world_context=world_context,
                    session_id=session_id,
                    turn_no=turn_no,
                )
            )
    
    def _create_fallback_proposal(
        self,
        reason: str,
        current_turn: int,
        state: Optional[CanonicalState] = None,
    ) -> WorldTickProposal:
        """
        Create fallback WorldTickProposal when LLM fails.
        
        Uses existing check_world_events for deterministic fallback.
        """
        proposal = create_fallback_world_tick(reason)
        
        if state is not None:
            game_id = "fallback"
            try:
                events = self.check_world_events(game_id)
                if events:
                    proposal.candidate_events = [
                        {
                            "event_type": event.get("type", "unknown"),
                            "description": event.get("description", ""),
                            "target_entity_ids": [],
                            "effects": event.get("effects", {}),
                            "importance": 0.5,
                            "visibility": "player_visible",
                        }
                        for event in events
                    ]
            except Exception:
                pass
        
        proposal.audit.fallback_reason = reason
        
        self._audit_log.append({
            "audit_id": f"world_fallback_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "type": "world_proposal_fallback",
            "source": "check_world_events",
            "reason": reason,
            "events_count": len(proposal.candidate_events),
        })
        
        return proposal
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        return self._audit_log.copy()
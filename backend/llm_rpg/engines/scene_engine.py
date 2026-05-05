"""
Scene Engine

Manages scene triggers, state transitions, and scene lifecycle.
Provides helpers for scene activation and state management.
"""

import asyncio
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from ..llm.proposal_pipeline import ProposalPipeline
    from ..models.proposals import SceneEventProposal, ParsedIntent


class SceneState(str, Enum):
    """Scene lifecycle states."""
    INACTIVE = "inactive"
    TRIGGERED = "triggered"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class TriggerType(str, Enum):
    """Types of scene triggers."""
    LOCATION = "location"
    TIME = "time"
    QUEST = "quest"
    ITEM = "item"
    NPC_STATE = "npc_state"
    PLAYER_ACTION = "player_action"
    RANDOM = "random"
    SCRIPTED = "scripted"


@dataclass
class SceneTrigger:
    """Represents a scene trigger condition."""
    trigger_id: str
    trigger_type: TriggerType
    conditions: Dict[str, Any] = field(default_factory=dict)
    priority: float = 1.0
    once_only: bool = True
    cooldown_turns: int = 0
    last_triggered_turn: Optional[int] = None
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "trigger_type": self.trigger_type.value,
            "conditions": self.conditions,
            "priority": self.priority,
            "once_only": self.once_only,
            "cooldown_turns": self.cooldown_turns,
            "last_triggered_turn": self.last_triggered_turn,
            "enabled": self.enabled,
        }


@dataclass
class Scene:
    """Represents a game scene."""
    scene_id: str
    name: str
    location_id: Optional[str] = None
    state: SceneState = SceneState.INACTIVE
    triggers: List[SceneTrigger] = field(default_factory=list)
    active_actors: List[str] = field(default_factory=list)
    blocked_paths: List[str] = field(default_factory=list)
    available_actions: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    activated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "location_id": self.location_id,
            "state": self.state.value,
            "triggers": [t.to_dict() for t in self.triggers],
            "active_actors": self.active_actors,
            "blocked_paths": self.blocked_paths,
            "available_actions": self.available_actions,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class SceneEngine:
    """
    Manages scene triggers, activation, and lifecycle.
    
    Features:
    - Scene trigger evaluation
    - Scene state management
    - Scene activation/deactivation
    - Actor management within scenes
    - LLM-driven scene event proposals via ProposalPipeline
    """
    
    def __init__(
        self,
        proposal_pipeline: Optional["ProposalPipeline"] = None,
    ):
        self._scenes: Dict[str, Scene] = {}
        self._location_scenes: Dict[str, List[str]] = {}
        self._active_scenes: List[str] = []
        self._trigger_history: List[Dict[str, Any]] = []
        self._max_history = 100
        self._proposal_pipeline = proposal_pipeline
        self._audit_log: List[Dict[str, Any]] = []
    
    def register_scene(self, scene: Scene) -> str:
        """Register a scene with the engine."""
        self._scenes[scene.scene_id] = scene
        
        if scene.location_id:
            if scene.location_id not in self._location_scenes:
                self._location_scenes[scene.location_id] = []
            if scene.scene_id not in self._location_scenes[scene.location_id]:
                self._location_scenes[scene.location_id].append(scene.scene_id)
        
        return scene.scene_id
    
    def create_scene(
        self,
        name: str,
        location_id: Optional[str] = None,
        triggers: Optional[List[SceneTrigger]] = None
    ) -> Scene:
        """Create and register a new scene."""
        scene_id = f"scene_{uuid.uuid4().hex[:12]}"
        scene = Scene(
            scene_id=scene_id,
            name=name,
            location_id=location_id,
            triggers=triggers or [],
        )
        self.register_scene(scene)
        return scene
    
    def get_scene(self, scene_id: str) -> Optional[Scene]:
        """Get a scene by ID."""
        return self._scenes.get(scene_id)
    
    def get_scenes_at_location(self, location_id: str) -> List[Scene]:
        """Get all scenes at a location."""
        scene_ids = self._location_scenes.get(location_id, [])
        return [self._scenes[sid] for sid in scene_ids if sid in self._scenes]
    
    def get_active_scenes(self) -> List[Scene]:
        """Get all currently active scenes."""
        return [self._scenes[sid] for sid in self._active_scenes if sid in self._scenes]
    
    def evaluate_triggers(
        self,
        game_state: Dict[str, Any],
        current_turn: int
    ) -> List[SceneTrigger]:
        """
        Evaluate all scene triggers against current game state.
        
        Args:
            game_state: Current game state
            current_turn: Current turn number
            
        Returns:
            List of triggered conditions
        """
        triggered = []
        
        for scene in self._scenes.values():
            for trigger in scene.triggers:
                if not trigger.enabled:
                    continue
                
                if trigger.once_only and trigger.last_triggered_turn is not None:
                    continue
                
                if trigger.cooldown_turns > 0 and trigger.last_triggered_turn is not None:
                    turns_since = current_turn - trigger.last_triggered_turn
                    if turns_since < trigger.cooldown_turns:
                        continue
                
                if self._check_trigger_conditions(trigger, game_state):
                    triggered.append(trigger)
                    trigger.last_triggered_turn = current_turn
                    
                    self._record_trigger(trigger, scene.scene_id, current_turn)
        
        triggered.sort(key=lambda t: t.priority, reverse=True)
        return triggered
    
    def _check_trigger_conditions(
        self,
        trigger: SceneTrigger,
        game_state: Dict[str, Any]
    ) -> bool:
        """Check if trigger conditions are met."""
        conditions = trigger.conditions
        
        if trigger.trigger_type == TriggerType.LOCATION:
            player_loc = game_state.get("player_location")
            required_loc = conditions.get("location_id")
            if player_loc == required_loc:
                return True
        
        elif trigger.trigger_type == TriggerType.TIME:
            world_time = game_state.get("world_time", {})
            if conditions.get("period") == world_time.get("period"):
                return True
            if conditions.get("day") == world_time.get("day"):
                return True
        
        elif trigger.trigger_type == TriggerType.QUEST:
            quest_id = conditions.get("quest_id")
            quest_states = game_state.get("quest_states", {})
            if quest_id in quest_states:
                quest_state = quest_states[quest_id]
                if conditions.get("status") == quest_state.get("status"):
                    return True
        
        elif trigger.trigger_type == TriggerType.NPC_STATE:
            npc_id = conditions.get("npc_id")
            npc_states = game_state.get("npc_states", {})
            if npc_id in npc_states:
                npc_state = npc_states[npc_id]
                if conditions.get("mood") == npc_state.get("mood"):
                    return True
                if conditions.get("location_id") == npc_state.get("location_id"):
                    return True
        
        elif trigger.trigger_type == TriggerType.PLAYER_ACTION:
            last_action = game_state.get("last_player_action")
            if last_action == conditions.get("action_type"):
                return True
        
        elif trigger.trigger_type == TriggerType.SCRIPTED:
            return conditions.get("should_trigger", False)
        
        return False
    
    def activate_scene(self, scene_id: str) -> bool:
        """Activate a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        if scene.state == SceneState.ACTIVE:
            return True
        
        scene.state = SceneState.ACTIVE
        scene.activated_at = datetime.now()
        
        if scene_id not in self._active_scenes:
            self._active_scenes.append(scene_id)
        
        return True
    
    def deactivate_scene(self, scene_id: str) -> bool:
        """Deactivate a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        scene.state = SceneState.INACTIVE
        
        if scene_id in self._active_scenes:
            self._active_scenes.remove(scene_id)
        
        return True
    
    def complete_scene(self, scene_id: str) -> bool:
        """Mark a scene as completed."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        scene.state = SceneState.COMPLETED
        scene.completed_at = datetime.now()
        
        if scene_id in self._active_scenes:
            self._active_scenes.remove(scene_id)
        
        return True
    
    def add_actor_to_scene(self, scene_id: str, actor_id: str) -> bool:
        """Add an actor to a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        if actor_id not in scene.active_actors:
            scene.active_actors.append(actor_id)
        
        return True
    
    def remove_actor_from_scene(self, scene_id: str, actor_id: str) -> bool:
        """Remove an actor from a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        if actor_id in scene.active_actors:
            scene.active_actors.remove(actor_id)
        
        return True
    
    def block_path(self, scene_id: str, path_id: str) -> bool:
        """Block a path in a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        if path_id not in scene.blocked_paths:
            scene.blocked_paths.append(path_id)
        
        return True
    
    def unblock_path(self, scene_id: str, path_id: str) -> bool:
        """Unblock a path in a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        if path_id in scene.blocked_paths:
            scene.blocked_paths.remove(path_id)
        
        return True
    
    def set_scene_context(self, scene_id: str, key: str, value: Any) -> bool:
        """Set context value for a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        scene.context[key] = value
        return True
    
    def get_scene_context(self, scene_id: str, key: str, default: Any = None) -> Any:
        """Get context value from a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return default
        
        return scene.context.get(key, default)
    
    def _record_trigger(
        self,
        trigger: SceneTrigger,
        scene_id: str,
        turn: int
    ) -> None:
        """Record a trigger event."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "turn": turn,
            "trigger_id": trigger.trigger_id,
            "trigger_type": trigger.trigger_type.value,
            "scene_id": scene_id,
        }
        self._trigger_history.append(entry)
        
        if len(self._trigger_history) > self._max_history:
            self._trigger_history = self._trigger_history[-self._max_history:]
    
    def get_trigger_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get trigger history."""
        return self._trigger_history[-limit:]
    
    def unregister_scene(self, scene_id: str) -> bool:
        """Unregister a scene."""
        scene = self._scenes.get(scene_id)
        if not scene:
            return False
        
        del self._scenes[scene_id]
        
        if scene_id in self._active_scenes:
            self._active_scenes.remove(scene_id)
        
        if scene.location_id and scene.location_id in self._location_scenes:
            if scene_id in self._location_scenes[scene.location_id]:
                self._location_scenes[scene.location_id].remove(scene_id)
        
        return True
    
    def generate_scene_candidates(
        self,
        game_state: Dict[str, Any],
        current_turn: int,
        parsed_intent: Optional["ParsedIntent"] = None,
        session_id: Optional[str] = None,
    ) -> "SceneEventProposal":
        """
        Generate scene event candidates using LLM via ProposalPipeline.
        
        Returns a SceneEventProposal containing:
        - Candidate events for the current scene
        - Environmental reactions
        - Visible object changes
        - Danger hints
        - Available/blocked action suggestions
        
        The proposal is a CANDIDATE only - no state mutation occurs.
        Falls back to deterministic trigger evaluation if LLM unavailable.
        """
        from ..models.proposals import (
            SceneEventProposal,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
            create_fallback_scene_event,
        )
        
        active_scenes = self.get_active_scenes()
        if not active_scenes:
            return create_fallback_scene_event(
                scene_id="none",
                reason="No active scenes"
            )
        
        current_scene = active_scenes[0]
        scene_id = current_scene.scene_id
        
        scene_context = self._build_scene_context(current_scene, game_state, parsed_intent)
        
        if self._proposal_pipeline is not None:
            try:
                proposal = self._generate_proposal_via_pipeline(
                    scene_id=scene_id,
                    scene_context=scene_context,
                    session_id=session_id,
                    turn_no=current_turn,
                )
                
                if proposal and not proposal.is_fallback:
                    self._audit_log.append({
                        "audit_id": f"scene_llm_{uuid.uuid4().hex[:8]}",
                        "timestamp": datetime.now().isoformat(),
                        "type": "scene_proposal_llm_success",
                        "scene_id": scene_id,
                        "confidence": proposal.confidence,
                        "events_count": len(proposal.candidate_events),
                    })
                    return proposal
                else:
                    fallback_reason = proposal.audit.fallback_reason if proposal else "Unknown error"
                    self._audit_log.append({
                        "audit_id": f"scene_fallback_{uuid.uuid4().hex[:8]}",
                        "timestamp": datetime.now().isoformat(),
                        "type": "scene_proposal_fallback",
                        "scene_id": scene_id,
                        "reason": fallback_reason,
                    })
                    
            except Exception as e:
                self._audit_log.append({
                    "audit_id": f"scene_error_{uuid.uuid4().hex[:8]}",
                    "timestamp": datetime.now().isoformat(),
                    "type": "scene_proposal_error",
                    "scene_id": scene_id,
                    "error": str(e),
                })
        
        proposal = self._create_fallback_proposal(scene_id, game_state, current_turn)
        
        self._audit_log.append({
            "audit_id": f"scene_fallback_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "type": "scene_proposal_fallback",
            "scene_id": scene_id,
            "reason": "LLM unavailable or failed, using deterministic triggers",
        })
        
        return proposal
    
    def _build_scene_context(
        self,
        scene: Scene,
        game_state: Dict[str, Any],
        parsed_intent: Optional["ParsedIntent"],
    ) -> Dict[str, Any]:
        context = {
            "scene_id": scene.scene_id,
            "scene_name": scene.name,
            "scene_state": scene.state.value,
            "location_id": scene.location_id,
            "active_actors": scene.active_actors,
            "blocked_paths": scene.blocked_paths,
            "available_actions": scene.available_actions,
            "scene_context": scene.context,
            "player_location": game_state.get("player_location"),
            "world_time": game_state.get("world_time"),
        }
        
        if parsed_intent:
            context["player_intent"] = {
                "intent_type": parsed_intent.intent_type,
                "target": parsed_intent.target,
                "risk_level": parsed_intent.risk_level,
            }
        
        return context
    
    def _generate_proposal_via_pipeline(
        self,
        scene_id: str,
        scene_context: Dict[str, Any],
        session_id: Optional[str],
        turn_no: int,
    ) -> Optional["SceneEventProposal"]:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._proposal_pipeline.generate_scene_event(
                            scene_id=scene_id,
                            scene_context=scene_context,
                            session_id=session_id,
                            turn_no=turn_no,
                        )
                    )
                    return future.result(timeout=30.0)
            else:
                return loop.run_until_complete(
                    self._proposal_pipeline.generate_scene_event(
                        scene_id=scene_id,
                        scene_context=scene_context,
                        session_id=session_id,
                        turn_no=turn_no,
                    )
                )
        except Exception:
            return None
    
    def _create_fallback_proposal(
        self,
        scene_id: str,
        game_state: Dict[str, Any],
        current_turn: int,
    ) -> "SceneEventProposal":
        from ..models.proposals import (
            SceneEventProposal,
            CandidateEvent,
            StateDeltaCandidate,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
            ValidationStatus,
        )
        
        triggered = self.evaluate_triggers(game_state, current_turn)
        
        candidate_events = []
        state_deltas = []
        
        for trigger in triggered:
            candidate_events.append(CandidateEvent(
                event_type="scene_trigger",
                description=f"Scene trigger activated: {trigger.trigger_id}",
                target_entity_ids=[],
                effects={},
                importance=trigger.priority,
                visibility="player_visible",
            ))
        
        scene = self.get_scene(scene_id)
        scene_name = scene.name if scene else None
        
        return SceneEventProposal(
            scene_id=scene_id,
            scene_name=scene_name,
            candidate_events=candidate_events,
            state_deltas=state_deltas,
            affected_entities=[],
            suggested_transition=None,
            transition_reason=None,
            visibility="player_visible",
            confidence=0.3 if triggered else 0.0,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.SCENE_EVENT,
                source_engine=ProposalSource.SCENE_ENGINE,
                fallback_used=not bool(triggered),
                fallback_reason="LLM unavailable or failed" if not triggered else "Using deterministic triggers",
                validation_status=ValidationStatus.PASSED,
            ),
            is_fallback=True,
        )
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        return self._audit_log.copy()
    
    def clear_audit_log(self) -> None:
        self._audit_log.clear()

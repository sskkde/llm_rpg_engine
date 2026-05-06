"""
Debug Replay System for LLM RPG Engine.

Provides tools for:
- Reconstructing game state from snapshots and event logs
- Replaying turns to verify state consistency
- Debugging turn processing with filtered information
- State comparison between expected and actual

Ensures no hidden lore leaks to player role during replay.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from copy import deepcopy

from pydantic import BaseModel, Field


class ReplayPerspective(str, Enum):
    """Perspective for replay viewing."""
    ADMIN = "admin"  # Full access, sees hidden info
    PLAYER = "player"  # Player view, no hidden info
    AUDITOR = "auditor"  # Audit view, sees audit data but not hidden lore


class StateSnapshot(BaseModel):
    """A snapshot of game state at a point in time."""
    snapshot_id: str = Field(..., description="Unique snapshot identifier")
    session_id: str = Field(..., description="Session ID")
    turn_no: int = Field(..., description="Turn number when snapshot was taken")
    
    # State data
    world_state: Dict[str, Any] = Field(default_factory=dict)
    player_state: Dict[str, Any] = Field(default_factory=dict)
    npc_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    location_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    quest_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    faction_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    snapshot_type: str = Field(default="manual", description="manual, auto, checkpoint")


class ReplayEvent(BaseModel):
    """Event in replay sequence."""
    event_id: str = Field(...)
    event_type: str = Field(...)
    turn_no: int = Field(...)
    timestamp: datetime = Field(...)
    actor_id: Optional[str] = Field(None)
    summary: Optional[str] = Field(None)
    visible_to_player: bool = Field(default=True)
    data: Dict[str, Any] = Field(default_factory=dict)


class LLMStageMetadata(BaseModel):
    """Metadata for a single LLM stage from result_json."""
    stage_name: str = Field(...)
    enabled: bool = Field(default=False)
    timeout: float = Field(default=0.0)
    accepted: bool = Field(default=False)
    fallback_reason: Optional[str] = Field(None)
    validation_errors: List[str] = Field(default_factory=list)
    model_call_id: Optional[str] = Field(None)


class ReplayStep(BaseModel):
    """A single step in the replay."""
    step_no: int = Field(...)
    turn_no: int = Field(...)
    player_input: Optional[str] = Field(None)
    
    # State before this step
    state_before: Dict[str, Any] = Field(default_factory=dict)
    
    # State after this step
    state_after: Dict[str, Any] = Field(default_factory=dict)
    
    # Events in this step
    events: List[ReplayEvent] = Field(default_factory=list)
    
    # State deltas
    state_deltas: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Audit data
    model_call_ids: List[str] = Field(default_factory=list)
    context_build_ids: List[str] = Field(default_factory=list)
    validation_ids: List[str] = Field(default_factory=list)
    
    # Proposal audit data (replay-safe - no re-calling LLM)
    proposal_audits: List[Dict[str, Any]] = Field(default_factory=list)
    
    # LLM stage metadata from result_json (replay-safe)
    llm_stages: List[LLMStageMetadata] = Field(default_factory=list)
    
    # Additional result_json data (filtered by perspective)
    result_metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Timing
    duration_ms: Optional[int] = Field(None)
    timestamp: datetime = Field(default_factory=datetime.now)


class ReplayResult(BaseModel):
    """Result of a replay operation."""
    replay_id: str = Field(..., description="Unique replay identifier")
    session_id: str = Field(..., description="Session ID")
    
    # Replay parameters
    start_turn: int = Field(...)
    end_turn: int = Field(...)
    perspective: ReplayPerspective = Field(...)
    
    # Results
    steps: List[ReplayStep] = Field(default_factory=list)
    final_state: Dict[str, Any] = Field(default_factory=dict)
    
    # Statistics
    total_steps: int = Field(default=0)
    total_events: int = Field(default=0)
    total_state_deltas: int = Field(default=0)
    
    # Status
    success: bool = Field(default=True)
    error_message: Optional[str] = Field(None)
    
    # Timing
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = Field(None)
    replay_duration_ms: Optional[int] = Field(None)


class StateDelta(BaseModel):
    """State change operation."""
    path: str = Field(..., description="Dot-separated path to state field")
    old_value: Any = Field(...)
    new_value: Any = Field(...)
    operation: str = Field(default="set")


class ReplayError(Exception):
    """Error during replay operation."""
    pass


class StateReconstructor:
    """Reconstructs game state from snapshots and events."""
    
    def __init__(self):
        self._snapshots: Dict[str, StateSnapshot] = {}
        self._snapshots_by_session: Dict[str, List[str]] = {}
    
    def store_snapshot(self, snapshot: StateSnapshot) -> str:
        """Store a state snapshot."""
        self._snapshots[snapshot.snapshot_id] = snapshot
        
        if snapshot.session_id not in self._snapshots_by_session:
            self._snapshots_by_session[snapshot.session_id] = []
        self._snapshots_by_session[snapshot.session_id].append(snapshot.snapshot_id)
        
        return snapshot.snapshot_id
    
    def create_snapshot(
        self,
        session_id: str,
        turn_no: int,
        world_state: Dict[str, Any],
        player_state: Dict[str, Any],
        npc_states: Optional[Dict[str, Dict[str, Any]]] = None,
        location_states: Optional[Dict[str, Dict[str, Any]]] = None,
        quest_states: Optional[Dict[str, Dict[str, Any]]] = None,
        faction_states: Optional[Dict[str, Dict[str, Any]]] = None,
        snapshot_type: str = "manual",
    ) -> StateSnapshot:
        """Create and store a new snapshot."""
        snapshot = StateSnapshot(
            snapshot_id=f"snap_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_no=turn_no,
            world_state=deepcopy(world_state),
            player_state=deepcopy(player_state),
            npc_states=deepcopy(npc_states) if npc_states else {},
            location_states=deepcopy(location_states) if location_states else {},
            quest_states=deepcopy(quest_states) if quest_states else {},
            faction_states=deepcopy(faction_states) if faction_states else {},
            snapshot_type=snapshot_type,
        )
        self.store_snapshot(snapshot)
        return snapshot
    
    def get_snapshot(self, snapshot_id: str) -> Optional[StateSnapshot]:
        """Get a snapshot by ID."""
        return self._snapshots.get(snapshot_id)
    
    def get_latest_snapshot_before_turn(
        self,
        session_id: str,
        turn_no: int
    ) -> Optional[StateSnapshot]:
        """Get the latest snapshot before or at a given turn."""
        snapshot_ids = self._snapshots_by_session.get(session_id, [])
        candidates = [
            self._snapshots[sid]
            for sid in snapshot_ids
            if self._snapshots[sid].turn_no <= turn_no
        ]
        
        if not candidates:
            return None
        
        candidates.sort(key=lambda s: s.turn_no, reverse=True)
        return candidates[0]
    
    def reconstruct_state(
        self,
        base_state: Dict[str, Any],
        deltas: List[StateDelta]
    ) -> Dict[str, Any]:
        """Apply state deltas to reconstruct state."""
        state = deepcopy(base_state)
        
        for delta in deltas:
            self._apply_delta(state, delta)
        
        return state
    
    def _apply_delta(self, state: Dict[str, Any], delta: StateDelta) -> None:
        """Apply a single state delta."""
        path_parts = delta.path.split(".")
        target = state
        
        for part in path_parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        
        final_key = path_parts[-1]
        
        if delta.operation == "set":
            target[final_key] = deepcopy(delta.new_value)
        elif delta.operation == "add":
            if final_key not in target:
                target[final_key] = []
            if isinstance(target[final_key], list):
                target[final_key].append(deepcopy(delta.new_value))
        elif delta.operation == "remove":
            if final_key in target:
                if isinstance(target[final_key], list) and delta.old_value in target[final_key]:
                    target[final_key].remove(delta.old_value)
                else:
                    del target[final_key]
        elif delta.operation == "increment":
            current = target.get(final_key, 0)
            target[final_key] = current + delta.new_value


class ReplayEngine:
    """Engine for replaying game turns."""
    
    def __init__(self, state_reconstructor: Optional[StateReconstructor] = None):
        self._state_reconstructor = state_reconstructor or StateReconstructor()
        self._replays: Dict[str, ReplayResult] = {}
    
    def replay_from_snapshot(
        self,
        session_id: str,
        snapshot_id: str,
        target_turn: int,
        events: List[ReplayEvent],
        perspective: ReplayPerspective = ReplayPerspective.ADMIN,
    ) -> ReplayResult:
        """
        Replay turns from a snapshot to target turn.
        
        Args:
            session_id: Game session ID
            snapshot_id: Starting snapshot ID
            target_turn: Turn to replay to
            events: Events to replay
            perspective: Viewing perspective (affects what data is visible)
        
        Returns:
            ReplayResult with reconstructed state
        """
        start_time = datetime.now()
        
        snapshot = self._state_reconstructor.get_snapshot(snapshot_id)
        if not snapshot:
            raise ReplayError(f"Snapshot not found: {snapshot_id}")
        
        replay_id = f"replay_{uuid.uuid4().hex[:12]}"
        
        # Initialize replay state from snapshot
        current_state = {
            "world_state": deepcopy(snapshot.world_state),
            "player_state": deepcopy(snapshot.player_state),
            "npc_states": deepcopy(snapshot.npc_states),
            "location_states": deepcopy(snapshot.location_states),
            "quest_states": deepcopy(snapshot.quest_states),
            "faction_states": deepcopy(snapshot.faction_states),
        }
        
        # Filter events by turn range
        relevant_events = [
            e for e in events
            if snapshot.turn_no < e.turn_no <= target_turn
        ]
        relevant_events.sort(key=lambda e: (e.turn_no, e.timestamp))
        
        # Group events by turn
        events_by_turn: Dict[int, List[ReplayEvent]] = {}
        for event in relevant_events:
            if event.turn_no not in events_by_turn:
                events_by_turn[event.turn_no] = []
            events_by_turn[event.turn_no].append(event)
        
        steps: List[ReplayStep] = []
        step_no = 0
        
        for turn_no in sorted(events_by_turn.keys()):
            turn_events = events_by_turn[turn_no]
            
            state_before = deepcopy(current_state)
            
            state_deltas: List[Dict[str, Any]] = []
            player_input = None
            result_json = None
            
            for event in turn_events:
                if "state_deltas" in event.data:
                    for delta_data in event.data["state_deltas"]:
                        delta = StateDelta(**delta_data)
                        state_deltas.append(delta_data)
                        self._state_reconstructor._apply_delta(current_state, delta)
                
                if event.event_type == "player_input" and "raw_input" in event.data:
                    player_input = event.data["raw_input"]
                
                if "result_json" in event.data:
                    result_json = event.data["result_json"]
            
            llm_stages = self.extract_llm_stage_metadata(result_json, perspective)
            result_metadata = self.extract_result_metadata(result_json, perspective)
            
            step_no += 1
            step = ReplayStep(
                step_no=step_no,
                turn_no=turn_no,
                player_input=player_input,
                state_before=self._filter_state_for_perspective(state_before, perspective),
                state_after=self._filter_state_for_perspective(deepcopy(current_state), perspective),
                events=self._filter_events_for_perspective(turn_events, perspective),
                state_deltas=state_deltas,
                llm_stages=llm_stages,
                result_metadata=result_metadata,
            )
            steps.append(step)
        
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        result = ReplayResult(
            replay_id=replay_id,
            session_id=session_id,
            start_turn=snapshot.turn_no,
            end_turn=target_turn,
            perspective=perspective,
            steps=steps,
            final_state=self._filter_state_for_perspective(current_state, perspective),
            total_steps=len(steps),
            total_events=len(relevant_events),
            total_state_deltas=sum(len(s.state_deltas) for s in steps),
            completed_at=end_time,
            replay_duration_ms=duration_ms,
        )
        
        self._replays[replay_id] = result
        return result
    
    def replay_turn_range(
        self,
        session_id: str,
        start_turn: int,
        end_turn: int,
        events: List[ReplayEvent],
        base_state: Optional[Dict[str, Any]] = None,
        perspective: ReplayPerspective = ReplayPerspective.ADMIN,
    ) -> ReplayResult:
        """
        Replay a range of turns.
        
        Args:
            session_id: Game session ID
            start_turn: Starting turn number
            end_turn: Ending turn number
            events: All events to consider
            base_state: Optional base state (if None, uses empty state)
            perspective: Viewing perspective
        
        Returns:
            ReplayResult with reconstructed state
        """
        start_time = datetime.now()
        replay_id = f"replay_{uuid.uuid4().hex[:12]}"
        
        # Initialize state
        current_state = deepcopy(base_state) if base_state else {
            "world_state": {},
            "player_state": {},
            "npc_states": {},
            "location_states": {},
            "quest_states": {},
            "faction_states": {},
        }
        
        # Filter events by turn range
        relevant_events = [
            e for e in events
            if start_turn <= e.turn_no <= end_turn
        ]
        relevant_events.sort(key=lambda e: (e.turn_no, e.timestamp))
        
        # Group events by turn
        events_by_turn: Dict[int, List[ReplayEvent]] = {}
        for event in relevant_events:
            if event.turn_no not in events_by_turn:
                events_by_turn[event.turn_no] = []
            events_by_turn[event.turn_no].append(event)
        
        steps: List[ReplayStep] = []
        step_no = 0
        
        for turn_no in sorted(events_by_turn.keys()):
            turn_events = events_by_turn[turn_no]
            
            state_before = deepcopy(current_state)
            state_deltas: List[Dict[str, Any]] = []
            player_input = None
            result_json = None
            
            for event in turn_events:
                if "state_deltas" in event.data:
                    for delta_data in event.data["state_deltas"]:
                        delta = StateDelta(**delta_data)
                        state_deltas.append(delta_data)
                        self._state_reconstructor._apply_delta(current_state, delta)
                
                if event.event_type == "player_input" and "raw_input" in event.data:
                    player_input = event.data["raw_input"]
                
                if "result_json" in event.data:
                    result_json = event.data["result_json"]
            
            llm_stages = self.extract_llm_stage_metadata(result_json, perspective)
            result_metadata = self.extract_result_metadata(result_json, perspective)
            
            step_no += 1
            step = ReplayStep(
                step_no=step_no,
                turn_no=turn_no,
                player_input=player_input,
                state_before=self._filter_state_for_perspective(state_before, perspective),
                state_after=self._filter_state_for_perspective(deepcopy(current_state), perspective),
                events=self._filter_events_for_perspective(turn_events, perspective),
                state_deltas=state_deltas,
                llm_stages=llm_stages,
                result_metadata=result_metadata,
            )
            steps.append(step)
        
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        result = ReplayResult(
            replay_id=replay_id,
            session_id=session_id,
            start_turn=start_turn,
            end_turn=end_turn,
            perspective=perspective,
            steps=steps,
            final_state=self._filter_state_for_perspective(current_state, perspective),
            total_steps=len(steps),
            total_events=len(relevant_events),
            total_state_deltas=sum(len(s.state_deltas) for s in steps),
            completed_at=end_time,
            replay_duration_ms=duration_ms,
        )
        
        self._replays[replay_id] = result
        return result
    
    def _filter_state_for_perspective(
        self,
        state: Dict[str, Any],
        perspective: ReplayPerspective
    ) -> Dict[str, Any]:
        """Filter state based on viewing perspective."""
        if perspective == ReplayPerspective.ADMIN:
            return state
        
        filtered = deepcopy(state)
        
        # For PLAYER perspective, remove hidden information
        if perspective == ReplayPerspective.PLAYER:
            # Remove hidden plan states from NPCs
            if "npc_states" in filtered:
                for npc_id, npc_state in filtered["npc_states"].items():
                    if isinstance(npc_state, dict):
                        npc_state.pop("hidden_plan_state", None)
                        npc_state.pop("hidden_identity", None)
                        npc_state.pop("secrets", None)
                        npc_state.pop("forbidden_knowledge", None)
            
            # Remove hidden identity info
            if "quest_states" in filtered:
                for quest_id, quest_state in filtered["quest_states"].items():
                    if isinstance(quest_state, dict):
                        quest_state.pop("hidden_objectives", None)
                        quest_state.pop("secret_rewards", None)
        
        # For AUDITOR perspective, show audit-relevant data but not hidden lore
        if perspective == ReplayPerspective.AUDITOR:
            # Keep structure but redact sensitive content
            if "npc_states" in filtered:
                for npc_id, npc_state in filtered["npc_states"].items():
                    if isinstance(npc_state, dict):
                        if "hidden_plan_state" in npc_state:
                            npc_state["hidden_plan_state"] = "[REDACTED - AUDITOR VIEW]"
                        if "secrets" in npc_state:
                            npc_state["secrets"] = "[REDACTED - AUDITOR VIEW]"
        
        return filtered
    
    def _filter_events_for_perspective(
        self,
        events: List[ReplayEvent],
        perspective: ReplayPerspective
    ) -> List[ReplayEvent]:
        """Filter events based on viewing perspective."""
        if perspective == ReplayPerspective.ADMIN:
            return events
        
        filtered = []
        for event in events:
            # For PLAYER perspective, only show player-visible events
            if perspective == ReplayPerspective.PLAYER:
                if event.visible_to_player:
                    filtered.append(event)
            else:
                filtered.append(event)
        
        return filtered
    
    def get_replay(self, replay_id: str) -> Optional[ReplayResult]:
        """Get a replay result by ID."""
        return self._replays.get(replay_id)
    
    def compare_states(
        self,
        expected: Dict[str, Any],
        actual: Dict[str, Any],
        path: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Compare two states and return differences.
        
        Returns list of differences with path, expected, and actual values.
        """
        differences = []
        
        # Check keys in expected
        for key in expected:
            current_path = f"{path}.{key}" if path else key
            
            if key not in actual:
                differences.append({
                    "path": current_path,
                    "expected": expected[key],
                    "actual": None,
                    "type": "missing_in_actual",
                })
            elif isinstance(expected[key], dict) and isinstance(actual[key], dict):
                differences.extend(self.compare_states(expected[key], actual[key], current_path))
            elif expected[key] != actual[key]:
                differences.append({
                    "path": current_path,
                    "expected": expected[key],
                    "actual": actual[key],
                    "type": "value_mismatch",
                })
        
        # Check for keys only in actual
        for key in actual:
            if key not in expected:
                current_path = f"{path}.{key}" if path else key
                differences.append({
                    "path": current_path,
                    "expected": None,
                    "actual": actual[key],
                    "type": "missing_in_expected",
                })
        
        return differences
    
    def verify_replay_consistency(
        self,
        replay_result: ReplayResult,
        expected_final_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Verify that a replay is consistent.
        
        Checks:
        - State transitions are valid
        - All events are accounted for
        - Final state matches expected (if provided)
        
        Returns verification report.
        """
        report = {
            "replay_id": replay_result.replay_id,
            "consistent": True,
            "checks": [],
            "errors": [],
        }
        
        # Check each step
        previous_state = None
        for step in replay_result.steps:
            # Verify state continuity
            if previous_state is not None:
                if step.state_before != previous_state:
                    report["checks"].append({
                        "step": step.step_no,
                        "check": "state_continuity",
                        "passed": False,
                        "message": "State before step doesn't match previous state after",
                    })
                    report["consistent"] = False
                else:
                    report["checks"].append({
                        "step": step.step_no,
                        "check": "state_continuity",
                        "passed": True,
                    })
            
            # Verify state deltas are applied
            for delta in step.state_deltas:
                report["checks"].append({
                    "step": step.step_no,
                    "check": f"delta_applied:{delta.get('path', 'unknown')}",
                    "passed": True,
                })
            
            previous_state = step.state_after
        
        # Compare with expected final state if provided
        if expected_final_state is not None:
            differences = self.compare_states(expected_final_state, replay_result.final_state)
            if differences:
                report["consistent"] = False
                report["errors"].append({
                    "type": "final_state_mismatch",
                    "differences": differences,
                })
            else:
                report["checks"].append({
                    "check": "final_state_match",
                    "passed": True,
                })
        
        return report
    
    def replay_with_proposal_audits(
        self,
        session_id: str,
        start_turn: int,
        end_turn: int,
        events: List[ReplayEvent],
        proposal_audits: Dict[int, List[Dict[str, Any]]],
        base_state: Optional[Dict[str, Any]] = None,
        perspective: ReplayPerspective = ReplayPerspective.ADMIN,
    ) -> ReplayResult:
        """
        Replay turns with proposal audit data (no LLM re-calls needed).
        
        Args:
            session_id: Game session ID
            start_turn: Starting turn number
            end_turn: Ending turn number
            events: All events to consider
            proposal_audits: Dict mapping turn_no -> list of proposal audit entries
            base_state: Optional base state
            perspective: Viewing perspective
        
        Returns:
            ReplayResult with proposal audit data included for each step
        """
        result = self.replay_turn_range(
            session_id=session_id,
            start_turn=start_turn,
            end_turn=end_turn,
            events=events,
            base_state=base_state,
            perspective=perspective,
        )
        
        # Attach proposal audits to each step
        for step in result.steps:
            turn_audits = proposal_audits.get(step.turn_no, [])
            step.proposal_audits = turn_audits
        
        return result
    
    def get_proposal_audit_summary(
        self,
        proposal_audits: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Summarize proposal audits for a turn.
        
        Returns statistics about proposals without needing to re-call LLM.
        """
        if not proposal_audits:
            return {
                "total": 0,
                "by_type": {},
                "fallbacks": 0,
                "rejections": 0,
                "avg_confidence": 0.0,
            }
        
        by_type: Dict[str, int] = {}
        fallbacks = 0
        rejections = 0
        total_confidence = 0.0
        
        for audit in proposal_audits:
            ptype = audit.get("proposal_type", "unknown")
            by_type[ptype] = by_type.get(ptype, 0) + 1
            
            if audit.get("fallback_used"):
                fallbacks += 1
            if audit.get("rejected"):
                rejections += 1
            total_confidence += audit.get("confidence", 0.5)
        
        return {
            "total": len(proposal_audits),
            "by_type": by_type,
            "fallbacks": fallbacks,
            "rejections": rejections,
            "avg_confidence": total_confidence / len(proposal_audits) if proposal_audits else 0.0,
        }
    
    def extract_llm_stage_metadata(
        self,
        result_json: Optional[Dict[str, Any]],
        perspective: ReplayPerspective,
    ) -> List[LLMStageMetadata]:
        if not result_json:
            return []
        
        llm_stages_data = result_json.get("llm_stages", [])
        if not llm_stages_data:
            return []
        
        metadata_list = []
        for stage_data in llm_stages_data:
            if not isinstance(stage_data, dict):
                continue
            
            metadata = LLMStageMetadata(
                stage_name=stage_data.get("stage_name", ""),
                enabled=stage_data.get("enabled", False),
                timeout=stage_data.get("timeout", 0.0),
                accepted=stage_data.get("accepted", False),
                fallback_reason=stage_data.get("fallback_reason"),
                validation_errors=stage_data.get("validation_errors", []),
                model_call_id=stage_data.get("model_call_id"),
            )
            metadata_list.append(metadata)
        
        return metadata_list
    
    def extract_result_metadata(
        self,
        result_json: Optional[Dict[str, Any]],
        perspective: ReplayPerspective,
    ) -> Dict[str, Any]:
        if not result_json:
            return {}
        
        allowed_keys = {
            "world_progression",
            "npc_reactions",
            "scene_event_summary",
            "parsed_intent",
            "memory_persistence",
        }
        
        metadata = {}
        for key in allowed_keys:
            if key in result_json:
                value = result_json[key]
                
                if perspective == ReplayPerspective.PLAYER:
                    if key == "npc_reactions" and isinstance(value, list):
                        value = [
                            {
                                k: v for k, v in reaction.items()
                                if k not in ("hidden_motivation", "internal_state")
                            }
                            for reaction in value
                        ]
                
                metadata[key] = value
        
        return metadata


class ReplayStore:
    """Storage for replay data and snapshots."""
    
    def __init__(self):
        self._state_reconstructor = StateReconstructor()
        self._replay_engine = ReplayEngine(self._state_reconstructor)
    
    def get_state_reconstructor(self) -> StateReconstructor:
        """Get the state reconstructor."""
        return self._state_reconstructor
    
    def get_replay_engine(self) -> ReplayEngine:
        """Get the replay engine."""
        return self._replay_engine
    
    def create_snapshot(
        self,
        session_id: str,
        turn_no: int,
        world_state: Dict[str, Any],
        player_state: Dict[str, Any],
        **kwargs
    ) -> StateSnapshot:
        """Create and store a state snapshot."""
        return self._state_reconstructor.create_snapshot(
            session_id=session_id,
            turn_no=turn_no,
            world_state=world_state,
            player_state=player_state,
            **kwargs
        )
    
    def get_snapshot(self, snapshot_id: str) -> Optional[StateSnapshot]:
        """Get a snapshot by ID."""
        return self._state_reconstructor.get_snapshot(snapshot_id)
    
    def replay_from_snapshot(
        self,
        session_id: str,
        snapshot_id: str,
        target_turn: int,
        events: List[ReplayEvent],
        perspective: ReplayPerspective = ReplayPerspective.ADMIN,
    ) -> ReplayResult:
        """Replay from a snapshot."""
        return self._replay_engine.replay_from_snapshot(
            session_id=session_id,
            snapshot_id=snapshot_id,
            target_turn=target_turn,
            events=events,
            perspective=perspective,
        )


# Global replay store instance
_replay_store: Optional[ReplayStore] = None


def get_replay_store() -> ReplayStore:
    """Get or create the global replay store."""
    global _replay_store
    if _replay_store is None:
        _replay_store = ReplayStore()
    return _replay_store


def reset_replay_store() -> None:
    """Reset the global replay store (useful for testing)."""
    global _replay_store
    _replay_store = ReplayStore()

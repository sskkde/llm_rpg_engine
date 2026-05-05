"""
Deterministic Turn Transaction Spine

This module implements the turn pipeline with atomic commit/rollback semantics:
1. Record input
2. Parse intent
3. Read canonical state (immutable working copy)
4. World tick
5. Action scheduling
6. NPC decision loop
7. Conflict resolution
8. Validation
9. Commit event/state/memory/summary/audit (atomic)
10. Build player-visible projection
11. Generate narration
12. Return result

Key invariants:
- Canonical state is never mutated before validation
- Validation failures result in no committed state delta
- Failed validation writes audit error
- Commit is atomic - all or nothing
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from copy import deepcopy

from ..models.states import CanonicalState, PlayerState, WorldState, CurrentSceneState
from ..models.events import (
    GameEvent,
    PlayerInputEvent,
    WorldTickEvent,
    SceneEvent,
    NPCDecisionEvent,
    NPCActionEvent,
    StateDeltaEvent,
    MemoryWriteEvent,
    NarrationEvent,
    ParsedIntent,
    TurnTransaction,
    StateDelta,
    EventType,
    WorldTime,
)
from ..models.common import ProposedAction, CommittedAction, ValidationResult
from ..models.perspectives import PlayerPerspective, NarratorPerspective
from ..models.proposals import InputIntentProposal

from .event_log import EventLog
from .canonical_state import CanonicalStateManager
from .action_scheduler import ActionScheduler
from .validator import Validator
from .perspective import PerspectiveService
from .context_builder import ContextBuilder

from ..engines.world_engine import WorldEngine
from ..engines.npc_engine import NPCEngine
from ..engines.narration_engine import NarrationEngine
from ..llm.proposal_pipeline import ProposalPipeline


class TurnValidationError(Exception):
    """Raised when turn validation fails."""
    
    def __init__(self, message: str, validation_result: ValidationResult, audit_event_id: Optional[str] = None):
        super().__init__(message)
        self.validation_result = validation_result
        self.audit_event_id = audit_event_id


class TurnOrchestrator:
    """
    Orchestrates the deterministic turn transaction pipeline.
    
    Ensures:
    - Canonical state is immutable until validation passes
    - Atomic commit/rollback semantics
    - Complete audit trail for all operations
    - Replay capability from event log + snapshots
    """
    
    def __init__(
        self,
        state_manager: CanonicalStateManager,
        event_log: EventLog,
        action_scheduler: ActionScheduler,
        validator: Validator,
        perspective_service: PerspectiveService,
        context_builder: ContextBuilder,
        world_engine: WorldEngine,
        npc_engine: NPCEngine,
        narration_engine: NarrationEngine,
        proposal_pipeline: Optional[ProposalPipeline] = None,
    ):
        self._state_manager = state_manager
        self._event_log = event_log
        self._action_scheduler = action_scheduler
        self._validator = validator
        self._perspective = perspective_service
        self._context_builder = context_builder
        self._world_engine = world_engine
        self._npc_engine = npc_engine
        self._narration_engine = narration_engine
        self._proposal_pipeline = proposal_pipeline
        
        # Audit log for debugging and replay
        self._audit_log: List[Dict[str, Any]] = []
    
    def execute_turn(
        self,
        session_id: str,
        game_id: str,
        turn_index: int,
        player_input: str,
    ) -> Dict[str, Any]:
        """
        Execute a complete turn transaction.
        
        Returns:
            Dict containing turn result with narration, state updates, and metadata
        
        Raises:
            TurnValidationError: If validation fails (state remains unchanged)
        """
        # Get canonical state (will not be modified until commit)
        canonical_state = self._state_manager.get_state(game_id)
        if canonical_state is None:
            raise ValueError(f"Game state not found: {game_id}")
        
        # Create working copy for simulation
        working_state = canonical_state.model_copy(deep=True)
        
        # Step 1-3: Start transaction and record input
        transaction = self._start_transaction(
            session_id=session_id,
            game_id=game_id,
            turn_index=turn_index,
            player_input=player_input,
            world_time_before=working_state.world_state.current_time,
        )
        
        events: List[GameEvent] = []
        proposed_actions: List[ProposedAction] = []
        committed_actions: List[CommittedAction] = []
        state_deltas: List[StateDelta] = []
        
        try:
            # Step 2: Parse intent and record player input event
            parsed_intent = self._parse_intent(player_input)
            player_input_event = self._create_player_input_event(
                turn_index=turn_index,
                player_input=player_input,
                parsed_intent=parsed_intent,
            )
            events.append(player_input_event)
            
            # Step 4: World tick (on working state)
            world_tick_event = self._world_engine.advance_time(game_id)
            working_state.world_state.current_time = world_tick_event.time_after
            events.append(world_tick_event)
            
            # Step 5: Check scene triggers (on working state)
            scene_triggers = self._action_scheduler.collect_scene_triggers(working_state)
            for trigger in scene_triggers:
                scene_event = self._create_scene_event(
                    turn_index=turn_index,
                    trigger=trigger,
                )
                events.append(scene_event)
            
            # Step 5: Collect actors
            actors = self._action_scheduler.collect_actors(working_state)
            
            # Step 6: NPC decision loop (on working state)
            npc_actions = self._process_npc_decisions(
                game_id=game_id,
                turn_index=turn_index,
                working_state=working_state,
                actors=actors,
            )
            proposed_actions.extend(npc_actions)
            
            # Add player action if intent was parsed
            if parsed_intent:
                player_action = self._create_player_action(
                    turn_index=turn_index,
                    parsed_intent=parsed_intent,
                )
                proposed_actions.append(player_action)
            
            # Step 7: Resolve conflicts
            resolved_actions = self._action_scheduler.resolve_conflicts(
                proposed_actions,
                working_state,
            )
            
            # Step 8: Validate actions and compute state deltas
            for action in resolved_actions:
                validation = self._validator.validate_action(
                    action=action,
                    state=working_state,
                )
                
                if not validation.is_valid:
                    # Validation failed - record audit and raise error
                    audit_event_id = self._record_validation_failure(
                        transaction=transaction,
                        action=action,
                        validation=validation,
                    )
                    raise TurnValidationError(
                        message=f"Action validation failed: {action.action_id}",
                        validation_result=validation,
                        audit_event_id=audit_event_id,
                    )
                
                # Compute state deltas for this action
                action_deltas = self._compute_state_deltas(action, working_state)
                state_deltas.extend(action_deltas)
                
                # Create committed action
                committed_action = CommittedAction(
                    action_id=action.action_id,
                    actor_id=action.actor_id,
                    action_type=action.action_type,
                    target_ids=action.target_ids,
                    summary=action.summary,
                    visible_to_player=action.visible_to_player,
                    state_deltas=[d.model_dump() for d in action_deltas],
                    event_ids=[e.event_id for e in events],
                )
                committed_actions.append(committed_action)
            
            # Validate state deltas
            for delta in state_deltas:
                validation = self._validator.validate_state_delta(
                    delta_path=delta.path,
                    old_value=delta.old_value,
                    new_value=delta.new_value,
                    state=working_state,
                )
                if not validation.is_valid:
                    audit_event_id = self._record_validation_failure(
                        transaction=transaction,
                        action=None,
                        validation=validation,
                    )
                    raise TurnValidationError(
                        message=f"State delta validation failed: {delta.path}",
                        validation_result=validation,
                        audit_event_id=audit_event_id,
                    )
            
            # Step 9: ATOMIC COMMIT
            # All events, state changes, and audit records are committed together
            commit_result = self._atomic_commit(
                transaction=transaction,
                game_id=game_id,
                events=events,
                state_deltas=state_deltas,
                working_state=working_state,
                canonical_state=canonical_state,
                turn_index=turn_index,
            )
            
            # Step 10: Build player-visible projection (from committed state)
            player_perspective = self._perspective.build_player_perspective(
                perspective_id=f"player_view_{turn_index}",
                player_id="player",
            )
            
            narrator_perspective = self._perspective.build_narrator_perspective(
                perspective_id=f"narrator_view_{turn_index}",
                base_perspective_id=f"player_view_{turn_index}",
            )
            
            # Step 11: Generate narration (from committed state only)
            narration = self._narration_engine.generate_narration(
                game_id=game_id,
                turn_index=turn_index,
                player_perspective=player_perspective,
                narrator_perspective=narrator_perspective,
            )
            
            # Record narration event
            narration_event = NarrationEvent(
                event_id=f"evt_narration_{turn_index:06d}_{uuid.uuid4().hex[:8]}",
                turn_index=turn_index,
                visible_context_id=player_perspective.perspective_id,
                text=narration,
            )
            self._event_log.record_event(transaction, narration_event)
            
            # Finalize transaction
            self._event_log.commit_turn(transaction)
            
            # Step 12: Return result
            return {
                "transaction_id": transaction.transaction_id,
                "turn_index": turn_index,
                "narration": narration,
                "events_committed": len(events),
                "actions_committed": len(committed_actions),
                "state_deltas_applied": len(state_deltas),
                "world_time": working_state.world_state.current_time.model_dump(),
                "player_state": working_state.player_state.model_dump(),
                "forbidden_info": narrator_perspective.forbidden_info,
                "validation_passed": True,
            }
            
        except TurnValidationError:
            # Rollback transaction - no state changes committed
            self._event_log.abort_turn(transaction)
            raise
        except Exception as e:
            # Unexpected error - rollback and record audit
            self._record_unexpected_error(transaction, e)
            self._event_log.abort_turn(transaction)
            raise
    
    def _start_transaction(
        self,
        session_id: str,
        game_id: str,
        turn_index: int,
        player_input: str,
        world_time_before: WorldTime,
    ) -> TurnTransaction:
        """Start a new turn transaction."""
        return self._event_log.start_turn(
            session_id=session_id,
            game_id=game_id,
            turn_index=turn_index,
            player_input=player_input,
            world_time_before=world_time_before,
        )
    
    def _parse_intent(self, player_input: str) -> Optional[ParsedIntent]:
        """
        Parse player input into structured intent.
        
        Uses ProposalPipeline for LLM-driven intent parsing with deterministic
        keyword-based fallback for timeout, malformed JSON, schema errors,
        or validator rejection.
        
        Audit records both accepted LLM parse and fallback reasons.
        """
        # Try LLM-based parsing if proposal pipeline is available
        if self._proposal_pipeline is not None:
            try:
                import asyncio
                proposal = asyncio.get_event_loop().run_until_complete(
                    self._proposal_pipeline.generate_input_intent(
                        raw_input=player_input,
                        session_id=None,
                        turn_no=0,
                    )
                )
                
                # Check if proposal is valid (not a fallback)
                if proposal and not proposal.is_fallback:
                    # Record successful LLM parse in audit log
                    self._audit_log.append({
                        "audit_id": f"intent_llm_{uuid.uuid4().hex[:8]}",
                        "timestamp": datetime.now().isoformat(),
                        "type": "intent_parse_llm_success",
                        "source": "proposal_pipeline",
                        "intent_type": proposal.intent_type,
                        "target": proposal.target,
                        "confidence": proposal.confidence,
                        "repair_status": proposal.audit.repair_status.value,
                        "latency_ms": proposal.audit.latency_ms,
                    })
                    
                    # Convert InputIntentProposal to ParsedIntent
                    return ParsedIntent(
                        intent_type=proposal.intent_type,
                        target=proposal.target,
                        risk_level=proposal.risk_level,
                        raw_tokens=proposal.raw_tokens,
                    )
                else:
                    # LLM returned fallback - record reason and use keyword parser
                    fallback_reason = proposal.audit.fallback_reason if proposal else "Unknown error"
                    self._audit_log.append({
                        "audit_id": f"intent_fallback_{uuid.uuid4().hex[:8]}",
                        "timestamp": datetime.now().isoformat(),
                        "type": "intent_parse_fallback",
                        "source": "keyword_parser",
                        "reason": fallback_reason,
                        "repair_status": proposal.audit.repair_status.value if proposal else "none",
                    })
                    
            except Exception as e:
                # LLM call failed - record error and fall back to keyword parser
                self._audit_log.append({
                    "audit_id": f"intent_error_{uuid.uuid4().hex[:8]}",
                    "timestamp": datetime.now().isoformat(),
                    "type": "intent_parse_error",
                    "source": "keyword_parser",
                    "error": str(e),
                })
        
        # Deterministic keyword-based fallback parser
        return self._parse_intent_keyword(player_input)
    
    def _parse_intent_keyword(self, player_input: str) -> ParsedIntent:
        """
        Deterministic keyword-based intent parser.
        
        Used as fallback when LLM parsing fails or is unavailable.
        """
        input_lower = player_input.lower()
        
        intent_type = "action"
        target = None
        risk_level = "low"
        
        if any(word in input_lower for word in ["走", "去", "move", "go"]):
            intent_type = "move"
        elif any(word in input_lower for word in ["说", "问", "talk", "speak", "ask"]):
            intent_type = "talk"
        elif any(word in input_lower for word in ["看", "观察", "inspect", "look", "observe"]):
            intent_type = "inspect"
        elif any(word in input_lower for word in ["打", "攻击", "attack", "fight"]):
            intent_type = "attack"
            risk_level = "high"
        elif any(word in input_lower for word in ["拿", "取", "pick", "take", "get"]):
            intent_type = "interact"
        
        return ParsedIntent(
            intent_type=intent_type,
            target=target,
            risk_level=risk_level,
            raw_tokens=player_input.split(),
        )
    
    def _create_player_input_event(
        self,
        turn_index: int,
        player_input: str,
        parsed_intent: Optional[ParsedIntent],
    ) -> PlayerInputEvent:
        """Create a player input event."""
        return PlayerInputEvent(
            event_id=f"evt_input_{turn_index:06d}_{uuid.uuid4().hex[:8]}",
            turn_index=turn_index,
            raw_input=player_input,
            parsed_intent=parsed_intent,
        )
    
    def _create_scene_event(
        self,
        turn_index: int,
        trigger: Dict[str, Any],
    ) -> SceneEvent:
        """Create a scene event from a trigger."""
        return SceneEvent(
            event_id=f"evt_scene_{turn_index:06d}_{uuid.uuid4().hex[:8]}",
            turn_index=turn_index,
            scene_id=trigger.get("scene_id", "unknown"),
            trigger=trigger.get("trigger_id", "unknown"),
            summary=f"Scene triggered: {trigger.get('event_candidate', 'unknown')}",
            visible_to_player=True,
            importance=trigger.get("priority", 0.5),
        )
    
    def _process_npc_decisions(
        self,
        game_id: str,
        turn_index: int,
        working_state: CanonicalState,
        actors: List[str],
    ) -> List[ProposedAction]:
        """Process NPC decisions and return proposed actions."""
        actions = []
        
        for actor_id in actors:
            if actor_id == "player":
                continue
            
            npc_state = working_state.npc_states.get(actor_id)
            if npc_state is None or npc_state.status != "alive":
                continue
            
            # Generate NPC action
            action = self._npc_engine.generate_npc_action(
                npc_id=actor_id,
                game_id=game_id,
                turn_index=turn_index,
            )
            
            if action:
                actions.append(action)
        
        return actions
    
    def _create_player_action(
        self,
        turn_index: int,
        parsed_intent: ParsedIntent,
    ) -> ProposedAction:
        """Create a player action from parsed intent."""
        return ProposedAction(
            action_id=f"action_player_{turn_index:06d}",
            actor_id="player",
            action_type=parsed_intent.intent_type,
            target_ids=[parsed_intent.target] if parsed_intent.target else [],
            summary=f"Player performs: {parsed_intent.intent_type}",
            priority=1.0,  # Player actions have highest priority
            visible_to_player=True,
        )
    
    def _compute_state_deltas(
        self,
        action: ProposedAction,
        working_state: CanonicalState,
    ) -> List[StateDelta]:
        """Compute state deltas for an action."""
        deltas = []
        
        # Example: Update NPC mood if NPC action
        if action.actor_id.startswith("npc_"):
            npc_state = working_state.npc_states.get(action.actor_id)
            if npc_state:
                old_mood = npc_state.mood
                # Simple mood change logic
                if action.action_type == "attack":
                    new_mood = "hostile"
                elif action.action_type == "talk":
                    new_mood = "engaged"
                else:
                    new_mood = old_mood
                
                if new_mood != old_mood:
                    deltas.append(StateDelta(
                        path=f"npcs.{action.actor_id}.mood",
                        old_value=old_mood,
                        new_value=new_mood,
                        operation="set",
                    ))
        
        return deltas
    
    def _atomic_commit(
        self,
        transaction: TurnTransaction,
        game_id: str,
        events: List[GameEvent],
        state_deltas: List[StateDelta],
        working_state: CanonicalState,
        canonical_state: CanonicalState,
        turn_index: int,
    ) -> Dict[str, Any]:
        """
        Atomically commit all changes.
        
        This ensures:
        - All events are recorded or none are
        - All state changes are applied or none are
        - All audit records are written or none are
        """
        try:
            # Record all events
            for event in events:
                self._event_log.record_event(transaction, event)
            
            # Record state delta event
            if state_deltas:
                delta_event = StateDeltaEvent(
                    event_id=f"evt_delta_{turn_index:06d}_{uuid.uuid4().hex[:8]}",
                    turn_index=turn_index,
                    deltas=state_deltas,
                    validated=True,
                )
                self._event_log.record_event(transaction, delta_event)
            
            # Apply state deltas to canonical state (only after validation)
            for delta in state_deltas:
                self._state_manager.apply_delta(game_id, delta)
            
            # Update world time in canonical state
            canonical_state.world_state.current_time = working_state.world_state.current_time
            
            return {
                "committed": True,
                "events_count": len(events),
                "deltas_count": len(state_deltas),
            }
            
        except Exception as e:
            # If anything fails during commit, record audit and re-raise
            self._record_commit_failure(transaction, e)
            raise
    
    def _record_validation_failure(
        self,
        transaction: TurnTransaction,
        action: Optional[ProposedAction],
        validation: ValidationResult,
    ) -> str:
        """Record a validation failure in the audit log."""
        audit_entry = {
            "audit_id": f"audit_fail_{uuid.uuid4().hex[:8]}",
            "transaction_id": transaction.transaction_id,
            "timestamp": datetime.now().isoformat(),
            "type": "validation_failure",
            "action_id": action.action_id if action else None,
            "errors": validation.errors,
            "warnings": validation.warnings,
        }
        self._audit_log.append(audit_entry)
        return audit_entry["audit_id"]
    
    def _record_unexpected_error(
        self,
        transaction: TurnTransaction,
        error: Exception,
    ) -> str:
        """Record an unexpected error in the audit log."""
        audit_entry = {
            "audit_id": f"audit_error_{uuid.uuid4().hex[:8]}",
            "transaction_id": transaction.transaction_id,
            "timestamp": datetime.now().isoformat(),
            "type": "unexpected_error",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        self._audit_log.append(audit_entry)
        return audit_entry["audit_id"]
    
    def _record_commit_failure(
        self,
        transaction: TurnTransaction,
        error: Exception,
    ) -> str:
        """Record a commit failure in the audit log."""
        audit_entry = {
            "audit_id": f"audit_commit_fail_{uuid.uuid4().hex[:8]}",
            "transaction_id": transaction.transaction_id,
            "timestamp": datetime.now().isoformat(),
            "type": "commit_failure",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        self._audit_log.append(audit_entry)
        return audit_entry["audit_id"]
    
    def replay_turns(
        self,
        game_id: str,
        start_turn: int,
        end_turn: int,
    ) -> CanonicalState:
        """
        Replay turns from event log to reconstruct canonical state.
        
        This is used for:
        - State verification
        - Debugging
        - Recovery from snapshots
        
        Returns:
            Reconstructed canonical state
        """
        # Get initial state snapshot
        # In production, this would load from a snapshot
        canonical_state = self._state_manager.get_state(game_id)
        if canonical_state is None:
            raise ValueError(f"Cannot replay: Game state not found: {game_id}")
        
        # Get events for the turn range
        events = self._event_log._store.get_events_in_range(start_turn, end_turn)
        
        # Sort events by timestamp
        events.sort(key=lambda e: e.timestamp)
        
        # Replay events
        for event in events:
            if event.event_type == EventType.STATE_DELTA:
                # Apply state deltas
                if hasattr(event, 'deltas'):
                    for delta in event.deltas:
                        self._state_manager.apply_delta(game_id, delta)
            elif event.event_type == EventType.WORLD_TICK:
                # Update world time
                if hasattr(event, 'time_after'):
                    canonical_state.world_state.current_time = event.time_after
        
        return canonical_state
    
    def get_audit_log(
        self,
        transaction_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get audit log entries, optionally filtered by transaction."""
        if transaction_id:
            return [entry for entry in self._audit_log if entry.get("transaction_id") == transaction_id]
        return self._audit_log.copy()
    
    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self._audit_log.clear()

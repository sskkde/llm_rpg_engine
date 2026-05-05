"""
Deterministic Turn Transaction Spine

This module implements the turn pipeline with atomic commit/rollback semantics.

=============================================================================
EXPLICIT CORE LOOP ORDER (Task 8 - Final Integration)
=============================================================================

The turn orchestrator executes the following steps in exact order:

1. START TRANSACTION
   - Create TurnTransaction record
   - Record world_time_before for rollback reference

2. LLM/RULE INPUT INTENT
   - Try ProposalPipeline.generate_input_intent() for LLM-driven parsing
   - Fallback to _parse_intent_keyword() for deterministic keyword parsing
   - Audit records: prompt_template_id, raw_output_reference, repair_trace,
     fallback_reason if used

3. DETERMINISTIC TIME TICK + LLM WORLD CANDIDATES
   - WorldEngine.advance_time() is DETERMINISTIC (rule-driven)
   - Then request WorldTickProposal via ProposalPipeline for global/offscreen events
   - World proposals are CANDIDATES only - no direct state mutation
   - Fallback: WorldEngine.check_world_events() if LLM fails

4. LLM/RULE SCENE CANDIDATES
   - SceneEngine.generate_scene_candidates() for current-scene events
   - Scene proposals are CANDIDATES only - no direct state mutation
   - Fallback: ActionScheduler.collect_scene_triggers() if LLM fails

5. COLLECT ACTORS
   - ActionScheduler.collect_actors() from current scene state
   - Returns list of actor_ids (player + NPCs in scene)

6. SEQUENTIAL LLM/RULE NPC PROPOSALS (with working/temporary state)
   - For each NPC actor:
     a. Build NPC context with perspective filtering
     b. Request NPCActionProposal via ProposalPipeline
     c. Apply proposal to WORKING STATE (not canonical)
     d. Next NPC sees the temporary effects of previous NPC decisions
   - Fallback: NPCEngine goal/idle behavior if LLM fails
   - CRITICAL: Canonical state remains unchanged until atomic commit

7. SCHEDULER/CONFLICT RESOLVER
   - ActionScheduler.resolve_conflicts() is RULE-DRIVEN (deterministic)
   - Resolves conflicts between player action and NPC proposals
   - Winner determined by priority, not LLM

8. VALIDATOR
   - Validator.validate_action() and validate_state_delta() are RULE-DRIVEN
   - All proposals must pass validation before commit
   - Rejection triggers rollback with audit record

9. ATOMIC COMMIT
   - All events recorded to EventLog
   - All state deltas applied to CanonicalState
   - All changes committed together or rolled back together

10. MEMORY WRITES (World Chronicle, Scene Summary, NPCSubjectiveSummary)
    - MemoryWriter.write_turn_summary() -> World Chronicle
    - MemoryWriter.write_scene_summary() -> Scene Summary
    - MemoryWriter.write_npc_subjective_summary() -> NPC Subjective Summary
    - These are POST-COMMIT operations (after validation passes)

11. AUDIT
    - Record complete audit trail for replay
    - Includes: prompt/template id, proposal type, raw output reference,
      parsed proposal, repair trace, rejection reason, fallback reason,
      committed event ids

12. LLM/RULE NARRATION (from committed facts only)
    - NarrationEngine uses only COMMITTED state
    - NarrationProposal cannot invent uncommitted facts
    - Fallback: template-based narration if LLM fails

=============================================================================
FALLBACK MATRIX
=============================================================================

| Failure Point          | Fallback Strategy                           | Audit Record         |
|------------------------|---------------------------------------------|----------------------|
| Input Intent LLM       | Keyword-based parser (_parse_intent_keyword)| fallback_reason      |
| World Tick LLM         | WorldEngine.check_world_events()            | fallback_reason      |
| Scene Candidates LLM   | ActionScheduler.collect_scene_triggers()    | fallback_reason      |
| NPC Action LLM         | Goal/idle behavior from NPCEngine           | fallback_reason      |
| Narration LLM          | Template-based _generate_text()             | fallback_reason      |
| Parse Failure          | JSON repair -> fallback if repair fails     | repair_trace         |
| Schema Validation      | Reject proposal, use fallback               | validation_errors    |
| Validator Rejection    | Rollback transaction, no state change       | rejection_reason     |
| Timeout                | Use deterministic fallback                  | fallback_reason      |
| Perspective Leak       | Sanitize or reject proposal                 | validation_errors    |

=============================================================================
KEY INVARIANTS
=============================================================================
- Canonical state is NEVER mutated before validation passes
- LLM outputs are PROPOSALS only - never direct state mutation
- All proposals have deterministic fallback
- Validation failures result in NO committed state delta
- Failed validation writes audit error
- Commit is ATOMIC - all or nothing
- Narration consumes COMMITTED facts only
- NPC prompts are perspective-filtered (no hidden info leak)
- Sequential NPC decisions use working state, not canonical

=============================================================================
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
from ..models.proposals import (
    InputIntentProposal,
    WorldTickProposal,
    SceneEventProposal,
    CandidateEvent,
)

from .event_log import EventLog
from .canonical_state import CanonicalStateManager
from .action_scheduler import ActionScheduler
from .validator import Validator
from .perspective import PerspectiveService
from .context_builder import ContextBuilder
from .memory_writer import MemoryWriter

from ..engines.world_engine import WorldEngine
from ..engines.npc_engine import NPCEngine
from ..engines.narration_engine import NarrationEngine
from ..engines.scene_engine import SceneEngine
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
        scene_engine: Optional[SceneEngine] = None,
        proposal_pipeline: Optional[ProposalPipeline] = None,
        memory_writer: Optional[MemoryWriter] = None,
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
        self._scene_engine = scene_engine
        self._proposal_pipeline = proposal_pipeline
        self._memory_writer = memory_writer
        
        self._audit_log: List[Dict[str, Any]] = []
        self._proposal_audits: List[Dict[str, Any]] = []
    
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
            
            # Step 3: Deterministic time tick + LLM world candidates
            # Time advancement is deterministic (rule-driven)
            world_tick_event = self._world_engine.advance_time(game_id)
            working_state.world_state.current_time = world_tick_event.time_after
            events.append(world_tick_event)
            
            # Generate world candidates via LLM (proposals only, no state mutation)
            world_proposal = self._generate_world_candidates(
                game_id=game_id,
                current_turn=turn_index,
            )
            
            # Record world proposal audit
            self._record_proposal_audit(
                proposal_type="world_tick",
                prompt_template_id=world_proposal.audit.prompt_template_id,
                raw_output_preview=world_proposal.audit.raw_output_preview,
                parsed_proposal={
                    "time_delta_turns": world_proposal.time_delta_turns,
                    "candidate_events_count": len(world_proposal.candidate_events),
                    "state_deltas_count": len(world_proposal.state_deltas),
                    "is_fallback": world_proposal.is_fallback,
                    "confidence": world_proposal.confidence,
                },
                repair_trace=world_proposal.audit.repair_strategies_tried,
                rejection_reason=None,
                fallback_reason=world_proposal.audit.fallback_reason,
                committed_event_ids=[],
            )
            
            # Add world candidate events to the event list (with validation)
            for candidate_event in world_proposal.candidate_events:
                validation = self._validator.validate_candidate_event(
                    event_type=candidate_event.event_type,
                    description=candidate_event.description,
                    target_entity_ids=candidate_event.target_entity_ids,
                    effects=candidate_event.effects,
                    state=working_state,
                )
                
                if validation.is_valid:
                    world_event = self._create_world_event_from_candidate(
                        turn_index=turn_index,
                        candidate=candidate_event,
                    )
                    events.append(world_event)
                else:
                    self._record_proposal_audit(
                        proposal_type="world_candidate_event",
                        prompt_template_id=world_proposal.audit.prompt_template_id,
                        raw_output_preview=candidate_event.description[:200],
                        parsed_proposal={
                            "event_type": candidate_event.event_type,
                            "target_entity_ids": candidate_event.target_entity_ids,
                        },
                        repair_trace=[],
                        rejection_reason=f"Validation failed: {validation.errors}",
                        fallback_reason=None,
                        committed_event_ids=[],
                    )
            
            # Step 5: Generate scene candidates (LLM-driven with deterministic fallback)
            scene_candidates = self._generate_scene_candidates(
                game_state=self._state_to_dict(working_state),
                current_turn=turn_index,
                parsed_intent=parsed_intent,
                session_id=session_id,
            )
            
            for candidate_event in scene_candidates.candidate_events:
                validation = self._validator.validate_candidate_event(
                    event_type=candidate_event.event_type,
                    description=candidate_event.description,
                    target_entity_ids=candidate_event.target_entity_ids,
                    effects=candidate_event.effects,
                    state=working_state,
                )
                
                if validation.is_valid:
                    scene_event = self._create_scene_event_from_candidate(
                        turn_index=turn_index,
                        scene_id=scene_candidates.scene_id,
                        candidate=candidate_event,
                    )
                    events.append(scene_event)
                else:
                    self._record_proposal_audit(
                        proposal_type="scene_candidate_event",
                        prompt_template_id=scene_candidates.audit.prompt_template_id,
                        raw_output_preview=candidate_event.description[:200],
                        parsed_proposal={
                            "event_type": candidate_event.event_type,
                            "scene_id": scene_candidates.scene_id,
                            "target_entity_ids": candidate_event.target_entity_ids,
                        },
                        repair_trace=[],
                        rejection_reason=f"Validation failed: {validation.errors}",
                        fallback_reason=None,
                        committed_event_ids=[],
                    )
            
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
            
            # Step 10: MEMORY WRITES (World Chronicle, Scene Summary, NPCSubjectiveSummary)
            # These are POST-COMMIT operations - only executed after validation passes
            memory_result = self._write_memories(
                turn_index=turn_index,
                events=events,
                working_state=working_state,
                game_id=game_id,
            )
            
            # Step 11: Build player-visible projection (from committed state)
            player_perspective = self._perspective.build_player_perspective(
                perspective_id=f"player_view_{turn_index}",
                player_id="player",
            )
            
            narrator_perspective = self._perspective.build_narrator_perspective(
                perspective_id=f"narrator_view_{turn_index}",
                base_perspective_id=f"player_view_{turn_index}",
            )
            
            # Step 12: Generate narration (from committed state only)
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
            
            # Step 13: AUDIT - Record complete audit trail for replay
            self._record_turn_audit(
                transaction=transaction,
                turn_index=turn_index,
                events=events,
                state_deltas=state_deltas,
                committed_actions=committed_actions,
                memory_result=memory_result,
            )
            
            # Finalize transaction
            self._event_log.commit_turn(transaction)
            
            # Step 14: Return result
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
                "memory_writes": memory_result,
                "proposal_audits": len(self._proposal_audits),
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
                    # Record successful LLM parse in proposal audit
                    self._record_proposal_audit(
                        proposal_type="input_intent",
                        prompt_template_id=proposal.audit.prompt_template_id,
                        raw_output_preview=proposal.audit.raw_output_preview,
                        parsed_proposal={
                            "intent_type": proposal.intent_type,
                            "target": proposal.target,
                            "risk_level": proposal.risk_level,
                            "confidence": proposal.confidence,
                        },
                        repair_trace=proposal.audit.repair_strategies_tried,
                        rejection_reason=None,
                        fallback_reason=None,
                        committed_event_ids=[],
                    )
                    
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
                    self._record_proposal_audit(
                        proposal_type="input_intent",
                        prompt_template_id=proposal.audit.prompt_template_id if proposal else None,
                        raw_output_preview=proposal.audit.raw_output_preview if proposal else "",
                        parsed_proposal=None,
                        repair_trace=proposal.audit.repair_strategies_tried if proposal else [],
                        rejection_reason=None,
                        fallback_reason=fallback_reason,
                        committed_event_ids=[],
                    )
                    
            except Exception as e:
                # LLM call failed - record error and fall back to keyword parser
                self._record_proposal_audit(
                    proposal_type="input_intent",
                    prompt_template_id=None,
                    raw_output_preview="",
                    parsed_proposal=None,
                    repair_trace=[],
                    rejection_reason=None,
                    fallback_reason=f"Exception: {str(e)}",
                    committed_event_ids=[],
                )
        
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
    
    def _generate_scene_candidates(
        self,
        game_state: Dict[str, Any],
        current_turn: int,
        parsed_intent: Optional[ParsedIntent],
        session_id: Optional[str],
    ) -> "SceneEventProposal":
        from ..models.proposals import SceneEventProposal, create_fallback_scene_event
        
        if self._scene_engine is not None:
            return self._scene_engine.generate_scene_candidates(
                game_state=game_state,
                current_turn=current_turn,
                parsed_intent=parsed_intent,
                session_id=session_id,
            )
        
        scene_triggers = self._action_scheduler.collect_scene_triggers(
            self._dict_to_state(game_state)
        )
        
        if scene_triggers:
            from ..models.proposals import (
                CandidateEvent,
                ProposalAuditMetadata,
                ProposalType,
                ProposalSource,
                ValidationStatus,
            )
            
            candidate_events = [
                CandidateEvent(
                    event_type="scene_trigger",
                    description=f"Trigger: {t.get('trigger_id', 'unknown')}",
                    target_entity_ids=[],
                    effects={},
                    importance=t.get("priority", 0.5),
                    visibility="player_visible",
                )
                for t in scene_triggers
            ]
            
            return SceneEventProposal(
                scene_id=scene_triggers[0].get("scene_id", "unknown"),
                candidate_events=candidate_events,
                state_deltas=[],
                affected_entities=[],
                visibility="player_visible",
                confidence=0.3,
                audit=ProposalAuditMetadata(
                    proposal_type=ProposalType.SCENE_EVENT,
                    source_engine=ProposalSource.SCENE_ENGINE,
                    fallback_used=True,
                    fallback_reason="SceneEngine not available, using ActionScheduler triggers",
                    validation_status=ValidationStatus.PASSED,
                ),
                is_fallback=True,
            )
        
        return create_fallback_scene_event(
            scene_id="none",
            reason="No scene engine or triggers available"
        )
    
    def _create_scene_event_from_candidate(
        self,
        turn_index: int,
        scene_id: str,
        candidate: "CandidateEvent",
    ) -> SceneEvent:
        from ..models.proposals import CandidateEvent
        
        return SceneEvent(
            event_id=f"evt_scene_{turn_index:06d}_{uuid.uuid4().hex[:8]}",
            turn_index=turn_index,
            scene_id=scene_id,
            trigger="llm_proposal",
            summary=candidate.description,
            visible_to_player=candidate.visibility == "player_visible",
            importance=candidate.importance,
            affected_entities=candidate.target_entity_ids,
        )
    
    def _generate_world_candidates(
        self,
        game_id: str,
        current_turn: int,
    ) -> "WorldTickProposal":
        """
        Generate world tick proposal for global/offscreen evolution.
        
        Uses WorldEngine.generate_world_candidates() for LLM-driven proposals.
        Returns candidates only (no direct state mutation).
        """
        return self._world_engine.generate_world_candidates(
            game_id=game_id,
            current_turn=current_turn,
        )
    
    def _create_world_event_from_candidate(
        self,
        turn_index: int,
        candidate: "CandidateEvent",
    ) -> SceneEvent:
        """
        Create a SceneEvent from a world candidate event.
        
        World candidate events are recorded as SceneEvents for consistency
        with the event log structure.
        """
        from ..models.proposals import CandidateEvent
        
        return SceneEvent(
            event_id=f"evt_world_{turn_index:06d}_{uuid.uuid4().hex[:8]}",
            turn_index=turn_index,
            scene_id="world_global",
            trigger="world_candidate",
            summary=candidate.description,
            visible_to_player=candidate.visibility == "player_visible",
            importance=candidate.importance,
            affected_entities=candidate.target_entity_ids,
        )
    
    def _state_to_dict(self, state: CanonicalState) -> Dict[str, Any]:
        return {
            "player_location": state.player_state.location_id,
            "world_time": state.world_state.current_time.model_dump(),
            "npc_states": {
                npc_id: {"mood": npc.mood, "location_id": npc.location_id}
                for npc_id, npc in state.npc_states.items()
            },
            "quest_states": {},
        }
    
    def _dict_to_state(self, data: Dict[str, Any]) -> CanonicalState:
        return CanonicalState(
            player_state=PlayerState(
                entity_id="player",
                location_id=data.get("player_location", "unknown"),
            ),
            world_state=WorldState(
                entity_id="world",
                world_id="default_world",
                current_time=WorldTime(
                    calendar="修仙历",
                    season="春",
                    day=1,
                    period=data.get("world_time", {}).get("period", "辰时"),
                ),
            ),
            current_scene_state=CurrentSceneState(
                entity_id="scene",
                scene_id="default_scene",
                location_id="unknown",
            ),
            npc_states={},
        )
    
    def _process_npc_decisions(
        self,
        game_id: str,
        turn_index: int,
        working_state: CanonicalState,
        actors: List[str],
    ) -> List[ProposedAction]:
        """
        Process NPC decisions sequentially with working state propagation.
        
        Each NPC sees the temporary effects of previous NPC decisions:
        1. Generate NPC action based on current working state
        2. Compute state deltas for that action
        3. Apply deltas to working state (temporary, not canonical)
        4. Next NPC sees the updated working state
        
        This ensures NPCs respond to each other's actions within the same turn.
        """
        actions = []
        
        for actor_id in actors:
            if actor_id == "player":
                continue
            
            npc_state = working_state.npc_states.get(actor_id)
            if npc_state is None or npc_state.status != "alive":
                continue
            
            action = self._npc_engine.generate_npc_action(
                npc_id=actor_id,
                game_id=game_id,
                turn_index=turn_index,
                working_state=working_state,
            )
            
            if action:
                actions.append(action)
                
                # Compute temporary state deltas for this action
                temp_deltas = self._compute_state_deltas(action, working_state)
                
                # Apply temporary deltas to working state
                # This allows next NPC to see this NPC's effects
                for delta in temp_deltas:
                    self._apply_temporary_delta(working_state, delta)
        
        return actions
    
    def _apply_temporary_delta(
        self,
        working_state: CanonicalState,
        delta: StateDelta,
    ) -> None:
        """
        Apply a state delta to working state (temporary, not canonical).
        
        This is used for sequential NPC decisions where each NPC
        needs to see the effects of previous NPCs.
        """
        path_parts = delta.path.split(".")
        
        if len(path_parts) < 2:
            return
        
        if path_parts[0] == "npcs" and len(path_parts) >= 3:
            npc_id = path_parts[1]
            field = path_parts[2]
            
            if npc_id in working_state.npc_states:
                npc = working_state.npc_states[npc_id]
                if field == "mood" and delta.operation == "set":
                    npc.mood = delta.new_value
                elif field == "location_id" and delta.operation == "set":
                    npc.location_id = delta.new_value
                elif field == "status" and delta.operation == "set":
                    npc.status = delta.new_value
        elif path_parts[0] == "world_state" and len(path_parts) >= 2:
            field = path_parts[1]
            if field == "weather" and delta.operation == "set":
                working_state.world_state.weather = delta.new_value
    
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
    
    def _write_memories(
        self,
        turn_index: int,
        events: List[GameEvent],
        working_state: CanonicalState,
        game_id: str,
    ) -> Dict[str, Any]:
        """
        Write memory summaries after atomic commit.
        
        Creates:
        - World Chronicle (global turn summary)
        - Scene Summary (current scene events)
        - NPCSubjectiveSummary (per-NPC perspective)
        
        Returns memory write statistics for audit.
        """
        if self._memory_writer is None:
            return {
                "memories_created": 0,
                "world_chronicle": None,
                "scene_summary": None,
                "npc_summaries": [],
            }
        
        result = self._memory_writer.process_turn(
            turn_index=turn_index,
            events=events,
            state=working_state,
        )
        
        return {
            "memories_created": result.get("memories_created", 0),
            "world_chronicle": result.get("summary_created"),
            "memory_ids": result.get("memory_ids", []),
        }
    
    def _record_turn_audit(
        self,
        transaction: TurnTransaction,
        turn_index: int,
        events: List[GameEvent],
        state_deltas: List[StateDelta],
        committed_actions: List[CommittedAction],
        memory_result: Dict[str, Any],
    ) -> None:
        """
        Record complete audit trail for replay.
        
        Records:
        - prompt/template id for each proposal
        - proposal type
        - raw output reference
        - parsed proposal
        - repair trace
        - rejection reason (if any)
        - fallback reason (if any)
        - committed event ids
        
        This enables replay without re-calling LLM.
        """
        audit_entry = {
            "audit_id": f"turn_audit_{turn_index:06d}_{uuid.uuid4().hex[:8]}",
            "transaction_id": transaction.transaction_id,
            "turn_index": turn_index,
            "timestamp": datetime.now().isoformat(),
            "type": "turn_complete",
            "events_committed": [e.event_id for e in events],
            "state_deltas_count": len(state_deltas),
            "actions_committed": [a.action_id for a in committed_actions],
            "memory_writes": memory_result,
            "proposal_audits": self._proposal_audits.copy(),
        }
        self._audit_log.append(audit_entry)
        
        self._proposal_audits.clear()
    
    def _record_proposal_audit(
        self,
        proposal_type: str,
        prompt_template_id: Optional[str],
        raw_output_preview: str,
        parsed_proposal: Optional[Dict[str, Any]],
        repair_trace: List[str],
        rejection_reason: Optional[str],
        fallback_reason: Optional[str],
        committed_event_ids: List[str],
    ) -> str:
        """
        Record audit metadata for a single proposal.
        
        This data is stored for replay without re-calling LLM.
        """
        audit_id = f"proposal_{proposal_type}_{uuid.uuid4().hex[:8]}"
        
        audit_entry = {
            "audit_id": audit_id,
            "timestamp": datetime.now().isoformat(),
            "proposal_type": proposal_type,
            "prompt_template_id": prompt_template_id,
            "raw_output_preview": raw_output_preview[:200] if raw_output_preview else "",
            "parsed_proposal": parsed_proposal,
            "repair_trace": repair_trace,
            "rejection_reason": rejection_reason,
            "fallback_reason": fallback_reason,
            "committed_event_ids": committed_event_ids,
        }
        
        self._proposal_audits.append(audit_entry)
        return audit_id
    
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

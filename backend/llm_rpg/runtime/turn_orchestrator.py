"""
Turn Orchestrator

DEPRECATED: This module is NOT the active production gameplay path.

The authoritative turn execution is handled by:
- `llm_rpg.core.turn_service.execute_turn_service()` - single durable turn boundary
- `llm_rpg.api.game` - production game endpoints
- `llm_rpg.api.streaming` - streaming turn endpoints

This file remains for reference only. Do not use for new gameplay features.
All turn execution must go through execute_turn_service() to ensure:
- DB-authoritative state persistence
- LLM stage evidence tracking
- Proper audit logging
- Transaction atomicity

Explicit runtime boundary for turn pipeline orchestration.
Coordinates the 12-step turn transaction process.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from copy import deepcopy


class TurnOrchestrator:
    """
    Orchestrates the deterministic turn transaction pipeline.
    
    This is the explicit runtime boundary that coordinates:
    1. Input recording
    2. Intent parsing
    3. Canonical state reading
    4. World tick
    5. Action scheduling
    6. NPC decision loop
    7. Conflict resolution
    8. Validation
    9. Atomic commit
    10. Player-visible projection
    11. Narration generation
    12. Result return
    
    Key invariants:
    - Canonical state is never mutated before validation
    - Validation failures result in no committed state delta
    - Commit is atomic - all or nothing
    """
    
    def __init__(self):
        self._step_handlers: Dict[int, List[callable]] = {i: [] for i in range(1, 13)}
        self._validation_handlers: List[callable] = []
        self._commit_handlers: List[callable] = []
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_size = 1000
    
    def execute_turn(
        self,
        session_id: str,
        game_id: str,
        turn_index: int,
        player_input: str,
        state_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a complete turn transaction through all 12 steps.
        
        Args:
            session_id: The session ID
            game_id: The game ID
            turn_index: Current turn index
            player_input: Player's raw input
            state_context: Current state context
            
        Returns:
            Turn execution result
        """
        transaction_id = f"turn_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        try:
            # Step 1: Record input
            step1_result = self._execute_step(1, {
                "transaction_id": transaction_id,
                "session_id": session_id,
                "game_id": game_id,
                "turn_index": turn_index,
                "player_input": player_input,
            })
            
            # Step 2: Parse intent
            step2_result = self._execute_step(2, {
                "transaction_id": transaction_id,
                "input": player_input,
            })
            parsed_intent = step2_result.get("intent", {})
            
            # Step 3: Read canonical state
            step3_result = self._execute_step(3, {
                "transaction_id": transaction_id,
                "game_id": game_id,
                "state_context": state_context,
            })
            working_state = step3_result.get("working_state", {})
            
            # Step 4: World tick
            step4_result = self._execute_step(4, {
                "transaction_id": transaction_id,
                "working_state": working_state,
                "turn_index": turn_index,
            })
            
            # Step 5: Action scheduling
            step5_result = self._execute_step(5, {
                "transaction_id": transaction_id,
                "working_state": working_state,
                "parsed_intent": parsed_intent,
            })
            proposed_actions = step5_result.get("actions", [])
            
            # Step 6: NPC decision loop
            step6_result = self._execute_step(6, {
                "transaction_id": transaction_id,
                "working_state": working_state,
                "game_id": game_id,
            })
            npc_actions = step6_result.get("npc_actions", [])
            proposed_actions.extend(npc_actions)
            
            # Step 7: Conflict resolution
            step7_result = self._execute_step(7, {
                "transaction_id": transaction_id,
                "actions": proposed_actions,
                "working_state": working_state,
            })
            resolved_actions = step7_result.get("resolved_actions", [])
            
            # Step 8: Validation
            validation_result = self._execute_validation({
                "transaction_id": transaction_id,
                "actions": resolved_actions,
                "working_state": working_state,
            })
            
            if not validation_result.get("valid", False):
                self._record_audit(transaction_id, "validation_failed", validation_result)
                return {
                    "transaction_id": transaction_id,
                    "turn_index": turn_index,
                    "success": False,
                    "error": validation_result.get("errors", ["Validation failed"]),
                    "narration": "Invalid action.",
                }
            
            # Step 9: Atomic commit
            commit_result = self._execute_commit({
                "transaction_id": transaction_id,
                "actions": resolved_actions,
                "working_state": working_state,
                "game_id": game_id,
            })
            
            # Step 10: Build player-visible projection
            step10_result = self._execute_step(10, {
                "transaction_id": transaction_id,
                "working_state": working_state,
            })
            
            # Step 11: Generate narration
            step11_result = self._execute_step(11, {
                "transaction_id": transaction_id,
                "working_state": working_state,
                "actions": resolved_actions,
            })
            narration = step11_result.get("narration", "")
            
            # Step 12: Return result
            end_time = datetime.now()
            latency_ms = (end_time - start_time).total_seconds() * 1000
            
            result = {
                "transaction_id": transaction_id,
                "turn_index": turn_index,
                "success": True,
                "narration": narration,
                "actions_committed": len(resolved_actions),
                "world_time": working_state.get("world_time", {}),
                "latency_ms": latency_ms,
            }
            
            self._record_audit(transaction_id, "completed", result)
            return result
            
        except Exception as e:
            self._record_audit(transaction_id, "failed", {"error": str(e)})
            return {
                "transaction_id": transaction_id,
                "turn_index": turn_index,
                "success": False,
                "error": str(e),
                "narration": "An error occurred.",
            }
    
    def register_step_handler(self, step: int, handler: callable) -> None:
        """Register a handler for a specific step."""
        if 1 <= step <= 12:
            self._step_handlers[step].append(handler)
    
    def register_validation_handler(self, handler: callable) -> None:
        """Register a validation handler."""
        self._validation_handlers.append(handler)
    
    def register_commit_handler(self, handler: callable) -> None:
        """Register a commit handler."""
        self._commit_handlers.append(handler)
    
    def _execute_step(self, step: int, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a pipeline step with registered handlers."""
        result = context.copy()
        
        for handler in self._step_handlers[step]:
            handler_result = handler(context)
            if handler_result:
                result.update(handler_result)
        
        return result
    
    def _execute_validation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute validation with registered handlers."""
        errors = []
        warnings = []
        
        for handler in self._validation_handlers:
            validation = handler(context)
            if validation:
                errors.extend(validation.get("errors", []))
                warnings.extend(validation.get("warnings", []))
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
    
    def _execute_commit(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute commit with registered handlers."""
        results = []
        
        for handler in self._commit_handlers:
            result = handler(context)
            results.append(result)
        
        return {
            "committed": True,
            "handler_results": results,
        }
    
    def _record_audit(self, transaction_id: str, status: str, details: Dict[str, Any]) -> None:
        """Record audit log entry."""
        entry = {
            "transaction_id": transaction_id,
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "details": details,
        }
        self._audit_log.append(entry)
        
        if len(self._audit_log) > self._max_audit_size:
            self._audit_log = self._audit_log[-self._max_audit_size:]
    
    def get_audit_log(self, transaction_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get audit log, optionally filtered by transaction ID."""
        if transaction_id:
            return [entry for entry in self._audit_log 
                    if entry.get("transaction_id") == transaction_id]
        return self._audit_log.copy()
    
    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self._audit_log.clear()

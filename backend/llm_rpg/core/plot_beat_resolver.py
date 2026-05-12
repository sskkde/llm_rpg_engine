"""Plot Beat Resolver - Evaluates plot beat conditions against game context.

This module provides the PlotBeatResolver class which evaluates whether
plot beats are eligible to trigger based on game state and conditions.
"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..models.content_pack import (
    CONDITIONS,
    PlotBeatCondition,
    PlotBeatDefinition,
)


class ConditionEvaluation(BaseModel):
    """Result of evaluating a single condition."""
    condition_type: str = Field(..., description="Type of condition evaluated")
    passed: bool = Field(..., description="Whether condition passed")
    reason: str = Field(..., description="Explanation of pass/failure")


class EvaluatedPlotBeat(BaseModel):
    """Result of evaluating a plot beat's eligibility."""
    beat_id: str = Field(..., description="ID of the evaluated plot beat")
    eligible: bool = Field(..., description="Whether the beat is eligible to trigger")
    condition_evaluations: List[ConditionEvaluation] = Field(
        default_factory=list,
        description="Evaluation result for each condition"
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="Summary reasons for eligibility status"
    )


class PlotBeatResolver:
    """Resolves plot beat eligibility based on game context.
    
    This class is stateless - it takes a beat definition and context,
    evaluates all conditions, and returns an evaluation result.
    
    Context dict should contain:
    - state: Dict[str, Any] - Game state variables
    - known_facts: List[str] - Facts known to the evaluating entity
    - quest_stages: Dict[str, int] - Current stage for each quest
    - npc_presence: List[str] - NPCs present in current scene
    - current_location: str - Current location ID
    """
    
    def evaluate(
        self,
        beat: PlotBeatDefinition,
        context: Dict[str, Any],
    ) -> EvaluatedPlotBeat:
        """Evaluate a plot beat against the provided context.
        
        Args:
            beat: The plot beat definition to evaluate
            context: Game context containing state, facts, quest stages, etc.
            
        Returns:
            EvaluatedPlotBeat with eligibility status and reasons
        """
        evaluations: List[ConditionEvaluation] = []
        
        # Extract context components with defaults
        state = context.get("state", {})
        known_facts = context.get("known_facts", [])
        quest_stages = context.get("quest_stages", {})
        npc_presence = context.get("npc_presence", [])
        current_location = context.get("current_location", "")
        
        # Evaluate each condition
        for condition in beat.conditions:
            evaluation = self._evaluate_condition(
                condition,
                state=state,
                known_facts=known_facts,
                quest_stages=quest_stages,
                npc_presence=npc_presence,
                current_location=current_location,
            )
            evaluations.append(evaluation)
        
        # Determine overall eligibility
        all_passed = all(e.passed for e in evaluations) if evaluations else True
        
        # Build summary reasons
        reasons: List[str] = []
        if not beat.conditions:
            reasons.append("No conditions - always eligible")
        elif all_passed:
            reasons.append(f"All {len(evaluations)} conditions passed")
        else:
            failed_count = sum(1 for e in evaluations if not e.passed)
            reasons.append(f"{failed_count} of {len(evaluations)} conditions failed")
            for e in evaluations:
                if not e.passed:
                    reasons.append(f"  - {e.condition_type}: {e.reason}")
        
        return EvaluatedPlotBeat(
            beat_id=beat.id,
            eligible=all_passed,
            condition_evaluations=evaluations,
            reasons=reasons,
        )
    
    def _evaluate_condition(
        self,
        condition: PlotBeatCondition,
        state: Dict[str, Any],
        known_facts: List[str],
        quest_stages: Dict[str, int],
        npc_presence: List[str],
        current_location: str,
    ) -> ConditionEvaluation:
        """Evaluate a single condition against context.
        
        Args:
            condition: The condition to evaluate
            state, known_facts, quest_stages, npc_presence, current_location:
                Context components for evaluation
                
        Returns:
            ConditionEvaluation with pass/fail status and reason
        """
        # Check if condition type is known
        if condition.type not in CONDITIONS:
            return ConditionEvaluation(
                condition_type=condition.type,
                passed=False,
                reason=f"Unknown condition type: {condition.type}",
            )
        
        # Dispatch to specific evaluator
        if condition.type == "fact_known":
            return self._evaluate_fact_known(condition, known_facts)
        elif condition.type == "state_equals":
            return self._evaluate_state_equals(condition, state)
        elif condition.type == "state_in":
            return self._evaluate_state_in(condition, state)
        elif condition.type == "quest_stage":
            return self._evaluate_quest_stage(condition, quest_stages)
        elif condition.type == "npc_present":
            return self._evaluate_npc_present(condition, npc_presence)
        elif condition.type == "location_is":
            return self._evaluate_location_is(condition, current_location)
        else:
            # Should not reach here if CONDITIONS is exhaustive
            return ConditionEvaluation(
                condition_type=condition.type,
                passed=False,
                reason=f"Condition type {condition.type} not implemented",
            )
    
    def _evaluate_fact_known(
        self,
        condition: PlotBeatCondition,
        known_facts: List[str],
    ) -> ConditionEvaluation:
        """Check if a fact is known."""
        fact_id = condition.params.get("fact_id")
        if not fact_id:
            return ConditionEvaluation(
                condition_type="fact_known",
                passed=False,
                reason="Missing 'fact_id' parameter",
            )
        
        if fact_id in known_facts:
            return ConditionEvaluation(
                condition_type="fact_known",
                passed=True,
                reason=f"Fact '{fact_id}' is known",
            )
        else:
            return ConditionEvaluation(
                condition_type="fact_known",
                passed=False,
                reason=f"Fact '{fact_id}' is not known",
            )
    
    def _evaluate_state_equals(
        self,
        condition: PlotBeatCondition,
        state: Dict[str, Any],
    ) -> ConditionEvaluation:
        """Check if a state variable equals a specific value."""
        key = condition.params.get("key")
        value = condition.params.get("value")
        
        if not key:
            return ConditionEvaluation(
                condition_type="state_equals",
                passed=False,
                reason="Missing 'key' parameter",
            )
        
        if key not in state:
            return ConditionEvaluation(
                condition_type="state_equals",
                passed=False,
                reason=f"State key '{key}' not found",
            )
        
        if state[key] == value:
            return ConditionEvaluation(
                condition_type="state_equals",
                passed=True,
                reason=f"State['{key}'] == {value!r}",
            )
        else:
            return ConditionEvaluation(
                condition_type="state_equals",
                passed=False,
                reason=f"State['{key}'] = {state[key]!r}, expected {value!r}",
            )
    
    def _evaluate_state_in(
        self,
        condition: PlotBeatCondition,
        state: Dict[str, Any],
    ) -> ConditionEvaluation:
        """Check if a state variable is in a set of values."""
        key = condition.params.get("key")
        values = condition.params.get("values", [])
        
        if not key:
            return ConditionEvaluation(
                condition_type="state_in",
                passed=False,
                reason="Missing 'key' parameter",
            )
        
        if not isinstance(values, list):
            return ConditionEvaluation(
                condition_type="state_in",
                passed=False,
                reason="'values' parameter must be a list",
            )
        
        if key not in state:
            return ConditionEvaluation(
                condition_type="state_in",
                passed=False,
                reason=f"State key '{key}' not found",
            )
        
        if state[key] in values:
            return ConditionEvaluation(
                condition_type="state_in",
                passed=True,
                reason=f"State['{key}'] = {state[key]!r} is in {values!r}",
            )
        else:
            return ConditionEvaluation(
                condition_type="state_in",
                passed=False,
                reason=f"State['{key}'] = {state[key]!r} not in {values!r}",
            )
    
    def _evaluate_quest_stage(
        self,
        condition: PlotBeatCondition,
        quest_stages: Dict[str, int],
    ) -> ConditionEvaluation:
        """Check if a quest is at a specific stage."""
        quest_id = condition.params.get("quest_id")
        stage = condition.params.get("stage")
        
        if not quest_id:
            return ConditionEvaluation(
                condition_type="quest_stage",
                passed=False,
                reason="Missing 'quest_id' parameter",
            )
        
        if stage is None:
            return ConditionEvaluation(
                condition_type="quest_stage",
                passed=False,
                reason="Missing 'stage' parameter",
            )
        
        current_stage = quest_stages.get(quest_id)
        if current_stage is None:
            return ConditionEvaluation(
                condition_type="quest_stage",
                passed=False,
                reason=f"Quest '{quest_id}' not found in quest_stages",
            )
        
        if current_stage == stage:
            return ConditionEvaluation(
                condition_type="quest_stage",
                passed=True,
                reason=f"Quest '{quest_id}' is at stage {stage}",
            )
        else:
            return ConditionEvaluation(
                condition_type="quest_stage",
                passed=False,
                reason=f"Quest '{quest_id}' is at stage {current_stage}, expected {stage}",
            )
    
    def _evaluate_npc_present(
        self,
        condition: PlotBeatCondition,
        npc_presence: List[str],
    ) -> ConditionEvaluation:
        """Check if an NPC is present in the current scene."""
        npc_id = condition.params.get("npc_id")
        
        if not npc_id:
            return ConditionEvaluation(
                condition_type="npc_present",
                passed=False,
                reason="Missing 'npc_id' parameter",
            )
        
        if npc_id in npc_presence:
            return ConditionEvaluation(
                condition_type="npc_present",
                passed=True,
                reason=f"NPC '{npc_id}' is present",
            )
        else:
            return ConditionEvaluation(
                condition_type="npc_present",
                passed=False,
                reason=f"NPC '{npc_id}' is not present",
            )
    
    def _evaluate_location_is(
        self,
        condition: PlotBeatCondition,
        current_location: str,
    ) -> ConditionEvaluation:
        """Check if the current location matches."""
        location_id = condition.params.get("location_id")
        
        if not location_id:
            return ConditionEvaluation(
                condition_type="location_is",
                passed=False,
                reason="Missing 'location_id' parameter",
            )
        
        if current_location == location_id:
            return ConditionEvaluation(
                condition_type="location_is",
                passed=True,
                reason=f"Current location is '{location_id}'",
            )
        else:
            return ConditionEvaluation(
                condition_type="location_is",
                passed=False,
                reason=f"Current location is '{current_location}', expected '{location_id}'",
            )

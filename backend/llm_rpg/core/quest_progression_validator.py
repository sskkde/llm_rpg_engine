"""Quest Progression Validator - Validates quest stage transitions.

This module provides the QuestProgressionValidator class which validates
that quest progression effects are legal based on current game state.
"""

from typing import Any, Dict, List, Optional

from ..models.common import ValidationCheck, ValidationResult
from ..models.content_pack import EFFECTS, PlotBeatEffect, PlotBeatVisibility


class QuestProgressionValidator:
    """Validates quest progression transitions and effects.
    
    This validator ensures that:
    - Quest stage transitions are legal (from_stage matches current)
    - Target stages exist in quest definitions
    - Hidden plot beats are not player-visible
    - Unknown effect types are rejected
    """
    
    def validate_transition(
        self,
        effect: PlotBeatEffect,
        current_quest_state: Dict[str, Any],
        quest_definition: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Validate a quest transition effect.
        
        Args:
            effect: The effect to validate
            current_quest_state: Current quest state containing:
                - quest_id: str
                - current_stage: int
                - (other quest metadata)
            quest_definition: Optional quest definition containing:
                - stages: List[int] or Dict with stage info
                - (other quest definition data)
                
        Returns:
            ValidationResult with pass/fail status and reasons
        """
        checks: List[ValidationCheck] = []
        errors: List[str] = []
        warnings: List[str] = []
        
        # Check effect type is known
        type_check = self._validate_effect_type(effect)
        checks.append(type_check)
        if not type_check.passed:
            errors.append(type_check.reason)
            return ValidationResult(
                is_valid=False,
                checks=checks,
                errors=errors,
                warnings=warnings,
            )
        
        # For advance_quest, validate stage transition
        if effect.type == "advance_quest":
            transition_check = self._validate_quest_stage_transition(
                effect, current_quest_state, quest_definition
            )
            checks.append(transition_check)
            if not transition_check.passed:
                errors.append(transition_check.reason)
        
        # Validate effect parameters
        params_check = self._validate_effect_params(effect)
        checks.append(params_check)
        if not params_check.passed:
            errors.append(params_check.reason)
        
        return ValidationResult(
            is_valid=all(c.passed for c in checks),
            checks=checks,
            errors=errors,
            warnings=warnings,
        )
    
    def validate_visibility_constraint(
        self,
        visibility: PlotBeatVisibility,
        is_player_visible: bool,
    ) -> ValidationResult:
        """Validate that hidden plot beats are not player-visible.
        
        Args:
            visibility: The plot beat's visibility level
            is_player_visible: Whether the beat is marked as player-visible
            
        Returns:
            ValidationResult indicating if the constraint is satisfied
        """
        checks: List[ValidationCheck] = []
        errors: List[str] = []
        
        if visibility == PlotBeatVisibility.HIDDEN and is_player_visible:
            check = ValidationCheck(
                check_name="visibility_constraint",
                passed=False,
                reason="Hidden plot beats must not be player-visible",
                severity="error",
            )
            checks.append(check)
            errors.append(check.reason)
        else:
            checks.append(ValidationCheck(
                check_name="visibility_constraint",
                passed=True,
            ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            checks=checks,
            errors=errors,
        )
    
    def validate_effect_type_whitelist(
        self,
        effect: PlotBeatEffect,
    ) -> ValidationResult:
        """Validate that effect type is in whitelist.
        
        Args:
            effect: The effect to validate
            
        Returns:
            ValidationResult indicating if effect type is valid
        """
        checks: List[ValidationCheck] = []
        errors: List[str] = []
        
        if effect.type not in EFFECTS:
            check = ValidationCheck(
                check_name="effect_type_whitelist",
                passed=False,
                reason=f"Unknown effect type: {effect.type}",
                severity="error",
            )
            checks.append(check)
            errors.append(check.reason)
        else:
            checks.append(ValidationCheck(
                check_name="effect_type_whitelist",
                passed=True,
            ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            checks=checks,
            errors=errors,
        )
    
    def _validate_effect_type(self, effect: PlotBeatEffect) -> ValidationCheck:
        """Check if effect type is known."""
        if effect.type not in EFFECTS:
            return ValidationCheck(
                check_name="effect_type",
                passed=False,
                reason=f"Unknown effect type: {effect.type}",
                severity="error",
            )
        return ValidationCheck(
            check_name="effect_type",
            passed=True,
        )
    
    def _validate_quest_stage_transition(
        self,
        effect: PlotBeatEffect,
        current_quest_state: Dict[str, Any],
        quest_definition: Optional[Dict[str, Any]],
    ) -> ValidationCheck:
        """Validate quest stage transition logic.
        
        Args:
            effect: The advance_quest effect
            current_quest_state: Current quest state
            quest_definition: Quest definition with stage info
            
        Returns:
            ValidationCheck with transition validation result
        """
        params = effect.params
        
        quest_id = params.get("quest_id")
        from_stage = params.get("from_stage")
        to_stage = params.get("to_stage")
        
        if not quest_id:
            return ValidationCheck(
                check_name="quest_transition",
                passed=False,
                reason="Missing 'quest_id' in advance_quest effect",
            )
        
        if from_stage is None:
            return ValidationCheck(
                check_name="quest_transition",
                passed=False,
                reason="Missing 'from_stage' in advance_quest effect",
            )
        
        if to_stage is None:
            return ValidationCheck(
                check_name="quest_transition",
                passed=False,
                reason="Missing 'to_stage' in advance_quest effect",
            )
        
        # Check if current quest state matches
        current_quest_id = current_quest_state.get("quest_id")
        current_stage = current_quest_state.get("current_stage")
        
        if current_quest_id != quest_id:
            return ValidationCheck(
                check_name="quest_transition",
                passed=False,
                reason=f"Quest ID mismatch: effect targets '{quest_id}', current state is '{current_quest_id}'",
            )
        
        if current_stage != from_stage:
            return ValidationCheck(
                check_name="quest_transition",
                passed=False,
                reason=f"Stage mismatch: effect expects stage {from_stage}, current is {current_stage}",
            )
        
        # Check if to_stage exists in quest definition
        if quest_definition:
            stages = quest_definition.get("stages", [])
            if isinstance(stages, list):
                if to_stage not in stages:
                    return ValidationCheck(
                        check_name="quest_transition",
                        passed=False,
                        reason=f"Target stage {to_stage} does not exist in quest definition",
                    )
            elif isinstance(stages, dict):
                if str(to_stage) not in stages and to_stage not in stages:
                    return ValidationCheck(
                        check_name="quest_transition",
                        passed=False,
                        reason=f"Target stage {to_stage} does not exist in quest definition",
                    )
        
        return ValidationCheck(
            check_name="quest_transition",
            passed=True,
            reason=f"Valid transition: quest '{quest_id}' stage {from_stage} -> {to_stage}",
        )
    
    def _validate_effect_params(self, effect: PlotBeatEffect) -> ValidationCheck:
        """Validate effect has required parameters.
        
        Args:
            effect: The effect to validate
            
        Returns:
            ValidationCheck with params validation result
        """
        required_params = {
            "add_known_fact": ["fact_id"],
            "advance_quest": ["quest_id", "from_stage", "to_stage"],
            "set_state": ["key", "value"],
            "emit_event": ["event_type"],
            "change_relationship": ["faction_id", "delta"],
            "add_memory": ["content"],
        }
        
        if effect.type not in required_params:
            return ValidationCheck(
                check_name="effect_params",
                passed=True,
            )
        
        missing = []
        for param in required_params[effect.type]:
            if param not in effect.params:
                missing.append(param)
        
        if missing:
            return ValidationCheck(
                check_name="effect_params",
                passed=False,
                reason=f"Missing required params for {effect.type}: {missing}",
            )
        
        return ValidationCheck(
            check_name="effect_params",
            passed=True,
        )

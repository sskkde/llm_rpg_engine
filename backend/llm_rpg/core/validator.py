from typing import Any, Dict, List, Optional

from ..models.common import ProposedAction, ValidationCheck, ValidationResult
from ..models.states import CanonicalState
from ..models.perspectives import Perspective
from ..models.lore import LoreEntry


class Validator:
    
    def __init__(self):
        self._rules: Dict[str, callable] = {}
    
    def register_rule(self, rule_name: str, rule_func: callable) -> None:
        self._rules[rule_name] = rule_func
    
    def validate_action(
        self,
        action: ProposedAction,
        state: CanonicalState,
        perspective: Optional[Perspective] = None,
    ) -> ValidationResult:
        checks = []
        errors = []
        warnings = []
        
        rule_check = self._validate_rules(action, state)
        checks.append(rule_check)
        if not rule_check.passed:
            errors.append(rule_check.reason)
        
        state_check = self._validate_state(action, state)
        checks.append(state_check)
        if not state_check.passed:
            errors.append(state_check.reason)
        
        if perspective:
            perspective_check = self._validate_perspective(action, perspective, state)
            checks.append(perspective_check)
            if not perspective_check.passed:
                errors.append(perspective_check.reason)
        
        lore_check = self._validate_lore(action, state)
        checks.append(lore_check)
        if not lore_check.passed:
            warnings.append(lore_check.reason)
        
        return ValidationResult(
            is_valid=all(c.passed for c in checks),
            checks=checks,
            errors=errors,
            warnings=warnings,
        )
    
    def _validate_rules(
        self,
        action: ProposedAction,
        state: CanonicalState,
    ) -> ValidationCheck:
        actor_id = action.actor_id
        
        if actor_id != "player":
            npc_state = state.npc_states.get(actor_id)
            if npc_state and npc_state.status == "dead":
                return ValidationCheck(
                    check_name="rule_validation",
                    passed=False,
                    reason=f"NPC {actor_id} is dead and cannot perform actions",
                )
        
        if action.action_type == "use_item":
            if not action.target_ids:
                return ValidationCheck(
                    check_name="rule_validation",
                    passed=False,
                    reason="Item use requires a target",
                )
        
        return ValidationCheck(
            check_name="rule_validation",
            passed=True,
        )
    
    def _validate_state(
        self,
        action: ProposedAction,
        state: CanonicalState,
    ) -> ValidationCheck:
        if action.target_ids:
            for target_id in action.target_ids:
                if target_id.startswith("npc_"):
                    if target_id not in state.npc_states:
                        return ValidationCheck(
                            check_name="state_validation",
                            passed=False,
                            reason=f"Target NPC {target_id} not found",
                        )
                elif target_id.startswith("loc_"):
                    if target_id not in state.location_states:
                        return ValidationCheck(
                            check_name="state_validation",
                            passed=False,
                            reason=f"Target location {target_id} not found",
                        )
        
        return ValidationCheck(
            check_name="state_validation",
            passed=True,
        )
    
    def _validate_perspective(
        self,
        action: ProposedAction,
        perspective: Perspective,
        state: CanonicalState,
    ) -> ValidationCheck:
        from ..models.perspectives import NPCPerspective
        
        if isinstance(perspective, NPCPerspective):
            npc_id = perspective.npc_id
            npc_state = state.npc_states.get(npc_id)
            
            if npc_state:
                scene_state = state.current_scene_state
                if npc_state.location_id != scene_state.location_id:
                    return ValidationCheck(
                        check_name="perspective_validation",
                        passed=False,
                        reason=f"NPC {npc_id} is not in the current scene",
                    )
        
        return ValidationCheck(
            check_name="perspective_validation",
            passed=True,
        )
    
    def _validate_lore(
        self,
        action: ProposedAction,
        state: CanonicalState,
    ) -> ValidationCheck:
        return ValidationCheck(
            check_name="lore_validation",
            passed=True,
        )
    
    def validate_state_delta(
        self,
        delta_path: str,
        old_value: Any,
        new_value: Any,
        state: CanonicalState,
    ) -> ValidationResult:
        checks = []
        errors = []
        
        parts = delta_path.split(".")
        if len(parts) < 2:
            return ValidationResult(
                is_valid=False,
                checks=[ValidationCheck(
                    check_name="path_validation",
                    passed=False,
                    reason=f"Invalid delta path: {delta_path}",
                )],
                errors=[f"Invalid delta path: {delta_path}"],
            )
        
        if "hp" in delta_path and isinstance(new_value, (int, float)):
            if new_value < 0:
                checks.append(ValidationCheck(
                    check_name="value_validation",
                    passed=False,
                    reason="HP cannot be negative",
                ))
                errors.append("HP cannot be negative")
            else:
                checks.append(ValidationCheck(
                    check_name="value_validation",
                    passed=True,
                ))
        else:
            checks.append(ValidationCheck(
                check_name="value_validation",
                passed=True,
            ))
        
        return ValidationResult(
            is_valid=all(c.passed for c in checks),
            checks=checks,
            errors=errors,
        )
    
    def validate_narration(
        self,
        text: str,
        forbidden_info: List[str],
    ) -> ValidationResult:
        checks = []
        errors = []
        
        for info in forbidden_info:
            if info.lower() in text.lower():
                checks.append(ValidationCheck(
                    check_name="narration_leak_check",
                    passed=False,
                    reason=f"Narration contains forbidden information: {info}",
                    severity="error",
                ))
                errors.append(f"Narration contains forbidden information: {info}")
            else:
                checks.append(ValidationCheck(
                    check_name="narration_leak_check",
                    passed=True,
                ))
        
        return ValidationResult(
            is_valid=all(c.passed for c in checks),
            checks=checks,
            errors=errors,
        )
    
    def validate_perspective_knowledge(
        self,
        npc_id: str,
        knowledge: str,
        state: CanonicalState,
    ) -> ValidationResult:
        npc_state = state.npc_states.get(npc_id)
        if npc_state is None:
            return ValidationResult(
                is_valid=False,
                checks=[ValidationCheck(
                    check_name="knowledge_validation",
                    passed=False,
                    reason=f"NPC {npc_id} not found",
                )],
                errors=[f"NPC {npc_id} not found"],
            )
        
        return ValidationResult(
            is_valid=True,
            checks=[ValidationCheck(
                check_name="knowledge_validation",
                passed=True,
            )],
        )
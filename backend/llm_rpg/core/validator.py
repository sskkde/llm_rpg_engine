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
    
    def validate_candidate_event(
        self,
        event_type: str,
        description: str,
        target_entity_ids: List[str],
        effects: Dict[str, Any],
        state: CanonicalState,
    ) -> ValidationResult:
        """
        Validate a candidate event before it is added to the event list.
        
        Checks:
        - Description is non-empty
        - Target entities exist in state (if specified)
        - Effects dict is well-formed
        """
        checks = []
        errors = []
        warnings = []
        
        if not description or not description.strip():
            checks.append(ValidationCheck(
                check_name="candidate_description",
                passed=False,
                reason="Candidate event has empty description",
            ))
            errors.append("Candidate event has empty description")
        else:
            checks.append(ValidationCheck(
                check_name="candidate_description",
                passed=True,
            ))
        
        for entity_id in target_entity_ids:
            if entity_id.startswith("npc_"):
                if entity_id not in state.npc_states:
                    checks.append(ValidationCheck(
                        check_name="candidate_target_validation",
                        passed=False,
                        reason=f"Target NPC {entity_id} not found in state",
                    ))
                    errors.append(f"Target NPC {entity_id} not found in state")
                else:
                    checks.append(ValidationCheck(
                        check_name="candidate_target_validation",
                        passed=True,
                    ))
            elif entity_id.startswith("loc_"):
                if entity_id not in state.location_states:
                    checks.append(ValidationCheck(
                        check_name="candidate_target_validation",
                        passed=False,
                        reason=f"Target location {entity_id} not found in state",
                    ))
                    errors.append(f"Target location {entity_id} not found in state")
                else:
                    checks.append(ValidationCheck(
                        check_name="candidate_target_validation",
                        passed=True,
                    ))
        
        if not target_entity_ids:
            checks.append(ValidationCheck(
                check_name="candidate_target_validation",
                passed=True,
            ))
        
        if not isinstance(effects, dict):
            checks.append(ValidationCheck(
                check_name="candidate_effects_validation",
                passed=False,
                reason=f"Effects must be a dict, got {type(effects).__name__}",
            ))
            errors.append(f"Effects must be a dict, got {type(effects).__name__}")
        else:
            checks.append(ValidationCheck(
                check_name="candidate_effects_validation",
                passed=True,
            ))
        
        return ValidationResult(
            is_valid=all(c.passed for c in checks),
            checks=checks,
            errors=errors,
            warnings=warnings,
        )
    
    def validate_candidate_event(
        self,
        event_type: str,
        description: str,
        target_entity_ids: List[str],
        effects: Dict[str, Any],
        state: CanonicalState,
    ) -> ValidationResult:
        """
        Validate a candidate event from world/scene proposals.
        
        Candidate events must pass validation before being committed.
        This ensures LLM-generated proposals don't bypass rule constraints.
        """
        checks = []
        errors = []
        warnings = []
        
        event_type_check = self._validate_event_type(event_type)
        checks.append(event_type_check)
        if not event_type_check.passed:
            errors.append(event_type_check.reason)
        
        targets_check = self._validate_event_targets(target_entity_ids, state)
        checks.append(targets_check)
        if not targets_check.passed:
            errors.append(targets_check.reason)
        
        effects_check = self._validate_event_effects(effects, state)
        checks.append(effects_check)
        if not effects_check.passed:
            warnings.append(effects_check.reason)
        
        return ValidationResult(
            is_valid=all(c.passed for c in checks),
            checks=checks,
            errors=errors,
            warnings=warnings,
        )
    
    def _validate_event_type(self, event_type: str) -> ValidationCheck:
        valid_types = [
            "world_tick", "scene_trigger", "npc_action", "player_action",
            "environment_change", "time_advance", "offscreen_activity",
            "global_event", "location_change", "quest_progress",
        ]
        if event_type not in valid_types:
            return ValidationCheck(
                check_name="event_type_validation",
                passed=False,
                reason=f"Invalid event type: {event_type}",
            )
        return ValidationCheck(
            check_name="event_type_validation",
            passed=True,
        )
    
    def _validate_event_targets(
        self,
        target_entity_ids: List[str],
        state: CanonicalState,
    ) -> ValidationCheck:
        for entity_id in target_entity_ids:
            if entity_id.startswith("npc_"):
                if entity_id not in state.npc_states:
                    return ValidationCheck(
                        check_name="event_target_validation",
                        passed=False,
                        reason=f"Target NPC {entity_id} not found in state",
                    )
            elif entity_id.startswith("loc_"):
                if entity_id not in state.location_states:
                    return ValidationCheck(
                        check_name="event_target_validation",
                        passed=False,
                        reason=f"Target location {entity_id} not found in state",
                    )
        return ValidationCheck(
            check_name="event_target_validation",
            passed=True,
        )
    
    def _validate_event_effects(
        self,
        effects: Dict[str, Any],
        state: CanonicalState,
    ) -> ValidationCheck:
        return ValidationCheck(
            check_name="event_effects_validation",
            passed=True,
        )
"""
Rule Engine

Main rule evaluation and validation system.
Coordinates between different rule types and provides unified validation.
"""

import uuid
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime


class RulePriority(int, Enum):
    """Rule priority levels."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    INFO = 4


class RuleType(str, Enum):
    """Types of rules."""
    MOVEMENT = "movement"
    QUEST = "quest"
    COMBAT = "combat"
    DIALOGUE = "dialogue"
    WORLD_TIME = "world_time"
    CUSTOM = "custom"


@dataclass
class RuleResult:
    """Result of a rule evaluation."""
    rule_id: str
    rule_type: RuleType
    passed: bool
    errors: List[str]
    warnings: List[str]
    modifications: Dict[str, Any]
    priority: RulePriority
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.value,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "modifications": self.modifications,
            "priority": self.priority.value,
            "timestamp": self.timestamp.isoformat(),
        }


class RuleEngine:
    """
    Main rule evaluation and validation system.
    
    Coordinates between different rule types:
    - MovementRules
    - QuestRules
    - CombatRules
    - DialogueRules
    - WorldTimeRules
    
    Provides unified validation and rule registration.
    """
    
    def __init__(self):
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._rule_handlers: Dict[RuleType, List[Callable]] = {
            rt: [] for rt in RuleType
        }
        self._validation_history: List[RuleResult] = []
        self._max_history = 1000
    
    def register_rule(
        self,
        rule_type: RuleType,
        handler: Callable,
        rule_id: Optional[str] = None,
        priority: RulePriority = RulePriority.NORMAL,
        description: str = ""
    ) -> str:
        """
        Register a rule handler.
        
        Args:
            rule_type: Type of rule
            handler: Function to evaluate the rule
            rule_id: Optional rule ID (generated if not provided)
            priority: Rule priority
            description: Rule description
            
        Returns:
            The rule ID
        """
        if rule_id is None:
            rule_id = f"rule_{uuid.uuid4().hex[:12]}"
        
        self._rules[rule_id] = {
            "rule_id": rule_id,
            "rule_type": rule_type,
            "handler": handler,
            "priority": priority,
            "description": description,
            "enabled": True,
        }
        
        self._rule_handlers[rule_type].append(handler)
        
        return rule_id
    
    def unregister_rule(self, rule_id: str) -> bool:
        """Unregister a rule."""
        if rule_id not in self._rules:
            return False
        
        rule = self._rules[rule_id]
        handler = rule["handler"]
        
        if handler in self._rule_handlers[rule["rule_type"]]:
            self._rule_handlers[rule["rule_type"]].remove(handler)
        
        del self._rules[rule_id]
        return True
    
    def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule."""
        if rule_id not in self._rules:
            return False
        
        self._rules[rule_id]["enabled"] = True
        return True
    
    def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule."""
        if rule_id not in self._rules:
            return False
        
        self._rules[rule_id]["enabled"] = False
        return True
    
    def evaluate_rule(
        self,
        rule_id: str,
        context: Dict[str, Any]
    ) -> Optional[RuleResult]:
        """
        Evaluate a specific rule.
        
        Args:
            rule_id: The rule ID to evaluate
            context: Evaluation context
            
        Returns:
            RuleResult or None if rule not found
        """
        rule = self._rules.get(rule_id)
        if not rule or not rule["enabled"]:
            return None
        
        try:
            result = rule["handler"](context)
            
            if isinstance(result, RuleResult):
                self._record_validation(result)
                return result
            elif isinstance(result, dict):
                rule_result = RuleResult(
                    rule_id=rule_id,
                    rule_type=rule["rule_type"],
                    passed=result.get("passed", False),
                    errors=result.get("errors", []),
                    warnings=result.get("warnings", []),
                    modifications=result.get("modifications", {}),
                    priority=rule["priority"],
                    timestamp=datetime.now(),
                )
                self._record_validation(rule_result)
                return rule_result
            else:
                rule_result = RuleResult(
                    rule_id=rule_id,
                    rule_type=rule["rule_type"],
                    passed=bool(result),
                    errors=[],
                    warnings=[],
                    modifications={},
                    priority=rule["priority"],
                    timestamp=datetime.now(),
                )
                self._record_validation(rule_result)
                return rule_result
                
        except Exception as e:
            rule_result = RuleResult(
                rule_id=rule_id,
                rule_type=rule["rule_type"],
                passed=False,
                errors=[str(e)],
                warnings=[],
                modifications={},
                priority=RulePriority.CRITICAL,
                timestamp=datetime.now(),
            )
            self._record_validation(rule_result)
            return rule_result
    
    def evaluate_rules_by_type(
        self,
        rule_type: RuleType,
        context: Dict[str, Any]
    ) -> List[RuleResult]:
        """
        Evaluate all rules of a specific type.
        
        Args:
            rule_type: Type of rules to evaluate
            context: Evaluation context
            
        Returns:
            List of rule results
        """
        results = []
        
        for rule_id, rule in self._rules.items():
            if rule["rule_type"] == rule_type and rule["enabled"]:
                result = self.evaluate_rule(rule_id, context)
                if result:
                    results.append(result)
        
        results.sort(key=lambda r: r.priority.value)
        return results
    
    def validate_all(
        self,
        context: Dict[str, Any],
        stop_on_error: bool = False
    ) -> Dict[str, Any]:
        """
        Validate all enabled rules.
        
        Args:
            context: Validation context
            stop_on_error: If True, stop on first error
            
        Returns:
            Validation summary
        """
        all_results = []
        errors = []
        warnings = []
        modifications = {}
        
        sorted_rules = sorted(
            self._rules.items(),
            key=lambda x: x[1]["priority"].value
        )
        
        for rule_id, rule in sorted_rules:
            if not rule["enabled"]:
                continue
            
            result = self.evaluate_rule(rule_id, context)
            if result:
                all_results.append(result)
                
                if not result.passed:
                    errors.extend(result.errors)
                    if stop_on_error:
                        break
                
                warnings.extend(result.warnings)
                modifications.update(result.modifications)
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "modifications": modifications,
            "results": [r.to_dict() for r in all_results],
            "total_rules": len(all_results),
            "passed_rules": sum(1 for r in all_results if r.passed),
            "failed_rules": sum(1 for r in all_results if not r.passed),
        }
    
    def _record_validation(self, result: RuleResult) -> None:
        """Record validation result."""
        self._validation_history.append(result)
        
        if len(self._validation_history) > self._max_history:
            self._validation_history = self._validation_history[-self._max_history:]
    
    def get_validation_history(
        self,
        rule_type: Optional[RuleType] = None,
        limit: int = 50
    ) -> List[RuleResult]:
        """Get validation history."""
        history = self._validation_history
        
        if rule_type:
            history = [r for r in history if r.rule_type == rule_type]
        
        return history[-limit:]
    
    def clear_history(self) -> None:
        """Clear validation history."""
        self._validation_history.clear()
    
    def get_registered_rules(self, rule_type: Optional[RuleType] = None) -> List[Dict[str, Any]]:
        """Get list of registered rules."""
        rules = []
        
        for rule_id, rule in self._rules.items():
            if rule_type is None or rule["rule_type"] == rule_type:
                rules.append({
                    "rule_id": rule_id,
                    "rule_type": rule["rule_type"].value,
                    "priority": rule["priority"].value,
                    "description": rule["description"],
                    "enabled": rule["enabled"],
                })
        
        return rules

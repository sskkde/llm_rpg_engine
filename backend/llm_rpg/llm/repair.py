"""
LLM JSON Repair Handler

This module provides structured-output repair flow for parse failures.
When LLM returns malformed JSON, the repair handler attempts to fix it
before falling back to a default response.
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Type
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field


class RepairStrategy(Enum):
    """Strategies for repairing malformed JSON."""
    JSON_PARSE = "json_parse"
    EXTRACT_JSON = "extract_json"
    FIX_QUOTES = "fix_quotes"
    FIX_TRAILING_COMMAS = "fix_trailing_commas"
    FIX_MISSING_BRACES = "fix_missing_braces"
    WRAPPER_REPAIR = "wrapper_repair"


class RepairStatus(Enum):
    """Status of repair attempt."""
    SUCCESS = "success"
    FAILED = "failed"
    FALLBACK = "fallback"


@dataclass
class RepairAttempt:
    """Record of a repair attempt."""
    strategy: RepairStrategy
    status: RepairStatus
    original_content: str
    repaired_content: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RepairAuditRecord:
    """Complete audit record of repair process."""
    original_content: str
    attempts: List[RepairAttempt]
    final_result: Optional[Dict[str, Any]] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None


class JSONRepairRule(ABC):
    """Abstract base class for JSON repair rules."""
    
    @abstractmethod
    def can_repair(self, content: str) -> bool:
        """Check if this rule can repair the content."""
        pass
    
    @abstractmethod
    def repair(self, content: str) -> Tuple[str, Dict[str, Any]]:
        """
        Attempt to repair the content.
        
        Returns:
            Tuple of (repaired_content, metadata)
        """
        pass


class ExtractJSONRule(JSONRepairRule):
    """Extract JSON from markdown code blocks or surrounding text."""
    
    def can_repair(self, content: str) -> bool:
        return "```" in content or "{" in content
    
    def repair(self, content: str) -> Tuple[str, Dict[str, Any]]:
        metadata = {"method": "extraction"}
        
        # Try to extract from markdown code blocks
        code_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
        matches = re.findall(code_block_pattern, content, re.DOTALL)
        if matches:
            return matches[0].strip(), {**metadata, "extracted_from": "code_block"}
        
        # Try to find JSON object boundaries
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            return content[start_idx:end_idx+1], {**metadata, "extracted_from": "boundaries"}
        
        # Try to find JSON array boundaries
        start_idx = content.find('[')
        end_idx = content.rfind(']')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            return content[start_idx:end_idx+1], {**metadata, "extracted_from": "array_boundaries"}
        
        return content, {**metadata, "extracted_from": "none"}


class FixQuotesRule(JSONRepairRule):
    """Fix common quote issues in JSON."""
    
    def can_repair(self, content: str) -> bool:
        return '"' in content or "'" in content
    
    def repair(self, content: str) -> Tuple[str, Dict[str, Any]]:
        metadata = {"method": "quote_fix"}
        repaired = content
        
        # Replace single quotes with double quotes (only for JSON keys/values)
        # This is a simplified approach - more sophisticated would parse properly
        repaired = re.sub(r"(?<=[{,:\s])'([^']*?)'(?=\s*[,}:])", r'"\1"', repaired)
        
        # Fix unescaped quotes within strings (common LLM error)
        # Replace smart quotes with regular quotes
        repaired = repaired.replace('"', '"').replace('"', '"')
        
        changes = content != repaired
        return repaired, {**metadata, "changes_made": changes}


class FixTrailingCommasRule(JSONRepairRule):
    """Fix trailing commas in JSON objects and arrays."""
    
    def can_repair(self, content: str) -> bool:
        return re.search(r',\s*[}\]]', content) is not None
    
    def repair(self, content: str) -> Tuple[str, Dict[str, Any]]:
        metadata = {"method": "trailing_comma_fix"}
        
        # Remove trailing commas before closing braces/brackets
        repaired = re.sub(r',\s*}', '}', content)
        repaired = re.sub(r',\s*\]', ']', repaired)
        
        changes = content != repaired
        return repaired, {**metadata, "changes_made": changes}


class FixMissingBracesRule(JSONRepairRule):
    """Fix missing closing braces or brackets."""
    
    def can_repair(self, content: str) -> bool:
        open_braces = content.count('{')
        close_braces = content.count('}')
        open_brackets = content.count('[')
        close_brackets = content.count(']')
        return open_braces != close_braces or open_brackets != close_brackets
    
    def repair(self, content: str) -> Tuple[str, Dict[str, Any]]:
        metadata = {"method": "brace_fix"}
        repaired = content
        
        # Count braces and brackets
        open_braces = repaired.count('{')
        close_braces = repaired.count('}')
        open_brackets = repaired.count('[')
        close_brackets = repaired.count(']')
        
        # Add missing closing braces
        while close_braces < open_braces:
            repaired += '}'
            close_braces += 1
        
        # Add missing closing brackets
        while close_brackets < open_brackets:
            repaired += ']'
            close_brackets += 1
        
        changes = content != repaired
        return repaired, {**metadata, "changes_made": changes, 
                         "braces_added": close_braces - content.count('}'),
                         "brackets_added": close_brackets - content.count(']')}


class WrapperRepairRule(JSONRepairRule):
    """Wrap plain text responses in a standard JSON structure."""
    
    def __init__(self, wrapper_field: str = "content"):
        self.wrapper_field = wrapper_field
    
    def can_repair(self, content: str) -> bool:
        # Can repair if content doesn't look like JSON
        content_stripped = content.strip()
        return not (content_stripped.startswith('{') or content_stripped.startswith('['))
    
    def repair(self, content: str) -> Tuple[str, Dict[str, Any]]:
        metadata = {"method": "wrapper", "wrapper_field": self.wrapper_field}
        
        # Escape the content for JSON
        escaped_content = json.dumps(content)
        wrapped = f'{{"{self.wrapper_field}": {escaped_content}}}'
        
        return wrapped, metadata


class RetryRepairHandler:
    """
    Handler for retrying and repairing malformed LLM JSON output.
    
    This handler:
    1. Attempts multiple repair strategies in order
    2. Records all repair attempts for audit
    3. Falls back to default values if repair fails
    4. Provides detailed repair audit records
    """
    
    DEFAULT_RULES = [
        ExtractJSONRule(),
        FixTrailingCommasRule(),
        FixMissingBracesRule(),
        FixQuotesRule(),
    ]
    
    def __init__(
        self,
        rules: Optional[List[JSONRepairRule]] = None,
        max_repair_attempts: int = 3,
        enable_wrapper_fallback: bool = True,
    ):
        self.rules = rules or self.DEFAULT_RULES.copy()
        self.max_repair_attempts = max_repair_attempts
        self.enable_wrapper_fallback = enable_wrapper_fallback
        self._repair_history: List[RepairAuditRecord] = []
    
    def add_rule(self, rule: JSONRepairRule, index: Optional[int] = None):
        """Add a repair rule at the specified index (or append if None)."""
        if index is not None:
            self.rules.insert(index, rule)
        else:
            self.rules.append(rule)
    
    def _try_parse(self, content: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Try to parse content as JSON.
        
        Returns:
            Tuple of (success, parsed_data, error_message)
        """
        try:
            parsed = json.loads(content)
            return True, parsed, None
        except json.JSONDecodeError as e:
            return False, None, str(e)
    
    def repair(
        self,
        content: str,
        fallback_defaults: Optional[Dict[str, Any]] = None,
        target_schema: Optional[Type[BaseModel]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], RepairAuditRecord]:
        """
        Attempt to repair malformed JSON content.
        
        Args:
            content: The malformed JSON content
            fallback_defaults: Default values to use if repair fails
            target_schema: Optional Pydantic model to validate against
            
        Returns:
            Tuple of (repaired_data_or_none, audit_record)
        """
        attempts: List[RepairAttempt] = []
        current_content = content
        
        # First, try direct parse
        success, parsed, error = self._try_parse(current_content)
        if success:
            record = RepairAuditRecord(
                original_content=content,
                attempts=attempts,
                final_result=parsed,
                fallback_used=False,
            )
            self._repair_history.append(record)
            return parsed, record
        
        # Try each repair rule
        for i, rule in enumerate(self.rules):
            if i >= self.max_repair_attempts:
                break
            
            if rule.can_repair(current_content):
                try:
                    repaired_content, metadata = rule.repair(current_content)
                    success, parsed, error = self._try_parse(repaired_content)
                    
                    if success:
                        # Validate against schema if provided
                        if target_schema:
                            try:
                                validated = target_schema(**parsed)
                                parsed = validated.model_dump()
                            except Exception as e:
                                attempt = RepairAttempt(
                                    strategy=self._get_strategy_from_rule(rule),
                                    status=RepairStatus.FAILED,
                                    original_content=current_content,
                                    repaired_content=repaired_content,
                                    error=f"Schema validation failed: {e}",
                                    metadata=metadata,
                                )
                                attempts.append(attempt)
                                current_content = repaired_content
                                continue
                        
                        attempt = RepairAttempt(
                            strategy=self._get_strategy_from_rule(rule),
                            status=RepairStatus.SUCCESS,
                            original_content=current_content,
                            repaired_content=repaired_content,
                            metadata=metadata,
                        )
                        attempts.append(attempt)
                        
                        record = RepairAuditRecord(
                            original_content=content,
                            attempts=attempts,
                            final_result=parsed,
                            fallback_used=False,
                        )
                        self._repair_history.append(record)
                        return parsed, record
                    else:
                        attempt = RepairAttempt(
                            strategy=self._get_strategy_from_rule(rule),
                            status=RepairStatus.FAILED,
                            original_content=current_content,
                            repaired_content=repaired_content,
                            error=error,
                            metadata=metadata,
                        )
                        attempts.append(attempt)
                        current_content = repaired_content
                        
                except Exception as e:
                    attempt = RepairAttempt(
                        strategy=self._get_strategy_from_rule(rule),
                        status=RepairStatus.FAILED,
                        original_content=current_content,
                        error=str(e),
                    )
                    attempts.append(attempt)
        
        # Try wrapper fallback if enabled
        if self.enable_wrapper_fallback and fallback_defaults is None:
            wrapper_rule = WrapperRepairRule()
            if wrapper_rule.can_repair(current_content):
                try:
                    repaired_content, metadata = wrapper_rule.repair(current_content)
                    success, parsed, error = self._try_parse(repaired_content)
                    
                    if success:
                        attempt = RepairAttempt(
                            strategy=RepairStrategy.WRAPPER_REPAIR,
                            status=RepairStatus.SUCCESS,
                            original_content=current_content,
                            repaired_content=repaired_content,
                            metadata=metadata,
                        )
                        attempts.append(attempt)
                        
                        record = RepairAuditRecord(
                            original_content=content,
                            attempts=attempts,
                            final_result=parsed,
                            fallback_used=False,
                        )
                        self._repair_history.append(record)
                        return parsed, record
                except Exception:
                    pass
        
        # All repair attempts failed - use fallback
        fallback_result = fallback_defaults.copy() if fallback_defaults else None
        
        record = RepairAuditRecord(
            original_content=content,
            attempts=attempts,
            final_result=fallback_result,
            fallback_used=True,
            fallback_reason="All repair strategies exhausted",
        )
        self._repair_history.append(record)
        
        return fallback_result, record
    
    def _get_strategy_from_rule(self, rule: JSONRepairRule) -> RepairStrategy:
        """Map rule to strategy enum."""
        rule_map = {
            ExtractJSONRule: RepairStrategy.EXTRACT_JSON,
            FixQuotesRule: RepairStrategy.FIX_QUOTES,
            FixTrailingCommasRule: RepairStrategy.FIX_TRAILING_COMMAS,
            FixMissingBracesRule: RepairStrategy.FIX_MISSING_BRACES,
            WrapperRepairRule: RepairStrategy.WRAPPER_REPAIR,
        }
        return rule_map.get(type(rule), RepairStrategy.JSON_PARSE)
    
    def get_repair_history(self) -> List[RepairAuditRecord]:
        """Get all repair history records."""
        return self._repair_history.copy()
    
    def clear_history(self):
        """Clear repair history."""
        self._repair_history.clear()
    
    def get_repair_stats(self) -> Dict[str, Any]:
        """Get statistics about repair attempts."""
        total = len(self._repair_history)
        successful = sum(1 for r in self._repair_history if not r.fallback_used)
        fallback = sum(1 for r in self._repair_history if r.fallback_used)
        
        strategy_counts: Dict[str, int] = {}
        for record in self._repair_history:
            for attempt in record.attempts:
                if attempt.status == RepairStatus.SUCCESS:
                    strategy_counts[attempt.strategy.value] = strategy_counts.get(attempt.strategy.value, 0) + 1
        
        return {
            "total_attempts": total,
            "successful_repairs": successful,
            "fallback_used": fallback,
            "success_rate": successful / total if total > 0 else 0.0,
            "strategy_success_counts": strategy_counts,
        }


# Common fallback defaults for different output types
FALLBACK_INTENT = {
    "intent_type": "unknown",
    "target": None,
    "risk_level": "low",
}

FALLBACK_NPC_ACTION = {
    "action_type": "observe",
    "target": "player",
    "summary": "NPC observes cautiously",
    "confidence": 0.5,
}

FALLBACK_NARRATION = {
    "content": "The scene unfolds before you...",
    "atmosphere": "neutral",
}

FALLBACK_LORE_DISCOVERY = {
    "discovered": False,
    "lore_id": None,
    "description": None,
}

FALLBACK_COMBAT_ACTION = {
    "action_type": "defend",
    "target": None,
    "reasoning": "Falling back to defensive stance",
}

FALLBACK_DIALOGUE = {
    "dialogue_type": "response",
    "content": "...",
    "mood": "neutral",
}


class RepairFallbacks:
    """Container for common repair fallback defaults."""
    
    INTENT = FALLBACK_INTENT
    NPC_ACTION = FALLBACK_NPC_ACTION
    NARRATION = FALLBACK_NARRATION
    LORE_DISCOVERY = FALLBACK_LORE_DISCOVERY
    COMBAT_ACTION = FALLBACK_COMBAT_ACTION
    DIALOGUE = FALLBACK_DIALOGUE

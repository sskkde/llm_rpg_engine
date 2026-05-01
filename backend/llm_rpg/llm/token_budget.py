"""
Token Budget Manager

This module provides deterministic context trimming and summarization
when token budget is exceeded, with full audit trail of trimmed sections.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple

from pydantic import BaseModel, Field


class TrimDecision(Enum):
    """Decision for how to handle a section that exceeds budget."""
    KEEP = "keep"
    SUMMARIZE = "summarize"
    TRIM = "trim"
    REMOVE = "remove"


class TrimReason(Enum):
    """Reason for trimming a section."""
    BUDGET_EXCEEDED = "budget_exceeded"
    LOW_RELEVANCE = "low_relevance"
    OLD_CONTENT = "old_content"
    REDUNDANT = "redundant"
    LARGE_SIZE = "large_size"


@dataclass
class TrimAuditEntry:
    """Audit entry for a single trim operation."""
    section_name: str
    original_tokens: int
    final_tokens: int
    decision: TrimDecision
    reason: TrimReason
    summary: Optional[str] = None
    removed_keys: List[str] = field(default_factory=list)


@dataclass
class TokenBudgetAudit:
    """Complete audit of token budget management for a request."""
    budget_limit: int
    original_total: int
    final_total: int
    entries: List[TrimAuditEntry] = field(default_factory=list)
    overflow_detected: bool = False
    fallback_triggered: bool = False
    fallback_reason: Optional[str] = None


class TokenCounter(Protocol):
    """Protocol for token counting implementations."""
    
    def count(self, text: str) -> int:
        """Count tokens in text."""
        ...


class ApproximateTokenCounter:
    """Approximate token counter using character count."""
    
    def __init__(self, chars_per_token: float = 4.0):
        self.chars_per_token = chars_per_token
    
    def count(self, text: str) -> int:
        """Count tokens by dividing character count."""
        if not text:
            return 0
        return int(len(text) / self.chars_per_token)


class TiktokenCounter:
    """Token counter using tiktoken (if available)."""
    
    def __init__(self, model: str = "gpt-4"):
        self.model = model
        self._encoding = None
        self._available = False
        
        try:
            import tiktoken
            self._encoding = tiktoken.encoding_for_model(model)
            self._available = True
        except ImportError:
            pass
        except KeyError:
            self._encoding = tiktoken.get_encoding("cl100k_base")
            self._available = True
    
    def count(self, text: str) -> int:
        """Count tokens using tiktoken."""
        if not text:
            return 0
        if not self._available or self._encoding is None:
            return int(len(text) / 4)
        return len(self._encoding.encode(text))


class Summarizer(ABC):
    """Abstract base class for content summarizers."""
    
    @abstractmethod
    def summarize(self, content: str, max_tokens: int) -> str:
        """
        Summarize content to fit within max_tokens.
        
        Args:
            content: The content to summarize
            max_tokens: Maximum tokens for the summary
            
        Returns:
            Summarized content
        """
        pass


class TruncationSummarizer(Summarizer):
    """Simple truncation summarizer."""
    
    def __init__(self, token_counter: Optional[TokenCounter] = None):
        self.token_counter = token_counter or ApproximateTokenCounter()
    
    def summarize(self, content: str, max_tokens: int) -> str:
        """Truncate content to fit within token limit."""
        if not content:
            return content
        
        current_tokens = self.token_counter.count(content)
        if current_tokens <= max_tokens:
            return content
        
        chars_per_token = len(content) / current_tokens
        target_chars = int(max_tokens * chars_per_token)
        
        return content[:target_chars] + "..."


class SectionPriority(Enum):
    """Priority levels for context sections."""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    OPTIONAL = 5


@dataclass
class ContextSection:
    """A section of context with metadata for budget management."""
    name: str
    content: str
    priority: SectionPriority = SectionPriority.MEDIUM
    trimmable: bool = True
    summarizable: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def token_count(self, counter: TokenCounter) -> int:
        """Get token count for this section."""
        return counter.count(self.content)


class TokenBudgetManager:
    """
    Manages token budget allocation and context trimming.
    
    This manager:
    1. Tracks token usage against budget limits
    2. Applies trimming strategies when budget is exceeded
    3. Records audit trail of all trimming decisions
    4. Ensures critical content is preserved
    5. Provides deterministic trimming based on priorities
    """
    
    DEFAULT_BUDGETS = {
        "intent_parsing": 1000,
        "world_simulation": 2000,
        "npc_decision": 1500,
        "conflict_resolution": 1500,
        "narration": 2000,
        "summary": 1000,
        "memory_extraction": 1000,
        "lore_retrieval": 1000,
        "validation_repair": 1000,
    }
    
    def __init__(
        self,
        token_counter: Optional[TokenCounter] = None,
        summarizer: Optional[Summarizer] = None,
        default_budget: int = 2000,
    ):
        self.token_counter = token_counter or ApproximateTokenCounter()
        self.summarizer = summarizer or TruncationSummarizer(self.token_counter)
        self.default_budget = default_budget
        self._budgets = self.DEFAULT_BUDGETS.copy()
        self._audit_history: List[TokenBudgetAudit] = []
    
    def set_budget(self, task_type: str, tokens: int):
        """Set token budget for a specific task type."""
        self._budgets[task_type] = tokens
    
    def get_budget(self, task_type: str) -> int:
        """Get token budget for a task type."""
        return self._budgets.get(task_type, self.default_budget)
    
    def manage_budget(
        self,
        sections: List[ContextSection],
        task_type: str,
        reserve_tokens: int = 200,
    ) -> Tuple[str, TokenBudgetAudit]:
        """
        Manage token budget for a set of context sections.
        
        Args:
            sections: List of context sections to fit within budget
            task_type: Type of task (determines budget limit)
            reserve_tokens: Tokens to reserve for response
            
        Returns:
            Tuple of (combined_context, audit_record)
        """
        budget = self.get_budget(task_type)
        available_budget = budget - reserve_tokens
        
        audit = TokenBudgetAudit(
            budget_limit=budget,
            original_total=0,
            final_total=0,
            entries=[],
        )
        
        sorted_sections = sorted(sections, key=lambda s: s.priority.value)
        
        total_tokens = sum(s.token_count(self.token_counter) for s in sections)
        audit.original_total = total_tokens
        
        if total_tokens <= available_budget:
            audit.final_total = total_tokens
            for section in sections:
                entry = TrimAuditEntry(
                    section_name=section.name,
                    original_tokens=section.token_count(self.token_counter),
                    final_tokens=section.token_count(self.token_counter),
                    decision=TrimDecision.KEEP,
                    reason=TrimReason.BUDGET_EXCEEDED,
                )
                audit.entries.append(entry)
            
            combined = "\n\n".join(s.content for s in sorted_sections)
            self._audit_history.append(audit)
            return combined, audit
        
        audit.overflow_detected = True
        
        processed_sections = []
        current_tokens = 0
        
        for section in sorted_sections:
            section_tokens = section.token_count(self.token_counter)
            
            if section.priority == SectionPriority.CRITICAL:
                if current_tokens + section_tokens > available_budget:
                    audit.fallback_triggered = True
                    audit.fallback_reason = "Critical section exceeds budget"
                    break
                
                processed_sections.append(section.content)
                current_tokens += section_tokens
                
                entry = TrimAuditEntry(
                    section_name=section.name,
                    original_tokens=section_tokens,
                    final_tokens=section_tokens,
                    decision=TrimDecision.KEEP,
                    reason=TrimReason.BUDGET_EXCEEDED,
                )
                audit.entries.append(entry)
            
            elif section.summarizable and section.trimmable:
                remaining_budget = available_budget - current_tokens
                
                if remaining_budget <= 0:
                    entry = TrimAuditEntry(
                        section_name=section.name,
                        original_tokens=section_tokens,
                        final_tokens=0,
                        decision=TrimDecision.REMOVE,
                        reason=TrimReason.BUDGET_EXCEEDED,
                    )
                    audit.entries.append(entry)
                    continue
                
                summarized = self.summarizer.summarize(section.content, remaining_budget)
                summarized_tokens = self.token_counter.count(summarized)
                
                processed_sections.append(summarized)
                current_tokens += summarized_tokens
                
                entry = TrimAuditEntry(
                    section_name=section.name,
                    original_tokens=section_tokens,
                    final_tokens=summarized_tokens,
                    decision=TrimDecision.SUMMARIZE,
                    reason=TrimReason.BUDGET_EXCEEDED,
                    summary=summarized[:100] + "..." if len(summarized) > 100 else summarized,
                )
                audit.entries.append(entry)
            
            elif section.trimmable:
                remaining_budget = available_budget - current_tokens
                
                if remaining_budget <= 0:
                    entry = TrimAuditEntry(
                        section_name=section.name,
                        original_tokens=section_tokens,
                        final_tokens=0,
                        decision=TrimDecision.REMOVE,
                        reason=TrimReason.BUDGET_EXCEEDED,
                    )
                    audit.entries.append(entry)
                    continue
                
                chars_per_token = len(section.content) / section_tokens
                target_chars = int(remaining_budget * chars_per_token)
                trimmed = section.content[:target_chars] + "..."
                trimmed_tokens = self.token_counter.count(trimmed)
                
                processed_sections.append(trimmed)
                current_tokens += trimmed_tokens
                
                entry = TrimAuditEntry(
                    section_name=section.name,
                    original_tokens=section_tokens,
                    final_tokens=trimmed_tokens,
                    decision=TrimDecision.TRIM,
                    reason=TrimReason.BUDGET_EXCEEDED,
                )
                audit.entries.append(entry)
            
            else:
                if current_tokens + section_tokens > available_budget:
                    entry = TrimAuditEntry(
                        section_name=section.name,
                        original_tokens=section_tokens,
                        final_tokens=0,
                        decision=TrimDecision.REMOVE,
                        reason=TrimReason.BUDGET_EXCEEDED,
                    )
                    audit.entries.append(entry)
                else:
                    processed_sections.append(section.content)
                    current_tokens += section_tokens
                    
                    entry = TrimAuditEntry(
                        section_name=section.name,
                        original_tokens=section_tokens,
                        final_tokens=section_tokens,
                        decision=TrimDecision.KEEP,
                        reason=TrimReason.BUDGET_EXCEEDED,
                    )
                    audit.entries.append(entry)
        
        audit.final_total = current_tokens
        
        combined = "\n\n".join(processed_sections)
        self._audit_history.append(audit)
        return combined, audit
    
    def trim_context_for_budget(
        self,
        context: Dict[str, Any],
        task_type: str,
        priority_map: Optional[Dict[str, SectionPriority]] = None,
        reserve_tokens: int = 200,
    ) -> Tuple[Dict[str, Any], TokenBudgetAudit]:
        """
        Trim a context dictionary to fit within budget.
        
        Args:
            context: Dictionary of context sections
            task_type: Type of task
            priority_map: Optional mapping of keys to priorities
            reserve_tokens: Tokens to reserve for response
            
        Returns:
            Tuple of (trimmed_context, audit_record)
        """
        priority_map = priority_map or {}
        sections = []
        
        for key, value in context.items():
            if isinstance(value, str):
                content = value
            else:
                content = json.dumps(value, ensure_ascii=False, indent=2)
            
            priority = priority_map.get(key, SectionPriority.MEDIUM)
            section = ContextSection(
                name=key,
                content=content,
                priority=priority,
                trimmable=priority != SectionPriority.CRITICAL,
                summarizable=priority not in (SectionPriority.CRITICAL, SectionPriority.HIGH),
            )
            sections.append(section)
        
        combined, audit = self.manage_budget(sections, task_type, reserve_tokens)
        
        trimmed_context = {}
        for section in sections:
            for entry in audit.entries:
                if entry.section_name == section.name and entry.decision != TrimDecision.REMOVE:
                    try:
                        trimmed_context[section.name] = json.loads(section.content)
                    except json.JSONDecodeError:
                        trimmed_context[section.name] = section.content
                    break
        
        return trimmed_context, audit
    
    def get_audit_history(self) -> List[TokenBudgetAudit]:
        """Get all budget management audit history."""
        return self._audit_history.copy()
    
    def clear_history(self):
        """Clear audit history."""
        self._audit_history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about budget management."""
        total = len(self._audit_history)
        overflows = sum(1 for a in self._audit_history if a.overflow_detected)
        fallbacks = sum(1 for a in self._audit_history if a.fallback_triggered)
        
        total_original = sum(a.original_total for a in self._audit_history)
        total_final = sum(a.final_total for a in self._audit_history)
        
        return {
            "total_requests": total,
            "overflow_events": overflows,
            "fallback_events": fallbacks,
            "total_original_tokens": total_original,
            "total_final_tokens": total_final,
            "tokens_saved": total_original - total_final,
            "average_reduction_pct": (
                (total_original - total_final) / total_original * 100
                if total_original > 0 else 0
            ),
        }


class BudgetEnforcer:
    """
    Enforces hard budget limits on LLM calls.
    
    Can be used to prevent calls that would exceed budget.
    """
    
    def __init__(
        self,
        token_counter: Optional[TokenCounter] = None,
        global_budget: Optional[int] = None,
    ):
        self.token_counter = token_counter or ApproximateTokenCounter()
        self.global_budget = global_budget
        self._session_budgets: Dict[str, int] = {}
        self._session_usage: Dict[str, int] = {}
    
    def set_session_budget(self, session_id: str, tokens: int):
        """Set a per-session token budget."""
        self._session_budgets[session_id] = tokens
        self._session_usage[session_id] = 0
    
    def check_budget(
        self,
        content: str,
        session_id: Optional[str] = None,
    ) -> Tuple[bool, int, Optional[str]]:
        """
        Check if content fits within budget.
        
        Returns:
            Tuple of (fits_budget, token_count, reason_if_exceeded)
        """
        tokens = self.token_counter.count(content)
        
        if self.global_budget and tokens > self.global_budget:
            return False, tokens, f"Exceeds global budget of {self.global_budget}"
        
        if session_id and session_id in self._session_budgets:
            session_usage = self._session_usage.get(session_id, 0)
            remaining = self._session_budgets[session_id] - session_usage
            
            if tokens > remaining:
                return (
                    False,
                    tokens,
                    f"Exceeds session remaining budget of {remaining}"
                )
        
        return True, tokens, None
    
    def record_usage(self, session_id: str, tokens: int):
        """Record token usage for a session."""
        if session_id in self._session_usage:
            self._session_usage[session_id] += tokens
    
    def get_session_usage(self, session_id: str) -> int:
        """Get token usage for a session."""
        return self._session_usage.get(session_id, 0)

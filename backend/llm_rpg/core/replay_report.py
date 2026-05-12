"""
Replay Report / State Diff Module for LLM RPG Engine.

Provides human-readable and machine-parseable replay reports with state diffs.
Non-intrusive wrapper around the existing replay system.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from .replay import (
    ReplayPerspective, ReplayResult, ReplayStep, StateSnapshot,
    get_replay_store, ReplayStore
)


class StateDiffEntry(BaseModel):
    """A single state difference entry."""
    path: str = Field(..., description="Dot-separated path to state field (e.g., 'npc_states.elder.trust')")
    operation: str = Field(..., description="Operation type: 'added', 'removed', or 'changed'")
    old_value: Any = Field(None, description="Value before the change (None for 'added')")
    new_value: Any = Field(None, description="Value after the change (None for 'removed')")


class StateDiff(BaseModel):
    """Complete state diff between two states."""
    entries: List[StateDiffEntry] = Field(default_factory=list, description="List of all diff entries")
    added_keys: List[str] = Field(default_factory=list, description="Keys that were added")
    removed_keys: List[str] = Field(default_factory=list, description="Keys that were removed")
    changed_keys: List[str] = Field(default_factory=list, description="Keys that were changed")


class ReplayReport(BaseModel):
    """Complete replay report with state diff."""
    session_id: str = Field(..., description="Session ID")
    snapshot_id: Optional[str] = Field(None, description="Starting snapshot ID if replay started from snapshot")
    from_turn: int = Field(..., description="Starting turn number")
    to_turn: int = Field(..., description="Ending turn number")
    replayed_event_count: int = Field(..., description="Number of events replayed")
    deterministic: bool = Field(..., description="True if no LLM calls were made during replay")
    llm_calls_made: int = Field(0, description="Number of LLM calls made during original turn execution")
    state_diff: StateDiff = Field(..., description="State diff between from_turn and to_turn")
    warnings: List[str] = Field(default_factory=list, description="Any warnings during replay")
    created_at: datetime = Field(default_factory=datetime.now, description="When this report was created")


def compute_state_diff(
    before: Dict[str, Any],
    after: Dict[str, Any],
    path_prefix: str = ""
) -> StateDiff:
    """
    Compute the diff between two states recursively.
    
    Handles nested dictionaries recursively, using dot-notation for paths.
    
    Args:
        before: State before changes
        after: State after changes
        path_prefix: Current path prefix for recursion
    
    Returns:
        StateDiff with all entries, added_keys, removed_keys, and changed_keys
    """
    entries: List[StateDiffEntry] = []
    added_keys: List[str] = []
    removed_keys: List[str] = []
    changed_keys: List[str] = []
    
    before_keys: Set[str] = set(before.keys()) if isinstance(before, dict) else set()
    after_keys: Set[str] = set(after.keys()) if isinstance(after, dict) else set()
    
    for key in after_keys - before_keys:
        current_path = f"{path_prefix}.{key}" if path_prefix else key
        added_keys.append(current_path)
        entries.append(StateDiffEntry(
            path=current_path,
            operation="added",
            old_value=None,
            new_value=after[key]
        ))
    
    for key in before_keys - after_keys:
        current_path = f"{path_prefix}.{key}" if path_prefix else key
        removed_keys.append(current_path)
        entries.append(StateDiffEntry(
            path=current_path,
            operation="removed",
            old_value=before[key],
            new_value=None
        ))
    
    for key in before_keys & after_keys:
        current_path = f"{path_prefix}.{key}" if path_prefix else key
        before_val = before[key]
        after_val = after[key]
        
        if isinstance(before_val, dict) and isinstance(after_val, dict):
            nested_diff = compute_state_diff(before_val, after_val, current_path)
            entries.extend(nested_diff.entries)
            added_keys.extend(nested_diff.added_keys)
            removed_keys.extend(nested_diff.removed_keys)
            changed_keys.extend(nested_diff.changed_keys)
        elif before_val != after_val:
            changed_keys.append(current_path)
            entries.append(StateDiffEntry(
                path=current_path,
                operation="changed",
                old_value=before_val,
                new_value=after_val
            ))
    
    return StateDiff(
        entries=entries,
        added_keys=added_keys,
        removed_keys=removed_keys,
        changed_keys=changed_keys
    )


class ReplayReportBuilder:
    """
    Builder for creating ReplayReport instances.
    
    Wraps existing replay components to build reports without re-executing turns.
    Uses stored data from ReplayStore.
    """
    
    def __init__(self, replay_store: Optional[ReplayStore] = None):
        """Initialize builder with optional replay store."""
        self._replay_store = replay_store or get_replay_store()
    
    def build_report(
        self,
        session_id: str,
        from_turn: int,
        to_turn: int,
        snapshot_id: Optional[str] = None,
        perspective: ReplayPerspective = ReplayPerspective.ADMIN,
        replay_result: Optional[ReplayResult] = None,
    ) -> ReplayReport:
        """
        Build a replay report for the specified turn range.
        
        Args:
            session_id: Game session ID
            from_turn: Starting turn number
            to_turn: Ending turn number
            snapshot_id: Optional snapshot ID to start from
            perspective: Viewing perspective for output filtering
            replay_result: Optional pre-computed replay result
        
        Returns:
            ReplayReport with state diff and metadata
        """
        warnings: List[str] = []
        
        if replay_result is None:
            replay_result = self._create_minimal_replay_result(
                session_id, from_turn, to_turn
            )
        
        llm_calls_made = self._count_llm_calls(replay_result)
        
        state_diff = self._compute_diff_from_replay(replay_result, perspective)
        
        if from_turn > to_turn:
            warnings.append(f"from_turn ({from_turn}) > to_turn ({to_turn}), report may be empty")
        
        if not replay_result.steps:
            warnings.append("No replay steps found in the specified turn range")
        
        if perspective != ReplayPerspective.ADMIN:
            state_diff = self._filter_diff_for_perspective(state_diff, perspective)
        
        return ReplayReport(
            session_id=session_id,
            snapshot_id=snapshot_id,
            from_turn=from_turn,
            to_turn=to_turn,
            replayed_event_count=replay_result.total_events,
            deterministic=(llm_calls_made == 0),
            llm_calls_made=llm_calls_made,
            state_diff=state_diff,
            warnings=warnings,
        )
    
    def build_report_from_result(
        self,
        replay_result: ReplayResult,
        perspective: ReplayPerspective = ReplayPerspective.ADMIN,
    ) -> ReplayReport:
        """
        Build a replay report from an existing ReplayResult.
        
        Args:
            replay_result: Pre-computed replay result
            perspective: Viewing perspective for output filtering
        
        Returns:
            ReplayReport with state diff and metadata
        """
        return self.build_report(
            session_id=replay_result.session_id,
            from_turn=replay_result.start_turn,
            to_turn=replay_result.end_turn,
            replay_result=replay_result,
            perspective=perspective,
        )
    
    def _create_minimal_replay_result(
        self,
        session_id: str,
        from_turn: int,
        to_turn: int,
    ) -> ReplayResult:
        """Create a minimal replay result for testing/demo purposes."""
        import uuid
        
        return ReplayResult(
            replay_id=f"report_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            start_turn=from_turn,
            end_turn=to_turn,
            perspective=ReplayPerspective.ADMIN,
            steps=[],
            final_state={},
            total_steps=0,
            total_events=0,
            total_state_deltas=0,
        )
    
    def _count_llm_calls(self, replay_result: ReplayResult) -> int:
        """Count LLM calls from replay result."""
        total_calls = 0
        for step in replay_result.steps:
            total_calls += len(step.model_call_ids)
        return total_calls
    
    def _compute_diff_from_replay(
        self,
        replay_result: ReplayResult,
        perspective: ReplayPerspective,
    ) -> StateDiff:
        """Compute state diff from replay result."""
        if not replay_result.steps:
            return StateDiff()
        
        first_step = replay_result.steps[0]
        last_step = replay_result.steps[-1]
        
        state_before = first_step.state_before
        state_after = last_step.state_after
        
        return compute_state_diff(state_before, state_after)
    
    def _filter_diff_for_perspective(
        self,
        state_diff: StateDiff,
        perspective: ReplayPerspective,
    ) -> StateDiff:
        """Filter state diff entries based on perspective."""
        hidden_patterns = [
            "hidden_plan_state",
            "hidden_identity",
            "secrets",
            "forbidden_knowledge",
            "hidden_objectives",
            "secret_rewards",
        ]
        
        if perspective == ReplayPerspective.ADMIN:
            return state_diff
        
        filtered_entries = []
        filtered_added = []
        filtered_removed = []
        filtered_changed = []
        
        for entry in state_diff.entries:
            should_filter = any(pattern in entry.path for pattern in hidden_patterns)
            
            if not should_filter:
                filtered_entries.append(entry)
                if entry.operation == "added":
                    filtered_added.append(entry.path)
                elif entry.operation == "removed":
                    filtered_removed.append(entry.path)
                elif entry.operation == "changed":
                    filtered_changed.append(entry.path)
        
        return StateDiff(
            entries=filtered_entries,
            added_keys=filtered_added,
            removed_keys=filtered_removed,
            changed_keys=filtered_changed,
        )


_replay_report_builder: Optional[ReplayReportBuilder] = None


def get_replay_report_builder() -> ReplayReportBuilder:
    """Get or create the global replay report builder."""
    global _replay_report_builder
    if _replay_report_builder is None:
        _replay_report_builder = ReplayReportBuilder()
    return _replay_report_builder


def reset_replay_report_builder() -> None:
    """Reset the global replay report builder (useful for testing)."""
    global _replay_report_builder
    _replay_report_builder = ReplayReportBuilder()

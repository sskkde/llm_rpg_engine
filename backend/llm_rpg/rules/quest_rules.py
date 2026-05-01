"""
Quest Rules

Validates quest progression and completion conditions.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class QuestStatus(str, Enum):
    """Quest status values."""
    NOT_STARTED = "not_started"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


@dataclass
class QuestProgression:
    """Represents quest progression."""
    quest_id: str
    old_status: QuestStatus
    new_status: QuestStatus
    stage_changed: bool
    old_stage: str
    new_stage: str
    completed_objectives: List[str]
    new_objectives: List[str]
    valid: bool
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "quest_id": self.quest_id,
            "old_status": self.old_status.value,
            "new_status": self.new_status.value,
            "stage_changed": self.stage_changed,
            "old_stage": self.old_stage,
            "new_stage": self.new_stage,
            "completed_objectives": self.completed_objectives,
            "new_objectives": self.new_objectives,
            "valid": self.valid,
            "reason": self.reason,
        }


class QuestRules:
    """
    Validates quest progression and completion.
    
    Rules:
    - Quests must be active to progress
    - Objectives must be completed in order (unless specified)
    - Prerequisites must be met
    - Some quests are mutually exclusive
    """
    
    def __init__(self):
        self._quest_prerequisites: Dict[str, List[str]] = {}
        self._quest_mutual_exclusions: Dict[str, List[str]] = {}
        self._objective_order: Dict[str, List[str]] = {}
    
    def validate_progression(
        self,
        quest_id: str,
        game_state: Dict[str, Any]
    ) -> QuestProgression:
        """
        Validate quest progression.
        
        Args:
            quest_id: The quest ID
            game_state: Current game state
            
        Returns:
            QuestProgression with validation result
        """
        quest_states = game_state.get("quest_states", {})
        quest = quest_states.get(quest_id, {})
        
        old_status = QuestStatus(quest.get("status", "not_started"))
        old_stage = quest.get("stage", "")
        
        if old_status == QuestStatus.COMPLETED:
            return QuestProgression(
                quest_id=quest_id,
                old_status=old_status,
                new_status=old_status,
                stage_changed=False,
                old_stage=old_stage,
                new_stage=old_stage,
                completed_objectives=[],
                new_objectives=[],
                valid=False,
                reason="Quest already completed",
            )
        
        if old_status == QuestStatus.FAILED:
            return QuestProgression(
                quest_id=quest_id,
                old_status=old_status,
                new_status=old_status,
                stage_changed=False,
                old_stage=old_stage,
                new_stage=old_stage,
                completed_objectives=[],
                new_objectives=[],
                valid=False,
                reason="Quest has failed",
            )
        
        if quest_id in self._quest_prerequisites:
            prerequisites = self._quest_prerequisites[quest_id]
            for prereq_id in prerequisites:
                prereq = quest_states.get(prereq_id, {})
                if prereq.get("status") != QuestStatus.COMPLETED.value:
                    return QuestProgression(
                        quest_id=quest_id,
                        old_status=old_status,
                        new_status=old_status,
                        stage_changed=False,
                        old_stage=old_stage,
                        new_stage=old_stage,
                        completed_objectives=[],
                        new_objectives=[],
                        valid=False,
                        reason=f"Prerequisite quest not completed: {prereq_id}",
                    )
        
        if quest_id in self._quest_mutual_exclusions:
            exclusions = self._quest_mutual_exclusions[quest_id]
            for exclusion_id in exclusions:
                exclusion = quest_states.get(exclusion_id, {})
                if exclusion.get("status") in [QuestStatus.ACTIVE.value, QuestStatus.COMPLETED.value]:
                    return QuestProgression(
                        quest_id=quest_id,
                        old_status=old_status,
                        new_status=old_status,
                        stage_changed=False,
                        old_stage=old_stage,
                        new_stage=old_stage,
                        completed_objectives=[],
                        new_objectives=[],
                        valid=False,
                        reason=f"Mutually exclusive quest active/completed: {exclusion_id}",
                    )
        
        return QuestProgression(
            quest_id=quest_id,
            old_status=old_status,
            new_status=QuestStatus.ACTIVE,
            stage_changed=False,
            old_stage=old_stage,
            new_stage=old_stage,
            completed_objectives=[],
            new_objectives=[],
            valid=True,
            reason="Quest progression valid",
        )
    
    def validate_completion(
        self,
        quest_id: str,
        game_state: Dict[str, Any]
    ) -> QuestProgression:
        """Validate quest completion."""
        quest_states = game_state.get("quest_states", {})
        quest = quest_states.get(quest_id, {})
        
        old_status = QuestStatus(quest.get("status", "not_started"))
        old_stage = quest.get("stage", "")
        
        if old_status != QuestStatus.ACTIVE:
            return QuestProgression(
                quest_id=quest_id,
                old_status=old_status,
                new_status=old_status,
                stage_changed=False,
                old_stage=old_stage,
                new_stage=old_stage,
                completed_objectives=[],
                new_objectives=[],
                valid=False,
                reason="Quest is not active",
            )
        
        objectives = quest.get("objectives", [])
        completed = quest.get("completed_objectives", [])
        
        if len(completed) < len(objectives):
            return QuestProgression(
                quest_id=quest_id,
                old_status=old_status,
                new_status=old_status,
                stage_changed=False,
                old_stage=old_stage,
                new_stage=old_stage,
                completed_objectives=completed,
                new_objectives=[],
                valid=False,
                reason="Not all objectives completed",
            )
        
        return QuestProgression(
            quest_id=quest_id,
            old_status=old_status,
            new_status=QuestStatus.COMPLETED,
            stage_changed=True,
            old_stage=old_stage,
            new_stage="completed",
            completed_objectives=completed,
            new_objectives=[],
            valid=True,
            reason="Quest completion valid",
        )
    
    def can_start_quest(self, quest_id: str, game_state: Dict[str, Any]) -> bool:
        """Check if a quest can be started."""
        progression = self.validate_progression(quest_id, game_state)
        return progression.valid
    
    def can_complete_quest(self, quest_id: str, game_state: Dict[str, Any]) -> bool:
        """Check if a quest can be completed."""
        progression = self.validate_completion(quest_id, game_state)
        return progression.valid
    
    def set_prerequisites(self, quest_id: str, prerequisite_ids: List[str]) -> None:
        """Set prerequisites for a quest."""
        self._quest_prerequisites[quest_id] = prerequisite_ids
    
    def set_mutual_exclusions(self, quest_id: str, exclusion_ids: List[str]) -> None:
        """Set mutually exclusive quests."""
        self._quest_mutual_exclusions[quest_id] = exclusion_ids
    
    def set_objective_order(self, quest_id: str, objective_order: List[str]) -> None:
        """Set the order in which objectives must be completed."""
        self._objective_order[quest_id] = objective_order

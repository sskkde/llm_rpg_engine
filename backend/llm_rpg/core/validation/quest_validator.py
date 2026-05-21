"""Quest Validator Module.

Validates quest-related actions including starting and progressing quests.

Validation checks:
- Quest not already completed/failed
- Stage transition validity (current stage allows target stage)
- Prerequisite quests completed
- Objective completion before stage progression
- Hidden objectives not referenced by player actions
"""

from typing import Any, Dict, List, Optional

from ...models.common import ValidationResult
from ...models.states import QuestState
from .context import ValidationContext
from .result import passed_result, failed_result, combine_results


class QuestValidator:
    """Validator for quest start and progression actions.

    Validates that:
    - Quests can only be started/progressed if not completed or failed
    - Stage transitions follow allowed paths (next_possible_stages)
    - Prerequisite quests are completed before starting
    - All objectives for current stage are met before progressing
    - Hidden objectives are not directly referenced by player actions
    """

    def validate_quest_start(
        self,
        action: Any,
        quest_state: QuestState,
        quest_template: Optional[Dict[str, Any]] = None,
        all_quest_states: Optional[Dict[str, QuestState]] = None,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Validate starting a quest.

        Checks:
        1. Quest is not already completed or failed
        2. Prerequisite quests are completed

        Args:
            action: The proposed action triggering quest start
            quest_state: Current quest state
            quest_template: Quest template with metadata (prerequisites, etc.)
            all_quest_states: All quest states for prerequisite checking
            context: Optional validation context

        Returns:
            ValidationResult indicating if quest can be started
        """
        results: List[ValidationResult] = []

        results.append(self._check_quest_status(quest_state, "start"))
        results.append(self._check_prerequisites(quest_state, quest_template, all_quest_states))

        return combine_results(results)

    def validate_quest_progress(
        self,
        action: Any,
        quest_state: QuestState,
        quest_template: Optional[Dict[str, Any]] = None,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Validate quest stage progression.

        Checks:
        1. Quest is not completed or failed (must be active)
        2. Stage transition is valid (target in next_possible_stages)
        3. All objectives for current stage are completed
        4. Hidden objectives are not directly referenced by player action

        Args:
            action: The proposed action triggering quest progress
            quest_state: Current quest state
            quest_template: Quest template with stage/objective definitions
            context: Optional validation context

        Returns:
            ValidationResult indicating if progression is valid
        """
        if quest_state is None:
            return passed_result("quest_progress_validation", "No quest state to validate (placeholder)")

        results: List[ValidationResult] = []

        results.append(self._check_quest_status(quest_state, "progress"))

        target_stage = self._extract_target_stage(action)
        if target_stage is not None:
            results.append(self._check_stage_transition(quest_state, target_stage))

        results.append(self._check_objective_completion(quest_state, quest_template))
        results.append(self._check_hidden_objective_reference(action, quest_state))

        return combine_results(results)

    def _check_quest_status(
        self,
        quest_state: QuestState,
        operation: str,
    ) -> ValidationResult:
        """Check that quest is not completed or failed.

        Args:
            quest_state: Current quest state
            operation: "start" or "progress" for error messages

        Returns:
            ValidationResult for status check
        """
        if quest_state.status == "completed":
            return failed_result(
                "quest_status_check",
                f"Cannot {operation} quest '{quest_state.quest_id}': quest already completed",
            )
        if quest_state.status == "failed":
            return failed_result(
                "quest_status_check",
                f"Cannot {operation} quest '{quest_state.quest_id}': quest has failed",
            )
        return passed_result(
            "quest_status_check",
            f"Quest '{quest_state.quest_id}' status '{quest_state.status}' allows {operation}",
        )

    def _check_prerequisites(
        self,
        quest_state: QuestState,
        quest_template: Optional[Dict[str, Any]],
        all_quest_states: Optional[Dict[str, QuestState]],
    ) -> ValidationResult:
        """Check that prerequisite quests are completed.

        Args:
            quest_state: Current quest state
            quest_template: Quest template with prerequisite_quest_ids
            all_quest_states: All quest states for lookup

        Returns:
            ValidationResult for prerequisite check
        """
        if quest_template is None:
            return passed_result("prerequisite_check", "No quest template provided, skipping prerequisite check")

        prerequisite_ids = quest_template.get("prerequisite_quest_ids", [])
        if not prerequisite_ids:
            return passed_result("prerequisite_check", "No prerequisites required")

        if all_quest_states is None:
            return passed_result(
                "prerequisite_check",
                "No quest states provided for prerequisite verification, allowing by default",
            )

        for prereq_id in prerequisite_ids:
            prereq_state = all_quest_states.get(prereq_id)
            if prereq_state is None or prereq_state.status != "completed":
                return failed_result(
                    "prerequisite_check",
                    f"Prerequisite quest '{prereq_id}' not completed",
                )

        return passed_result(
            "prerequisite_check",
            f"All prerequisites satisfied for quest '{quest_state.quest_id}'",
        )

    def _check_stage_transition(
        self,
        quest_state: QuestState,
        target_stage: str,
    ) -> ValidationResult:
        """Check that stage transition is valid via next_possible_stages.

        Args:
            quest_state: Current quest state with next_possible_stages
            target_stage: The stage the action wants to transition to

        Returns:
            ValidationResult for stage transition check
        """
        if not quest_state.next_possible_stages:
            return failed_result(
                "stage_transition_check",
                f"No allowed next stages from current stage '{quest_state.stage}'",
            )

        if target_stage not in quest_state.next_possible_stages:
            return failed_result(
                "stage_transition_check",
                f"Invalid stage transition: '{target_stage}' is not in next_possible_stages "
                f"{quest_state.next_possible_stages} from stage '{quest_state.stage}'",
            )

        return passed_result(
            "stage_transition_check",
            f"Valid stage transition: '{quest_state.stage}' -> '{target_stage}'",
        )

    def _check_objective_completion(
        self,
        quest_state: QuestState,
        quest_template: Optional[Dict[str, Any]],
    ) -> ValidationResult:
        """Check that all objectives for current stage are completed.

        Uses quest_template to determine required objectives for the current
        stage, then verifies they are all in known_objectives (completed).

        Args:
            quest_state: Current quest state with known_objectives
            quest_template: Quest template with stage objective definitions

        Returns:
            ValidationResult for objective completion check
        """
        if quest_template is None:
            return passed_result(
                "objective_completion_check",
                "No quest template provided, skipping objective completion check",
            )

        stage_objectives = self._get_stage_objectives(quest_state.stage, quest_template)
        if not stage_objectives:
            return passed_result(
                "objective_completion_check",
                f"No required objectives defined for stage '{quest_state.stage}'",
            )

        completed = set(quest_state.known_objectives)
        incomplete = [obj for obj in stage_objectives if obj not in completed]

        if incomplete:
            return failed_result(
                "objective_completion_check",
                f"Objectives not met for stage '{quest_state.stage}': {incomplete}",
            )

        return passed_result(
            "objective_completion_check",
            f"All objectives completed for stage '{quest_state.stage}'",
        )

    def _check_hidden_objective_reference(
        self,
        action: Any,
        quest_state: QuestState,
    ) -> ValidationResult:
        """Check that player action does not directly reference hidden objectives.

        If a player action's summary or intention mentions a hidden objective
        by ID or name, the action is rejected — the player should not know
        about hidden objectives.

        Args:
            action: The proposed action
            quest_state: Current quest state with hidden_objectives

        Returns:
            ValidationResult for hidden objective reference check
        """
        if not quest_state.hidden_objectives:
            return passed_result(
                "hidden_objective_check",
                "No hidden objectives to check",
            )

        action_text = self._get_action_text(action).lower()

        for hidden_obj in quest_state.hidden_objectives:
            # Check both the objective ID and a normalized version of its text
            if hidden_obj.lower() in action_text:
                return failed_result(
                    "hidden_objective_check",
                    f"Player action references hidden objective: '{hidden_obj}'",
                )

        return passed_result(
            "hidden_objective_check",
            "No hidden objectives referenced by player action",
        )

    def _extract_target_stage(self, action: Any) -> Optional[str]:
        """Extract target stage from action's state_delta_candidates.

        Looks for quest stage changes in the action's state_delta_candidates.

        Args:
            action: The proposed action

        Returns:
            Target stage string if found, None otherwise
        """
        if not hasattr(action, "state_delta_candidates"):
            return None

        for delta in action.state_delta_candidates:
            if isinstance(delta, dict):
                path = delta.get("path", "")
                if "stage" in path and "quest" in path:
                    new_value = delta.get("new_value")
                    if new_value is not None:
                        return str(new_value)
                if "stage" in delta and "new_value" in delta:
                    return str(delta["new_value"])

        if hasattr(action, "target_ids") and action.target_ids:
            for tid in action.target_ids:
                if tid.startswith("stage_"):
                    return tid.replace("stage_", "", 1)

        return None

    def _get_stage_objectives(
        self,
        stage: str,
        quest_template: Dict[str, Any],
    ) -> List[str]:
        """Get required objectives for a stage from quest template.

        Args:
            stage: Current stage identifier
            quest_template: Quest template with stage definitions

        Returns:
            List of objective IDs required for the stage
        """
        stage_objectives = quest_template.get("stage_objectives", {})
        if stage_objectives:
            return stage_objectives.get(stage, [])

        stages = quest_template.get("stages", [])
        if isinstance(stages, list):
            for s in stages:
                if isinstance(s, dict) and s.get("id") == stage:
                    return s.get("objectives", [])
            return []
        if isinstance(stages, dict):
            stage_info = stages.get(stage, {})
            if isinstance(stage_info, dict):
                return stage_info.get("objectives", [])
            return []

        return []

    def _get_action_text(self, action: Any) -> str:
        """Extract text content from an action for string matching.

        Args:
            action: The proposed action

        Returns:
            Combined text from action summary and intention
        """
        parts = []
        if hasattr(action, "summary") and action.summary:
            parts.append(action.summary)
        if hasattr(action, "intention") and action.intention:
            parts.append(action.intention)
        return " ".join(parts)


__all__ = ["QuestValidator"]

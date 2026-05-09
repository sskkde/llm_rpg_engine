"""State Delta Validator.

This module provides validation for state delta operations before they are committed.
All state changes must pass through this validator to ensure integrity.

Validation checks:
1. source_event_id - must be non-empty (unless exception)
2. path - must be in allowed whitelist and not in blocked list
3. operation - must be in allowed operations list
4. old_value - must match current state (for non-exception sources)
5. numeric bounds - values must be within defined constraints
"""

from typing import Any

from ...models.common import ValidationCheck, ValidationResult
from ...models.states import CanonicalState
from .state_delta_contract import (
    ALLOWED_OPERATIONS,
    get_numeric_bounds,
    is_operation_allowed,
    is_path_allowed,
    is_source_event_id_exception,
)


class StateDeltaValidator:
    """Validator for state delta operations.

    Validates that state changes conform to the contract defined in
    state_delta_contract.py. This ensures that only valid modifications
    are applied to the game state.
    """

    def validate(
        self,
        path: str,
        operation: str,
        old_value: Any,
        new_value: Any,
        current_state: CanonicalState | None = None,
        source_event_id: str | None = None,
    ) -> ValidationResult:
        """Validate a state delta operation.

        Args:
            path: The state path being modified (e.g., "player_state.hp")
            operation: The operation type (e.g., "set", "increment")
            old_value: The previous value (for verification)
            new_value: The new value to be set
            current_state: The current canonical state (for old_value verification)
            source_event_id: The ID of the event that triggered this delta

        Returns:
            ValidationResult with is_valid, checks, and errors
        """
        checks: list[ValidationCheck] = []
        errors: list[str] = []

        # 1. Check source_event_id (unless it's an exception)
        source_check = self._validate_source_event_id(source_event_id)
        checks.append(source_check)
        if not source_check.passed:
            errors.append(source_check.reason)

        # 2. Check path is allowed
        path_check = self._validate_path(path)
        checks.append(path_check)
        if not path_check.passed:
            errors.append(path_check.reason)

        # 3. Check operation is allowed
        operation_check = self._validate_operation(operation)
        checks.append(operation_check)
        if not operation_check.passed:
            errors.append(operation_check.reason)

        # 4. Check old_value matches current state (if state provided and not exception)
        is_exception = is_source_event_id_exception(source_event_id)
        if current_state is not None and not is_exception:
            old_value_check = self._validate_old_value(path, old_value, current_state)
            checks.append(old_value_check)
            if not old_value_check.passed:
                errors.append(old_value_check.reason)

        # 5. Check numeric bounds (if applicable)
        bounds = get_numeric_bounds(path)
        if bounds is not None and isinstance(new_value, (int, float)):
            bounds_check = self._validate_numeric_bounds(path, new_value, bounds)
            checks.append(bounds_check)
            if not bounds_check.passed:
                errors.append(bounds_check.reason)

        return ValidationResult(
            is_valid=len(errors) == 0,
            checks=checks,
            errors=errors,
        )

    def _validate_source_event_id(self, source_event_id: str | None) -> ValidationCheck:
        """Validate that source_event_id is present (unless exception)."""
        if source_event_id is None:
            return ValidationCheck(
                check_name="source_event_id",
                passed=False,
                reason="source_event_id is required",
                severity="error",
            )

        if is_source_event_id_exception(source_event_id):
            return ValidationCheck(
                check_name="source_event_id",
                passed=True,
                reason=f"source_event_id '{source_event_id}' is an exception value",
                severity="info",
            )

        return ValidationCheck(
            check_name="source_event_id",
            passed=True,
            reason="source_event_id is valid",
        )

    def _validate_path(self, path: str) -> ValidationCheck:
        """Validate that path is in allowed list and not blocked."""
        if not path:
            return ValidationCheck(
                check_name="path",
                passed=False,
                reason="path must be a non-empty string",
                severity="error",
            )

        if not is_path_allowed(path):
            return ValidationCheck(
                check_name="path",
                passed=False,
                reason=f"path '{path}' is not allowed",
                severity="error",
            )

        return ValidationCheck(
            check_name="path",
            passed=True,
            reason=f"path '{path}' is allowed",
        )

    def _validate_operation(self, operation: str) -> ValidationCheck:
        """Validate that operation is in allowed list."""
        if not operation:
            return ValidationCheck(
                check_name="operation",
                passed=False,
                reason="operation must be a non-empty string",
                severity="error",
            )

        if not is_operation_allowed(operation):
            return ValidationCheck(
                check_name="operation",
                passed=False,
                reason=f"operation '{operation}' is not allowed. Allowed: {ALLOWED_OPERATIONS}",
                severity="error",
            )

        return ValidationCheck(
            check_name="operation",
            passed=True,
            reason=f"operation '{operation}' is allowed",
        )

    def _validate_old_value(
        self, path: str, old_value: Any, current_state: CanonicalState
    ) -> ValidationCheck:
        """Validate that old_value matches current state."""
        try:
            current_value = self._get_current_value(path, current_state)
            if current_value != old_value:
                return ValidationCheck(
                    check_name="old_value",
                    passed=False,
                    reason=f"old_value mismatch: expected {current_value}, got {old_value}",
                    severity="error",
                )
            return ValidationCheck(
                check_name="old_value",
                passed=True,
                reason="old_value matches current state",
            )
        except (ValueError, AttributeError, KeyError) as e:
            # If we can't get current value, pass the check (path may be new)
            return ValidationCheck(
                check_name="old_value",
                passed=True,
                reason=f"could not verify old_value: {str(e)}",
                severity="warning",
            )

    def _validate_numeric_bounds(
        self, path: str, value: Any, bounds: tuple[int | None, int | None]
    ) -> ValidationCheck:
        """Validate that numeric value is within bounds."""
        min_val, max_val = bounds

        if min_val is not None and value < min_val:
            return ValidationCheck(
                check_name="numeric_bounds",
                passed=False,
                reason=f"value {value} is below minimum {min_val} for path '{path}'",
                severity="error",
            )

        if max_val is not None and value > max_val:
            return ValidationCheck(
                check_name="numeric_bounds",
                passed=False,
                reason=f"value {value} is above maximum {max_val} for path '{path}'",
                severity="error",
            )

        return ValidationCheck(
            check_name="numeric_bounds",
            passed=True,
            reason=f"value {value} is within bounds {bounds}",
        )

    def _get_current_value(self, path: str, current_state: CanonicalState) -> Any:
        """Get current value from canonical state by path.

        Path format: "entity_type.field_name" or "entity_type.entity_id.field_name"
        Examples:
            - "player_state.hp" -> current_state.player_state.hp
            - "npc_state.npc_001.trust_score" -> current_state.npc_states["npc_001"].mental_state.trust_toward_player * 100
        """
        parts = path.split(".")
        if len(parts) < 2:
            raise ValueError(f"Invalid path format: {path}")

        entity_type = parts[0]

        # Handle different entity types
        if entity_type == "player_state":
            return self._get_player_state_value(parts[1:], current_state)
        elif entity_type == "session_state":
            return self._get_session_state_value(parts[1:], current_state)
        elif entity_type == "npc_state":
            return self._get_npc_state_value(parts[1:], current_state)
        elif entity_type == "world_state":
            return self._get_world_state_value(parts[1:], current_state)
        elif entity_type == "quest_state":
            return self._get_quest_state_value(parts[1:], current_state)
        else:
            # Try generic path resolution
            return current_state.get_state_by_path(path)

    def _get_player_state_value(self, field_parts: list[str], state: CanonicalState) -> Any:
        """Get value from player state."""
        if not field_parts:
            raise ValueError("Missing field in player_state path")

        field = field_parts[0]
        player = state.player_state

        # Map contract paths to actual model fields
        field_mapping = {
            "hp": "hp",  # Note: PlayerState doesn't have hp directly, it's in physical attributes
            "stamina": None,  # Not directly in PlayerState
            "spirit_power": "spiritual_power",
            "realm": "realm",
            "experience": None,  # Not directly in PlayerState
            "gold": None,  # Not directly in PlayerState
            "inventory": "inventory_ids",
            "learned_techniques": None,
            "completed_quests": None,
            "reputation": None,
        }

        if field in field_mapping:
            mapped_field = field_mapping[field]
            if mapped_field is None:
                # Field not in current model, return None to allow any old_value
                return None
            return getattr(player, mapped_field, None)

        # Try direct attribute access
        return getattr(player, field, None)

    def _get_session_state_value(self, field_parts: list[str], state: CanonicalState) -> Any:
        """Get value from session state (stored in world_state or current_scene_state)."""
        if not field_parts:
            raise ValueError("Missing field in session_state path")

        field = field_parts[0]

        if field == "current_location_id":
            return state.current_scene_state.location_id
        elif field == "world_time":
            return state.world_state.current_time
        elif field == "current_chapter_id":
            # Not directly available, return None
            return None
        elif field == "flags":
            # Wildcard pattern, return the flags dict
            return state.player_state.flags

        return None

    def _get_npc_state_value(self, field_parts: list[str], state: CanonicalState) -> Any:
        """Get value from NPC state."""
        if len(field_parts) < 2:
            raise ValueError("NPC path requires npc_id and field")

        npc_id = field_parts[0]
        field = field_parts[1]

        if npc_id not in state.npc_states:
            # NPC doesn't exist yet, return None to allow any old_value
            return None

        npc = state.npc_states[npc_id]

        # Map contract paths to actual model fields
        if field == "trust_score":
            # Convert from 0-1 to 0-100 scale
            return int(npc.mental_state.trust_toward_player * 100)
        elif field == "suspicion_score":
            # Convert from 0-1 to 0-100 scale
            return int(npc.mental_state.suspicion_toward_player * 100)
        elif field == "current_location_id":
            return npc.location_id
        elif field == "affinity":
            # Not directly available
            return None
        elif field == "dialogue_state":
            return npc.current_action
        elif field == "quest_progress":
            # Not directly available
            return None

        return getattr(npc, field, None)

    def _get_world_state_value(self, field_parts: list[str], state: CanonicalState) -> Any:
        """Get value from world state."""
        if not field_parts:
            raise ValueError("Missing field in world_state path")

        field = field_parts[0]
        world = state.world_state

        if field == "weather":
            return world.weather
        elif field == "time_of_day":
            return world.current_time
        elif field == "global_flags":
            return world.global_flags

        return getattr(world, field, None)

    def _get_quest_state_value(self, field_parts: list[str], state: CanonicalState) -> Any:
        """Get value from quest state."""
        if len(field_parts) < 2:
            raise ValueError("Quest path requires quest_id and field")

        quest_id = field_parts[0]
        field = field_parts[1]

        if quest_id not in state.quest_states:
            return None

        quest = state.quest_states[quest_id]

        if field == "status":
            return quest.status
        elif field == "current_step":
            return quest.stage
        elif field == "objectives":
            return quest.known_objectives

        return getattr(quest, field, None)

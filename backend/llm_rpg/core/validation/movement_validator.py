"""Movement Validator Module.

Validates movement actions against five checks:
1. Target location exists in state.location_states
2. Target location is known/discovered by the player
3. Path is not blocked (current_scene_state.blocked_paths)
4. Access rules are met (danger_level, quest_stage overrides)
5. Player has sufficient stamina (fatigue < threshold)
"""

from typing import Optional

from ...models.common import ProposedAction, ValidationResult
from ...models.states import CanonicalState
from ...models.perspectives import PlayerPerspective, Perspective
from .context import ValidationContext
from .result import passed_result, failed_result, combine_results


# Spiritual power threshold: movement blocked when spiritual_power <= this value
STAMINA_THRESHOLD = 10

# Danger level threshold: locations above this require quest override
DANGER_LEVEL_THRESHOLD = 0.7

# Quest stage values that grant access to high-danger locations
DANGER_QUEST_STAGES = {"ready_to_enter", "in_progress", "completed"}


class MovementValidator:
    """Validator for movement actions.

    Checks location existence, discovery status, path blocking,
    access rules, and stamina before allowing movement.
    """

    def validate_movement(
        self,
        action: ProposedAction,
        state: CanonicalState,
        perspective: Optional[Perspective] = None,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Validate a movement action.

        Args:
            action: The proposed movement action (action_type="move")
            state: Current canonical state
            perspective: Optional player/NPC perspective for known-location check
            context: Optional validation context (overrides state/perspective)

        Returns:
            ValidationResult with all check outcomes combined
        """
        if context is not None:
            state = context.canonical_state
            if context.perspective is not None:
                perspective = context.perspective

        if not action.target_ids:
            return failed_result(
                "movement_target",
                "Movement action requires a target location",
            )

        target_location_id = action.target_ids[0]
        results: list[ValidationResult] = []

        # Check 1: Target location exists
        results.append(self._check_location_exists(target_location_id, state))

        # Early exit if location doesn't exist — no point checking further
        if not results[-1].is_valid:
            return results[-1]

        # Check 2: Target location is known/discovered by player
        results.append(self._check_location_known(target_location_id, state, perspective))

        # Check 3: Path not blocked
        results.append(self._check_path_not_blocked(target_location_id, state))

        # Check 4: Access rules (danger_level, quest_stage)
        results.append(self._check_access_rules(target_location_id, state))

        # Check 5: Stamina/fatigue
        results.append(self._check_stamina(state))

        return combine_results(results)

    def _check_location_exists(
        self,
        target_location_id: str,
        state: CanonicalState,
    ) -> ValidationResult:
        if target_location_id not in state.location_states:
            return failed_result(
                "location_existence",
                f"Target location {target_location_id} does not exist",
            )
        return passed_result("location_existence", "Target location exists")

    def _check_location_known(
        self,
        target_location_id: str,
        state: CanonicalState,
        perspective: Optional[Perspective],
    ) -> ValidationResult:
        # Check via PlayerPerspective.discovered_locations first
        if isinstance(perspective, PlayerPerspective):
            if target_location_id in perspective.discovered_locations:
                return passed_result("location_known", "Location is discovered (perspective)")
            return failed_result(
                "location_known",
                f"Location {target_location_id} has not been discovered by the player",
            )

        # Fallback: check player_state.flags for discovered_{location_id}
        flag_key = f"discovered_{target_location_id}"
        if state.player_state.flags.get(flag_key, False):
            return passed_result("location_known", "Location is discovered (flags)")

        # Also check LocationState.known_to_player
        loc_state = state.location_states.get(target_location_id)
        if loc_state and loc_state.known_to_player:
            return passed_result("location_known", "Location is known to player")

        # If explicit perspective was provided (but not PlayerPerspective), enforce strictly
        if perspective is not None:
            return failed_result(
                "location_known",
                f"Location {target_location_id} has not been discovered",
            )

        # No perspective available (internal engine call) — skip check
        return passed_result("location_known", "Location known (no perspective)")

    def _check_path_not_blocked(
        self,
        target_location_id: str,
        state: CanonicalState,
    ) -> ValidationResult:
        blocked_paths = state.current_scene_state.blocked_paths
        if target_location_id in blocked_paths:
            return failed_result(
                "path_blocked",
                f"Path to {target_location_id} is blocked by current scene",
            )
        return passed_result("path_blocked", "Path is not blocked")

    def _check_access_rules(
        self,
        target_location_id: str,
        state: CanonicalState,
    ) -> ValidationResult:
        loc_state = state.location_states.get(target_location_id)
        if not loc_state:
            return passed_result("access_rules", "No location state to check")

        # Danger level check
        if loc_state.danger_level > DANGER_LEVEL_THRESHOLD:
            # Check if player has an active quest that grants access
            for quest in state.quest_states.values():
                if (
                    quest.status == "active"
                    and quest.stage in DANGER_QUEST_STAGES
                ):
                    return passed_result(
                        "access_rules",
                        f"Dangerous location access granted by quest {quest.quest_id}",
                    )

            return failed_result(
                "access_rules",
                f"Location {target_location_id} danger level "
                f"({loc_state.danger_level:.1f}) exceeds threshold "
                f"({DANGER_LEVEL_THRESHOLD:.1f}) without qualifying quest",
            )

        return passed_result("access_rules", "Access rules satisfied")

    def _check_stamina(
        self,
        state: CanonicalState,
    ) -> ValidationResult:
        sp = state.player_state.spiritual_power
        if sp <= STAMINA_THRESHOLD:
            return failed_result(
                "stamina_check",
                f"Player too exhausted to move (spiritual_power: {sp}, threshold: {STAMINA_THRESHOLD})",
            )
        return passed_result("stamina_check", "Player has sufficient stamina")


__all__ = ["MovementValidator", "STAMINA_THRESHOLD", "DANGER_LEVEL_THRESHOLD"]

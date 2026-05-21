"""Unit tests for MovementValidator.

Tests the full movement validation pipeline including:
1. Location existence check
2. Known locations check (player has discovered the location)
3. Path blocking check (blocked_paths in current scene)
4. Access rules check (danger_level, quest_stage, faction_standing)
5. Stamina/fatigue check
"""

import pytest

from llm_rpg.core.validation.movement_validator import MovementValidator, STAMINA_THRESHOLD
from llm_rpg.core.validation.result import passed_result, failed_result
from llm_rpg.models.common import ProposedAction, ValidationResult
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    LocationState,
    QuestState,
    FactionState,
    WorldTime,
)
from llm_rpg.models.perspectives import PlayerPerspective, PerspectiveType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_world_time() -> WorldTime:
    return WorldTime(calendar="修仙历", season="春", day=1, period="辰时")


def _make_base_state(
    *,
    player_location: str = "loc_tavern",
    spiritual_power: int = 100,
    player_flags: dict | None = None,
    location_states: dict | None = None,
    blocked_paths: list | None = None,
    scene_danger_level: float = 0.0,
    quest_states: dict | None = None,
    faction_states: dict | None = None,
) -> CanonicalState:
    """Create a CanonicalState with sensible defaults for movement tests."""
    if location_states is None:
        location_states = {
            "loc_tavern": LocationState(
                entity_id="loc_tavern",
                location_id="loc_tavern",
                name="客栈",
                known_to_player=True,
            ),
            "loc_forest": LocationState(
                entity_id="loc_forest",
                location_id="loc_forest",
                name="密林",
                known_to_player=True,
                danger_level=0.3,
            ),
            "loc_danger_zone": LocationState(
                entity_id="loc_danger_zone",
                location_id="loc_danger_zone",
                name="禁地",
                known_to_player=True,
                danger_level=0.9,
            ),
            "loc_unknown": LocationState(
                entity_id="loc_unknown",
                location_id="loc_unknown",
                name="未知区域",
                known_to_player=False,
            ),
        }

    return CanonicalState(
        player_state=PlayerState(
            entity_id="player",
            name="测试玩家",
            location_id=player_location,
            spiritual_power=spiritual_power,
            flags=player_flags or {},
        ),
        world_state=WorldState(
            entity_id="world",
            world_id="world_1",
            current_time=_make_world_time(),
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene",
            scene_id="scene_1",
            location_id=player_location,
            blocked_paths=blocked_paths or [],
            danger_level=scene_danger_level,
        ),
        location_states=location_states,
        quest_states=quest_states or {},
        faction_states=faction_states or {},
    )


def _make_move_action(
    target_location: str = "loc_forest",
    actor_id: str = "player",
) -> ProposedAction:
    return ProposedAction(
        action_id="action_move_1",
        actor_id=actor_id,
        action_type="move",
        target_ids=[target_location],
        summary=f"Move to {target_location}",
    )


def _make_player_perspective(
    discovered_locations: list | None = None,
) -> PlayerPerspective:
    return PlayerPerspective(
        perspective_id="perspective_player",
        perspective_type=PerspectiveType.PLAYER,
        owner_id="player",
        discovered_locations=discovered_locations
        if discovered_locations is not None
        else ["loc_tavern", "loc_forest", "loc_danger_zone"],
    )


# ---------------------------------------------------------------------------
# Test 1: Valid movement to known accessible location
# ---------------------------------------------------------------------------

class TestValidMovement:
    """Movement should succeed when all checks pass."""

    def test_valid_movement_all_checks_pass(self):
        state = _make_base_state(player_location="loc_tavern")
        action = _make_move_action(target_location="loc_forest")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_valid_movement_no_perspective_still_passes(self):
        """Without perspective, known-location check uses state flags."""
        state = _make_base_state(
            player_location="loc_tavern",
            player_flags={"discovered_loc_forest": True},
        )
        action = _make_move_action(target_location="loc_forest")

        validator = MovementValidator()
        result = validator.validate_movement(action, state)

        assert result.is_valid is True


# ---------------------------------------------------------------------------
# Test 2: Blocked by path (blocked_paths check)
# ---------------------------------------------------------------------------

class TestBlockedPath:
    """Movement should fail when the target is in blocked_paths."""

    def test_blocked_path_in_current_scene(self):
        state = _make_base_state(
            player_location="loc_tavern",
            blocked_paths=["loc_forest"],
        )
        action = _make_move_action(target_location="loc_forest")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is False
        assert any("blocked" in e.lower() or "path" in e.lower() for e in result.errors)

    def test_not_blocked_when_path_absent(self):
        state = _make_base_state(
            player_location="loc_tavern",
            blocked_paths=["loc_danger_zone"],
        )
        action = _make_move_action(target_location="loc_forest")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is True


# ---------------------------------------------------------------------------
# Test 3: Blocked by access rules (danger_level too high)
# ---------------------------------------------------------------------------

class TestAccessRules:
    """Movement should fail when access rules are not met."""

    def test_danger_level_too_high(self):
        """Target location with high danger_level should block movement
        when the player doesn't have sufficient quest progression."""
        state = _make_base_state(
            player_location="loc_tavern",
            # danger_level 0.9 on loc_danger_zone is already set in defaults
        )
        action = _make_move_action(target_location="loc_danger_zone")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        # Default threshold is 0.7; loc_danger_zone has 0.9
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is False
        assert any("danger" in e.lower() or "access" in e.lower() for e in result.errors)

    def test_danger_level_passes_when_low(self):
        """Low danger_level location should not block."""
        state = _make_base_state(player_location="loc_tavern")
        action = _make_move_action(target_location="loc_forest")  # danger 0.3
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is True

    def test_quest_stage_allows_dangerous_location(self):
        """Player with qualifying quest stage can enter high-danger location."""
        quest_states = {
            "quest_explore_danger": QuestState(
                entity_id="quest_explore_danger",
                quest_id="quest_explore_danger",
                name="探索禁地",
                stage="ready_to_enter",
                status="active",
            ),
        }
        state = _make_base_state(
            player_location="loc_tavern",
            quest_states=quest_states,
        )
        action = _make_move_action(target_location="loc_danger_zone")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        # With active quest for the dangerous area, should be allowed
        assert result.is_valid is True


# ---------------------------------------------------------------------------
# Test 4: Blocked by stamina (player too fatigued)
# ---------------------------------------------------------------------------

class TestStaminaCheck:
    """Movement should fail when player fatigue is too high."""

    def test_fatigue_too_high(self):
        state = _make_base_state(
            player_location="loc_tavern",
            spiritual_power=5,
        )

        action = _make_move_action(target_location="loc_forest")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is False
        assert any("stamina" in e.lower() or "exhausted" in e.lower() for e in result.errors)

    def test_fatigue_at_threshold_passes(self):
        """Spiritual power just above threshold should still allow movement."""
        state = _make_base_state(
            player_location="loc_tavern",
            spiritual_power=STAMINA_THRESHOLD + 1,
        )

        action = _make_move_action(target_location="loc_forest")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is True

    def test_low_fatigue_passes(self):
        state = _make_base_state(
            player_location="loc_tavern",
            spiritual_power=80,
        )

        action = _make_move_action(target_location="loc_forest")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is True


# ---------------------------------------------------------------------------
# Test 5: Invalid target location (doesn't exist)
# ---------------------------------------------------------------------------

class TestInvalidTargetLocation:
    """Movement should fail when target location doesn't exist in state."""

    def test_nonexistent_target_location(self):
        state = _make_base_state(player_location="loc_tavern")
        action = _make_move_action(target_location="loc_nonexistent")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is False
        assert any("does not exist" in e.lower() or "not found" in e.lower() for e in result.errors)

    def test_empty_target_ids_fails(self):
        """Movement action with no target_ids should fail."""
        state = _make_base_state(player_location="loc_tavern")
        action = ProposedAction(
            action_id="action_move_empty",
            actor_id="player",
            action_type="move",
            target_ids=[],
            summary="Move somewhere",
        )

        validator = MovementValidator()
        result = validator.validate_movement(action, state)

        assert result.is_valid is False


# ---------------------------------------------------------------------------
# Test: Unknown location (not discovered by player)
# ---------------------------------------------------------------------------

class TestUnknownLocation:
    """Movement to a location the player hasn't discovered should fail."""

    def test_undiscovered_location_without_perspective(self):
        """Without perspective, known-location check is skipped (internal engine call)."""
        state = _make_base_state(
            player_location="loc_tavern",
            player_flags={},  # no discovered flags
        )
        action = _make_move_action(target_location="loc_unknown")

        validator = MovementValidator()
        result = validator.validate_movement(action, state)

        assert result.is_valid is True

    def test_undiscovered_location_with_perspective(self):
        """With PlayerPerspective, undiscovered locations are rejected."""
        state = _make_base_state(player_location="loc_tavern")
        action = _make_move_action(target_location="loc_unknown")
        perspective = _make_player_perspective(
            discovered_locations=["loc_tavern", "loc_forest"],
        )

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective=perspective)

        assert result.is_valid is False

    def test_discovered_via_flags_passes(self):
        """Location discovered via player flags should pass."""
        state = _make_base_state(
            player_location="loc_tavern",
            player_flags={"discovered_loc_unknown": True},
        )
        action = _make_move_action(target_location="loc_unknown")

        validator = MovementValidator()
        result = validator.validate_movement(action, state)

        assert result.is_valid is True


# ---------------------------------------------------------------------------
# Test: Combined checks produce multiple errors
# ---------------------------------------------------------------------------

class TestCombinedChecks:
    """Multiple failing checks should all be reported."""

    def test_multiple_failures_reported(self):
        """Both stamina and blocked path should appear in errors."""
        state = _make_base_state(
            player_location="loc_tavern",
            blocked_paths=["loc_forest"],
            spiritual_power=5,
        )

        action = _make_move_action(target_location="loc_forest")
        perspective = _make_player_perspective()

        validator = MovementValidator()
        result = validator.validate_movement(action, state, perspective)

        assert result.is_valid is False
        # Should have at least 2 errors (blocked path + stamina)
        assert len(result.errors) >= 2

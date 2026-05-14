"""Scenario tests for World Time and Area Summary functionality.

Tests that:
1. World time advances correctly after each player action
2. World time advances correctly after NPC actions
3. Time-based events trigger at correct time thresholds
4. Area summary updates for non-current areas correctly
5. Seal/countdown timers advance with world time
"""

import pytest
from typing import Any

from llm_rpg.observability.scenario_runner import (
    ScenarioRunner,
    ScenarioType,
)
from tests.conftest import MockLLMProvider


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestWorldTimeProgression:
    """Test world time progression scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_world_time_advances_after_player_action(self):
        """Test that world time advances correctly after each player action."""
        result = self.runner.run_scenario(
            ScenarioType.WORLD_TIME_PROGRESSION,
            "session_time_001",
            custom_setup={
                "initial_day": 1,
                "initial_hour": 8,
                "actions_count": 3,
            }
        )
        
        assert result is not None
        assert result.scenario_type == ScenarioType.WORLD_TIME_PROGRESSION
        assert result.status == "passed"
        
        # Verify time initialization step
        init_step = next((s for s in result.steps if s.action == "initialize_world_time"), None)
        assert init_step is not None
        assert init_step.passed is True
        assert "Day 1" in init_step.actual_result
        assert "Hour 8" in init_step.actual_result
        
        # Verify actions execution step
        actions_step = next((s for s in result.steps if s.action == "execute_actions"), None)
        assert actions_step is not None
        assert actions_step.passed is True
        assert "3 actions" in actions_step.actual_result
        
        # Verify time advanced step
        verify_step = next((s for s in result.steps if s.action == "verify_time_advanced"), None)
        assert verify_step is not None
        assert verify_step.passed is True
        # After 3 actions from hour 8, should be hour 11
        assert "Hour 11" in verify_step.actual_result

    @pytest.mark.smoke
    def test_world_time_advances_after_npc_actions(self):
        """Test that world time advances correctly after NPC actions."""
        result = self.runner.run_custom_scenario(
            "world_time_npc_actions",
            "session_time_npc_001",
            steps=[
                {
                    "action": "setup_npc_turn",
                    "input_data": {
                        "npc_id": "npc_villager_001",
                        "current_time": {"day": 1, "hour": 10},
                    },
                    "expected": "npc_turn_initialized",
                },
                {
                    "action": "npc_performs_action",
                    "input_data": {
                        "npc_id": "npc_villager_001",
                        "action": "move_to_location",
                    },
                    "expected": "npc_action_executed",
                },
                {
                    "action": "verify_time_after_npc",
                    "input_data": {
                        "expected_hour": 11,
                    },
                    "expected": "time_advanced_by_npc_action",
                },
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 3
        
        # Verify all steps passed
        for step in result.steps:
            assert step.passed is True
        
        # Verify NPC action step
        npc_step = next((s for s in result.steps if s.action == "npc_performs_action"), None)
        assert npc_step is not None
        
        # Verify time advancement after NPC action
        time_step = next((s for s in result.steps if s.action == "verify_time_after_npc"), None)
        assert time_step is not None
        assert time_step.passed is True
        assert time_step.input_data["expected_hour"] == 11

    @pytest.mark.smoke
    def test_time_based_events_trigger_at_thresholds(self):
        """Test that time-based events trigger at correct time thresholds."""
        result = self.runner.run_custom_scenario(
            "time_based_event_triggers",
            "session_event_001",
            steps=[
                {
                    "action": "setup_scheduled_event",
                    "input_data": {
                        "event_id": "event_night_ritual",
                        "trigger_time": {"period": "子时"},
                        "effects": {"danger_level": 0.3},
                    },
                    "expected": "event_scheduled",
                },
                {
                    "action": "advance_to_trigger_time",
                    "input_data": {
                        "target_period": "子时",
                        "current_period": "午时",
                    },
                    "expected": "time_advanced_to_trigger",
                },
                {
                    "action": "verify_event_triggered",
                    "input_data": {
                        "event_id": "event_night_ritual",
                    },
                    "expected": "event_fired_at_correct_time",
                },
                {
                    "action": "verify_effects_applied",
                    "input_data": {
                        "expected_effects": {"danger_level": 0.3},
                    },
                    "expected": "effects_applied_to_world_state",
                },
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4
        
        # Verify event scheduling
        setup_step = next((s for s in result.steps if s.action == "setup_scheduled_event"), None)
        assert setup_step is not None
        assert setup_step.passed is True
        
        # Verify event trigger
        trigger_step = next((s for s in result.steps if s.action == "verify_event_triggered"), None)
        assert trigger_step is not None
        assert trigger_step.passed is True
        
        # Verify effects
        effects_step = next((s for s in result.steps if s.action == "verify_effects_applied"), None)
        assert effects_step is not None
        assert effects_step.passed is True


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestAreaSummaryGeneration:
    """Test area summary generation scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_area_summary_updates_for_non_current_areas(self):
        """Test that area summary updates correctly for non-current areas."""
        result = self.runner.run_scenario(
            ScenarioType.AREA_SUMMARY_GENERATION,
            "session_area_001",
            custom_setup={
                "current_area": "village_square",
                "previous_area": "forest_path",
            }
        )
        
        assert result is not None
        assert result.scenario_type == ScenarioType.AREA_SUMMARY_GENERATION
        assert result.status == "passed"
        
        # Verify area setup step
        setup_step = next((s for s in result.steps if s.action == "setup_current_area"), None)
        assert setup_step is not None
        assert setup_step.passed is True
        assert "village_square" in setup_step.actual_result
        
        # Verify leave area step
        leave_step = next((s for s in result.steps if s.action == "leave_area"), None)
        assert leave_step is not None
        assert leave_step.passed is True
        assert "forest_path" in leave_step.actual_result
        
        # Verify summary generation step
        summary_step = next((s for s in result.steps if s.action == "verify_summary_generated"), None)
        assert summary_step is not None
        assert summary_step.passed is True
        assert "3 events" in summary_step.actual_result
        
        # Verify summary content step
        content_step = next((s for s in result.steps if s.action == "verify_summary_content"), None)
        assert content_step is not None
        assert content_step.passed is True

    def test_area_summary_preserves_event_order(self):
        """Test that area summary preserves chronological event order."""
        result = self.runner.run_custom_scenario(
            "area_summary_event_order",
            "session_area_order_001",
            steps=[
                {
                    "action": "record_events_in_area",
                    "input_data": {
                        "area": "market_district",
                        "events": [
                            {"type": "dialogue", "turn": 1, "npc": "merchant"},
                            {"type": "combat", "turn": 2, "enemy": "thief"},
                            {"type": "item_pickup", "turn": 3, "item": "gold_pouch"},
                        ],
                    },
                    "expected": "events_recorded_chronologically",
                },
                {
                    "action": "leave_area",
                    "input_data": {
                        "from_area": "market_district",
                        "to_area": "temple",
                    },
                    "expected": "area_transition_complete",
                },
                {
                    "action": "verify_summary_order",
                    "input_data": {
                        "expected_order": ["dialogue", "combat", "item_pickup"],
                    },
                    "expected": "summary_preserves_chronological_order",
                },
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 3
        
        # Verify event recording
        record_step = next((s for s in result.steps if s.action == "record_events_in_area"), None)
        assert record_step is not None
        assert record_step.passed is True
        
        # Verify summary order
        order_step = next((s for s in result.steps if s.action == "verify_summary_order"), None)
        assert order_step is not None
        assert order_step.passed is True


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestSealCountdownWithWorldTime:
    """Test seal countdown integration with world time."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_seal_countdown_advances_with_world_time(self):
        """Test that seal/countdown timers advance with world time."""
        result = self.runner.run_scenario(
            ScenarioType.SEAL_COUNTDOWN,
            "session_seal_time_001",
            custom_setup={
                "initial_countdown": 10,
                "turns": 5,
            }
        )
        
        assert result is not None
        assert result.scenario_type == ScenarioType.SEAL_COUNTDOWN
        assert result.status == "passed"
        
        # Verify seal initialization
        init_step = next((s for s in result.steps if s.action == "initialize_seal_countdown"), None)
        assert init_step is not None
        assert init_step.passed is True
        assert "10" in init_step.actual_result
        
        # Verify countdown progression
        advance_step = next((s for s in result.steps if s.action == "advance_turns"), None)
        assert advance_step is not None
        assert advance_step.passed is True
        # After 5 turns, countdown should be 5
        assert "5" in advance_step.actual_result
        
        # Verify time progression
        time_step = next((s for s in result.steps if s.action == "verify_time_progression"), None)
        assert time_step is not None
        assert time_step.passed is True
        # Each turn advances 2 hours, starting from hour 8
        # After 5 turns: 8 + (5 * 2) = 18
        assert "18" in time_step.actual_result or "Hour 18" in time_step.actual_result

    def test_seal_countdown_triggers_event_at_zero(self):
        """Test that seal countdown triggers event when reaching zero."""
        result = self.runner.run_custom_scenario(
            "seal_countdown_zero_trigger",
            "session_seal_zero_001",
            steps=[
                {
                    "action": "initialize_seal",
                    "input_data": {
                        "countdown": 3,
                        "trigger_event": "seal_broken",
                    },
                    "expected": "seal_initialized_with_trigger",
                },
                {
                    "action": "advance_turns_to_zero",
                    "input_data": {
                        "turns": 3,
                    },
                    "expected": "countdown_reaches_zero",
                },
                {
                    "action": "verify_trigger_event_fired",
                    "input_data": {
                        "event": "seal_broken",
                    },
                    "expected": "trigger_event_fired_at_countdown_zero",
                },
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 3
        
        # Verify seal initialization
        init_step = next((s for s in result.steps if s.action == "initialize_seal"), None)
        assert init_step is not None
        assert init_step.passed is True
        
        # Verify countdown reaches zero
        zero_step = next((s for s in result.steps if s.action == "advance_turns_to_zero"), None)
        assert zero_step is not None
        assert zero_step.passed is True
        
        # Verify trigger event fired
        trigger_step = next((s for s in result.steps if s.action == "verify_trigger_event_fired"), None)
        assert trigger_step is not None
        assert trigger_step.passed is True


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestDayNightCycle:
    """Test day/night cycle transitions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_day_to_night_transition(self):
        """Test that day/night cycle transitions correctly."""
        result = self.runner.run_custom_scenario(
            "day_night_transition",
            "session_cycle_001",
            steps=[
                {
                    "action": "set_time_to_day",
                    "input_data": {
                        "period": "午时",
                        "day": 1,
                    },
                    "expected": "time_set_to_day_period",
                },
                {
                    "action": "advance_to_night",
                    "input_data": {
                        "hours": 12,
                    },
                    "expected": "time_advanced_to_night",
                },
                {
                    "action": "verify_night_period",
                    "input_data": {
                        "expected_period": "子时",
                    },
                    "expected": "night_period_reached",
                },
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 3
        
        # Verify day period set
        day_step = next((s for s in result.steps if s.action == "set_time_to_day"), None)
        assert day_step is not None
        assert day_step.passed is True
        
        # Verify night period reached
        night_step = next((s for s in result.steps if s.action == "verify_night_period"), None)
        assert night_step is not None
        assert night_step.passed is True

    def test_day_boundary_rollover(self):
        """Test that day counter increments when time passes midnight."""
        result = self.runner.run_custom_scenario(
            "day_boundary_rollover",
            "session_rollover_001",
            steps=[
                {
                    "action": "set_time_near_midnight",
                    "input_data": {
                        "day": 1,
                        "hour": 23,
                    },
                    "expected": "time_set_near_midnight",
                },
                {
                    "action": "advance_past_midnight",
                    "input_data": {
                        "hours": 2,
                    },
                    "expected": "time_advanced_past_midnight",
                },
                {
                    "action": "verify_day_incremented",
                    "input_data": {
                        "expected_day": 2,
                        "expected_hour": 1,
                    },
                    "expected": "day_counter_incremented_correctly",
                },
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 3
        
        # Verify day rollover
        rollover_step = next((s for s in result.steps if s.action == "verify_day_incremented"), None)
        assert rollover_step is not None
        assert rollover_step.passed is True
        assert rollover_step.input_data["expected_day"] == 2
        assert rollover_step.input_data["expected_hour"] == 1


if __name__ == "__main__":
    _ = pytest.main([__file__, "-v"])

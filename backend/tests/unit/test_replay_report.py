"""
Unit tests for Replay Report / State Diff module.

Tests compute_state_diff function with nested dictionaries,
ReplayReportBuilder, and ReplayReport model.
"""

import pytest
from datetime import datetime

from llm_rpg.core.replay import (
    ReplayPerspective, ReplayResult, ReplayStep
)
from llm_rpg.core.replay_report import (
    StateDiffEntry, StateDiff, ReplayReport,
    compute_state_diff, ReplayReportBuilder, reset_replay_report_builder
)


class TestComputeStateDiff:
    """Tests for compute_state_diff function."""

    def test_empty_diff_for_identical_states(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1, "b": 2}
        
        diff = compute_state_diff(before, after)
        
        assert diff.entries == []
        assert diff.added_keys == []
        assert diff.removed_keys == []
        assert diff.changed_keys == []

    def test_detects_added_keys(self):
        before = {"a": 1}
        after = {"a": 1, "b": 2, "c": 3}
        
        diff = compute_state_diff(before, after)
        
        assert len(diff.entries) == 2
        assert set(diff.added_keys) == {"b", "c"}
        assert diff.removed_keys == []
        assert diff.changed_keys == []
        
        added_entries = [e for e in diff.entries if e.operation == "added"]
        assert len(added_entries) == 2
        for entry in added_entries:
            assert entry.old_value is None
            assert entry.new_value in [2, 3]

    def test_detects_removed_keys(self):
        before = {"a": 1, "b": 2, "c": 3}
        after = {"a": 1}
        
        diff = compute_state_diff(before, after)
        
        assert len(diff.entries) == 2
        assert diff.added_keys == []
        assert set(diff.removed_keys) == {"b", "c"}
        assert diff.changed_keys == []
        
        removed_entries = [e for e in diff.entries if e.operation == "removed"]
        assert len(removed_entries) == 2
        for entry in removed_entries:
            assert entry.new_value is None
            assert entry.old_value in [2, 3]

    def test_detects_changed_keys(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1, "b": 5}
        
        diff = compute_state_diff(before, after)
        
        assert len(diff.entries) == 1
        assert diff.added_keys == []
        assert diff.removed_keys == []
        assert diff.changed_keys == ["b"]
        
        entry = diff.entries[0]
        assert entry.path == "b"
        assert entry.operation == "changed"
        assert entry.old_value == 2
        assert entry.new_value == 5

    def test_handles_empty_dicts(self):
        before = {}
        after = {}
        
        diff = compute_state_diff(before, after)
        
        assert diff.entries == []

    def test_single_level_diff(self):
        before = {
            "player_hp": 100,
            "player_mana": 50,
        }
        after = {
            "player_hp": 80,
            "player_mana": 50,
            "player_stamina": 100,
        }
        
        diff = compute_state_diff(before, after)
        
        assert "player_hp" in diff.changed_keys
        assert "player_stamina" in diff.added_keys
        assert len(diff.entries) == 2

    def test_nested_dict_diff_added(self):
        before = {
            "npc_states": {
                "elder": {"trust": 50}
            }
        }
        after = {
            "npc_states": {
                "elder": {"trust": 50},
                "merchant": {"trust": 30}
            }
        }
        
        diff = compute_state_diff(before, after)
        
        assert "npc_states.merchant" in diff.added_keys
        assert any(e.path == "npc_states.merchant" for e in diff.entries)
        entry = next(e for e in diff.entries if e.path == "npc_states.merchant")
        assert entry.new_value == {"trust": 30}

    def test_nested_dict_diff_removed(self):
        before = {
            "npc_states": {
                "elder": {"trust": 50},
                "merchant": {"trust": 30}
            }
        }
        after = {
            "npc_states": {
                "elder": {"trust": 50}
            }
        }
        
        diff = compute_state_diff(before, after)
        
        assert "npc_states.merchant" in diff.removed_keys

    def test_nested_dict_diff_changed(self):
        before = {
            "npc_states": {
                "elder": {"trust": 50, "suspicion": 0}
            }
        }
        after = {
            "npc_states": {
                "elder": {"trust": 75, "suspicion": 0}
            }
        }
        
        diff = compute_state_diff(before, after)
        
        assert "npc_states.elder.trust" in diff.changed_keys
        
        entry = next(e for e in diff.entries if e.path == "npc_states.elder.trust")
        assert entry.old_value == 50
        assert entry.new_value == 75

    def test_multi_level_deep_diff(self):
        before = {
            "world_state": {
                "locations": {
                    "village": {
                        "npcs": ["elder", "merchant"],
                        "weather": "sunny"
                    }
                }
            }
        }
        after = {
            "world_state": {
                "locations": {
                    "village": {
                        "npcs": ["elder", "merchant", "guard"],
                        "weather": "rainy"
                    },
                    "forest": {
                        "npcs": ["hunter"]
                    }
                }
            }
        }
        
        diff = compute_state_diff(before, after)
        
        assert any("weather" in e.path for e in diff.entries)
        assert any("forest" in e.path for e in diff.entries)
        assert any("npcs" in e.path for e in diff.entries)


class TestStateDiffEntry:
    """Tests for StateDiffEntry model."""

    def test_create_added_entry(self):
        entry = StateDiffEntry(
            path="player.stamina",
            operation="added",
            old_value=None,
            new_value=100
        )
        
        assert entry.path == "player.stamina"
        assert entry.operation == "added"
        assert entry.old_value is None
        assert entry.new_value == 100

    def test_create_removed_entry(self):
        entry = StateDiffEntry(
            path="player.buffs.speed",
            operation="removed",
            old_value=True,
            new_value=None
        )
        
        assert entry.operation == "removed"
        assert entry.old_value is True
        assert entry.new_value is None

    def test_create_changed_entry(self):
        entry = StateDiffEntry(
            path="npc_states.elder.trust",
            operation="changed",
            old_value=50,
            new_value=75
        )
        
        assert entry.operation == "changed"
        assert entry.old_value == 50
        assert entry.new_value == 75


class TestStateDiff:
    """Tests for StateDiff model."""

    def test_empty_state_diff(self):
        diff = StateDiff()
        
        assert diff.entries == []
        assert diff.added_keys == []
        assert diff.removed_keys == []
        assert diff.changed_keys == []

    def test_state_diff_with_entries(self):
        diff = StateDiff(
            entries=[
                StateDiffEntry(path="a", operation="added", old_value=None, new_value=1),
                StateDiffEntry(path="b", operation="changed", old_value=2, new_value=3),
            ],
            added_keys=["a"],
            changed_keys=["b"]
        )
        
        assert len(diff.entries) == 2
        assert len(diff.added_keys) == 1


class TestReplayReport:
    """Tests for ReplayReport model."""

    def test_create_basic_report(self):
        report = ReplayReport(
            session_id="test_session",
            from_turn=1,
            to_turn=5,
            replayed_event_count=10,
            deterministic=True,
            llm_calls_made=0,
            state_diff=StateDiff()
        )
        
        assert report.session_id == "test_session"
        assert report.from_turn == 1
        assert report.to_turn == 5
        assert report.deterministic is True
        assert report.llm_calls_made == 0

    def test_report_with_snapshot_id(self):
        report = ReplayReport(
            session_id="test_session",
            snapshot_id="snap_abc123",
            from_turn=1,
            to_turn=5,
            replayed_event_count=10,
            deterministic=True,
            llm_calls_made=0,
            state_diff=StateDiff()
        )
        
        assert report.snapshot_id == "snap_abc123"

    def test_deterministic_true_when_no_llm_calls(self):
        report = ReplayReport(
            session_id="test_session",
            from_turn=1,
            to_turn=1,
            replayed_event_count=0,
            deterministic=True,
            llm_calls_made=0,
            state_diff=StateDiff()
        )
        
        assert report.deterministic is True

    def test_deterministic_false_when_llm_calls(self):
        report = ReplayReport(
            session_id="test_session",
            from_turn=1,
            to_turn=1,
            replayed_event_count=5,
            deterministic=False,
            llm_calls_made=3,
            state_diff=StateDiff()
        )
        
        assert report.deterministic is False
        assert report.llm_calls_made == 3

    def test_report_with_warnings(self):
        report = ReplayReport(
            session_id="test_session",
            from_turn=1,
            to_turn=5,
            replayed_event_count=10,
            deterministic=True,
            llm_calls_made=0,
            state_diff=StateDiff(),
            warnings=["No replay steps found", "Empty state"]
        )
        
        assert len(report.warnings) == 2
        assert "No replay steps found" in report.warnings


class TestReplayReportBuilder:
    """Tests for ReplayReportBuilder class."""

    def setup_method(self):
        reset_replay_report_builder()

    def test_build_report_minimal(self):
        builder = ReplayReportBuilder()
        
        report = builder.build_report(
            session_id="test_session",
            from_turn=1,
            to_turn=5
        )
        
        assert report.session_id == "test_session"
        assert report.from_turn == 1
        assert report.to_turn == 5

    def test_build_report_from_result(self):
        builder = ReplayReportBuilder()
        
        replay_result = ReplayResult(
            replay_id="replay_test",
            session_id="test_session",
            start_turn=1,
            end_turn=3,
            perspective=ReplayPerspective.ADMIN,
            steps=[],
            total_events=5
        )
        
        report = builder.build_report_from_result(replay_result)
        
        assert report.session_id == "test_session"
        assert report.from_turn == 1
        assert report.to_turn == 3
        assert report.replayed_event_count == 5

    def test_builder_counts_llm_calls(self):
        builder = ReplayReportBuilder()
        
        step_with_calls = ReplayStep(
            step_no=1,
            turn_no=1,
            model_call_ids=["call_1", "call_2", "call_3"]
        )
        
        replay_result = ReplayResult(
            replay_id="replay_test",
            session_id="test_session",
            start_turn=1,
            end_turn=1,
            perspective=ReplayPerspective.ADMIN,
            steps=[step_with_calls]
        )
        
        report = builder.build_report_from_result(replay_result)
        
        assert report.llm_calls_made == 3
        assert report.deterministic is False

    def test_builder_detects_no_llm_calls(self):
        builder = ReplayReportBuilder()
        
        step_no_calls = ReplayStep(
            step_no=1,
            turn_no=1,
            model_call_ids=[]
        )
        
        replay_result = ReplayResult(
            replay_id="replay_test",
            session_id="test_session",
            start_turn=1,
            end_turn=1,
            perspective=ReplayPerspective.ADMIN,
            steps=[step_no_calls]
        )
        
        report = builder.build_report_from_result(replay_result)
        
        assert report.llm_calls_made == 0
        assert report.deterministic is True

    def test_builder_warns_on_invalid_turn_range(self):
        builder = ReplayReportBuilder()
        
        report = builder.build_report(
            session_id="test_session",
            from_turn=5,
            to_turn=1
        )
        
        assert any("from_turn" in w for w in report.warnings)

    def test_builder_warns_on_empty_steps(self):
        builder = ReplayReportBuilder()
        
        report = builder.build_report(
            session_id="test_session",
            from_turn=1,
            to_turn=5
        )
        
        assert any("No replay steps" in w for w in report.warnings)

    def test_builder_with_snapshot_id(self):
        builder = ReplayReportBuilder()
        
        report = builder.build_report(
            session_id="test_session",
            from_turn=1,
            to_turn=5,
            snapshot_id="snap_abc123"
        )
        
        assert report.snapshot_id == "snap_abc123"


class TestPerspectiveFilter:
    """Tests for perspective filtering in ReplayReportBuilder."""

    def setup_method(self):
        reset_replay_report_builder()

    def test_admin_sees_all_entries(self):
        builder = ReplayReportBuilder()
        
        step = ReplayStep(
            step_no=1,
            turn_no=1,
            state_before={
                "npc_states": {
                    "elder": {"trust": 50}
                }
            },
            state_after={
                "npc_states": {
                    "elder": {"trust": 75, "hidden_plan_state": "evil_scheme"}
                }
            }
        )
        
        replay_result = ReplayResult(
            replay_id="replay_test",
            session_id="test_session",
            start_turn=1,
            end_turn=1,
            perspective=ReplayPerspective.ADMIN,
            steps=[step]
        )
        
        report = builder.build_report_from_result(
            replay_result,
            perspective=ReplayPerspective.ADMIN
        )
        
        paths = [e.path for e in report.state_diff.entries]
        assert "npc_states.elder.trust" in paths
        assert "npc_states.elder.hidden_plan_state" in paths

    def test_player_filtered_hidden_fields(self):
        builder = ReplayReportBuilder()
        
        step = ReplayStep(
            step_no=1,
            turn_no=1,
            state_before={
                "npc_states": {
                    "elder": {"trust": 50}
                }
            },
            state_after={
                "npc_states": {
                    "elder": {"trust": 75, "hidden_plan_state": "evil_scheme"}
                }
            }
        )
        
        replay_result = ReplayResult(
            replay_id="replay_test",
            session_id="test_session",
            start_turn=1,
            end_turn=1,
            perspective=ReplayPerspective.ADMIN,
            steps=[step]
        )
        
        report = builder.build_report_from_result(
            replay_result,
            perspective=ReplayPerspective.PLAYER
        )
        
        paths = [e.path for e in report.state_diff.entries]
        assert "npc_states.elder.trust" in paths
        assert "npc_states.elder.hidden_plan_state" not in paths

    def test_player_filtered_secrets(self):
        builder = ReplayReportBuilder()
        
        step = ReplayStep(
            step_no=1,
            turn_no=1,
            state_before={
                "quest_states": {
                    "main_quest": {"progress": 0}
                }
            },
            state_after={
                "quest_states": {
                    "main_quest": {
                        "progress": 50,
                        "secret_rewards": ["ancient_artifact"]
                    }
                }
            }
        )
        
        replay_result = ReplayResult(
            replay_id="replay_test",
            session_id="test_session",
            start_turn=1,
            end_turn=1,
            perspective=ReplayPerspective.ADMIN,
            steps=[step]
        )
        
        report = builder.build_report_from_result(
            replay_result,
            perspective=ReplayPerspective.PLAYER
        )
        
        paths = [e.path for e in report.state_diff.entries]
        assert "quest_states.main_quest.progress" in paths
        assert "quest_states.main_quest.secret_rewards" not in paths

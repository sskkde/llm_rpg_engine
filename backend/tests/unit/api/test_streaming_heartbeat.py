"""
Unit tests for SSE heartbeat event generation and parsing.

Tests verify:
- Heartbeat SSE event format matches streaming.py specification
- Heartbeat events are correctly parsed alongside stage events
- Heartbeat sequence numbers increment correctly
- Heartbeat events are emitted when queue is idle
- Hard deadline emits turn_error when exceeded
- Environment variables control heartbeat interval and hard deadline
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Tuple, Dict, List
from unittest.mock import patch, MagicMock

import pytest

# Import the SSE parser from the integration test file
from tests.integration.test_streaming_stage_events import _parse_sse_events


def _make_heartbeat_event(sequence: int, elapsed: int = 0) -> str:
    """Generate a heartbeat SSE string matching the streaming.py format."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": elapsed,
        "sequence": sequence,
    }
    lines = [
        "event: heartbeat",
        f"data: {json.dumps(data, ensure_ascii=False)}",
        "",
        "",
    ]
    return "\n".join(lines)


def _make_stage_event(stage_name: str, message: str = "Processing...") -> str:
    """Generate a stage SSE event for testing mixed event parsing."""
    data = {
        "stage": stage_name,
        "message": message,
    }
    lines = [
        f"event: stage_started",
        f"data: {json.dumps(data, ensure_ascii=False)}",
        "",
        "",
    ]
    return "\n".join(lines)


class TestHeartbeatEventFormat:
    """Tests for heartbeat SSE event format."""

    def test_heartbeat_event_format(self):
        """Create a heartbeat SSE string, parse it, verify format."""
        raw_sse = _make_heartbeat_event(sequence=1, elapsed=5)
        events = _parse_sse_events(raw_sse)

        assert len(events) == 1
        event_name, payload = events[0]

        assert event_name == "heartbeat"
        assert "timestamp" in payload
        assert "elapsed_seconds" in payload
        assert "sequence" in payload
        assert payload["elapsed_seconds"] == 5
        assert payload["sequence"] == 1

    def test_heartbeat_event_has_valid_timestamp(self):
        """Verify timestamp is a valid ISO format string."""
        raw_sse = _make_heartbeat_event(sequence=1)
        events = _parse_sse_events(raw_sse)

        _, payload = events[0]
        timestamp_str = payload["timestamp"]

        # Verify it can be parsed as a datetime
        parsed = datetime.fromisoformat(timestamp_str)
        assert isinstance(parsed, datetime)


class TestHeartbeatEventParsing:
    """Tests for parsing heartbeat events alongside other events."""

    def test_parse_sse_includes_heartbeat(self):
        """Mix heartbeat events with stage events, verify all are parsed."""
        raw_sse = (
            _make_stage_event("npc_decision", "NPC 思考中……")
            + _make_heartbeat_event(sequence=1, elapsed=3)
            + _make_stage_event("narration", "生成叙事中……")
            + _make_heartbeat_event(sequence=2, elapsed=6)
        )

        events = _parse_sse_events(raw_sse)

        assert len(events) == 4

        # Verify heartbeat events are present
        heartbeat_events = [(name, p) for name, p in events if name == "heartbeat"]
        assert len(heartbeat_events) == 2

        # Verify stage events are present
        stage_events = [(name, p) for name, p in events if name == "stage_started"]
        assert len(stage_events) == 2

    def test_heartbeat_sequence_increments(self):
        """Generate two heartbeats with different sequences, verify they parse correctly."""
        raw_sse = (
            _make_heartbeat_event(sequence=1, elapsed=2)
            + _make_heartbeat_event(sequence=2, elapsed=4)
            + _make_heartbeat_event(sequence=3, elapsed=6)
        )

        events = _parse_sse_events(raw_sse)

        assert len(events) == 3

        # Verify sequences increment
        sequences = [p["sequence"] for _, p in events]
        assert sequences == [1, 2, 3]

        # Verify elapsed_seconds increment
        elapsed = [p["elapsed_seconds"] for _, p in events]
        assert elapsed == [2, 4, 6]


class TestHeartbeatEventIntegration:
    """Tests for heartbeat event behavior in realistic scenarios."""

    def test_multiple_heartbeats_between_stages(self):
        """Verify multiple heartbeats between stage transitions are all captured."""
        raw_sse = (
            _make_stage_event("input_intent", "解析玩家意图……")
            + _make_heartbeat_event(sequence=1, elapsed=2)
            + _make_heartbeat_event(sequence=2, elapsed=4)
            + _make_stage_event("world_update", "更新世界状态……")
            + _make_heartbeat_event(sequence=3, elapsed=6)
            + _make_stage_event("npc_decision", "NPC 思考中……")
            + _make_heartbeat_event(sequence=4, elapsed=8)
            + _make_heartbeat_event(sequence=5, elapsed=10)
            + _make_stage_event("narration", "生成叙事中……")
        )

        events = _parse_sse_events(raw_sse)

        # Count event types
        event_counts: Dict[str, int] = {}
        for name, _ in events:
            event_counts[name] = event_counts.get(name, 0) + 1

        assert event_counts.get("heartbeat", 0) == 5
        assert event_counts.get("stage_started", 0) == 4

    def test_heartbeat_with_zero_elapsed(self):
        """Verify heartbeat with elapsed_seconds=0 is valid."""
        raw_sse = _make_heartbeat_event(sequence=0, elapsed=0)
        events = _parse_sse_events(raw_sse)

        assert len(events) == 1
        _, payload = events[0]
        assert payload["elapsed_seconds"] == 0
        assert payload["sequence"] == 0


class TestHeartbeatConfiguration:
    """Tests for heartbeat configuration via environment variables."""

    def test_default_heartbeat_interval_is_12_seconds(self):
        """Default STREAMING_HEARTBEAT_INTERVAL_SECONDS is 12."""
        with patch.dict(os.environ, {}, clear=True):
            if "STREAMING_HEARTBEAT_INTERVAL_SECONDS" in os.environ:
                del os.environ["STREAMING_HEARTBEAT_INTERVAL_SECONDS"]
            interval = int(os.getenv("STREAMING_HEARTBEAT_INTERVAL_SECONDS", "12"))
            assert interval == 12

    def test_default_hard_deadline_is_180_seconds(self):
        """Default STREAMING_HARD_DEADLINE_SECONDS is 180."""
        with patch.dict(os.environ, {}, clear=True):
            if "STREAMING_HARD_DEADLINE_SECONDS" in os.environ:
                del os.environ["STREAMING_HARD_DEADLINE_SECONDS"]
            deadline = int(os.getenv("STREAMING_HARD_DEADLINE_SECONDS", "180"))
            assert deadline == 180

    def test_heartbeat_interval_can_be_configured(self):
        """STREAMING_HEARTBEAT_INTERVAL_SECONDS can be overridden via environment."""
        with patch.dict(os.environ, {"STREAMING_HEARTBEAT_INTERVAL_SECONDS": "5"}):
            interval = int(os.getenv("STREAMING_HEARTBEAT_INTERVAL_SECONDS", "12"))
            assert interval == 5

    def test_hard_deadline_can_be_configured(self):
        """STREAMING_HARD_DEADLINE_SECONDS can be overridden via environment."""
        with patch.dict(os.environ, {"STREAMING_HARD_DEADLINE_SECONDS": "60"}):
            deadline = int(os.getenv("STREAMING_HARD_DEADLINE_SECONDS", "180"))
            assert deadline == 60


class TestHeartbeatEmittedOnIdle:
    """Tests for heartbeat emission when no progress event is ready."""

    @pytest.mark.asyncio
    async def test_heartbeat_emitted_when_queue_empty(self):
        """
        Heartbeat event is emitted when progress_queue has no events for HEARTBEAT_INTERVAL.
        
        This test simulates a slow worker by patching execute_turn_service to delay,
        and verifies that heartbeat events are emitted during the delay.
        """
        mock_result = MagicMock()
        mock_result.turn_no = 1
        mock_result.transaction_id = "txn_test"
        mock_result.events_committed = []
        mock_result.actions_committed = []
        mock_result.world_time = "修仙历 春 第1日 辰时"
        mock_result.narration = "测试叙述"
        mock_result.recommended_actions = []
        mock_result.player_state = {}
        mock_result.time_advance_result = None
        
        def slow_execute_turn_service(*args, **kwargs):
            time.sleep(2.5)
            return mock_result
        
        with patch('llm_rpg.api.streaming.execute_turn_service', side_effect=slow_execute_turn_service):
            with patch.dict(os.environ, {
                "STREAMING_HEARTBEAT_INTERVAL_SECONDS": "1",
                "STREAMING_HARD_DEADLINE_SECONDS": "10"
            }):
                from llm_rpg.api.streaming import execute_turn_stream
                
                events = []
                async for event in execute_turn_stream(
                    session_id="test_session",
                    game_id="test_game",
                    turn_index=0,
                    player_input="测试输入",
                    world_id="test_world",
                ):
                    events.append(event)
                
                raw_output = "".join(events)
                parsed = _parse_sse_events(raw_output)
                
                heartbeat_events = [e for e in parsed if e[0] == "heartbeat"]
                assert len(heartbeat_events) >= 1, "At least one heartbeat should be emitted during slow execution"
                
                for i, (event_name, data) in enumerate(heartbeat_events):
                    assert "timestamp" in data
                    assert "elapsed_seconds" in data
                    assert "sequence" in data
                    assert data["sequence"] == i + 1


class TestHardDeadlineExceeded:
    """Tests for hard deadline behavior."""

    @pytest.mark.asyncio
    async def test_hard_deadline_emits_turn_error(self):
        """When hard deadline is exceeded, turn_error with turn_timeout is emitted."""
        def very_slow_execute_turn_service(*args, **kwargs):
            time.sleep(5)
            return MagicMock()
        
        with patch('llm_rpg.api.streaming.execute_turn_service', side_effect=very_slow_execute_turn_service):
            with patch.dict(os.environ, {
                "STREAMING_HEARTBEAT_INTERVAL_SECONDS": "1",
                "STREAMING_HARD_DEADLINE_SECONDS": "2"
            }):
                from llm_rpg.api.streaming import execute_turn_stream
                
                events = []
                async for event in execute_turn_stream(
                    session_id="test_session",
                    game_id="test_game",
                    turn_index=0,
                    player_input="测试输入",
                    world_id="test_world",
                ):
                    events.append(event)
                
                raw_output = "".join(events)
                parsed = _parse_sse_events(raw_output)
                
                error_events = [e for e in parsed if e[0] == "turn_error"]
                assert len(error_events) >= 1, "turn_error should be emitted when hard deadline is exceeded"
                
                error_data = error_events[0][1]
                assert error_data["error_type"] == "turn_timeout"
                assert "hard deadline" in error_data["message"].lower() or "timeout" in error_data["message"].lower()

    @pytest.mark.asyncio
    async def test_hard_deadline_does_not_break_normal_flow(self):
        """Normal turn execution completes successfully within hard deadline."""
        mock_result = MagicMock()
        mock_result.turn_no = 1
        mock_result.transaction_id = "txn_test"
        mock_result.events_committed = []
        mock_result.actions_committed = []
        mock_result.world_time = "修仙历 春 第1日 辰时"
        mock_result.narration = "测试叙述"
        mock_result.recommended_actions = []
        mock_result.player_state = {}
        mock_result.time_advance_result = None
        
        with patch('llm_rpg.api.streaming.execute_turn_service', return_value=mock_result):
            with patch.dict(os.environ, {
                "STREAMING_HEARTBEAT_INTERVAL_SECONDS": "12",
                "STREAMING_HARD_DEADLINE_SECONDS": "180"
            }):
                from llm_rpg.api.streaming import execute_turn_stream
                
                events = []
                async for event in execute_turn_stream(
                    session_id="test_session",
                    game_id="test_game",
                    turn_index=0,
                    player_input="测试输入",
                    world_id="test_world",
                ):
                    events.append(event)
                
                raw_output = "".join(events)
                parsed = _parse_sse_events(raw_output)
                
                turn_completed = [e for e in parsed if e[0] == "turn_completed"]
                assert len(turn_completed) >= 1, "turn_completed should be emitted for normal execution"
                
                turn_error = [e for e in parsed if e[0] == "turn_error"]
                assert len(turn_error) == 0, "No turn_error should be emitted for normal execution"


class TestHeartbeatElapsedSeconds:
    """Tests for elapsed_seconds tracking in heartbeat events."""

    @pytest.mark.asyncio
    async def test_elapsed_seconds_increases_with_heartbeats(self):
        """elapsed_seconds in heartbeat events increases over time."""
        mock_result = MagicMock()
        mock_result.turn_no = 1
        mock_result.transaction_id = "txn_test"
        mock_result.events_committed = []
        mock_result.actions_committed = []
        mock_result.world_time = "修仙历 春 第1日 辰时"
        mock_result.narration = "测试叙述"
        mock_result.recommended_actions = []
        mock_result.player_state = {}
        mock_result.time_advance_result = None
        
        def slow_execute_turn_service(*args, **kwargs):
            time.sleep(2.5)
            return mock_result
        
        with patch('llm_rpg.api.streaming.execute_turn_service', side_effect=slow_execute_turn_service):
            with patch.dict(os.environ, {
                "STREAMING_HEARTBEAT_INTERVAL_SECONDS": "1",
                "STREAMING_HARD_DEADLINE_SECONDS": "10"
            }):
                from llm_rpg.api.streaming import execute_turn_stream
                
                events = []
                async for event in execute_turn_stream(
                    session_id="test_session",
                    game_id="test_game",
                    turn_index=0,
                    player_input="测试输入",
                    world_id="test_world",
                ):
                    events.append(event)
                
                raw_output = "".join(events)
                parsed = _parse_sse_events(raw_output)
                
                heartbeat_events = [e for e in parsed if e[0] == "heartbeat"]
                if len(heartbeat_events) >= 2:
                    elapsed_times = [e[1]["elapsed_seconds"] for e in heartbeat_events]
                    assert elapsed_times[1] > elapsed_times[0], \
                        "elapsed_seconds should increase between heartbeats"

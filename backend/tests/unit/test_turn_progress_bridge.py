"""
Unit tests for the SSE bridge thread safety in streaming.py.

Tests:
- sync callback delivers events to async queue via loop.call_soon_threadsafe
- QueueFull does not crash the callback
- Worker thread exceptions become turn_error SSE events
- Worker DB session is closed on success
- Worker DB session is closed on error
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, call

from llm_rpg.core.turn_progress import TurnProgressEvent, emit_stage
from llm_rpg.api.streaming import execute_turn_stream


class TestSyncCallbackDeliversToAsyncQueue:
    """Verify a sync callback can put events into an asyncio.Queue via loop.call_soon_threadsafe."""

    @pytest.mark.asyncio
    async def test_sync_callback_delivers_to_async_queue(self):
        event = emit_stage("world_stage", "started")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[TurnProgressEvent | object] = asyncio.Queue(maxsize=100)

        def progress_callback(ev: TurnProgressEvent) -> None:
            def put_event() -> None:
                try:
                    queue.put_nowait(ev)
                except asyncio.QueueFull:
                    pass
            loop.call_soon_threadsafe(put_event)

        progress_callback(event)

        await asyncio.sleep(0.05)

        result = queue.get_nowait()
        assert isinstance(result, TurnProgressEvent)
        assert result.stage == "world_stage"
        assert result.phase == "started"


class TestQueueFullDoesNotCrash:
    """Verify that when queue is full, callback silently drops events instead of crashing."""

    @pytest.mark.asyncio
    async def test_queue_full_does_not_crash(self):
        event = emit_stage("world_stage", "started")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[TurnProgressEvent | object] = asyncio.Queue(maxsize=1)

        def progress_callback(ev: TurnProgressEvent) -> None:
            def put_event() -> None:
                try:
                    queue.put_nowait(ev)
                except asyncio.QueueFull:
                    pass
            loop.call_soon_threadsafe(put_event)

        queue.put_nowait(emit_stage("npc_stage", "started"))

        progress_callback(event)

        await asyncio.sleep(0.05)

        assert queue.qsize() == 1

        first = queue.get_nowait()
        assert isinstance(first, TurnProgressEvent)
        assert first.stage == "npc_stage"


class TestWorkerExceptionBecomesTurnError:
    """Verify that a worker thread exception results in a turn_error SSE event."""

    @pytest.mark.asyncio
    async def test_worker_exception_becomes_turn_error(self):
        from llm_rpg.core.turn_service import TurnServiceError

        class FakeTurnServiceError(TurnServiceError):
            def __init__(self):
                super().__init__(turn_no=1, message="test error")

        mock_session = MagicMock()
        mock_session.close = MagicMock()

        with patch('llm_rpg.api.streaming.SessionLocal', return_value=mock_session), \
             patch('llm_rpg.api.streaming.execute_turn_service', side_effect=FakeTurnServiceError()):
            events = []
            async for event in execute_turn_stream(
                session_id="test_session",
                game_id="test_game",
                turn_index=0,
                player_input="test",
                world_id="test_world",
            ):
                events.append(event)

        error_events = [e for e in events if "turn_error" in e]
        assert len(error_events) > 0, "Expected at least one turn_error SSE event"


class TestWorkerDbSessionClosedOnSuccess:
    """Mock SessionLocal and verify close() is called when worker succeeds."""

    @pytest.mark.asyncio
    async def test_worker_db_session_closed_on_success(self):
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

        mock_session = MagicMock()
        mock_session.close = MagicMock()

        with patch('llm_rpg.api.streaming.SessionLocal', return_value=mock_session), \
             patch('llm_rpg.api.streaming.execute_turn_service', return_value=mock_result):
            events = []
            async for event in execute_turn_stream(
                session_id="test_session",
                game_id="test_game",
                turn_index=0,
                player_input="test",
                world_id="test_world",
            ):
                events.append(event)

        mock_session.close.assert_called_once()


class TestWorkerDbSessionClosedOnError:
    """Mock SessionLocal and verify close() is called even on exception."""

    @pytest.mark.asyncio
    async def test_worker_db_session_closed_on_error(self):
        from llm_rpg.core.turn_service import TurnServiceError

        class FakeTurnServiceError(TurnServiceError):
            def __init__(self):
                super().__init__(turn_no=1, message="test error")

        mock_session = MagicMock()
        mock_session.close = MagicMock()

        with patch('llm_rpg.api.streaming.SessionLocal', return_value=mock_session), \
             patch('llm_rpg.api.streaming.execute_turn_service', side_effect=FakeTurnServiceError()):
            events = []
            async for event in execute_turn_stream(
                session_id="test_session",
                game_id="test_game",
                turn_index=0,
                player_input="test",
                world_id="test_world",
            ):
                events.append(event)

        mock_session.close.assert_called_once()

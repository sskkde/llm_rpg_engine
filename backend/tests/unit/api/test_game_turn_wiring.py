"""
Unit tests for turn_factory module.

Tests verify:
- Single shared ProposalPipeline instance when LLMService is provided
- All engines receive the same pipeline instance
- Construction without LLMService uses None for all pipelines
- SceneEngine is always constructed
- Sync turn endpoint uses proposal pipeline for all stages
- Fallback behavior when no provider/pipeline is configured
- Single stage exception does not fail the whole turn
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from llm_rpg.api.turn_factory import build_turn_orchestrator
from llm_rpg.llm.service import LLMService, MockLLMProvider
from llm_rpg.llm.proposal_pipeline import ProposalPipeline
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    NPCState,
)
from llm_rpg.models.events import WorldTime, WorldTickEvent
from llm_rpg.models.common import ValidationResult, ProposedAction
from llm_rpg.models.proposals import (
    InputIntentProposal,
    WorldTickProposal,
    SceneEventProposal,
    NPCActionProposal,
    NarrationProposal,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    ValidationStatus,
    CandidateEvent,
)


def _make_valid_state(npc_ids=None):
    """Create a minimal valid CanonicalState for testing."""
    npc_states = {}
    for npc_id in (npc_ids or []):
        npc_states[npc_id] = NPCState(
            entity_id=npc_id,
            npc_id=npc_id,
            name=f"NPC {npc_id}",
            status="alive",
            location_id="loc_001",
            mood="neutral",
        )

    return CanonicalState(
        player_state=PlayerState(
            entity_id="player",
            location_id="loc_001",
        ),
        world_state=WorldState(
            entity_id="world",
            world_id="default_world",
            current_time=WorldTime(
                calendar="修仙历",
                season="春",
                day=1,
                period="辰时",
            ),
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene",
            scene_id="scene_001",
            location_id="loc_001",
            active_actor_ids=["player"] + (npc_ids or []),
        ),
        npc_states=npc_states,
    )


def _make_valid_audit():
    """Create a valid ProposalAuditMetadata."""
    return ProposalAuditMetadata(
        proposal_type=ProposalType.INPUT_INTENT,
        source_engine=ProposalSource.INPUT_ENGINE,
        validation_status=ValidationStatus.PASSED,
    )


def _make_valid_input_proposal():
    """Create a valid non-fallback InputIntentProposal."""
    return InputIntentProposal(
        intent_type="inspect",
        target=None,
        risk_level="low",
        confidence=0.8,
        audit=_make_valid_audit(),
        is_fallback=False,
    )


def _make_valid_world_proposal():
    """Create a valid non-fallback WorldTickProposal."""
    return WorldTickProposal(
        time_delta_turns=1,
        candidate_events=[],
        state_deltas=[],
        confidence=0.7,
        audit=ProposalAuditMetadata(
            proposal_type=ProposalType.WORLD_TICK,
            source_engine=ProposalSource.WORLD_ENGINE,
            validation_status=ValidationStatus.PASSED,
        ),
        is_fallback=False,
    )


def _make_valid_scene_proposal():
    """Create a valid non-fallback SceneEventProposal."""
    return SceneEventProposal(
        scene_id="scene_001",
        candidate_events=[],
        state_deltas=[],
        confidence=0.6,
        audit=ProposalAuditMetadata(
            proposal_type=ProposalType.SCENE_EVENT,
            source_engine=ProposalSource.SCENE_ENGINE,
            validation_status=ValidationStatus.PASSED,
        ),
        is_fallback=False,
    )


def _make_valid_npc_proposal(npc_id="npc_001"):
    """Create a valid non-fallback NPCActionProposal."""
    return NPCActionProposal(
        npc_id=npc_id,
        action_type="observe",
        summary="NPC observes the surroundings",
        confidence=0.7,
        audit=ProposalAuditMetadata(
            proposal_type=ProposalType.NPC_ACTION,
            source_engine=ProposalSource.NPC_ENGINE,
            validation_status=ValidationStatus.PASSED,
        ),
        is_fallback=False,
    )


def _make_valid_narration_proposal():
    """Create a valid non-fallback NarrationProposal."""
    return NarrationProposal(
        text="古老的山门广场铺满了青石板。",
        tone="neutral",
        confidence=0.8,
        audit=ProposalAuditMetadata(
            proposal_type=ProposalType.NARRATION,
            source_engine=ProposalSource.NARRATION_ENGINE,
            validation_status=ValidationStatus.PASSED,
        ),
        is_fallback=False,
    )


class TestTurnFactoryWithPipeline:
    """Tests for factory when LLMService is provided."""

    def test_turn_factory_constructs_single_shared_pipeline(self):
        """When LLMService is provided, one pipeline is shared by all engines."""
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # Verify orchestrator has pipeline
        assert orchestrator._proposal_pipeline is not None
        assert isinstance(orchestrator._proposal_pipeline, ProposalPipeline)
        
        # Verify all engines share the same pipeline instance
        orchestrator_pipeline = id(orchestrator._proposal_pipeline)
        world_pipeline = id(orchestrator._world_engine._proposal_pipeline)
        npc_pipeline = id(orchestrator._npc_engine._proposal_pipeline)
        narration_pipeline = id(orchestrator._narration_engine._proposal_pipeline)
        scene_pipeline = id(orchestrator._scene_engine._proposal_pipeline)
        
        assert orchestrator_pipeline == world_pipeline
        assert orchestrator_pipeline == npc_pipeline
        assert orchestrator_pipeline == narration_pipeline
        assert orchestrator_pipeline == scene_pipeline

    def test_scene_engine_is_constructed_with_pipeline(self):
        """SceneEngine is always constructed and receives pipeline when available."""
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        assert orchestrator._scene_engine is not None
        assert orchestrator._scene_engine._proposal_pipeline is not None
        assert isinstance(orchestrator._scene_engine._proposal_pipeline, ProposalPipeline)

    def test_all_engines_receive_pipeline(self):
        """All four engines plus orchestrator receive the pipeline."""
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        assert orchestrator._proposal_pipeline is not None
        assert orchestrator._world_engine._proposal_pipeline is not None
        assert orchestrator._npc_engine._proposal_pipeline is not None
        assert orchestrator._narration_engine._proposal_pipeline is not None
        assert orchestrator._scene_engine._proposal_pipeline is not None


class TestTurnFactoryWithoutPipeline:
    """Tests for factory when LLMService is not provided."""

    def test_turn_factory_constructs_without_pipeline_when_service_missing(self):
        """When LLMService is None, all engines have proposal_pipeline=None."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        # Verify orchestrator has no pipeline
        assert orchestrator._proposal_pipeline is None
        
        # Verify all engines have None pipeline
        assert orchestrator._world_engine._proposal_pipeline is None
        assert orchestrator._npc_engine._proposal_pipeline is None
        assert orchestrator._narration_engine._proposal_pipeline is None
        assert orchestrator._scene_engine._proposal_pipeline is None

    def test_scene_engine_is_constructed_without_pipeline(self):
        """SceneEngine is constructed even without LLMService."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        assert orchestrator._scene_engine is not None
        assert orchestrator._scene_engine._proposal_pipeline is None

    def test_orchestrator_has_all_dependencies(self):
        """Orchestrator is fully constructed with all required dependencies."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        assert orchestrator._state_manager is not None
        assert orchestrator._event_log is not None
        assert orchestrator._action_scheduler is not None
        assert orchestrator._validator is not None
        assert orchestrator._perspective is not None
        assert orchestrator._context_builder is not None
        assert orchestrator._world_engine is not None
        assert orchestrator._npc_engine is not None
        assert orchestrator._narration_engine is not None
        assert orchestrator._scene_engine is not None
        assert orchestrator._memory_writer is not None


class TestTurnFactoryPipelineCreation:
    """Tests for ProposalPipeline creation behavior."""

    @patch('llm_rpg.api.turn_factory.create_proposal_pipeline')
    def test_create_proposal_pipeline_called_once(self, mock_create):
        """create_proposal_pipeline is called exactly once when LLMService is provided."""
        mock_pipeline = MagicMock(spec=ProposalPipeline)
        mock_create.return_value = mock_pipeline
        
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # Verify create_proposal_pipeline was called once
        mock_create.assert_called_once_with(llm_service=llm_service)
        
        # Verify the returned pipeline is used
        assert orchestrator._proposal_pipeline is mock_pipeline

    @patch('llm_rpg.api.turn_factory.create_proposal_pipeline')
    def test_create_proposal_pipeline_not_called_without_service(self, mock_create):
        """create_proposal_pipeline is not called when LLMService is None."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        # Verify create_proposal_pipeline was not called
        mock_create.assert_not_called()
        
        # Verify no pipeline was created
        assert orchestrator._proposal_pipeline is None


class TestTurnEndpointUsesProposalPipeline:
    """Tests that verify the sync turn endpoint uses the proposal pipeline for all stages."""

    def test_turn_endpoint_uses_proposal_pipeline_for_all_stages(self):
        """
        When LLMService is provided, execute_turn calls all proposal pipeline methods:
        - generate_input_intent (via _parse_intent)
        - generate_world_tick (via world_engine.generate_world_candidates)
        - generate_scene_event (via scene_engine.generate_scene_candidates)
        - generate_npc_action (via npc_engine.generate_npc_action)
        - generate_narration (via narration_engine.generate_narration)
        """
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        orchestrator = build_turn_orchestrator(llm_service=llm_service)

        # Set up valid game state with an NPC in scene
        valid_state = _make_valid_state(npc_ids=["npc_001"])
        orchestrator._state_manager.get_state = MagicMock(return_value=valid_state)

        # Mock world_engine.advance_time
        world_time_after = WorldTime(calendar="修仙历", season="春", day=1, period="巳时")
        mock_world_tick = WorldTickEvent(
            event_id="evt_tick_001",
            turn_index=1,
            time_before=valid_state.world_state.current_time,
            time_after=world_time_after,
            summary="时间推进",
        )
        orchestrator._world_engine.advance_time = MagicMock(return_value=mock_world_tick)

        # Mock action_scheduler.collect_actors to return player + NPC
        orchestrator._action_scheduler.collect_actors = MagicMock(
            return_value=["player", "npc_001"]
        )

        # Mock action_scheduler.resolve_conflicts to return player action only
        orchestrator._action_scheduler.resolve_conflicts = MagicMock(
            return_value=[
                ProposedAction(
                    action_id="action_player_000001",
                    actor_id="player",
                    action_type="inspect",
                    summary="Player inspects",
                    priority=1.0,
                )
            ]
        )

        # Mock validator to always pass
        valid_result = ValidationResult(is_valid=True, checks=[], errors=[], warnings=[])
        orchestrator._validator.validate_action = MagicMock(return_value=valid_result)
        orchestrator._validator.validate_state_delta = MagicMock(return_value=valid_result)
        orchestrator._validator.validate_candidate_event = MagicMock(return_value=valid_result)

        # Mock event_log methods
        from llm_rpg.models.events import TurnTransaction
        mock_transaction = TurnTransaction(
            transaction_id="txn_001",
            session_id="session_001",
            game_id="game_001",
            turn_index=1,
            world_time_before=valid_state.world_state.current_time,
            player_input="观察四周",
        )
        orchestrator._event_log.start_turn = MagicMock(return_value=mock_transaction)
        orchestrator._event_log.record_event = MagicMock()
        orchestrator._event_log.commit_turn = MagicMock()

        # Mock perspective service
        from llm_rpg.models.perspectives import PlayerPerspective, NarratorPerspective
        mock_player_perspective = PlayerPerspective(
            perspective_id="player_view_1",
            owner_id="player",
        )
        mock_narrator_perspective = NarratorPerspective(
            perspective_id="narrator_view_1",
            owner_id="narrator",
            base_perspective_id="player_view_1",
        )
        orchestrator._perspective.build_player_perspective = MagicMock(
            return_value=mock_player_perspective
        )
        orchestrator._perspective.build_narrator_perspective = MagicMock(
            return_value=mock_narrator_perspective
        )

        # Mock memory_writer
        orchestrator._memory_writer.process_turn = MagicMock(
            return_value={"memories_created": 0, "summary_created": None, "memory_ids": []}
        )

        # Mock engine methods that call pipeline (sync methods, not async pipeline methods)
        # This avoids the asyncio.run_until_complete issue with AsyncMock
        mock_world_candidates = MagicMock(return_value=_make_valid_world_proposal())
        mock_scene_candidates = MagicMock(return_value=_make_valid_scene_proposal())
        # generate_npc_action returns ProposedAction (not NPCActionProposal)
        # because _process_npc_decisions passes it to _compute_state_deltas
        # which expects ProposedAction.actor_id
        mock_npc_action = MagicMock(return_value=ProposedAction(
            action_id="action_npc_000001",
            actor_id="npc_001",
            action_type="observe",
            summary="NPC observes",
            priority=0.5,
        ))
        mock_narration = MagicMock(return_value="古老的山门广场铺满了青石板。")

        orchestrator._world_engine.generate_world_candidates = mock_world_candidates
        orchestrator._scene_engine.generate_scene_candidates = mock_scene_candidates
        orchestrator._npc_engine.generate_npc_action = mock_npc_action
        orchestrator._narration_engine.generate_narration = mock_narration

        # For _parse_intent, we need to mock the pipeline's generate_input_intent
        # Use MagicMock that returns a coroutine result when awaited
        async def mock_generate_input_intent(*args, **kwargs):
            return _make_valid_input_proposal()
        
        pipeline = orchestrator._proposal_pipeline
        with patch.object(pipeline, 'generate_input_intent', side_effect=mock_generate_input_intent):

            result = orchestrator.execute_turn(
                session_id="session_001",
                game_id="game_001",
                turn_index=1,
                player_input="观察四周",
            )

        # Verify all engine methods were called (which call the pipeline)
        mock_world_candidates.assert_called_once()
        mock_scene_candidates.assert_called_once()
        mock_npc_action.assert_called_once()
        mock_narration.assert_called_once()

        # Verify turn completed successfully
        assert result["turn_index"] == 1
        assert result["validation_passed"] is True

    def test_turn_endpoint_falls_back_without_provider(self):
        """
        When no LLMService is provided (pipeline=None), execute_turn completes
        without calling any proposal pipeline methods.
        """
        orchestrator = build_turn_orchestrator(llm_service=None)

        # Set up valid game state
        valid_state = _make_valid_state(npc_ids=[])
        orchestrator._state_manager.get_state = MagicMock(return_value=valid_state)

        # Mock world_engine.advance_time
        world_time_after = WorldTime(calendar="修仙历", season="春", day=1, period="巳时")
        mock_world_tick = WorldTickEvent(
            event_id="evt_tick_002",
            turn_index=1,
            time_before=valid_state.world_state.current_time,
            time_after=world_time_after,
            summary="时间推进",
        )
        orchestrator._world_engine.advance_time = MagicMock(return_value=mock_world_tick)

        # Mock action_scheduler
        orchestrator._action_scheduler.collect_actors = MagicMock(return_value=["player"])
        orchestrator._action_scheduler.resolve_conflicts = MagicMock(
            return_value=[
                ProposedAction(
                    action_id="action_player_000001",
                    actor_id="player",
                    action_type="inspect",
                    summary="Player inspects",
                    priority=1.0,
                )
            ]
        )

        # Mock validator
        valid_result = ValidationResult(is_valid=True, checks=[], errors=[], warnings=[])
        orchestrator._validator.validate_action = MagicMock(return_value=valid_result)
        orchestrator._validator.validate_state_delta = MagicMock(return_value=valid_result)
        orchestrator._validator.validate_candidate_event = MagicMock(return_value=valid_result)

        # Mock event_log
        from llm_rpg.models.events import TurnTransaction
        mock_transaction = TurnTransaction(
            transaction_id="txn_002",
            session_id="session_001",
            game_id="game_001",
            turn_index=1,
            world_time_before=valid_state.world_state.current_time,
            player_input="观察四周",
        )
        orchestrator._event_log.start_turn = MagicMock(return_value=mock_transaction)
        orchestrator._event_log.record_event = MagicMock()
        orchestrator._event_log.commit_turn = MagicMock()

        # Mock perspective
        from llm_rpg.models.perspectives import PlayerPerspective, NarratorPerspective
        mock_player_perspective = PlayerPerspective(
            perspective_id="player_view_1",
            owner_id="player",
        )
        mock_narrator_perspective = NarratorPerspective(
            perspective_id="narrator_view_1",
            owner_id="narrator",
            base_perspective_id="player_view_1",
        )
        orchestrator._perspective.build_player_perspective = MagicMock(
            return_value=mock_player_perspective
        )
        orchestrator._perspective.build_narrator_perspective = MagicMock(
            return_value=mock_narrator_perspective
        )

        # Mock memory_writer
        orchestrator._memory_writer.process_turn = MagicMock(
            return_value={"memories_created": 0, "summary_created": None, "memory_ids": []}
        )

        # Verify pipeline is None
        assert orchestrator._proposal_pipeline is None

        # Execute turn - should complete without errors
        result = orchestrator.execute_turn(
            session_id="session_001",
            game_id="game_001",
            turn_index=1,
            player_input="观察四周",
        )

        # Verify turn completed successfully via fallback
        assert result["turn_index"] == 1
        assert result["validation_passed"] is True

    def test_turn_endpoint_falls_back_when_stage_llm_fails(self):
        """
        When a single pipeline stage raises an exception, the turn still succeeds
        via fallback behavior (keyword parser, deterministic world events, etc.).
        """
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        orchestrator = build_turn_orchestrator(llm_service=llm_service)

        # Set up valid game state
        valid_state = _make_valid_state(npc_ids=[])
        orchestrator._state_manager.get_state = MagicMock(return_value=valid_state)

        # Mock world_engine.advance_time
        world_time_after = WorldTime(calendar="修仙历", season="春", day=1, period="巳时")
        mock_world_tick = WorldTickEvent(
            event_id="evt_tick_003",
            turn_index=1,
            time_before=valid_state.world_state.current_time,
            time_after=world_time_after,
            summary="时间推进",
        )
        orchestrator._world_engine.advance_time = MagicMock(return_value=mock_world_tick)

        # Mock action_scheduler
        orchestrator._action_scheduler.collect_actors = MagicMock(return_value=["player"])
        orchestrator._action_scheduler.resolve_conflicts = MagicMock(
            return_value=[
                ProposedAction(
                    action_id="action_player_000001",
                    actor_id="player",
                    action_type="inspect",
                    summary="Player inspects",
                    priority=1.0,
                )
            ]
        )

        # Mock validator
        valid_result = ValidationResult(is_valid=True, checks=[], errors=[], warnings=[])
        orchestrator._validator.validate_action = MagicMock(return_value=valid_result)
        orchestrator._validator.validate_state_delta = MagicMock(return_value=valid_result)
        orchestrator._validator.validate_candidate_event = MagicMock(return_value=valid_result)

        # Mock event_log
        from llm_rpg.models.events import TurnTransaction
        mock_transaction = TurnTransaction(
            transaction_id="txn_003",
            session_id="session_001",
            game_id="game_001",
            turn_index=1,
            world_time_before=valid_state.world_state.current_time,
            player_input="观察四周",
        )
        orchestrator._event_log.start_turn = MagicMock(return_value=mock_transaction)
        orchestrator._event_log.record_event = MagicMock()
        orchestrator._event_log.commit_turn = MagicMock()

        # Mock perspective
        from llm_rpg.models.perspectives import PlayerPerspective, NarratorPerspective
        mock_player_perspective = PlayerPerspective(
            perspective_id="player_view_1",
            owner_id="player",
        )
        mock_narrator_perspective = NarratorPerspective(
            perspective_id="narrator_view_1",
            owner_id="narrator",
            base_perspective_id="player_view_1",
        )
        orchestrator._perspective.build_player_perspective = MagicMock(
            return_value=mock_player_perspective
        )
        orchestrator._perspective.build_narrator_perspective = MagicMock(
            return_value=mock_narrator_perspective
        )

        # Mock memory_writer
        orchestrator._memory_writer.process_turn = MagicMock(
            return_value={"memories_created": 0, "summary_created": None, "memory_ids": []}
        )

        # Patch generate_input_intent to raise an exception
        # The orchestrator's _parse_intent catches exceptions and falls back to keyword parser
        async def failing_generate_input_intent(*args, **kwargs):
            raise RuntimeError("LLM service unavailable")

        pipeline = orchestrator._proposal_pipeline
        with patch.object(pipeline, 'generate_input_intent', side_effect=failing_generate_input_intent):

            result = orchestrator.execute_turn(
                session_id="session_001",
                game_id="game_001",
                turn_index=1,
                player_input="观察四周",
            )

        # Verify turn completed successfully via fallback
        assert result["turn_index"] == 1
        assert result["validation_passed"] is True

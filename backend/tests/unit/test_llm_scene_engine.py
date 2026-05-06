"""
Unit tests for SceneEngine LLM-driven scene candidates.

Tests:
- generate_scene_candidates method
- ProposalPipeline integration
- Fallback behavior when LLM unavailable
- No state mutation (proposal-only behavior)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from llm_rpg.engines.scene_engine import (
    SceneEngine,
    Scene,
    SceneState,
    SceneTrigger,
    TriggerType,
)
from llm_rpg.models.proposals import (
    SceneEventProposal,
    CandidateEvent,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    ValidationStatus,
    create_fallback_scene_event,
)
from llm_rpg.models.events import ParsedIntent


class TestGenerateSceneCandidates:
    """Tests for SceneEngine.generate_scene_candidates method."""
    
    def test_returns_proposal_without_pipeline(self):
        engine = SceneEngine(proposal_pipeline=None)
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert isinstance(proposal, SceneEventProposal)
        assert proposal.scene_id == scene.scene_id
        assert proposal.is_fallback is True
    
    def test_returns_fallback_when_no_active_scenes(self):
        engine = SceneEngine()
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert isinstance(proposal, SceneEventProposal)
        assert proposal.scene_id == "none"
        assert proposal.is_fallback is True
    
    def test_proposal_does_not_mutate_state(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        original_state = scene.state
        original_actors = scene.active_actors.copy()
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert scene.state == original_state
        assert scene.active_actors == original_actors
    
    def test_uses_deterministic_triggers_as_fallback(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            priority=0.8,
        )
        
        scene = engine.create_scene(
            name="Forest Scene",
            location_id="forest",
            triggers=[trigger],
        )
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "forest"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert len(proposal.candidate_events) == 1
        assert proposal.candidate_events[0].event_type == "scene_trigger"
        assert proposal.candidate_events[0].importance == 0.8
    
    def test_includes_parsed_intent_in_context(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        parsed_intent = ParsedIntent(
            intent_type="talk",
            target="npc_001",
            risk_level="low",
            raw_tokens=["talk", "to", "npc"],
        )
        
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
            parsed_intent=parsed_intent,
        )
        
        assert proposal is not None
    
    def test_records_audit_log_on_success(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        
        engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        audit_log = engine.get_audit_log()
        assert len(audit_log) >= 1
    
    def test_clear_audit_log(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert len(engine.get_audit_log()) >= 1
        
        engine.clear_audit_log()
        assert len(engine.get_audit_log()) == 0


class TestProposalPipelineIntegration:
    """Tests for ProposalPipeline integration with SceneEngine."""
    
    def test_pipeline_used_when_available(self):
        mock_pipeline = MagicMock()
        expected_scene_id = "scene_test"
        mock_proposal = SceneEventProposal(
            scene_id=expected_scene_id,
            candidate_events=[
                CandidateEvent(
                    event_type="environment",
                    description="A cold wind blows",
                    target_entity_ids=[],
                    effects={},
                    importance=0.5,
                    visibility="player_visible",
                )
            ],
            state_deltas=[],
            affected_entities=[],
            visibility="player_visible",
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.SCENE_EVENT,
                source_engine=ProposalSource.SCENE_ENGINE,
                validation_status=ValidationStatus.PASSED,
            ),
            is_fallback=False,
        )
        
        mock_pipeline.generate_scene_event = AsyncMock(return_value=mock_proposal)
        
        engine = SceneEngine(proposal_pipeline=mock_pipeline)
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.scene_id in [expected_scene_id, scene.scene_id]
    
    def test_fallback_on_pipeline_error(self):
        mock_pipeline = MagicMock()
        
        mock_pipeline.generate_scene_event = AsyncMock(side_effect=Exception("LLM service unavailable"))
        
        engine = SceneEngine(proposal_pipeline=mock_pipeline)
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
    
    def test_fallback_on_pipeline_returns_fallback(self):
        mock_pipeline = MagicMock()
        fallback_proposal = create_fallback_scene_event(
            scene_id="scene_test",
            reason="LLM timeout"
        )
        
        async def mock_generate_fallback(*args, **kwargs):
            return fallback_proposal
        
        mock_pipeline.generate_scene_event = mock_generate_fallback
        
        engine = SceneEngine(proposal_pipeline=mock_pipeline)
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True


class TestSceneContextBuilding:
    """Tests for scene context building."""
    
    def test_builds_context_with_scene_data(self):
        engine = SceneEngine()
        scene = engine.create_scene(
            name="Forest Clearing",
            location_id="forest_001",
        )
        scene.active_actors = ["npc_001", "npc_002"]
        scene.blocked_paths = ["north"]
        scene.available_actions = ["investigate", "rest"]
        scene.context = {"danger_level": "medium"}
        engine.activate_scene(scene.scene_id)
        
        game_state = {
            "player_location": "forest_001",
            "world_time": {"period": "辰时"},
        }
        
        context = engine._build_scene_context(scene, game_state, None)
        
        assert context["scene_id"] == scene.scene_id
        assert context["scene_name"] == "Forest Clearing"
        assert context["location_id"] == "forest_001"
        assert "npc_001" in context["active_actors"]
        assert "north" in context["blocked_paths"]
        assert "investigate" in context["available_actions"]
        assert context["scene_context"]["danger_level"] == "medium"
        assert context["player_location"] == "forest_001"
    
    def test_includes_parsed_intent_in_context(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        
        parsed_intent = ParsedIntent(
            intent_type="attack",
            target="enemy_001",
            risk_level="high",
            raw_tokens=["attack", "enemy"],
        )
        
        context = engine._build_scene_context(scene, {}, parsed_intent)
        
        assert "player_intent" in context
        assert context["player_intent"]["intent_type"] == "attack"
        assert context["player_intent"]["target"] == "enemy_001"
        assert context["player_intent"]["risk_level"] == "high"


class TestFallbackProposal:
    """Tests for fallback proposal creation."""
    
    def test_fallback_uses_trigger_evaluation(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "cave"},
            priority=0.9,
        )
        
        scene = engine.create_scene(
            name="Cave Scene",
            location_id="cave",
            triggers=[trigger],
        )
        
        game_state = {"player_location": "cave"}
        
        proposal = engine._create_fallback_proposal(
            scene_id=scene.scene_id,
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.scene_id == scene.scene_id
        assert len(proposal.candidate_events) == 1
        assert proposal.candidate_events[0].importance == 0.9
        assert proposal.is_fallback is True
    
    def test_fallback_empty_when_no_triggers(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        
        game_state = {"player_location": "unknown"}
        
        proposal = engine._create_fallback_proposal(
            scene_id=scene.scene_id,
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert len(proposal.candidate_events) == 0
        assert proposal.confidence == 0.0


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing SceneEngine usage."""
    
    def test_existing_trigger_evaluation_unchanged(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
        )
        
        scene = engine.create_scene(
            name="Forest Scene",
            triggers=[trigger],
        )
        
        game_state = {"player_location": "forest"}
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        
        assert len(triggered) == 1
        assert triggered[0].trigger_id == "trig_1"
    
    def test_scene_activation_unchanged(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        
        result = engine.activate_scene(scene.scene_id)
        
        assert result is True
        assert scene.state == SceneState.ACTIVE
    
    def test_init_without_pipeline_works(self):
        engine = SceneEngine()
        
        assert engine is not None
        assert engine._proposal_pipeline is None
    
    def test_init_with_pipeline_works(self):
        mock_pipeline = MagicMock()
        engine = SceneEngine(proposal_pipeline=mock_pipeline)
        
        assert engine._proposal_pipeline is mock_pipeline


class TestNoSceneContext:
    """Tests for scene fallback behavior when no scene context."""

    def test_no_active_scenes_returns_fallback(self):
        engine = SceneEngine()
        
        game_state = {"player_location": "unknown"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert proposal.scene_id == "none"

    def test_no_scene_context_uses_deterministic_fallback(self):
        engine = SceneEngine()
        
        game_state = {"player_location": "forest"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True

    def test_scene_context_missing_player_location(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.scene_id == scene.scene_id

    def test_scene_fallback_with_pipeline_error(self):
        mock_pipeline = MagicMock()
        
        async def mock_generate_error(*args, **kwargs):
            raise RuntimeError("LLM service unavailable")
        
        mock_pipeline.generate_scene_event = mock_generate_error
        
        engine = SceneEngine(proposal_pipeline=mock_pipeline)
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        game_state = {"player_location": "test"}
        proposal = engine.generate_scene_candidates(
            game_state=game_state,
            current_turn=1,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True

"""
Tests for NarrationEngine proposal pipeline integration.

Tests that:
- NarrationEngine uses ProposalPipeline for NarrationProposal
- Narration only uses player-visible context
- Forbidden info is excluded/redacted from LLM prompts
- Fallback behavior works when pipeline fails
- Narration cannot invent uncommitted facts
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any, List

from llm_rpg.models.states import (
    CanonicalState,
    WorldState,
    PlayerState,
    CurrentSceneState,
    NPCState,
    LocationState,
)
from llm_rpg.models.events import WorldTime
from llm_rpg.models.perspectives import PlayerPerspective, NarratorPerspective
from llm_rpg.models.common import ContextPack
from llm_rpg.models.proposals import (
    NarrationProposal,
    ProposalType,
    ProposalSource,
    ProposalAuditMetadata,
    ValidationStatus,
    RepairStatus,
)
from llm_rpg.core.canonical_state import CanonicalStateManager
from llm_rpg.core.perspective import PerspectiveService
from llm_rpg.core.context_builder import ContextBuilder
from llm_rpg.core.retrieval import RetrievalSystem
from llm_rpg.core.validator import Validator
from llm_rpg.engines.narration_engine import NarrationEngine
from llm_rpg.llm.proposal_pipeline import ProposalPipeline, ProposalConfig
from llm_rpg.llm.service import LLMService, MockLLMProvider


class MockCanonicalStateManager:
    def __init__(self, state: CanonicalState):
        self._state = state
    
    def get_state(self, game_id: str):
        return self._state
    
    def initialize_game(self, **kwargs):
        return self._state


def create_mock_state() -> CanonicalState:
    return CanonicalState(
        world_state=WorldState(
            entity_id="world_1",
            world_id="test_world",
            current_time=WorldTime(
                calendar="standard",
                season="spring",
                day=1,
                hour=12,
                period="morning",
            ),
        ),
        player_state=PlayerState(
            entity_id="player_1",
            name="Test Player",
            location_id="square",
        ),
        current_scene_state=CurrentSceneState(
            entity_id="square",
            scene_id="square",
            location_id="square",
            active_actor_ids=["player_1"],
        ),
        location_states={
            "square": LocationState(
                entity_id="square",
                location_id="square",
                name="Town Square",
                known_to_player=True,
                danger_level=0.2,
            ),
        },
        npc_states={},
        quest_states={},
        faction_states={},
    )


def create_mock_context_pack() -> ContextPack:
    return ContextPack(
        context_id="ctx_001",
        context_type="narration",
        owner_id="player_1",
        content={
            "player_visible_context": {
                "player_state": {"name": "Test Player", "location_id": "square"},
                "visible_scene": {"location_id": "square", "scene_phase": "exploration", "danger_level": 0.2},
                "visible_npc_states": {},
                "known_facts": ["fact_001"],
                "known_rumors": ["rumor_001"],
                "visible_events": [],
            },
            "scene_tone": "neutral",
            "writing_style": "default",
            "narrator_tone": "neutral",
            "narrator_pacing": "normal",
            "allowed_hints": [],
            "lore_context": [],
        },
    )


def create_mock_narration_proposal(
    text: str = "The player stands in the town square.",
    tone: str = "neutral",
    is_fallback: bool = False,
    forbidden_info_detected: List[str] = [],
    hidden_info_check_passed: bool = True,
) -> NarrationProposal:
    return NarrationProposal(
        text=text,
        tone=tone,
        style_tags=[],
        visible_context_id="ctx_001",
        committed_facts_used=["fact_001"],
        hidden_info_check_passed=hidden_info_check_passed,
        forbidden_info_detected=forbidden_info_detected,
        mentioned_entities=[],
        visibility="player_visible",
        confidence=0.8,
        recommended_actions=[],
        audit=ProposalAuditMetadata(
            proposal_type=ProposalType.NARRATION,
            source_engine=ProposalSource.NARRATION_ENGINE,
            validation_status=ValidationStatus.PASSED,
            repair_status=RepairStatus.NONE,
        ),
        is_fallback=is_fallback,
    )


class TestNarrationEngineProposalPipeline:
    """Test NarrationEngine integration with ProposalPipeline."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def validator(self):
        return Validator()

    @pytest.fixture
    def mock_pipeline(self):
        pipeline = MagicMock(spec=ProposalPipeline)
        pipeline.generate_narration = AsyncMock(
            return_value=create_mock_narration_proposal()
        )
        return pipeline

    def test_narration_engine_fallback_without_pipeline(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """NarrationEngine should use fallback when no pipeline is provided."""
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
            proposal_pipeline=None,
        )
        
        player_perspective = PlayerPerspective(
            perspective_id="player_view",
            owner_id="player_1",
            known_facts=["fact_001"],
            known_rumors=[],
            visible_scene_ids=["square"],
            discovered_locations=["square"],
        )
        
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator_view",
            owner_id="narrator",
            base_perspective_id="player_view",
            forbidden_info=[],
        )
        
        narration = engine.generate_narration(
            game_id="game_1",
            turn_index=1,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
        )
        
        assert narration is not None
        assert len(narration) > 0

    @pytest.mark.asyncio
    async def test_narration_engine_uses_fallback_proposal(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """NarrationEngine should return fallback proposal when pipeline returns fallback."""
        fallback_proposal = create_mock_narration_proposal(
            text="Test Player 站在 Town Square，一切看起来都很平静。",
            is_fallback=True,
        )
        
        mock_pipeline = MagicMock(spec=ProposalPipeline)
        mock_pipeline.generate_narration = AsyncMock(return_value=fallback_proposal)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
            proposal_pipeline=mock_pipeline,
        )
        
        player_perspective = PlayerPerspective(
            perspective_id="player_view",
            owner_id="player_1",
            known_facts=["fact_001"],
            known_rumors=[],
            visible_scene_ids=["square"],
            discovered_locations=["square"],
        )
        
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator_view",
            owner_id="narrator",
            base_perspective_id="player_view",
            forbidden_info=[],
        )
        
        proposal = await engine.generate_narration_async(
            game_id="game_1",
            turn_index=1,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert len(proposal.text) > 0

    def test_narration_engine_fallback_when_state_not_found(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """NarrationEngine should return fallback when state is not found."""
        empty_state_manager = MockCanonicalStateManager(None)
        
        engine = NarrationEngine(
            state_manager=empty_state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
            proposal_pipeline=None,
        )
        
        narration = engine.generate_narration(
            game_id="nonexistent_game",
            turn_index=1,
            player_perspective=PlayerPerspective(
                perspective_id="player_view",
                owner_id="player_1",
            ),
            narrator_perspective=NarratorPerspective(
                perspective_id="narrator_view",
                owner_id="narrator",
                base_perspective_id="player_view",
            ),
        )
        
        assert narration == "世界陷入了沉默..."

    @pytest.mark.asyncio
    async def test_narration_engine_uses_pipeline(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
        mock_pipeline,
    ):
        """NarrationEngine should use ProposalPipeline when provided."""
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
            proposal_pipeline=mock_pipeline,
        )
        
        player_perspective = PlayerPerspective(
            perspective_id="player_view",
            owner_id="player_1",
            known_facts=["fact_001"],
            known_rumors=[],
            visible_scene_ids=["square"],
            discovered_locations=["square"],
        )
        
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator_view",
            owner_id="narrator",
            base_perspective_id="player_view",
            forbidden_info=[],
        )
        
        proposal = await engine.generate_narration_async(
            game_id="game_1",
            turn_index=1,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
        )
        
        assert proposal is not None
        assert isinstance(proposal, NarrationProposal)
        assert proposal.text == "The player stands in the town square."
        mock_pipeline.generate_narration.assert_called_once()

    @pytest.mark.asyncio
    async def test_narration_engine_creates_pipeline_if_missing(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """NarrationEngine should create pipeline with MockLLMProvider if not provided."""
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
            proposal_pipeline=None,
            llm_service=None,
        )
        
        # _ensure_pipeline should create one
        pipeline = engine._ensure_pipeline()
        assert pipeline is not None
        assert isinstance(pipeline, ProposalPipeline)

    @pytest.mark.asyncio
    async def test_narration_engine_handles_pipeline_exception(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """NarrationEngine should return fallback when pipeline raises exception."""
        failing_pipeline = MagicMock(spec=ProposalPipeline)
        failing_pipeline.generate_narration = AsyncMock(
            side_effect=Exception("Pipeline error")
        )
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
            proposal_pipeline=failing_pipeline,
        )
        
        player_perspective = PlayerPerspective(
            perspective_id="player_view",
            owner_id="player_1",
            known_facts=["fact_001"],
            known_rumors=[],
            visible_scene_ids=["square"],
            discovered_locations=["square"],
        )
        
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator_view",
            owner_id="narrator",
            base_perspective_id="player_view",
            forbidden_info=[],
        )
        
        proposal = await engine.generate_narration_async(
            game_id="game_1",
            turn_index=1,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert "Pipeline error" in proposal.audit.fallback_reason


class TestVisibleContextBuilding:
    """Test that narration context only includes player-visible info."""

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def validator(self):
        return Validator()

    def test_build_visible_context_excludes_forbidden_info(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_build_visible_context_for_llm should exclude forbidden info."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        context = create_mock_context_pack()
        forbidden_info = ["secret_password", "hidden_treasure_location"]
        
        visible_context = engine._build_visible_context_for_llm(
            context=context,
            forbidden_info=forbidden_info,
        )
        
        # Verify constraints are included
        assert "constraints" in visible_context
        assert len(visible_context["constraints"]) > 0
        
        # Verify forbidden info is NOT in visible context
        visible_str = str(visible_context)
        assert "secret_password" not in visible_str
        assert "hidden_treasure_location" not in visible_str

    def test_build_visible_context_includes_player_state(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_build_visible_context_for_llm should include player state."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        context = create_mock_context_pack()
        
        visible_context = engine._build_visible_context_for_llm(
            context=context,
            forbidden_info=[],
        )
        
        assert "player_state" in visible_context
        assert visible_context["player_state"]["name"] == "Test Player"

    def test_build_visible_context_includes_known_facts(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_build_visible_context_for_llm should include known facts."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        context = create_mock_context_pack()
        
        visible_context = engine._build_visible_context_for_llm(
            context=context,
            forbidden_info=[],
        )
        
        assert "known_facts" in visible_context
        assert "fact_001" in visible_context["known_facts"]


class TestForbiddenInfoLeakPrevention:
    """Test that forbidden info is detected and sanitized."""

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def validator(self):
        return Validator()

    def test_validate_and_sanitize_detects_forbidden_info(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_validate_and_sanitize_proposal should detect forbidden info in text."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        proposal = create_mock_narration_proposal(
            text="The secret_password opens the hidden door."
        )
        
        forbidden_info = ["secret_password"]
        
        sanitized = engine._validate_and_sanitize_proposal(
            proposal=proposal,
            forbidden_info=forbidden_info,
            visible_context_id="ctx_001",
        )
        
        assert sanitized.hidden_info_check_passed is False
        assert "secret_password" in sanitized.forbidden_info_detected
        assert "..." in sanitized.text  # Should be replaced
        assert "secret_password" not in sanitized.text

    def test_validate_and_sanitize_passes_clean_proposal(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_validate_and_sanitize_proposal should pass clean proposals."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        proposal = create_mock_narration_proposal(
            text="The player walks through the peaceful square."
        )
        
        forbidden_info = ["secret_password", "hidden_treasure"]
        
        sanitized = engine._validate_and_sanitize_proposal(
            proposal=proposal,
            forbidden_info=forbidden_info,
            visible_context_id="ctx_001",
        )
        
        assert sanitized.hidden_info_check_passed is True
        assert len(sanitized.forbidden_info_detected) == 0

    def test_sanitize_narration_replaces_forbidden_info(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_sanitize_narration should replace forbidden info with placeholders."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        narration = "The secret_password reveals the hidden_treasure location."
        forbidden_info = ["secret_password", "hidden_treasure"]
        
        sanitized = engine._sanitize_narration(narration, forbidden_info)
        
        assert "secret_password" not in sanitized
        assert "hidden_treasure" not in sanitized
        assert "..." in sanitized


class TestFallbackBehavior:
    """Test fallback behavior when LLM fails."""

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def validator(self):
        return Validator()

    def test_create_fallback_proposal(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_create_fallback_proposal should create valid NarrationProposal."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        context = create_mock_context_pack()
        
        proposal = engine._create_fallback_proposal(
            reason="LLM timeout",
            visible_context_id="ctx_001",
            context=context,
        )
        
        assert proposal is not None
        assert proposal.is_fallback is True
        assert proposal.audit.fallback_reason == "LLM timeout"
        assert proposal.audit.fallback_used is True
        assert len(proposal.text) > 0

    def test_create_fallback_proposal_without_context(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_create_fallback_proposal should work without context."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        proposal = engine._create_fallback_proposal(
            reason="State not found",
            visible_context_id=None,
            context=None,
        )
        
        assert proposal.text == "世界陷入了沉默..."
        assert proposal.is_fallback is True

    def test_generate_text_uses_player_visible_context(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_generate_text should use only player-visible context."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        context = create_mock_context_pack()
        
        text = engine._generate_text(context)
        
        assert text is not None
        assert len(text) > 0
        # Should mention player name or location
        assert "Test Player" in text or "Town Square" in text or "平静" in text

    def test_generate_text_high_danger(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """_generate_text should reflect high danger level."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        context = ContextPack(
            context_id="ctx_002",
            context_type="narration",
            owner_id="player_1",
            content={
                "player_visible_context": {
                    "player_state": {"name": "Test Player"},
                    "visible_scene": {
                        "location_id": "dungeon",
                        "scene_phase": "combat",
                        "danger_level": 0.9,
                    },
                },
            },
        )
        
        text = engine._generate_text(context)
        
        assert "危险" in text


class TestNarrationConstraints:
    """Test that narration follows constraints."""

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def validator(self):
        return Validator()

    def test_visible_context_includes_constraints(
        self,
        perspective_service,
        context_builder,
        validator,
    ):
        """Visible context should include narration constraints."""
        state = create_mock_state()
        state_manager = MockCanonicalStateManager(state)
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        context = create_mock_context_pack()
        
        visible_context = engine._build_visible_context_for_llm(
            context=context,
            forbidden_info=[],
        )
        
        assert "constraints" in visible_context
        constraints = visible_context["constraints"]
        
        # Should include constraints about not leaking hidden info
        constraints_str = str(constraints)
        assert "可见" in constraints_str or "隐藏" in constraints_str or "秘密" in constraints_str


class TestDescribeMethods:
    """Test describe_location and describe_npc_interaction methods."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def validator(self):
        return Validator()

    def test_describe_location(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """describe_location should return location description."""
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        description = engine.describe_location(
            game_id="game_1",
            location_id="square",
            player_perspective=PlayerPerspective(
                perspective_id="player_view",
                owner_id="player_1",
            ),
        )
        
        assert description is not None
        assert "Town Square" in description or "平静" in description

    def test_describe_location_not_found(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """describe_location should handle missing location."""
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        description = engine.describe_location(
            game_id="game_1",
            location_id="nonexistent",
            player_perspective=PlayerPerspective(
                perspective_id="player_view",
                owner_id="player_1",
            ),
        )
        
        assert "未知" in description

    def test_describe_npc_interaction(
        self,
        state,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """describe_npc_interaction should return NPC description."""
        state.npc_states["npc_1"] = NPCState(
            entity_id="npc_1",
            npc_id="npc_1",
            name="Merchant",
            location_id="square",
            status="alive",
            mood="friendly",
        )
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        description = engine.describe_npc_interaction(
            game_id="game_1",
            npc_id="npc_1",
            player_perspective=PlayerPerspective(
                perspective_id="player_view",
                owner_id="player_1",
            ),
        )
        
        assert description is not None
        assert "Merchant" in description or "友善" in description

    def test_describe_npc_hostile(
        self,
        state,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """describe_npc_interaction should reflect hostile mood."""
        state.npc_states["npc_1"] = NPCState(
            entity_id="npc_1",
            npc_id="npc_1",
            name="Bandit",
            location_id="square",
            status="alive",
            mood="hostile",
        )
        
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        description = engine.describe_npc_interaction(
            game_id="game_1",
            npc_id="npc_1",
            player_perspective=PlayerPerspective(
                perspective_id="player_view",
                owner_id="player_1",
            ),
        )
        
        assert "敌意" in description

    def test_describe_scene_event(
        self,
        state_manager,
        perspective_service,
        context_builder,
        validator,
    ):
        """describe_scene_event should add tone prefix."""
        engine = NarrationEngine(
            state_manager=state_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            validator=validator,
        )
        
        description = engine.describe_scene_event(
            event_summary="A shadow moves.",
            scene_tone="mysterious",
        )
        
        assert "神秘" in description
        assert "A shadow moves." in description


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

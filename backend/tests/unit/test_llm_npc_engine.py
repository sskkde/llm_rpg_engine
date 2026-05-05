"""
Tests for NPCEngine proposal pipeline integration.

Tests that:
- NPCEngine uses ProposalPipeline for NPCActionProposal
- Valid proposals are converted to ProposedAction
- Fallback behavior works when pipeline is unavailable
- NPC context is perspective-filtered (no forbidden info leak)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any

from llm_rpg.models.states import (
    CanonicalState,
    WorldState,
    PlayerState,
    CurrentSceneState,
    NPCState,
)
from llm_rpg.models.events import WorldTime
from llm_rpg.models.memories import (
    NPCMemoryScope,
    NPCProfile,
    NPCBeliefState,
    NPCKnowledgeState,
    NPCGoals,
    NPCSecrets,
    NPCRecentContext,
)
from llm_rpg.models.common import ProposedAction, ContextPack
from llm_rpg.models.proposals import (
    NPCActionProposal,
    ProposalType,
    ProposalSource,
    ProposalAuditMetadata,
    ValidationStatus,
    RepairStatus,
    StateDeltaCandidate,
)
from llm_rpg.core.perspective import PerspectiveService
from llm_rpg.core.retrieval import RetrievalSystem
from llm_rpg.core.context_builder import ContextBuilder
from llm_rpg.engines.npc_engine import NPCEngine


class MockCanonicalStateManager:
    def __init__(self, state: CanonicalState):
        self._state = state
    
    def get_state(self, game_id: str):
        return self._state


class MockNPCMemoryManager:
    def __init__(self, scope: NPCMemoryScope):
        self._scope = scope
    
    def get_scope(self, npc_id: str):
        return self._scope
    
    def add_perceived_event(self, npc_id, turn, summary, importance):
        pass
    
    def add_belief(self, npc_id, content, belief_type, confidence, truth_status, current_turn):
        pass


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
            active_actor_ids=["player_1", "npc_1"],
        ),
        location_states={},
        npc_states={
            "npc_1": NPCState(
                entity_id="npc_1",
                npc_id="npc_1",
                name="Test NPC",
                location_id="square",
                status="alive",
                mood="neutral",
                current_goal_ids=["goal_1"],
            ),
        },
        quest_states={},
        faction_states={},
    )


def create_mock_scope() -> NPCMemoryScope:
    return NPCMemoryScope(
        npc_id="npc_1",
        profile=NPCProfile(
            npc_id="npc_1",
            name="Test NPC",
        ),
        belief_state=NPCBeliefState(npc_id="npc_1"),
        recent_context=NPCRecentContext(npc_id="npc_1"),
        secrets=NPCSecrets(npc_id="npc_1"),
        knowledge_state=NPCKnowledgeState(npc_id="npc_1"),
        goals=NPCGoals(npc_id="npc_1"),
    )


def create_mock_proposal(
    npc_id: str = "npc_1",
    action_type: str = "talk",
    summary: str = "NPC与玩家交谈",
    confidence: float = 0.8,
    is_fallback: bool = False,
) -> NPCActionProposal:
    return NPCActionProposal(
        npc_id=npc_id,
        npc_name="Test NPC",
        action_type=action_type,
        target="player_1",
        summary=summary,
        visible_motivation="想要了解玩家",
        hidden_motivation="暗中观察玩家的反应",
        state_deltas=[
            StateDeltaCandidate(
                path="npc_states.npc_1.mood",
                operation="set",
                value="friendly",
                reason="玩家表现友好",
            )
        ],
        affected_entities=[],
        visibility="player_visible",
        confidence=confidence,
        alternatives=[],
        audit=ProposalAuditMetadata(
            proposal_type=ProposalType.NPC_ACTION,
            source_engine=ProposalSource.NPC_ENGINE,
            validation_status=ValidationStatus.PASSED,
            repair_status=RepairStatus.NONE,
        ),
        is_fallback=is_fallback,
    )


class TestNPCEngineProposalPipeline:
    """Test NPCEngine integration with ProposalPipeline."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def scope(self):
        return create_mock_scope()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def memory_manager(self, scope):
        return MockNPCMemoryManager(scope)

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    def test_npc_engine_fallback_without_pipeline(
        self,
        state_manager,
        memory_manager,
        perspective_service,
        context_builder,
    ):
        """NPCEngine should use fallback when no pipeline is provided."""
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        action = engine.generate_npc_action(
            npc_id="npc_1",
            game_id="game_1",
            turn_index=1,
        )
        
        assert action is not None
        assert action.actor_id == "npc_1"
        assert action.action_type == "pursue_goal"
        assert "目标" in action.summary

    def test_npc_engine_fallback_idle_without_goals(
        self,
        state,
        scope,
        perspective_service,
        context_builder,
    ):
        """NPCEngine should idle when NPC has no goals and no pipeline."""
        state.npc_states["npc_1"].current_goal_ids = []
        
        state_manager = MockCanonicalStateManager(state)
        memory_manager = MockNPCMemoryManager(scope)
        
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        action = engine.generate_npc_action(
            npc_id="npc_1",
            game_id="game_1",
            turn_index=1,
        )
        
        assert action is not None
        assert action.action_type == "idle"
        assert action.priority == 0.3

    def test_npc_engine_returns_none_for_dead_npc(
        self,
        state,
        scope,
        perspective_service,
        context_builder,
    ):
        """NPCEngine should return None for dead NPCs."""
        state.npc_states["npc_1"].status = "dead"
        
        state_manager = MockCanonicalStateManager(state)
        memory_manager = MockNPCMemoryManager(scope)
        
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        action = engine.generate_npc_action(
            npc_id="npc_1",
            game_id="game_1",
            turn_index=1,
        )
        
        assert action is None

    def test_npc_engine_returns_none_for_missing_npc(
        self,
        state,
        scope,
        perspective_service,
        context_builder,
    ):
        """NPCEngine should return None for non-existent NPCs."""
        state_manager = MockCanonicalStateManager(state)
        memory_manager = MockNPCMemoryManager(scope)
        
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        action = engine.generate_npc_action(
            npc_id="nonexistent_npc",
            game_id="game_1",
            turn_index=1,
        )
        
        assert action is None


class TestProposalConversion:
    """Test conversion of NPCActionProposal to ProposedAction."""

    @pytest.fixture
    def state(self):
        return create_mock_state()

    @pytest.fixture
    def scope(self):
        return create_mock_scope()

    @pytest.fixture
    def state_manager(self, state):
        return MockCanonicalStateManager(state)

    @pytest.fixture
    def memory_manager(self, scope):
        return MockNPCMemoryManager(scope)

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    def test_convert_proposal_to_action(
        self,
        state_manager,
        memory_manager,
        perspective_service,
        context_builder,
    ):
        """NPCActionProposal should be correctly converted to ProposedAction."""
        proposal = create_mock_proposal(
            npc_id="npc_1",
            action_type="talk",
            summary="NPC与玩家交谈",
            confidence=0.8,
        )
        
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        npc_state = state_manager.get_state("game_1").npc_states["npc_1"]
        action = engine._convert_proposal_to_action(proposal, npc_state)
        
        assert action.actor_id == "npc_1"
        assert action.action_type == "talk"
        assert action.summary == "NPC与玩家交谈"
        assert action.target_ids == ["player_1"]
        assert action.intention == "想要了解玩家"
        assert action.hidden_motivation == "暗中观察玩家的反应"
        assert action.visible_to_player is True
        assert action.priority == 0.8
        assert len(action.state_delta_candidates) == 1

    def test_convert_proposal_with_hidden_visibility(
        self,
        state_manager,
        memory_manager,
        perspective_service,
        context_builder,
    ):
        """Proposals with hidden visibility should set visible_to_player=False."""
        proposal = create_mock_proposal()
        proposal.visibility = "hidden"
        
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        npc_state = state_manager.get_state("game_1").npc_states["npc_1"]
        action = engine._convert_proposal_to_action(proposal, npc_state)
        
        assert action.visible_to_player is False

    def test_convert_proposal_without_target(
        self,
        state_manager,
        memory_manager,
        perspective_service,
        context_builder,
    ):
        """Proposals without target should have empty target_ids."""
        proposal = create_mock_proposal()
        proposal.target = None
        
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        npc_state = state_manager.get_state("game_1").npc_states["npc_1"]
        action = engine._convert_proposal_to_action(proposal, npc_state)
        
        assert action.target_ids == []

    def test_convert_proposal_state_deltas(
        self,
        state_manager,
        memory_manager,
        perspective_service,
        context_builder,
    ):
        """State deltas should be correctly converted."""
        proposal = create_mock_proposal()
        proposal.state_deltas = [
            StateDeltaCandidate(
                path="npc_states.npc_1.mood",
                operation="set",
                value="happy",
                reason="玩家帮助了NPC",
            ),
            StateDeltaCandidate(
                path="npc_states.npc_1.mental_state.trust_toward_player",
                operation="increment",
                value=0.1,
                reason="信任增加",
            ),
        ]
        
        engine = NPCEngine(
            state_manager=state_manager,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        npc_state = state_manager.get_state("game_1").npc_states["npc_1"]
        action = engine._convert_proposal_to_action(proposal, npc_state)
        
        assert len(action.state_delta_candidates) == 2
        assert action.state_delta_candidates[0]["path"] == "npc_states.npc_1.mood"
        assert action.state_delta_candidates[0]["operation"] == "set"
        assert action.state_delta_candidates[0]["value"] == "happy"


class TestPerspectiveSafety:
    """Test that NPC context is properly perspective-filtered."""

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    def test_npc_context_excludes_other_npc_private_memories(
        self,
        context_builder,
    ):
        """NPC context should not include other NPCs' private memories."""
        state = create_mock_state()
        state.npc_states["npc_2"] = NPCState(
            entity_id="npc_2",
            npc_id="npc_2",
            name="Other NPC",
            location_id="square",
            status="alive",
        )
        
        scope = NPCMemoryScope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
            belief_state=NPCBeliefState(npc_id="npc_1"),
            recent_context=NPCRecentContext(npc_id="npc_1"),
            secrets=NPCSecrets(npc_id="npc_1"),
            knowledge_state=NPCKnowledgeState(npc_id="npc_1"),
            goals=NPCGoals(npc_id="npc_1"),
        )
        
        context = context_builder.build_npc_context(
            npc_id="npc_1",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=scope,
        )
        
        context_str = str(context.content)
        private_memories = context.content.get("private_memories", [])
        assert "npc_2" not in str(private_memories)

    def test_npc_context_includes_own_secrets(
        self,
        context_builder,
    ):
        """NPC context should include the NPC's own secrets."""
        from llm_rpg.models.memories import Secret
        
        state = create_mock_state()
        
        scope = NPCMemoryScope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
            belief_state=NPCBeliefState(npc_id="npc_1"),
            recent_context=NPCRecentContext(npc_id="npc_1"),
            secrets=NPCSecrets(
                npc_id="npc_1",
                secrets=[
                    Secret(
                        secret_id="secret_1",
                        content="NPC的秘密身份",
                        willingness_to_reveal=0.1,
                    )
                ],
            ),
            knowledge_state=NPCKnowledgeState(npc_id="npc_1"),
            goals=NPCGoals(npc_id="npc_1"),
        )
        
        context = context_builder.build_npc_context(
            npc_id="npc_1",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=scope,
        )
        
        assert "secrets" in context.content
        assert len(context.content["secrets"]) == 1
        assert context.content["secrets"][0]["secret_id"] == "secret_1"

    def test_npc_context_includes_forbidden_knowledge_constraints(
        self,
        context_builder,
    ):
        """NPC context should include constraints about forbidden knowledge."""
        state = create_mock_state()
        
        scope = NPCMemoryScope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
            belief_state=NPCBeliefState(npc_id="npc_1"),
            recent_context=NPCRecentContext(npc_id="npc_1"),
            secrets=NPCSecrets(npc_id="npc_1"),
            knowledge_state=NPCKnowledgeState(
                npc_id="npc_1",
                forbidden_knowledge=["secret_conspiracy", "hidden_truth"],
            ),
            goals=NPCGoals(npc_id="npc_1"),
        )
        
        context = context_builder.build_npc_context(
            npc_id="npc_1",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=scope,
        )
        
        assert "constraints" in context.content
        constraints_str = str(context.content["constraints"])
        assert "secret_conspiracy" in constraints_str or "hidden_truth" in constraints_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

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


class TestNoNPCInScene:
    """Tests for behavior when no NPC is present in scene."""

    @pytest.fixture
    def state_no_npc(self):
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
            location_states={},
            npc_states={},
            quest_states={},
            faction_states={},
        )

    @pytest.fixture
    def state_manager_no_npc(self, state_no_npc):
        return MockCanonicalStateManager(state_no_npc)

    @pytest.fixture
    def memory_manager(self):
        scope = NPCMemoryScope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
            belief_state=NPCBeliefState(npc_id="npc_1"),
            recent_context=NPCRecentContext(npc_id="npc_1"),
            secrets=NPCSecrets(npc_id="npc_1"),
            knowledge_state=NPCKnowledgeState(npc_id="npc_1"),
            goals=NPCGoals(npc_id="npc_1"),
        )
        return MockNPCMemoryManager(scope)

    @pytest.fixture
    def perspective_service(self):
        return MagicMock(spec=PerspectiveService)

    @pytest.fixture
    def context_builder(self):
        return MagicMock(spec=ContextBuilder)

    def test_no_npc_in_scene_generate_npc_action_returns_none(
        self,
        state_no_npc,
        state_manager_no_npc,
        memory_manager,
        perspective_service,
        context_builder,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.generate_npc_action = AsyncMock()
        
        engine = NPCEngine(
            state_manager=state_manager_no_npc,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=mock_pipeline,
        )
        
        action = engine.generate_npc_action(
            npc_id="npc_nonexistent",
            game_id="game_1",
            turn_index=1,
        )
        
        assert action is None

    def test_empty_npc_states_generate_npc_action_returns_none(
        self,
        state_no_npc,
        state_manager_no_npc,
        memory_manager,
        perspective_service,
        context_builder,
    ):
        engine = NPCEngine(
            state_manager=state_manager_no_npc,
            memory_manager=memory_manager,
            perspective_service=perspective_service,
            context_builder=context_builder,
            proposal_pipeline=None,
        )
        
        action = engine.generate_npc_action(
            npc_id="any_npc",
            game_id="game_1",
            turn_index=1,
        )
        
        assert action is None


class TestExecuteNPCStage:
    """Tests for _execute_npc_stage() integration with turn service."""

    @pytest.fixture
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from llm_rpg.storage.database import Base
        from llm_rpg.storage.models import (
            UserModel, WorldModel, ChapterModel, LocationModel,
            NPCTemplateModel, SessionModel, SessionStateModel,
            SessionNPCStateModel, SessionPlayerStateModel,
        )

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        user = UserModel(id="u1", username="test", email="t@t.com", password_hash="h")
        world = WorldModel(id="w1", code="w1", name="World", genre="xianxia", status="active")
        chapter = ChapterModel(id="ch1", world_id="w1", chapter_no=1, name="Ch1")
        location = LocationModel(
            id="loc1", world_id="w1", chapter_id="ch1",
            code="square", name="广场", access_rules={"always_accessible": True},
        )
        npc_template = NPCTemplateModel(
            id="npc_t1", world_id="w1", code="guide",
            name="柳师姐", role_type="guide",
            public_identity="宗门向导",
            hidden_identity="暗影组织间谍",
            personality="温和友善",
            goals=["保护新弟子"],
        )
        session_model = SessionModel(
            id="s1", user_id="u1", save_slot_id=None,
            world_id="w1", current_chapter_id="ch1", status="active",
        )
        session_state = SessionStateModel(
            session_id="s1", current_location_id="loc1",
        )
        player_state = SessionPlayerStateModel(
            session_id="s1",
        )
        npc_state = SessionNPCStateModel(
            id="ns1", session_id="s1", npc_template_id="npc_t1",
            current_location_id="loc1", trust_score=50,
            suspicion_score=0, status_flags={"status": "alive", "mood": "neutral"},
        )

        session.add_all([
            user, world, chapter, location, npc_template,
            session_model, session_state, player_state, npc_state,
        ])
        session.commit()
        yield session
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    def test_npc_stage_disabled_returns_fallback(self, db):
        from llm_rpg.core.turn_service import _execute_npc_stage
        from llm_rpg.models.states import CanonicalState, WorldState, PlayerState, CurrentSceneState, NPCState
        from llm_rpg.models.events import WorldTime

        state = CanonicalState(
            world_state=WorldState(entity_id="w1", world_id="w1", current_time=WorldTime(
                calendar="修仙历", season="春", day=1, hour=12, period="辰时",
            )),
            player_state=PlayerState(entity_id="p1", name="玩家", location_id="loc1"),
            current_scene_state=CurrentSceneState(
                entity_id="loc1", scene_id="loc1", location_id="loc1", active_actor_ids=["p1"],
            ),
            location_states={}, npc_states={}, quest_states={}, faction_states={},
        )

        with patch("llm_rpg.core.turn_service._is_npc_stage_enabled", return_value=False):
            result = _execute_npc_stage(
                db=db, session_id="s1", turn_no=1,
                canonical_state=state, player_input="测试",
                action_type="action", current_location_id="loc1",
            )

        assert result.stage_name == "npc"
        assert result.accepted is False
        assert result.fallback_reason == "npc_stage_disabled"

    def test_npc_stage_no_active_npcs_returns_empty(self, db):
        from llm_rpg.core.turn_service import _execute_npc_stage
        from llm_rpg.models.states import CanonicalState, WorldState, PlayerState, CurrentSceneState, NPCState
        from llm_rpg.models.events import WorldTime

        state = CanonicalState(
            world_state=WorldState(entity_id="w1", world_id="w1", current_time=WorldTime(
                calendar="修仙历", season="春", day=1, hour=12, period="辰时",
            )),
            player_state=PlayerState(entity_id="p1", name="玩家", location_id="loc1"),
            current_scene_state=CurrentSceneState(
                entity_id="loc1", scene_id="loc1", location_id="loc1", active_actor_ids=["p1"],
            ),
            location_states={}, npc_states={}, quest_states={}, faction_states={},
        )

        result = _execute_npc_stage(
            db=db, session_id="s1", turn_no=1,
            canonical_state=state, player_input="测试",
            action_type="action", current_location_id="nonexistent",
        )

        assert result.stage_name == "npc"
        assert result.accepted is True
        assert result.parsed_proposal == {"npc_reactions": []}

    def test_validate_npc_action_rejects_none(self):
        from llm_rpg.core.turn_service import _validate_npc_action

        is_valid, errors = _validate_npc_action(None, {})
        assert is_valid is False
        assert "None" in errors[0]

    def test_validate_npc_action_rejects_forbidden_pattern(self):
        from llm_rpg.core.turn_service import _validate_npc_action

        class MockProposal:
            npc_id = "npc_1"
            action_type = "talk"
            summary = "NPC泄露了隐藏身份"
            visibility = "player_visible"

        is_valid, errors = _validate_npc_action(MockProposal(), {})
        assert is_valid is False
        assert any("hidden" in e or "隐藏" in e for e in errors)

    def test_validate_npc_action_accepts_valid(self):
        from llm_rpg.core.turn_service import _validate_npc_action

        class MockProposal:
            npc_id = "npc_1"
            action_type = "talk"
            summary = "NPC与玩家交谈"
            visibility = "player_visible"

        is_valid, errors = _validate_npc_action(MockProposal(), {})
        assert is_valid is True
        assert errors == []

    def test_build_npc_context_excludes_hidden_identity(self, db):
        from llm_rpg.core.turn_service import _build_npc_context
        from llm_rpg.models.states import CanonicalState, WorldState, PlayerState, CurrentSceneState, NPCState
        from llm_rpg.models.events import WorldTime

        state = CanonicalState(
            world_state=WorldState(entity_id="w1", world_id="w1", current_time=WorldTime(
                calendar="修仙历", season="春", day=1, hour=12, period="辰时",
            )),
            player_state=PlayerState(entity_id="p1", name="玩家", location_id="loc1"),
            current_scene_state=CurrentSceneState(
                entity_id="loc1", scene_id="loc1", location_id="loc1", active_actor_ids=["p1"],
            ),
            location_states={}, npc_states={}, quest_states={}, faction_states={},
        )

        context = _build_npc_context(
            db=db, session_id="s1", npc_id="ns1", npc_template_id="npc_t1",
            canonical_state=state, player_input="测试", action_type="action",
            current_location_id="loc1",
        )

        assert "hidden_identity" not in context
        assert "hidden_plan_state" not in context
        assert context.get("public_identity") == "宗门向导"
        assert context.get("personality") == "温和友善"
        assert context.get("goals") == ["保护新弟子"]
        assert context.get("trust_score") == 50

    def test_get_active_npcs_excludes_dead(self, db):
        from llm_rpg.core.turn_service import _get_active_npcs_at_location
        from llm_rpg.storage.models import SessionNPCStateModel

        npc_state = db.query(SessionNPCStateModel).filter_by(id="ns1").one()
        npc_state.status_flags = {"status": "dead", "mood": "neutral"}
        db.commit()

        active_npcs = _get_active_npcs_at_location(db, "s1", "loc1")
        assert len(active_npcs) == 0

    def test_get_active_npcs_excludes_wrong_location(self, db):
        from llm_rpg.core.turn_service import _get_active_npcs_at_location

        active_npcs = _get_active_npcs_at_location(db, "s1", "wrong_location")
        assert len(active_npcs) == 0

    def test_get_active_npcs_returns_alive_at_location(self, db):
        from llm_rpg.core.turn_service import _get_active_npcs_at_location

        active_npcs = _get_active_npcs_at_location(db, "s1", "loc1")
        assert len(active_npcs) == 1
        assert active_npcs[0]["name"] == "柳师姐"
        assert active_npcs[0]["public_identity"] == "宗门向导"
        assert "hidden_identity" not in active_npcs[0]


class TestNPCStageInLLMStages:
    """Tests for NPC stage within _execute_llm_stages() pipeline."""

    @pytest.fixture
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from llm_rpg.storage.database import Base
        from llm_rpg.storage.models import (
            UserModel, WorldModel, ChapterModel, LocationModel,
            NPCTemplateModel, SessionModel, SessionStateModel,
            SessionNPCStateModel, SessionPlayerStateModel,
        )

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        user = UserModel(id="u1", username="test", email="t@t.com", password_hash="h")
        world = WorldModel(id="w1", code="w1", name="World", genre="xianxia", status="active")
        chapter = ChapterModel(id="ch1", world_id="w1", chapter_no=1, name="Ch1")
        location = LocationModel(
            id="loc1", world_id="w1", chapter_id="ch1",
            code="square", name="广场", access_rules={"always_accessible": True},
        )
        npc_template = NPCTemplateModel(
            id="npc_t1", world_id="w1", code="guide",
            name="柳师姐", role_type="guide",
            public_identity="宗门向导",
            hidden_identity="暗影组织间谍",
            personality="温和友善",
            goals=["保护新弟子"],
        )
        session_model = SessionModel(
            id="s1", user_id="u1", save_slot_id=None,
            world_id="w1", current_chapter_id="ch1", status="active",
        )
        session_state = SessionStateModel(
            session_id="s1", current_location_id="loc1",
        )
        player_state = SessionPlayerStateModel(
            session_id="s1",
        )
        npc_state = SessionNPCStateModel(
            id="ns1", session_id="s1", npc_template_id="npc_t1",
            current_location_id="loc1", trust_score=50,
            suspicion_score=0, status_flags={"status": "alive", "mood": "neutral"},
        )

        session.add_all([
            user, world, chapter, location, npc_template,
            session_model, session_state, player_state, npc_state,
        ])
        session.commit()
        yield session
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    def test_llm_stages_includes_npc_result(self, db):
        from llm_rpg.core.turn_service import _execute_llm_stages
        from llm_rpg.models.states import CanonicalState, WorldState, PlayerState, CurrentSceneState
        from llm_rpg.models.events import WorldTime

        state = CanonicalState(
            world_state=WorldState(entity_id="w1", world_id="w1", current_time=WorldTime(
                calendar="修仙历", season="春", day=1, hour=12, period="辰时",
            )),
            player_state=PlayerState(entity_id="p1", name="玩家", location_id="loc1"),
            current_scene_state=CurrentSceneState(
                entity_id="loc1", scene_id="loc1", location_id="loc1", active_actor_ids=["p1"],
            ),
            location_states={}, npc_states={}, quest_states={}, faction_states={},
        )

        results = _execute_llm_stages(
            db=db, session_id="s1", turn_no=1,
            canonical_state=state, player_input="测试",
            action_type="action", current_location_id="loc1",
        )

        stage_names = [r.stage_name for r in results]
        assert "scene" in stage_names
        assert "npc" in stage_names
        assert "narration" in stage_names

        npc_result = next(r for r in results if r.stage_name == "npc")
        assert npc_result.enabled is True

    def test_npc_reactions_passed_to_narration(self, db):
        from llm_rpg.core.turn_service import _execute_llm_stages
        from llm_rpg.models.states import CanonicalState, WorldState, PlayerState, CurrentSceneState
        from llm_rpg.models.events import WorldTime

        state = CanonicalState(
            world_state=WorldState(entity_id="w1", world_id="w1", current_time=WorldTime(
                calendar="修仙历", season="春", day=1, hour=12, period="辰时",
            )),
            player_state=PlayerState(entity_id="p1", name="玩家", location_id="loc1"),
            current_scene_state=CurrentSceneState(
                entity_id="loc1", scene_id="loc1", location_id="loc1", active_actor_ids=["p1"],
            ),
            location_states={}, npc_states={}, quest_states={}, faction_states={},
        )

        results = _execute_llm_stages(
            db=db, session_id="s1", turn_no=1,
            canonical_state=state, player_input="测试",
            action_type="action", current_location_id="loc1",
        )

        npc_result = next(r for r in results if r.stage_name == "npc")
        narration_result = next(r for r in results if r.stage_name == "narration")

        if npc_result.accepted and npc_result.parsed_proposal:
            npc_reactions = npc_result.parsed_proposal.get("npc_reactions", [])
            if npc_reactions:
                assert narration_result.fallback_reason != "narration_stage_disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

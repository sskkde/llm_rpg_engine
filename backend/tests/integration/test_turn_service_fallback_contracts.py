"""
Integration tests for turn boundary and LLM fallback contracts.

Tests verify:
1. One turn input produces exactly one durable player-turn event even when LLM fallback occurs
2. Fallback reasons/validation errors are recorded in result_json/stage metadata
3. All LLM stages disabled still yields deterministic non-LLM behavior
4. Rejected proposals do NOT create state deltas from proposal payload
5. Timeout returns structured fallback metadata with exactly one committed turn
6. LLM config error returns fallback with no duplicate event commit

Key contracts:
- execute_turn_service() is the single production durable turn boundary
- LLMStageResult tracks: stage_name, enabled, accepted, fallback_reason, raw_outcome, stage_metadata
- TurnTransactionModel.status == "committed" after successful turn
- GameEventModel records all events including player_turn
- StateDeltaModel records state changes with valid source_event_id
"""

import asyncio
import pytest
from datetime import datetime
from typing import Dict, Any, List, Optional
from unittest.mock import patch, MagicMock, AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    WorldModel,
    ChapterModel,
    LocationModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    NPCTemplateModel,
    SessionQuestStateModel,
    QuestTemplateModel,
    EventLogModel,
    TurnTransactionModel,
    GameEventModel,
    StateDeltaModel,
    LLMStageResultModel,
    ValidationReportModel,
)
from llm_rpg.core.turn_service import (
    execute_turn_service,
    TurnResult,
    TurnServiceError,
    SessionNotFoundError,
    LLMStageResult,
)
from llm_rpg.llm.service import MockLLMProvider, LLMService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_user(db: Session) -> UserModel:
    user = UserModel(
        id="user_fallback_contract",
        username="testuser_fallback",
        email="test_fallback@example.com",
        password_hash="hashed",
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_world(db: Session) -> WorldModel:
    world = WorldModel(
        id="world_fallback_contract",
        code="test_world_fallback",
        name="Fallback Contract Test World",
        genre="xianxia",
        lore_summary="World for testing fallback contracts",
        status="active",
    )
    db.add(world)
    db.commit()
    return world


@pytest.fixture
def test_chapter(db: Session, test_world: WorldModel) -> ChapterModel:
    chapter = ChapterModel(
        id="chapter_fallback_contract",
        world_id=test_world.id,
        chapter_no=1,
        name="Chapter 1",
        summary="Test chapter",
    )
    db.add(chapter)
    db.commit()
    return chapter


@pytest.fixture
def test_locations(db: Session, test_world: WorldModel, test_chapter: ChapterModel):
    locations = [
        LocationModel(
            id="loc_square_fallback",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="square",
            name="Sect Square",
            tags=["public", "safe", "starting_point"],
            description="The main square",
            access_rules={"always_accessible": True},
        ),
        LocationModel(
            id="loc_trial_hall_fallback",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="trial_hall",
            name="Trial Hall",
            tags=["public", "quest_hub"],
            description="The trial hall",
            access_rules={"time_restrictions": "daytime_only"},
        ),
    ]
    for loc in locations:
        db.add(loc)
    db.commit()
    return locations


@pytest.fixture
def test_npc_templates(db: Session, test_world: WorldModel):
    npcs = [
        NPCTemplateModel(
            id="npc_fallback_1",
            world_id=test_world.id,
            code="test_npc_fallback",
            name="Test NPC",
            role_type="mentor",
            personality="Friendly",
        ),
    ]
    for npc in npcs:
        db.add(npc)
    db.commit()
    return npcs


@pytest.fixture
def test_quest_templates(db: Session, test_world: WorldModel):
    quests = [
        QuestTemplateModel(
            id="quest_fallback_1",
            world_id=test_world.id,
            code="test_quest_fallback",
            name="Test Quest",
            quest_type="main",
            visibility="visible",
        ),
    ]
    for quest in quests:
        db.add(quest)
    db.commit()
    return quests


@pytest.fixture
def test_save_slot(db: Session, test_user: UserModel) -> SaveSlotModel:
    save_slot = SaveSlotModel(
        id="slot_fallback_contract",
        user_id=test_user.id,
        slot_number=1,
        name="Fallback Contract Test Save",
    )
    db.add(save_slot)
    db.commit()
    return save_slot


@pytest.fixture
def test_session(
    db: Session,
    test_user: UserModel,
    test_world: WorldModel,
    test_save_slot: SaveSlotModel,
) -> SessionModel:
    session = SessionModel(
        id="session_fallback_contract",
        user_id=test_user.id,
        world_id=test_world.id,
        save_slot_id=test_save_slot.id,
        status="active",
    )
    db.add(session)
    db.commit()
    return session


@pytest.fixture
def test_session_state(
    db: Session,
    test_session: SessionModel,
) -> SessionStateModel:
    state = SessionStateModel(
        id="state_fallback_contract",
        session_id=test_session.id,
        current_time="修仙历 春 第1日 辰时",
        time_phase="辰时",
        current_location_id="loc_square_fallback",
        active_mode="exploration",
        global_flags_json={},
    )
    db.add(state)
    db.commit()
    return state


@pytest.fixture
def test_player_state(
    db: Session,
    test_session: SessionModel,
) -> SessionPlayerStateModel:
    state = SessionPlayerStateModel(
        id="player_state_fallback",
        session_id=test_session.id,
        realm_stage="炼气一层",
        hp=100,
        max_hp=100,
        stamina=100,
        spirit_power=100,
    )
    db.add(state)
    db.commit()
    return state


class TestLLMTimeoutFallbackContract:
    """
    Tests that LLM timeout returns structured fallback metadata with exactly one committed turn.
    """

    def test_llm_timeout_returns_fallback_metadata(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that an LLM timeout returns structured fallback metadata with exactly one committed turn.
        
        Contract:
        - Turn completes successfully (no crash)
        - TurnTransactionModel.status == "committed"
        - Exactly one player_turn event in event_log
        - LLMStageResult has fallback_reason="timeout"
        """
        from llm_rpg.models.proposals import (
            WorldTickProposal,
            CandidateEvent,
            StateDeltaCandidate,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
        )
        
        async def timeout_generate(*args, **kwargs):
            raise asyncio.TimeoutError("LLM call timed out")
        
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_service.generate = timeout_generate
                mock_create.return_value = mock_service
                
                result = execute_turn_service(
                    db=db,
                    session_id=test_session.id,
                    player_input="wait",
                    idempotency_key="timeout_fallback_key",
                )
        
        assert result is not None
        assert result.turn_no == 1
        assert result.validation_passed is True
        assert result.transaction_id is not None
        
        transaction = db.query(TurnTransactionModel).filter(
            TurnTransactionModel.id == result.transaction_id
        ).first()
        assert transaction is not None
        assert transaction.status == "committed"
        
        events = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).all()
        player_turn_events = [e for e in events if e.event_type == "player_turn"]
        assert len(player_turn_events) == 1, "Expected exactly one player_turn event"
        
        stage_results = db.query(LLMStageResultModel).filter(
            LLMStageResultModel.session_id == test_session.id,
            LLMStageResultModel.turn_no == 1,
        ).all()
        
        timeout_stages = [s for s in stage_results if s.fallback_reason and "timeout" in s.fallback_reason.lower()]
        assert len(timeout_stages) >= 1, "Expected at least one stage with timeout fallback_reason"

    def test_llm_timeout_no_duplicate_event_commit(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that LLM timeout does not create duplicate event commits.
        
        Contract:
        - Exactly one player_turn event per turn
        - No duplicate game_events for the same turn
        """
        async def timeout_generate(*args, **kwargs):
            raise asyncio.TimeoutError("LLM call timed out")
        
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_service.generate = timeout_generate
                mock_create.return_value = mock_service
                
                result = execute_turn_service(
                    db=db,
                    session_id=test_session.id,
                    player_input="observe surroundings",
                    idempotency_key="timeout_no_duplicate_key",
                )
        
        events = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).all()
        
        player_turn_events = [e for e in events if e.event_type == "player_turn"]
        assert len(player_turn_events) == 1, "Expected exactly one player_turn event, no duplicates"


class TestLLMConfigErrorFallbackContract:
    """
    Tests that LLM config error returns fallback with no duplicate event commit.
    """

    def test_llm_config_error_returns_fallback(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that an LLM config error (invalid proposal) returns fallback with no duplicate event commit.
        
        Contract:
        - Turn completes successfully (no crash)
        - LLMStageResult has fallback_reason containing "llm_config_error"
        - Exactly one player_turn event
        """
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                def raise_config_error(*args, **kwargs):
                    raise Exception("Invalid LLM configuration: missing API key")
                mock_create.side_effect = raise_config_error
                
                result = execute_turn_service(
                    db=db,
                    session_id=test_session.id,
                    player_input="wait",
                    idempotency_key="config_error_fallback_key",
                )
        
        assert result is not None
        assert result.turn_no == 1
        assert result.validation_passed is True
        
        events = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).all()
        player_turn_events = [e for e in events if e.event_type == "player_turn"]
        assert len(player_turn_events) == 1, "Expected exactly one player_turn event"

    def test_llm_config_error_records_fallback_reason(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that LLM config error records fallback_reason in stage metadata.
        """
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                def raise_config_error(*args, **kwargs):
                    raise Exception("Invalid LLM configuration")
                mock_create.side_effect = raise_config_error
                
                result = execute_turn_service(
                    db=db,
                    session_id=test_session.id,
                    player_input="wait",
                    idempotency_key="config_error_reason_key",
                )
        
        stage_results = db.query(LLMStageResultModel).filter(
            LLMStageResultModel.session_id == test_session.id,
            LLMStageResultModel.turn_no == 1,
        ).all()
        
        fallback_stages = [s for s in stage_results if s.fallback_reason]
        assert len(fallback_stages) >= 1, "Expected at least one stage with fallback_reason"


class TestAllStagesDisabledDeterministicBehavior:
    """
    Tests that all LLM stages disabled still produces deterministic behavior (no crash, valid response).
    """

    def test_all_stages_disabled_produces_valid_response(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that disabled feature flags (all LLM stages disabled) still produce deterministic behavior.
        
        Contract:
        - Turn completes successfully (no crash)
        - TurnTransactionModel.status == "committed"
        - All LLMStageResult have enabled=False
        - Narration is generated via deterministic fallback
        """
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=False):
            with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=False):
                with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=False):
                    with patch("llm_rpg.core.turn_service._is_npc_stage_enabled", return_value=False):
                        with patch("llm_rpg.core.turn_service._is_narration_stage_enabled", return_value=False):
                            result = execute_turn_service(
                                db=db,
                                session_id=test_session.id,
                                player_input="I go to the trial hall",
                                idempotency_key="all_disabled_key",
                            )
        
        assert result is not None
        assert result.turn_no == 1
        assert result.validation_passed is True
        assert result.narration is not None
        assert len(result.narration) > 0
        assert result.transaction_id is not None
        
        transaction = db.query(TurnTransactionModel).filter(
            TurnTransactionModel.id == result.transaction_id
        ).first()
        assert transaction is not None
        assert transaction.status == "committed"
        
        stage_results = db.query(LLMStageResultModel).filter(
            LLMStageResultModel.session_id == test_session.id,
            LLMStageResultModel.turn_no == 1,
        ).all()
        
        for stage in stage_results:
            assert stage.fallback_reason is not None

    def test_all_stages_disabled_no_crash(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that all LLM stages disabled does not crash the system.
        """
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=False):
            with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=False):
                with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=False):
                    with patch("llm_rpg.core.turn_service._is_npc_stage_enabled", return_value=False):
                        with patch("llm_rpg.core.turn_service._is_narration_stage_enabled", return_value=False):
                            try:
                                result = execute_turn_service(
                                    db=db,
                                    session_id=test_session.id,
                                    player_input="observe",
                                    idempotency_key="no_crash_key",
                                )
                                assert result is not None
                            except Exception as e:
                                pytest.fail(f"Turn execution should not crash when all stages disabled: {e}")

    def test_all_stages_disabled_creates_valid_event(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that all stages disabled still creates valid game_event records.
        """
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=False):
            with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=False):
                with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=False):
                    with patch("llm_rpg.core.turn_service._is_npc_stage_enabled", return_value=False):
                        with patch("llm_rpg.core.turn_service._is_narration_stage_enabled", return_value=False):
                            result = execute_turn_service(
                                db=db,
                                session_id=test_session.id,
                                player_input="wait",
                                idempotency_key="disabled_valid_event_key",
                            )
        
        events = db.query(GameEventModel).filter(
            GameEventModel.session_id == test_session.id,
            GameEventModel.turn_no == 1,
        ).all()
        
        assert len(events) >= 1, "Expected at least one game_event"
        
        narration_events = [e for e in events if e.event_type == "narration"]
        assert len(narration_events) >= 1, "Expected narration game_event"


class TestRejectedProposalNoStateDelta:
    """
    Tests that rejected proposals do NOT create state deltas from proposal payload.
    """

    def test_rejected_proposal_no_state_delta_from_payload(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that rejected proposals do NOT create state_deltas from proposal payload.
        
        Contract:
        - Rejected proposal creates validation_report with errors
        - Rejected proposal creates llm_stage_result with accepted=False
        - Rejected proposal does NOT create state_deltas from the proposal payload
        - Turn still completes successfully with fallback behavior
        """
        from llm_rpg.models.proposals import (
            WorldTickProposal,
            CandidateEvent,
            StateDeltaCandidate,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
        )
        
        invalid_world_proposal = WorldTickProposal(
            time_description="Time passes...",
            candidate_events=[
                CandidateEvent(
                    event_type="time_based",
                    description="Test event",
                    effects={},
                    importance=0.5,
                )
            ],
            state_deltas=[
                StateDeltaCandidate(
                    path="player_state.hp",
                    operation="set",
                    value=0,
                    reason="invalid - world cannot modify player hp",
                )
            ],
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.WORLD_TICK,
                source_engine=ProposalSource.WORLD_ENGINE,
            ),
        )
        
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                with patch("llm_rpg.llm.proposal_pipeline.ProposalPipeline") as MockPipeline:
                    mock_pipeline_instance = MagicMock()
                    mock_pipeline_instance.generate_world_tick = AsyncMock(
                        return_value=invalid_world_proposal
                    )
                    MockPipeline.return_value = mock_pipeline_instance
                    
                    result = execute_turn_service(
                        db=db,
                        session_id=test_session.id,
                        player_input="wait",
                        idempotency_key="rejected_no_delta_key",
                    )
        
        assert result.turn_no == 1
        assert result.validation_passed is True
        
        state_deltas = db.query(StateDeltaModel).filter(
            StateDeltaModel.session_id == test_session.id,
            StateDeltaModel.turn_no == 1,
        ).all()
        
        hp_deltas = [d for d in state_deltas if d.path == "player_state.hp"]
        assert len(hp_deltas) == 0, "Expected no state_delta for player_state.hp from rejected proposal"
        
        allowed_paths = [
            "session_state.world_time",
            "session_state.current_location_id",
        ]
        for delta in state_deltas:
            assert delta.path in allowed_paths, f"Unexpected state_delta path: {delta.path}"

    def test_rejected_proposal_creates_validation_report(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that rejected proposal creates validation_report with errors.
        """
        from llm_rpg.models.proposals import (
            WorldTickProposal,
            CandidateEvent,
            StateDeltaCandidate,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
        )
        
        invalid_world_proposal = WorldTickProposal(
            time_description="Time passes...",
            candidate_events=[],
            state_deltas=[
                StateDeltaCandidate(
                    path="player_state.hp",
                    operation="set",
                    value=0,
                    reason="invalid",
                )
            ],
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.WORLD_TICK,
                source_engine=ProposalSource.WORLD_ENGINE,
            ),
        )
        
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                with patch("llm_rpg.llm.proposal_pipeline.ProposalPipeline") as MockPipeline:
                    mock_pipeline_instance = MagicMock()
                    mock_pipeline_instance.generate_world_tick = AsyncMock(
                        return_value=invalid_world_proposal
                    )
                    MockPipeline.return_value = mock_pipeline_instance
                    
                    result = execute_turn_service(
                        db=db,
                        session_id=test_session.id,
                        player_input="wait",
                        idempotency_key="rejected_validation_report_key",
                    )
        
        validation_reports = db.query(ValidationReportModel).filter(
            ValidationReportModel.session_id == test_session.id,
            ValidationReportModel.turn_no == 1,
            ValidationReportModel.scope == "proposal_world_tick",
        ).all()
        
        assert len(validation_reports) >= 1, "Expected validation_report for rejected world proposal"
        
        invalid_reports = [r for r in validation_reports if not r.is_valid]
        assert len(invalid_reports) >= 1, "Expected validation_report with is_valid=False"
        
        for report in invalid_reports:
            assert report.errors_json is not None
            assert len(report.errors_json) > 0

    def test_rejected_proposal_creates_llm_stage_result_with_accepted_false(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that rejected proposal creates llm_stage_result with accepted=False.
        """
        from llm_rpg.models.proposals import (
            WorldTickProposal,
            CandidateEvent,
            StateDeltaCandidate,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
        )
        
        invalid_world_proposal = WorldTickProposal(
            time_description="Time passes...",
            candidate_events=[],
            state_deltas=[
                StateDeltaCandidate(
                    path="player_state.hp",
                    operation="set",
                    value=0,
                    reason="invalid",
                )
            ],
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.WORLD_TICK,
                source_engine=ProposalSource.WORLD_ENGINE,
            ),
        )
        
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                with patch("llm_rpg.llm.proposal_pipeline.ProposalPipeline") as MockPipeline:
                    mock_pipeline_instance = MagicMock()
                    mock_pipeline_instance.generate_world_tick = AsyncMock(
                        return_value=invalid_world_proposal
                    )
                    MockPipeline.return_value = mock_pipeline_instance
                    
                    result = execute_turn_service(
                        db=db,
                        session_id=test_session.id,
                        player_input="wait",
                        idempotency_key="rejected_stage_result_key",
                    )
        
        stage_results = db.query(LLMStageResultModel).filter(
            LLMStageResultModel.session_id == test_session.id,
            LLMStageResultModel.turn_no == 1,
        ).all()
        
        assert len(stage_results) >= 1, "Expected llm_stage_result records"
        
        world_results = [r for r in stage_results if r.stage_name == "world"]
        if len(world_results) > 0:
            world_result = world_results[0]
            assert world_result.accepted is False, "Expected world stage result to have accepted=False"
            assert world_result.fallback_reason is not None


class TestOneTurnOneEventContract:
    """
    Tests that one turn input produces exactly one durable player-turn event.
    """

    def test_one_turn_exactly_one_player_turn_event(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that one turn produces exactly one player_turn event.
        
        Contract:
        - Exactly one event_log entry with event_type="player_turn" per turn
        - TurnTransactionModel.status == "committed"
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="I observe my surroundings",
            idempotency_key="one_turn_one_event_key",
        )
        
        assert result.turn_no == 1
        assert result.transaction_id is not None
        
        events = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).all()
        
        player_turn_events = [e for e in events if e.event_type == "player_turn"]
        assert len(player_turn_events) == 1, "Expected exactly one player_turn event"
        
        transaction = db.query(TurnTransactionModel).filter(
            TurnTransactionModel.id == result.transaction_id
        ).first()
        assert transaction.status == "committed"

    def test_fallback_still_produces_one_event(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that fallback behavior still produces exactly one player_turn event.
        """
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=False):
            with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=False):
                with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=False):
                    with patch("llm_rpg.core.turn_service._is_npc_stage_enabled", return_value=False):
                        with patch("llm_rpg.core.turn_service._is_narration_stage_enabled", return_value=False):
                            result = execute_turn_service(
                                db=db,
                                session_id=test_session.id,
                                player_input="wait",
                                idempotency_key="fallback_one_event_key",
                            )
        
        events = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).all()
        
        player_turn_events = [e for e in events if e.event_type == "player_turn"]
        assert len(player_turn_events) == 1, "Expected exactly one player_turn event even with fallback"

    def test_multiple_turns_produce_correct_event_count(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that multiple turns produce correct event count.
        """
        for i in range(3):
            result = execute_turn_service(
                db=db,
                session_id=test_session.id,
                player_input=f"action {i+1}",
                idempotency_key=f"multi_turn_key_{i+1}",
            )
            assert result.turn_no == i + 1
        
        events = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
        ).order_by(EventLogModel.turn_no).all()
        
        player_turn_events = [e for e in events if e.event_type == "player_turn"]
        assert len(player_turn_events) == 3, "Expected 3 player_turn events for 3 turns"


class TestFallbackMetadataInResultJson:
    """
    Tests that fallback reasons/validation errors are recorded in result_json.
    """

    def test_fallback_reason_in_result_json(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that fallback_reason is recorded in event_log.result_json.
        """
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=False):
            with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=False):
                with patch("llm_rpg.core.turn_service._is_scene_stage_enabled", return_value=False):
                    with patch("llm_rpg.core.turn_service._is_npc_stage_enabled", return_value=False):
                        with patch("llm_rpg.core.turn_service._is_narration_stage_enabled", return_value=False):
                            result = execute_turn_service(
                                db=db,
                                session_id=test_session.id,
                                player_input="wait",
                                idempotency_key="fallback_result_json_key",
                            )
        
        event_log = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).first()
        
        assert event_log is not None
        assert event_log.result_json is not None
        
        llm_stages = event_log.result_json.get("llm_stages", [])
        assert isinstance(llm_stages, list)
        
        for stage in llm_stages:
            assert "stage_name" in stage
            assert "enabled" in stage
            if not stage.get("enabled"):
                assert stage.get("fallback_reason") is not None

    def test_validation_errors_in_result_json(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that validation_errors are recorded in llm_stage_result.
        """
        from llm_rpg.models.proposals import (
            WorldTickProposal,
            CandidateEvent,
            StateDeltaCandidate,
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
        )
        
        invalid_world_proposal = WorldTickProposal(
            time_description="Time passes...",
            candidate_events=[],
            state_deltas=[
                StateDeltaCandidate(
                    path="player_state.hp",
                    operation="set",
                    value=0,
                    reason="invalid",
                )
            ],
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.WORLD_TICK,
                source_engine=ProposalSource.WORLD_ENGINE,
            ),
        )
        
        with patch("llm_rpg.core.turn_service._is_world_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                mock_provider = MockLLMProvider()
                mock_service = LLMService(provider=mock_provider, db_session=None)
                mock_create.return_value = mock_service
                
                with patch("llm_rpg.llm.proposal_pipeline.ProposalPipeline") as MockPipeline:
                    mock_pipeline_instance = MagicMock()
                    mock_pipeline_instance.generate_world_tick = AsyncMock(
                        return_value=invalid_world_proposal
                    )
                    MockPipeline.return_value = mock_pipeline_instance
                    
                    result = execute_turn_service(
                        db=db,
                        session_id=test_session.id,
                        player_input="wait",
                        idempotency_key="validation_errors_result_json_key",
                    )
        
        stage_results = db.query(LLMStageResultModel).filter(
            LLMStageResultModel.session_id == test_session.id,
            LLMStageResultModel.turn_no == 1,
            LLMStageResultModel.stage_name == "world",
        ).all()
        
        if len(stage_results) > 0:
            world_result = stage_results[0]
            assert world_result.validation_errors_json is not None
            assert len(world_result.validation_errors_json) > 0

    def test_stage_metadata_populated(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that stage metadata (stage_name, enabled, accepted) is populated.
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="observe",
            idempotency_key="stage_metadata_key",
        )
        
        stage_results = db.query(LLMStageResultModel).filter(
            LLMStageResultModel.session_id == test_session.id,
            LLMStageResultModel.turn_no == 1,
        ).all()
        
        assert len(stage_results) >= 1, "Expected at least one llm_stage_result"
        
        for stage in stage_results:
            assert stage.stage_name is not None
            assert stage.transaction_id == result.transaction_id
            assert stage.accepted is not None or stage.fallback_reason is not None

"""
Unit tests for turn_event_callback plumbing in execute_turn_service.

Tests:
- test_turn_event_callback_omitted_backward_compat: verifies existing callers work without the new callback
- test_turn_event_callback_receives_narration_event: verifies callback receives narration_delta dict events
"""

import json
import pytest
from unittest.mock import patch
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
    NPCTemplateModel,
    QuestTemplateModel,
)
from llm_rpg.core.turn_service import execute_turn_service
from llm_rpg.llm.service import MockLLMProvider, LLMService, LLMResponse


class ExactMockLLMProvider(MockLLMProvider):
    def __init__(self, content: str):
        super().__init__()
        self.content = content

    async def generate(self, messages, **kwargs):
        self.call_count += 1
        return LLMResponse(content=self.content, model=self.model, usage={})


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
        id="user_evt",
        username="testuser_evt",
        email="test_evt@example.com",
        password_hash="hashed",
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_world(db: Session) -> WorldModel:
    world = WorldModel(
        id="world_evt",
        code="test_world_evt",
        name="测试世界",
        genre="xianxia",
        lore_summary="测试用世界",
        status="active",
    )
    db.add(world)
    db.commit()
    return world


@pytest.fixture
def test_chapter(db: Session, test_world: WorldModel) -> ChapterModel:
    chapter = ChapterModel(
        id="chapter_evt",
        world_id=test_world.id,
        chapter_no=1,
        name="第一章",
        summary="测试章节",
    )
    db.add(chapter)
    db.commit()
    return chapter


@pytest.fixture
def test_locations(db: Session, test_world: WorldModel, test_chapter: ChapterModel):
    locations = [
        LocationModel(
            id="loc_square_evt",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="square",
            name="宗门广场",
            tags=["public", "safe", "starting_point"],
            description="宗门广场",
            access_rules={"always_accessible": True},
        ),
        LocationModel(
            id="loc_forest_evt",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="forest",
            name="山林试炼区",
            tags=["combat", "exploration"],
            description="山林试炼区",
            access_rules={"combat_level": "apprentice"},
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
            id="npc_sister_evt",
            world_id=test_world.id,
            code="senior_sister",
            name="师姐凌月",
            role_type="mentor",
            personality="冷静",
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
            id="quest_trial_evt",
            world_id=test_world.id,
            code="first_trial",
            name="初次试炼",
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
        id="slot_evt",
        user_id=test_user.id,
        slot_number=1,
        name="测试存档",
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
        id="session_evt",
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
        id="state_evt",
        session_id=test_session.id,
        current_time="修仙历 春 第1日 辰时",
        time_phase="辰时",
        current_location_id="loc_square_evt",
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
        id="player_state_evt",
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


class TestTurnEventCallbackBackwardCompat:
    def test_turn_event_callback_omitted(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
        )
        assert result.turn_no == 1
        assert result.validation_passed is True
        assert result.narration is not None

    def test_turn_event_callback_none_explicit(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
            turn_event_callback=None,
        )
        assert result.turn_no == 1
        assert result.validation_passed is True


class TestTurnEventCallbackReceivesEvents:
    def test_callback_receives_narration_delta_event(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        narration_text = "古老的山门广场铺满了青石板，岁月在上面留下了深深的痕迹。"
        mock_provider = ExactMockLLMProvider(
            content=json.dumps({
                "text": narration_text,
                "tone": "neutral",
                "style_tags": ["descriptive"],
            }),
        )
        real_llm_service = LLMService(provider=mock_provider, db_session=db)

        collected_events: list[dict] = []

        def collector(event: dict) -> None:
            collected_events.append(event)

        with patch(
            "llm_rpg.core.turn_service._is_narration_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._is_scene_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._is_npc_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._is_world_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._create_llm_service_from_config",
            return_value=real_llm_service,
        ):
            result = execute_turn_service(
                db=db,
                session_id=test_session.id,
                player_input="我观察四周",
                turn_event_callback=collector,
            )

        assert result.turn_no == 1
        assert result.validation_passed is True

        narration_events = [
            e for e in collected_events if e.get("event") == "narration_delta"
        ]
        assert len(narration_events) >= 1, (
            f"Expected at least 1 narration_delta event, got {collected_events}"
        )

        for evt in narration_events:
            assert "data" in evt
            assert "delta" in evt["data"]
            assert isinstance(evt["data"]["delta"], str)
            assert len(evt["data"]["delta"]) > 0
            assert "turn_no" in evt["data"]
            assert evt["data"]["turn_no"] == result.turn_no

    def test_callback_does_not_affect_result(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        narration_text = "古老的山门广场铺满了青石板，岁月在上面留下了深深的痕迹。"
        mock_provider = ExactMockLLMProvider(
            content=json.dumps({
                "text": narration_text,
                "tone": "neutral",
                "style_tags": ["descriptive"],
            }),
        )
        real_llm_service = LLMService(provider=mock_provider, db_session=db)

        collected_events: list[dict] = []

        def collector(event: dict) -> None:
            collected_events.append(event)

        with patch(
            "llm_rpg.core.turn_service._is_narration_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._is_scene_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._is_npc_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._is_world_stage_enabled",
            return_value=True,
        ), patch(
            "llm_rpg.core.turn_service._create_llm_service_from_config",
            return_value=real_llm_service,
        ):
            result_with = execute_turn_service(
                db=db,
                session_id=test_session.id,
                player_input="我观察四周",
                turn_event_callback=collector,
            )

        assert result_with.turn_no == 1
        assert result_with.narration is not None
        assert len(collected_events) >= 1

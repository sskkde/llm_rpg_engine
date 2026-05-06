"""
Integration tests for scene action generator.

Tests recommended action generation from location access_rules,
active quests, and visible NPCs.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    WorldModel,
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionQuestStateModel,
    EventLogModel,
)
from llm_rpg.core.scene_action_generator import (
    generate_recommended_actions,
    get_active_scene_state,
)


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
def test_world(db: Session) -> WorldModel:
    world = WorldModel(
        id="test_world_1",
        code="test_world",
        name="测试世界",
        genre="xianxia",
        status="active",
    )
    db.add(world)
    db.commit()
    return world


@pytest.fixture
def test_chapter(db: Session, test_world: WorldModel) -> ChapterModel:
    chapter = ChapterModel(
        id="test_chapter_1",
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
            id="loc_square",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="square",
            name="宗门广场",
            tags=["public", "safe", "starting_point"],
            description="宗门广场",
            access_rules={"always_accessible": True},
        ),
        LocationModel(
            id="loc_trial_hall",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="trial_hall",
            name="试炼堂",
            tags=["public", "quest_hub"],
            description="试炼堂",
            access_rules={"time_restrictions": "daytime_only"},
        ),
        LocationModel(
            id="loc_herb_garden",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="herb_garden",
            name="药园",
            tags=["gathering", "resource"],
            description="药园",
            access_rules={"quest_requirement": None},
        ),
        LocationModel(
            id="loc_library",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="library",
            name="藏经阁外区",
            tags=["knowledge", "lore"],
            description="藏经阁外区",
            access_rules={"player_level": "outer_disciple", "inner_restricted": True},
        ),
        LocationModel(
            id="loc_forest",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="forest",
            name="山林试炼区",
            tags=["combat", "exploration"],
            description="山林试炼区",
            access_rules={"combat_level": "apprentice"},
        ),
        LocationModel(
            id="loc_secret_gate",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="secret_gate",
            name="秘境入口",
            tags=["dungeon", "danger_high"],
            description="秘境入口",
            access_rules={"item_required": "gate_key", "quest_completed": "investigate_anomaly"},
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
            id="npc_senior_sister",
            world_id=test_world.id,
            code="senior_sister",
            name="师姐凌月",
            role_type="mentor",
            public_identity="外门师姐",
        ),
        NPCTemplateModel(
            id="npc_elder",
            world_id=test_world.id,
            code="elder",
            name="长老",
            role_type="authority",
            public_identity="宗门长老",
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
            id="quest_trial",
            world_id=test_world.id,
            code="trial",
            name="试炼任务",
            quest_type="main",
            visibility="visible",
        ),
        QuestTemplateModel(
            id="quest_hidden",
            world_id=test_world.id,
            code="hidden",
            name="隐藏任务",
            quest_type="side",
            visibility="hidden",
        ),
    ]
    for quest in quests:
        db.add(quest)
    db.commit()
    return quests


@pytest.fixture
def test_user(db: Session) -> UserModel:
    user = UserModel(
        id="test_user_1",
        username="testuser",
        email="test@example.com",
        password_hash="hashed",
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_save_slot(db: Session, test_user: UserModel) -> SaveSlotModel:
    slot = SaveSlotModel(
        id="test_slot_1",
        user_id=test_user.id,
        slot_number=1,
        name="测试存档",
    )
    db.add(slot)
    db.commit()
    return slot


@pytest.fixture
def test_session(
    db: Session,
    test_user: UserModel,
    test_save_slot: SaveSlotModel,
    test_world: WorldModel,
) -> SessionModel:
    session = SessionModel(
        id="test_session_1",
        user_id=test_user.id,
        save_slot_id=test_save_slot.id,
        world_id=test_world.id,
        status="active",
    )
    db.add(session)
    db.commit()
    return session


@pytest.fixture
def test_session_state(
    db: Session,
    test_session: SessionModel,
    test_locations: list,
) -> SessionStateModel:
    square = next(loc for loc in test_locations if loc.code == "square")
    state = SessionStateModel(
        id="test_state_1",
        session_id=test_session.id,
        current_time="辰时",
        time_phase="辰时",
        current_location_id=square.id,
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
        id="test_player_state_1",
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


class TestSquareRecommendedActions:
    """Tests for recommended actions at square (starting location)."""

    def test_square_recommended_actions_are_non_empty_and_legal(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
    ):
        """Square should have >= 2 recommended actions that are legal movements."""
        square = next(loc for loc in test_locations if loc.code == "square")
        
        actions = generate_recommended_actions(db, test_session.id, square.id)
        
        assert len(actions) >= 2, f"Expected >= 2 actions, got {len(actions)}: {actions}"
        
        for action in actions:
            assert action.startswith("前往") or action.startswith("与") or action.startswith("查看任务"), \
                f"Action '{action}' should be a movement, NPC interaction, or quest action"
        
        assert "前往试炼堂" in actions, "Should include trial_hall movement"
        assert "前往药园" in actions, "Should include herb_garden movement"
        assert "前往藏经阁外区" in actions, "Should include library movement"

    def test_gated_locations_are_not_recommended_without_requirements(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
    ):
        """Secret gate and forest should NOT be recommended without requirements."""
        square = next(loc for loc in test_locations if loc.code == "square")
        
        actions = generate_recommended_actions(db, test_session.id, square.id)
        
        assert "前往秘境入口" not in actions, \
            "Secret gate should not be recommended without gate_key and quest completion"
        
        assert "前往山林试炼区" not in actions, \
            "Forest should not be recommended without combat_level: apprentice"


class TestRecommendedActionsPersistence:
    """Tests for recommended actions persistence in event_logs."""

    def test_recommended_actions_persisted_in_event_log(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
    ):
        """Recommended actions should be stored in event_logs.result_json."""
        from llm_rpg.storage.repositories import EventLogRepository
        
        square = next(loc for loc in test_locations if loc.code == "square")
        
        actions = generate_recommended_actions(db, test_session.id, square.id)
        
        event_log_repo = EventLogRepository(db)
        event_log = event_log_repo.create({
            "id": "test_event_1",
            "session_id": test_session.id,
            "turn_no": 1,
            "event_type": "player_turn",
            "input_text": "测试输入",
            "narrative_text": "测试叙述",
            "result_json": {"recommended_actions": actions},
        })
        
        db.refresh(event_log)
        assert event_log.result_json is not None
        assert "recommended_actions" in event_log.result_json
        assert event_log.result_json["recommended_actions"] == actions


class TestSceneStateMatching:
    """Tests for scene state matching session location."""

    def test_scene_state_matches_location(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
    ):
        """Scene state location should match session's current location."""
        square = next(loc for loc in test_locations if loc.code == "square")
        
        scene_state = get_active_scene_state(db, test_session.id)
        
        assert scene_state is not None
        assert scene_state.location_id == square.id
        assert scene_state.scene_id == "scene_square"
        assert "player" in scene_state.active_actor_ids
        assert len(scene_state.available_actions) >= 2

    def test_scene_state_includes_npcs_at_location(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
        test_npc_templates: list,
    ):
        """Scene state should include NPCs at the current location."""
        square = next(loc for loc in test_locations if loc.code == "square")
        sister = next(npc for npc in test_npc_templates if npc.code == "senior_sister")
        
        npc_state = SessionNPCStateModel(
            id="test_npc_state_1",
            session_id=test_session.id,
            npc_template_id=sister.id,
            current_location_id=square.id,
            trust_score=50,
            suspicion_score=0,
        )
        db.add(npc_state)
        db.commit()
        
        scene_state = get_active_scene_state(db, test_session.id)
        
        assert scene_state is not None
        assert f"npc_{sister.id}" in scene_state.active_actor_ids
        
        assert any("师姐凌月" in action for action in scene_state.available_actions), \
            "Should include NPC interaction action"

    def test_scene_state_includes_active_quests(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
        test_quest_templates: list,
    ):
        """Scene state should include active quest actions."""
        square = next(loc for loc in test_locations if loc.code == "square")
        trial_quest = next(q for q in test_quest_templates if q.code == "trial")
        
        quest_state = SessionQuestStateModel(
            id="test_quest_state_1",
            session_id=test_session.id,
            quest_template_id=trial_quest.id,
            status="active",
            current_step_no=1,
        )
        db.add(quest_state)
        db.commit()
        
        scene_state = get_active_scene_state(db, test_session.id)
        
        assert scene_state is not None
        assert any("试炼任务" in action for action in scene_state.available_actions), \
            "Should include active quest action"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_missing_session_returns_empty_actions(
        self,
        db: Session,
    ):
        """Missing session should return empty actions list."""
        actions = generate_recommended_actions(db, "nonexistent_session")
        assert actions == []

    def test_missing_session_returns_none_scene_state(
        self,
        db: Session,
    ):
        """Missing session should return None for scene state."""
        scene_state = get_active_scene_state(db, "nonexistent_session")
        assert scene_state is None

    def test_missing_session_state_uses_default_square(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations: list,
    ):
        """Missing session_state should default to square location."""
        actions = generate_recommended_actions(db, test_session.id)
        
        assert len(actions) >= 2, "Should have actions even without session_state"
        assert "前往试炼堂" in actions

    def test_time_restricted_location_blocked_at_night(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
    ):
        """Trial hall should be blocked at night (time_restrictions: daytime_only)."""
        test_session_state.time_phase = "子时"
        db.commit()
        
        square = next(loc for loc in test_locations if loc.code == "square")
        actions = generate_recommended_actions(db, test_session.id, square.id)
        
        assert "前往试炼堂" not in actions, \
            "Trial hall should be blocked at night"

    def test_time_restricted_location_accessible_during_day(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations: list,
    ):
        """Trial hall should be accessible during daytime."""
        test_session_state.time_phase = "午时"
        db.commit()
        
        square = next(loc for loc in test_locations if loc.code == "square")
        actions = generate_recommended_actions(db, test_session.id, square.id)
        
        assert "前往试炼堂" in actions, \
            "Trial hall should be accessible during daytime"

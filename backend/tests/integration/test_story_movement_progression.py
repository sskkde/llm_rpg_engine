"""
Integration tests for deterministic movement handler.

Tests location resolution by code/name/alias, access_rules validation,
and session state mutation on success vs. no-mutation on failure.
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
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
)
from llm_rpg.core.movement_handler import (
    handle_movement,
    MovementResult,
    MovementError,
    _resolve_location_code,
    LOCATION_ALIASES,
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
            id="loc_secret_gate",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="secret_gate",
            name="秘境入口",
            tags=["dungeon", "danger_high"],
            description="秘境入口",
            access_rules={"item_required": "gate_key", "quest_completed": "investigate_cliff"},
        ),
        LocationModel(
            id="loc_core",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="core",
            name="异变核心",
            tags=["boss_area", "danger_extreme"],
            description="异变核心",
            access_rules={"chapter": 3, "boss_unlocked": True},
        ),
        LocationModel(
            id="loc_residence",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="residence",
            name="外门居所",
            tags=["private", "safe"],
            description="外门居所",
            access_rules={"player_level": "outer_disciple"},
        ),
    ]
    for loc in locations:
        db.add(loc)
    db.commit()
    return locations


@pytest.fixture
def test_user(db: Session) -> UserModel:
    user = UserModel(
        id="test_user_1",
        username="testplayer",
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
    test_world: WorldModel,
    test_save_slot: SaveSlotModel,
) -> SessionModel:
    session = SessionModel(
        id="test_session_1",
        user_id=test_user.id,
        save_slot_id=test_save_slot.id,
        world_id=test_world.id,
        current_chapter_id="test_chapter_1",
        status="active",
    )
    db.add(session)
    db.commit()
    return session


@pytest.fixture
def test_session_state(
    db: Session,
    test_session: SessionModel,
    test_locations,
) -> SessionStateModel:
    state = SessionStateModel(
        id="test_state_1",
        session_id=test_session.id,
        current_time="修仙历 春 第1日 辰时",
        time_phase="辰时",
        current_location_id="loc_square",
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolveLocationCode:
    def test_resolve_by_code(self):
        assert _resolve_location_code("square") == "square"
        assert _resolve_location_code("trial_hall") == "trial_hall"

    def test_resolve_by_chinese_name(self):
        assert _resolve_location_code("宗门广场") == "square"
        assert _resolve_location_code("试炼堂") == "trial_hall"
        assert _resolve_location_code("山林") == "forest"
        assert _resolve_location_code("藏经阁") == "library"
        assert _resolve_location_code("药园") == "herb_garden"

    def test_resolve_by_alias(self):
        assert _resolve_location_code("广场") == "square"
        assert _resolve_location_code("宗门") == "square"
        assert _resolve_location_code("试炼") == "trial_hall"
        assert _resolve_location_code("林") == "forest"
        assert _resolve_location_code("秘境") == "secret_gate"
        assert _resolve_location_code("核心") == "core"

    def test_resolve_case_insensitive(self):
        assert _resolve_location_code("SQUARE") == "square"
        assert _resolve_location_code("Square") == "square"

    def test_resolve_unknown_returns_none(self):
        assert _resolve_location_code("不存在的地方") is None
        assert _resolve_location_code("narnia") is None


class TestMoveToTrialHallUpdatesSessionLocation:
    def test_move_to_trial_hall_updates_session_location(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "trial_hall")

        assert result.success is True
        assert result.new_location_id == "loc_trial_hall"
        assert result.new_location_code == "trial_hall"
        assert result.new_location_name == "试炼堂"
        assert result.previous_location_id == "loc_square"
        assert result.blocked_reason is None

        updated_state = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == "test_session_1"
        ).first()
        assert updated_state.current_location_id == "loc_trial_hall"

    def test_move_by_chinese_name(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "试炼堂")

        assert result.success is True
        assert result.new_location_id == "loc_trial_hall"
        assert result.new_location_code == "trial_hall"

    def test_move_by_alias(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "广场")

        assert result.success is True
        assert result.new_location_id == "loc_square"


class TestGatedLocationDoesNotMutateLocation:
    def test_secret_gate_blocked_without_items(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "secret_gate")

        assert result.success is False
        assert result.blocked_reason is not None
        assert result.new_location_id is None

        state_after = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == "test_session_1"
        ).first()
        assert state_after.current_location_id == "loc_square"

    def test_core_blocked_without_chapter3(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "core")

        assert result.success is False
        assert result.blocked_reason is not None

        state_after = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == "test_session_1"
        ).first()
        assert state_after.current_location_id == "loc_square"

    def test_forest_blocked_without_combat_level(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "forest")

        assert result.success is False
        assert "战斗等级" in result.blocked_reason

        state_after = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == "test_session_1"
        ).first()
        assert state_after.current_location_id == "loc_square"


class TestMoveByNameAlias:
    def test_move_to_herb_garden_by_chinese(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "药园")

        assert result.success is True
        assert result.new_location_id == "loc_herb_garden"

    def test_move_to_library_by_chinese(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "藏经阁")

        assert result.success is True
        assert result.new_location_id == "loc_library"

    def test_move_to_residence_by_alias(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "居所")

        assert result.success is True
        assert result.new_location_id == "loc_residence"


class TestInvalidLocationReturnsError:
    def test_nonexistent_location_code(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "nonexistent_place")

        assert result.success is False
        assert "未找到" in result.blocked_reason
        assert result.new_location_id is None

        state_after = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == "test_session_1"
        ).first()
        assert state_after.current_location_id == "loc_square"

    def test_empty_string_returns_error(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "")

        assert result.success is False
        assert result.new_location_id is None


class TestSessionNotFound:
    def test_missing_session_raises_error(self, db, test_locations):
        with pytest.raises(MovementError, match="Session not found"):
            handle_movement(db, "nonexistent_session", "square")


class TestAccessRulesDeterministic:
    def test_always_accessible_passes(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "square")
        assert result.success is True

    def test_time_restriction_blocks_night(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        test_session_state.time_phase = "子时"
        db.commit()

        result = handle_movement(db, "test_session_1", "trial_hall")
        assert result.success is False
        assert "白天" in result.blocked_reason

    def test_time_restriction_allows_day(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        test_session_state.time_phase = "午时"
        db.commit()

        result = handle_movement(db, "test_session_1", "trial_hall")
        assert result.success is True

    def test_item_required_blocks_without_item(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        result = handle_movement(db, "test_session_1", "secret_gate")
        assert result.success is False
        assert "gate_key" in result.blocked_reason

    def test_item_required_passes_with_flag(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        test_session_state.global_flags_json = {
            "has_item_gate_key": True,
            "quest_completed_investigate_cliff": True,
        }
        db.commit()

        result = handle_movement(db, "test_session_1", "secret_gate")
        assert result.success is True

    def test_chapter_requirement_blocks(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        test_session_state.global_flags_json = {"current_chapter_no": 1}
        db.commit()

        result = handle_movement(db, "test_session_1", "core")
        assert result.success is False
        assert "第3章" in result.blocked_reason

    def test_chapter_requirement_passes(
        self, db, test_session, test_session_state, test_player_state, test_locations
    ):
        test_session_state.global_flags_json = {
            "current_chapter_no": 3,
            "boss_unlocked": True,
        }
        db.commit()

        result = handle_movement(db, "test_session_1", "core")
        assert result.success is True

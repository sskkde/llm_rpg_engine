"""T0 contract tests for complete persisted turn-result recovery."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.turn_service import _get_existing_turn_result
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import EventLogModel, SessionModel, UserModel, WorldModel, SaveSlotModel


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_existing_turn_restores_world_time_and_player_state(db_engine):
    """Contract: idempotent recovery returns stored result fields, never empty placeholders."""
    db = sessionmaker(bind=db_engine)()
    user = UserModel(id="recovery-user", username="recovery-user", email="recovery@example.com", password_hash="x")
    world = WorldModel(id="recovery-world", code="recovery-world", name="世界", genre="xianxia", status="active")
    slot = SaveSlotModel(id="recovery-slot", user_id=user.id, slot_number=1, name="存档")
    session = SessionModel(id="recovery-session", user_id=user.id, save_slot_id=slot.id, world_id=world.id, status="active")
    db.add_all([user, world, slot, session])
    db.flush()
    stored_time = {"calendar": "修仙历", "day": "第3日", "period": "午时", "hour": 11, "minute": 30}
    stored_player = {"hp": 73, "location_id": "hall", "realm_stage": "炼气二层"}
    db.add(EventLogModel(
        session_id=session.id,
        turn_no=1,
        event_type="player_turn",
        narrative_text="已提交叙述",
        result_json={"world_time": stored_time, "player_state": stored_player, "recommended_actions": ["继续探索"], "state_deltas": {"hp": -2}},
    ))
    db.commit()

    result = _get_existing_turn_result(db, session.id, 1)

    assert result is not None
    assert result.world_time == stored_time, "T0 complete-recovery contract: world_time must come from persisted result_json"
    assert result.player_state == stored_player, "T0 complete-recovery contract: player_state must come from persisted result_json"
    db.close()

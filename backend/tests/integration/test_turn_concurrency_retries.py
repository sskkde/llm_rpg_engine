"""
Integration tests for turn concurrency control and retry mechanisms.

Tests DB-level concurrency guardrails for same-session turn execution.
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
    EventLogModel,
    SessionStateModel,
)
from llm_rpg.core.turn_concurrency import (
    execute_with_concurrency_control,
    execute_turn_with_retry,
    TurnConcurrencyError,
    TurnLockAcquisitionError,
)
from llm_rpg.core.turn_allocation import (
    allocate_turn,
    commit_turn,
    get_current_turn_number,
)


@pytest.fixture
def db():
    """Create in-memory SQLite database for testing."""
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
    """Create a test user."""
    user = UserModel(
        id="user_1",
        username="testuser",
        email="test@example.com",
        password_hash="hashed",
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_world(db: Session) -> WorldModel:
    """Create a test world."""
    world = WorldModel(
        id="world_1",
        code="test_world",
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
    """Create a test chapter."""
    chapter = ChapterModel(
        id="chapter_1",
        world_id=test_world.id,
        chapter_no=1,
        name="第一章",
        summary="测试章节",
    )
    db.add(chapter)
    db.commit()
    return chapter


@pytest.fixture
def test_location(db: Session, test_world: WorldModel, test_chapter: ChapterModel) -> LocationModel:
    """Create a test location."""
    location = LocationModel(
        id="loc_square",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="square",
        name="宗门广场",
        tags=["public", "safe", "starting_point"],
        description="起始地点",
    )
    db.add(location)
    db.commit()
    return location


@pytest.fixture
def test_save_slot(db: Session, test_user: UserModel) -> SaveSlotModel:
    """Create a test save slot."""
    save_slot = SaveSlotModel(
        id="slot_1",
        user_id=test_user.id,
        slot_number=1,
        name="测试存档",
    )
    db.add(save_slot)
    db.commit()
    return save_slot


@pytest.fixture
def test_session(db: Session, test_user: UserModel, test_world: WorldModel, test_save_slot: SaveSlotModel) -> SessionModel:
    """Create a test session."""
    session = SessionModel(
        id="session_1",
        user_id=test_user.id,
        world_id=test_world.id,
        save_slot_id=test_save_slot.id,
        status="active",
    )
    db.add(session)
    
    session_state = SessionStateModel(
        id="state_1",
        session_id=session.id,
        current_location_id="loc_square",
    )
    db.add(session_state)
    
    db.commit()
    return session


def test_concurrent_same_session_turns_do_not_duplicate_turn_number(db: Session, test_session: SessionModel):
    """
    Test that concurrent requests to the same session never produce duplicate turns.
    
    This test simulates the scenario where multiple sequential requests
    are made to the same session. The DB-level unique constraint ensures
    no duplicate turn numbers.
    
    Scenario:
    1. Create initial_scene event (turn 0)
    2. Execute multiple turns sequentially with concurrency control
    3. Verify no duplicate turn numbers in event_logs
    """
    session_id = test_session.id
    
    commit_turn(
        db=db,
        session_id=session_id,
        turn_no=0,
        event_type="initial_scene",
        narrative_text="初始场景",
    )
    db.commit()
    
    for i in range(5):
        with execute_with_concurrency_control(db, session_id):
            turn_no, is_new = allocate_turn(db, session_id)
            
            assert turn_no == i + 1, f"Expected turn {i + 1}, got {turn_no}"
            
            event = commit_turn(
                db=db,
                session_id=session_id,
                turn_no=turn_no,
                event_type="player_turn",
                input_text=f"请求{i}",
                narrative_text=f"叙述{i}",
            )
            db.commit()
    
    events = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id
    ).order_by(EventLogModel.turn_no).all()
    
    turn_numbers = [e.turn_no for e in events]
    assert turn_numbers == [0, 1, 2, 3, 4, 5]
    assert len(set(turn_numbers)) == len(turn_numbers)


def test_retry_with_same_idempotency_key_reuses_result(db: Session, test_session: SessionModel):
    """
    Test that retry with same idempotency key returns same result.
    
    Scenario:
    1. Create initial_scene event (turn 0)
    2. Execute turn with idempotency key "req_123"
    3. Retry with same idempotency key "req_123"
    4. Verify both return same turn number and result
    5. Verify is_new=False for retry
    
    This ensures safe retries for network failures or timeouts.
    """
    session_id = test_session.id
    
    commit_turn(
        db=db,
        session_id=session_id,
        turn_no=0,
        event_type="initial_scene",
        narrative_text="初始场景",
    )
    db.commit()
    
    def process_turn(local_db: Session, session_id: str, turn_no: int):
        return {
            "narrative": f"第{turn_no}回合的叙述",
            "location": "forest",
            "action": "explore",
        }
    
    result_1, is_new_1 = execute_turn_with_retry(
        db=db,
        session_id=session_id,
        idempotency_key="req_123",
        turn_func=process_turn,
        event_type="player_turn",
        input_text="我走向山林",
    )
    
    assert is_new_1 is True
    assert result_1["narrative"] == "第1回合的叙述"
    
    result_2, is_new_2 = execute_turn_with_retry(
        db=db,
        session_id=session_id,
        idempotency_key="req_123",
        turn_func=process_turn,
        event_type="player_turn",
        input_text="我走向山林",
    )
    
    assert is_new_2 is False
    assert result_2["narrative"] == "第1回合的叙述"
    assert result_2["location"] == "forest"
    
    events = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id,
        EventLogModel.event_type == "player_turn",
    ).all()
    
    assert len(events) == 1
    assert events[0].turn_no == 1


def test_failed_validation_leaves_location_unchanged(db: Session, test_session: SessionModel, test_location: LocationModel):
    """
    Test that failed validation leaves location unchanged.
    
    Scenario:
    1. Create initial_scene event (turn 0) with player at square
    2. Execute turn that fails validation (invalid location transition)
    3. Verify player location remains at square
    4. Verify no state changes committed
    
    This ensures that validation failures don't corrupt state.
    """
    session_id = test_session.id
    
    commit_turn(
        db=db,
        session_id=session_id,
        turn_no=0,
        event_type="initial_scene",
        narrative_text="初始场景",
    )
    db.commit()
    
    session_state = db.query(SessionStateModel).filter(
        SessionStateModel.session_id == session_id
    ).first()
    
    initial_location = session_state.current_location_id
    assert initial_location == "loc_square"
    
    try:
        with execute_with_concurrency_control(db, session_id):
            turn_no, is_new = allocate_turn(db, session_id)
            raise ValueError("Validation failed: invalid location transition")
    except ValueError as e:
        assert "Validation failed" in str(e)
    
    db.rollback()
    
    session_state_after = db.query(SessionStateModel).filter(
        SessionStateModel.session_id == session_id
    ).first()
    
    assert session_state_after.current_location_id == initial_location
    
    events = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id,
        EventLogModel.event_type == "player_turn",
    ).all()
    
    assert len(events) == 0


def test_lock_is_released_on_transaction_end(db: Session, test_session: SessionModel):
    """
    Test that lock is automatically released when transaction ends.
    
    Scenario:
    1. Create initial_scene event (turn 0)
    2. Acquire lock and start transaction
    3. Commit transaction
    4. Verify lock is released (can acquire again immediately)
    
    This ensures locks don't leak across transactions.
    """
    session_id = test_session.id
    
    commit_turn(
        db=db,
        session_id=session_id,
        turn_no=0,
        event_type="initial_scene",
        narrative_text="初始场景",
    )
    db.commit()
    
    with execute_with_concurrency_control(db, session_id) as lock_ctx:
        assert lock_ctx.lock_acquired is True
        
        turn_no, is_new = allocate_turn(db, session_id)
        event = commit_turn(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            event_type="player_turn",
            narrative_text="第一次执行",
        )
        db.commit()
    
    with execute_with_concurrency_control(db, session_id) as lock_ctx:
        assert lock_ctx.lock_acquired is True
        
        turn_no_2, is_new_2 = allocate_turn(db, session_id)
        assert turn_no_2 == 2
        
        event_2 = commit_turn(
            db=db,
            session_id=session_id,
            turn_no=turn_no_2,
            event_type="player_turn",
            narrative_text="第二次执行",
        )
        db.commit()


def test_lock_is_released_on_rollback(db: Session, test_session: SessionModel):
    """
    Test that lock is automatically released when transaction is rolled back.
    
    Scenario:
    1. Create initial_scene event (turn 0)
    2. Acquire lock and start transaction
    3. Rollback transaction (simulate error)
    4. Verify lock is released (can acquire again immediately)
    
    This ensures locks don't leak on errors.
    """
    session_id = test_session.id
    
    commit_turn(
        db=db,
        session_id=session_id,
        turn_no=0,
        event_type="initial_scene",
        narrative_text="初始场景",
    )
    db.commit()
    
    try:
        with execute_with_concurrency_control(db, session_id) as lock_ctx:
            assert lock_ctx.lock_acquired is True
            
            turn_no, is_new = allocate_turn(db, session_id)
            
            raise ValueError("Simulated error")
            
    except ValueError:
        db.rollback()
    
    with execute_with_concurrency_control(db, session_id) as lock_ctx:
        assert lock_ctx.lock_acquired is True
        
        turn_no_2, is_new_2 = allocate_turn(db, session_id)
        assert turn_no_2 == 1
        
        event = commit_turn(
            db=db,
            session_id=session_id,
            turn_no=turn_no_2,
            event_type="player_turn",
            narrative_text="回滚后执行",
        )
        db.commit()


def test_different_idempotency_keys_create_separate_turns(db: Session, test_session: SessionModel):
    """
    Test that different idempotency keys create separate turns.
    
    Scenario:
    1. Create initial_scene event (turn 0)
    2. Execute turn with idempotency key "req_123"
    3. Execute turn with idempotency key "req_456"
    4. Verify both create separate turns (turn 1 and turn 2)
    
    This ensures idempotency keys don't interfere with each other.
    """
    session_id = test_session.id
    
    commit_turn(
        db=db,
        session_id=session_id,
        turn_no=0,
        event_type="initial_scene",
        narrative_text="初始场景",
    )
    db.commit()
    
    def process_turn(local_db: Session, session_id: str, turn_no: int):
        return {"narrative": f"第{turn_no}回合", "action": "explore"}
    
    result_1, is_new_1 = execute_turn_with_retry(
        db=db,
        session_id=session_id,
        idempotency_key="req_123",
        turn_func=process_turn,
    )
    
    assert is_new_1 is True
    assert result_1["narrative"] == "第1回合"
    
    result_2, is_new_2 = execute_turn_with_retry(
        db=db,
        session_id=session_id,
        idempotency_key="req_456",
        turn_func=process_turn,
    )
    
    assert is_new_2 is True
    assert result_2["narrative"] == "第2回合"
    
    events = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id,
        EventLogModel.event_type == "player_turn",
    ).order_by(EventLogModel.turn_no).all()
    
    assert len(events) == 2
    assert events[0].turn_no == 1
    assert events[1].turn_no == 2


def test_concurrency_control_with_idempotency_prevents_duplicates(db: Session, test_session: SessionModel):
    """
    Test that combining concurrency control with idempotency prevents duplicates.
    
    Scenario:
    1. Create initial_scene event (turn 0)
    2. Execute turn with idempotency key "req_abc"
    3. Try to execute again with same key - should reuse result
    4. Verify only one turn was created
    
    This ensures the combination of concurrency control and idempotency works.
    """
    session_id = test_session.id
    
    commit_turn(
        db=db,
        session_id=session_id,
        turn_no=0,
        event_type="initial_scene",
        narrative_text="初始场景",
    )
    db.commit()
    
    call_count = [0]
    
    def process_turn(local_db: Session, session_id: str, turn_no: int):
        call_count[0] += 1
        return {"narrative": f"Turn {turn_no}", "calls": call_count[0]}
    
    result_1, is_new_1 = execute_turn_with_retry(
        db=db,
        session_id=session_id,
        idempotency_key="req_abc",
        turn_func=process_turn,
    )
    
    assert is_new_1 is True
    assert result_1["calls"] == 1
    
    result_2, is_new_2 = execute_turn_with_retry(
        db=db,
        session_id=session_id,
        idempotency_key="req_abc",
        turn_func=process_turn,
    )
    
    assert is_new_2 is False
    assert result_2["calls"] == 1
    assert call_count[0] == 1
    
    events = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id,
        EventLogModel.event_type == "player_turn",
    ).all()
    
    assert len(events) == 1

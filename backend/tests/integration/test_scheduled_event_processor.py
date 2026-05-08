"""
Integration tests for ScheduledEventProcessor.

Tests that:
- Scheduled events fire at correct world time
- Trigger conditions are properly evaluated
- Game events are created when scheduled events fire
- Integration with WorldEngine works correctly
"""

import pytest
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.models import Base, generate_uuid
from llm_rpg.storage.models import (
    UserModel,
    WorldModel,
    SessionModel,
    SaveSlotModel,
    ScheduledEventModel,
    EventTemplateModel,
    GameEventModel,
    TurnTransactionModel,
)
from llm_rpg.engines.scheduled_event_processor import ScheduledEventProcessor
from llm_rpg.models.events import WorldTime


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = UserModel(
        id=generate_uuid(),
        username="test_user",
        email="test@example.com",
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_world(db_session):
    """Create a test world."""
    world = WorldModel(
        id=generate_uuid(),
        code="test_world",
        name="Test World",
        status="active",
    )
    db_session.add(world)
    db_session.commit()
    return world


@pytest.fixture
def test_save_slot(db_session, test_user):
    """Create a test save slot."""
    save_slot = SaveSlotModel(
        id=generate_uuid(),
        user_id=test_user.id,
        slot_number=1,
        name="Test Save",
    )
    db_session.add(save_slot)
    db_session.commit()
    return save_slot


@pytest.fixture
def test_session(db_session, test_user, test_world, test_save_slot):
    """Create a test game session."""
    session = SessionModel(
        id=generate_uuid(),
        user_id=test_user.id,
        save_slot_id=test_save_slot.id,
        world_id=test_world.id,
        status="active",
    )
    db_session.add(session)
    db_session.commit()
    return session


@pytest.fixture
def test_event_template(db_session, test_world):
    """Create a test event template."""
    template = EventTemplateModel(
        id=generate_uuid(),
        world_id=test_world.id,
        code="test_event",
        name="Test Event",
        event_type="time_based",
        trigger_conditions={"world_time": {"period": "子时"}},
        effects={"danger_level": 0.2},
    )
    db_session.add(template)
    db_session.commit()
    return template


@pytest.fixture
def processor(db_session):
    """Create a ScheduledEventProcessor instance."""
    return ScheduledEventProcessor(db_session)


class TestScheduledEventFiresAtWorldTime:
    """Test that scheduled events fire at the correct world time."""

    def test_event_fires_at_matching_period(
        self,
        db_session,
        test_session,
        test_event_template,
        processor,
    ):
        """Event should fire when world time period matches."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=test_event_template.id,
            trigger_conditions_json={
                "world_time": {
                    "period": "子时",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="子时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 1
        assert fired_events[0]["event_type"] == "time_based"

        db_session.refresh(scheduled_event)
        assert scheduled_event.status == "triggered"

    def test_event_does_not_fire_at_wrong_period(
        self,
        db_session,
        test_session,
        test_event_template,
        processor,
    ):
        """Event should not fire when world time period doesn't match."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=test_event_template.id,
            trigger_conditions_json={
                "world_time": {
                    "period": "子时",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="午时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 0

        db_session.refresh(scheduled_event)
        assert scheduled_event.status == "pending"

    def test_event_fires_at_matching_season(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when season matches."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_time": {
                    "season": "夏",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="夏",
            day=15,
            period="午时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 1

    def test_event_fires_at_matching_day(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when day matches."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_time": {
                    "day": 15,
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=15,
            period="午时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 1

    def test_event_fires_in_day_range(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when day is within specified range."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_time": {
                    "day": {"min": 10, "max": 20},
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=15,
            period="午时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 1

    def test_event_fires_in_period_list(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when period is in allowed list."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_time": {
                    "period": ["子时", "丑时", "寅时"],
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="丑时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 1


class TestTriggerConditionsEvaluation:
    """Test trigger condition evaluation."""

    def test_global_flag_condition(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when global flag matches."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_state": {
                    "global_flags": {
                        "boss_defeated": True,
                    },
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="午时",
        )

        world_state = {
            "global_flags": {
                "boss_defeated": True,
            },
        }

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
            world_state=world_state,
        )

        assert len(fired_events) == 1

    def test_global_flag_condition_not_met(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should not fire when global flag doesn't match."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_state": {
                    "global_flags": {
                        "boss_defeated": True,
                    },
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="午时",
        )

        world_state = {
            "global_flags": {
                "boss_defeated": False,
            },
        }

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
            world_state=world_state,
        )

        assert len(fired_events) == 0

    def test_player_location_condition(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when player location matches."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_state": {
                    "player_location": "dungeon_boss_room",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="午时",
        )

        world_state = {
            "player_location": "dungeon_boss_room",
        }

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
            world_state=world_state,
        )

        assert len(fired_events) == 1

    def test_combined_time_and_state_conditions(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when both time and state conditions match."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_time": {
                    "period": "子时",
                },
                "world_state": {
                    "global_flags": {
                        "night_ritual_active": True,
                    },
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="子时",
        )

        world_state = {
            "global_flags": {
                "night_ritual_active": True,
            },
        }

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
            world_state=world_state,
        )

        assert len(fired_events) == 1


class TestGameEventCreation:
    """Test that game events are created correctly."""

    def test_game_event_created_on_fire(
        self,
        db_session,
        test_session,
        test_event_template,
        processor,
    ):
        """A game event should be created when scheduled event fires."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=test_event_template.id,
            trigger_conditions_json={
                "world_time": {
                    "period": "子时",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="子时",
        )

        processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        game_events = db_session.query(GameEventModel).filter(
            GameEventModel.session_id == test_session.id
        ).all()

        assert len(game_events) == 1
        assert game_events[0].event_type == "time_based"
        assert game_events[0].turn_no == 1

    def test_game_event_has_correct_payload(
        self,
        db_session,
        test_session,
        test_event_template,
        processor,
    ):
        """Game event should have correct payload from template."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=test_event_template.id,
            trigger_conditions_json={
                "world_time": {
                    "period": "子时",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="子时",
        )

        processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        game_event = db_session.query(GameEventModel).filter(
            GameEventModel.session_id == test_session.id
        ).first()

        assert game_event is not None
        assert game_event.public_payload_json is not None
        assert "effects" in game_event.public_payload_json
        assert game_event.public_payload_json["effects"]["danger_level"] == 0.2


class TestScheduleEventAPI:
    """Test the schedule_event and cancel_scheduled_event methods."""

    def test_schedule_event(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Should be able to schedule a new event."""
        scheduled_event = processor.schedule_event(
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions={
                "world_time": {
                    "period": "子时",
                },
            },
        )

        assert scheduled_event.id is not None
        assert scheduled_event.session_id == test_session.id
        assert scheduled_event.status == "pending"

    def test_cancel_scheduled_event(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Should be able to cancel a pending event."""
        scheduled_event = processor.schedule_event(
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions={},
        )

        result = processor.cancel_scheduled_event(scheduled_event.id)

        assert result is True

        db_session.refresh(scheduled_event)
        assert scheduled_event.status == "cancelled"

    def test_cancel_already_triggered_event(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Should not be able to cancel an already triggered event."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={},
            status="triggered",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        result = processor.cancel_scheduled_event(scheduled_event.id)

        assert result is False

    def test_get_pending_events(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Should be able to get all pending events for a session."""
        for i in range(3):
            processor.schedule_event(
                session_id=test_session.id,
                event_template_id=None,
                trigger_conditions={},
            )

        pending = processor.get_pending_events(test_session.id)

        assert len(pending) == 3


class TestPeriodOrdering:
    """Test period_after and period_before conditions."""

    def test_period_after_condition(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when current period is after specified period."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_time": {
                    "period_after": "午时",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="未时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 1

    def test_period_before_condition(
        self,
        db_session,
        test_session,
        processor,
    ):
        """Event should fire when current period is before specified period."""
        scheduled_event = ScheduledEventModel(
            id=generate_uuid(),
            session_id=test_session.id,
            event_template_id=None,
            trigger_conditions_json={
                "world_time": {
                    "period_before": "午时",
                },
            },
            status="pending",
        )
        db_session.add(scheduled_event)
        db_session.commit()

        world_time = WorldTime(
            calendar="standard",
            season="春",
            day=1,
            period="辰时",
        )

        fired_events = processor.process_scheduled_events(
            session_id=test_session.id,
            world_time=world_time,
            current_turn=1,
        )

        assert len(fired_events) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

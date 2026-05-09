"""
Integration tests for MemoryWriter DB persistence.

Tests that MemoryWriter correctly persists to DB tables:
- memory_summaries
- memory_facts
- npc_beliefs
- npc_relationship_memories
"""

import pytest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.core.memory_writer import MemoryWriter
from llm_rpg.core.event_log import EventLog
from llm_rpg.core.npc_memory import NPCMemoryManager
from llm_rpg.core.summary import SummaryManager
from llm_rpg.models.events import SceneEvent, NPCActionEvent, EventType
from llm_rpg.models.states import (
    CanonicalState,
    CurrentSceneState,
    PlayerState,
    WorldState,
    WorldTime,
)
from llm_rpg.storage.database import Base
from llm_rpg.storage.repositories import (
    MemorySummaryRepository,
    MemoryFactRepository,
    NPCBeliefRepository,
    NPCRelationshipMemoryRepository,
)


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def canonical_state():
    return CanonicalState(
        player_state=PlayerState(
            entity_id="player",
            location_id="loc_square",
        ),
        world_state=WorldState(
            entity_id="world",
            world_id="world_1",
            current_time=WorldTime(
                calendar="修仙历",
                season="春",
                day=1,
                period="辰时",
            ),
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene_1",
            scene_id="scene_1",
            location_id="loc_square",
            active_actor_ids=["player", "npc_1"],
        ),
    )


class TestMemoryWriterDBPersistence:
    """Test MemoryWriter writes to DB tables."""

    def test_write_turn_summary_persists_to_db(self, db_session, canonical_state):
        memory_summary_repo = MemorySummaryRepository(db_session)
        memory_fact_repo = MemoryFactRepository(db_session)
        npc_belief_repo = NPCBeliefRepository(db_session)
        npc_relationship_repo = NPCRelationshipMemoryRepository(db_session)
        
        from llm_rpg.storage.models import generate_uuid
        session_id = generate_uuid()
        
        event_log = EventLog()
        npc_memory = NPCMemoryManager()
        summary_manager = SummaryManager()
        
        memory_writer = MemoryWriter(
            event_log=event_log,
            npc_memory_manager=npc_memory,
            summary_manager=summary_manager,
            memory_summary_repo=memory_summary_repo,
            memory_fact_repo=memory_fact_repo,
            npc_belief_repo=npc_belief_repo,
            npc_relationship_repo=npc_relationship_repo,
            session_id=session_id,
        )
        
        events = [
            SceneEvent(
                event_id="evt_1",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                scene_id="scene_1",
                trigger="player_move",
                summary="玩家移动到广场",
            ),
        ]
        
        summary = memory_writer.write_turn_summary(
            turn_index=1,
            events=events,
            state=canonical_state,
        )
        
        assert summary is not None
        
        summaries = memory_summary_repo.get_by_scope(
            session_id=session_id,
            scope_type="world",
        )
        
        assert len(summaries) >= 1
        world_summaries = [s for s in summaries if s.scope_type == "world"]
        assert len(world_summaries) >= 1
        assert "回合 1" in world_summaries[0].summary_text

    def test_write_scene_summary_persists_to_db(self, db_session, canonical_state):
        memory_summary_repo = MemorySummaryRepository(db_session)
        memory_fact_repo = MemoryFactRepository(db_session)
        npc_belief_repo = NPCBeliefRepository(db_session)
        npc_relationship_repo = NPCRelationshipMemoryRepository(db_session)
        
        from llm_rpg.storage.models import generate_uuid
        session_id = generate_uuid()
        
        event_log = EventLog()
        npc_memory = NPCMemoryManager()
        summary_manager = SummaryManager()
        
        memory_writer = MemoryWriter(
            event_log=event_log,
            npc_memory_manager=npc_memory,
            summary_manager=summary_manager,
            memory_summary_repo=memory_summary_repo,
            memory_fact_repo=memory_fact_repo,
            npc_belief_repo=npc_belief_repo,
            npc_relationship_repo=npc_relationship_repo,
            session_id=session_id,
        )
        
        events = [
            SceneEvent(
                event_id="evt_1",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                scene_id="scene_1",
                trigger="ambient",
                summary="广场上人来人往",
            ),
        ]
        
        summary = memory_writer.write_scene_summary(
            scene_id="loc_square",
            start_turn=1,
            end_turn=1,
            events=events,
            state=canonical_state,
        )
        
        assert summary is not None
        
        summaries = memory_summary_repo.get_by_scope(
            session_id=session_id,
            scope_type="scene",
            scope_ref_id="loc_square",
        )
        
        assert len(summaries) >= 1
        assert "场景 loc_square" in summaries[0].summary_text

    def test_write_npc_subjective_summary_persists_to_db(self, db_session, canonical_state):
        memory_summary_repo = MemorySummaryRepository(db_session)
        memory_fact_repo = MemoryFactRepository(db_session)
        npc_belief_repo = NPCBeliefRepository(db_session)
        npc_relationship_repo = NPCRelationshipMemoryRepository(db_session)
        
        from llm_rpg.storage.models import generate_uuid
        session_id = generate_uuid()
        npc_id = "npc_1"
        
        event_log = EventLog()
        npc_memory = NPCMemoryManager()
        summary_manager = SummaryManager()
        
        memory_writer = MemoryWriter(
            event_log=event_log,
            npc_memory_manager=npc_memory,
            summary_manager=summary_manager,
            memory_summary_repo=memory_summary_repo,
            memory_fact_repo=memory_fact_repo,
            npc_belief_repo=npc_belief_repo,
            npc_relationship_repo=npc_relationship_repo,
            session_id=session_id,
        )
        
        events = [
            NPCActionEvent(
                event_id="evt_1",
                event_type=EventType.NPC_ACTION,
                turn_index=1,
                npc_id=npc_id,
                action_type="observe",
                summary="玩家看起来很可疑",
            ),
        ]
        
        summary = memory_writer.write_npc_subjective_summary(
            npc_id=npc_id,
            start_turn=1,
            end_turn=1,
            events=events,
            state=canonical_state,
        )
        
        assert summary is not None
        
        summaries = memory_summary_repo.get_by_scope(
            session_id=session_id,
            scope_type="npc",
            scope_ref_id=npc_id,
        )
        
        assert len(summaries) >= 1
        assert npc_id in summaries[0].summary_text
        assert "主观记忆" in summaries[0].summary_text

    def test_write_npc_belief_update_persists_to_db(self, db_session):
        memory_summary_repo = MemorySummaryRepository(db_session)
        memory_fact_repo = MemoryFactRepository(db_session)
        npc_belief_repo = NPCBeliefRepository(db_session)
        npc_relationship_repo = NPCRelationshipMemoryRepository(db_session)
        
        from llm_rpg.storage.models import generate_uuid
        session_id = generate_uuid()
        npc_id = "npc_1"
        
        event_log = EventLog()
        npc_memory = NPCMemoryManager()
        summary_manager = SummaryManager()
        
        memory_writer = MemoryWriter(
            event_log=event_log,
            npc_memory_manager=npc_memory,
            summary_manager=summary_manager,
            memory_summary_repo=memory_summary_repo,
            memory_fact_repo=memory_fact_repo,
            npc_belief_repo=npc_belief_repo,
            npc_relationship_repo=npc_relationship_repo,
            session_id=session_id,
        )
        
        observed_event = SceneEvent(
            event_id="evt_1",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            scene_id="scene_1",
            trigger="player_action",
            summary="玩家在广场上四处张望",
        )
        
        memory_writer.write_npc_belief_update(
            npc_id=npc_id,
            observed_event=observed_event,
            current_turn=1,
            belief_type="fact",
            confidence=0.8,
        )
        
        beliefs = npc_belief_repo.get_by_npc(
            session_id=session_id,
            npc_id=npc_id,
        )
        
        assert len(beliefs) >= 1
        assert "广场" in beliefs[0].content

    def test_write_relationship_memory_persists_to_db(self, db_session):
        memory_summary_repo = MemorySummaryRepository(db_session)
        memory_fact_repo = MemoryFactRepository(db_session)
        npc_belief_repo = NPCBeliefRepository(db_session)
        npc_relationship_repo = NPCRelationshipMemoryRepository(db_session)
        
        from llm_rpg.storage.models import generate_uuid
        session_id = generate_uuid()
        npc_id = "npc_1"
        target_id = "player"
        
        event_log = EventLog()
        npc_memory = NPCMemoryManager()
        summary_manager = SummaryManager()
        
        memory_writer = MemoryWriter(
            event_log=event_log,
            npc_memory_manager=npc_memory,
            summary_manager=summary_manager,
            memory_summary_repo=memory_summary_repo,
            memory_fact_repo=memory_fact_repo,
            npc_belief_repo=npc_belief_repo,
            npc_relationship_repo=npc_relationship_repo,
            session_id=session_id,
        )
        
        event = NPCActionEvent(
            event_id="evt_1",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            npc_id=npc_id,
            action_type="interact",
            summary="玩家帮助了NPC",
        )
        
        memory_writer.write_relationship_memories(
            source_id=npc_id,
            target_id=target_id,
            event=event,
            impact={"trust": 1, "favor": 1},
            current_turn=1,
        )
        
        relationship_memories = npc_relationship_repo.get_by_target(
            session_id=session_id,
            npc_id=npc_id,
            target_id=target_id,
        )
        
        assert len(relationship_memories) >= 1
        assert "帮助" in relationship_memories[0].content

    def test_memory_writer_without_repos_is_in_memory_only(self, canonical_state):
        event_log = EventLog()
        npc_memory = NPCMemoryManager()
        summary_manager = SummaryManager()
        
        memory_writer = MemoryWriter(
            event_log=event_log,
            npc_memory_manager=npc_memory,
            summary_manager=summary_manager,
        )
        
        events = [
            SceneEvent(
                event_id="evt_1",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                scene_id="scene_1",
                trigger="player_move",
                summary="玩家移动到广场",
            ),
        ]
        
        summary = memory_writer.write_turn_summary(
            turn_index=1,
            events=events,
            state=canonical_state,
        )
        
        assert summary is not None
        assert summary.summary_id is not None


    def test_memory_stage_enabled_with_mock_provider(self, db_session):
        """
        Test that _is_memory_stage_enabled returns True even with mock provider.
        
        Memory persistence should work independently of LLM provider mode
        because it uses already-computed deterministic data.
        """
        from llm_rpg.core.turn_service import _is_memory_stage_enabled
        
        # The function should return True regardless of provider mode
        # because memory persistence uses deterministic data, not LLM output
        result = _is_memory_stage_enabled(db_session)
        assert result is True, "Memory stage should be enabled even with mock provider"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

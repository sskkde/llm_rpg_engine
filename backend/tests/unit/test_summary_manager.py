"""
Unit tests for SummaryManager.

Tests summary output stability, summary length/content constraints,
and empty state input handling.
"""

import pytest

from llm_rpg.core.summary import SummaryManager
from llm_rpg.models.summaries import (
    Summary,
    SummaryType,
    WorldChronicle,
    SceneSummary,
    SessionSummary,
    NPCSubjectiveSummary,
    FactionSummary,
    PlayerJourneySummary,
    EmotionalImpression,
)


class TestSummaryManagerBasicOperations:
    """Test basic add/retrieve operations."""

    def test_add_summary_stores_summary(self):
        manager = SummaryManager()
        summary = Summary(
            summary_id="sum_1",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=1,
            end_turn=5,
            content="Test summary",
        )
        
        manager.add_summary(summary)
        
        assert manager.get_summary("sum_1") == summary

    def test_get_summary_returns_none_for_unknown(self):
        manager = SummaryManager()
        
        result = manager.get_summary("unknown")
        
        assert result is None

    def test_get_summaries_by_type(self):
        manager = SummaryManager()
        chronicle = Summary(
            summary_id="sum_1",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=1,
            end_turn=5,
            content="Chronicle",
        )
        scene = Summary(
            summary_id="sum_2",
            summary_type=SummaryType.SCENE_SUMMARY,
            start_turn=1,
            end_turn=5,
            content="Scene",
            scene_id="scene_1",
        )
        
        manager.add_summary(chronicle)
        manager.add_summary(scene)
        
        results = manager.get_summaries_by_type(SummaryType.WORLD_CHRONICLE)
        
        assert len(results) == 1
        assert results[0].summary_id == "sum_1"

    def test_get_summaries_by_owner(self):
        manager = SummaryManager()
        summary1 = Summary(
            summary_id="sum_1",
            summary_type=SummaryType.NPC_SUBJECTIVE,
            owner_type="npc",
            owner_id="npc_1",
            start_turn=1,
            end_turn=5,
            content="NPC summary",
        )
        summary2 = Summary(
            summary_id="sum_2",
            summary_type=SummaryType.NPC_SUBJECTIVE,
            owner_type="npc",
            owner_id="npc_2",
            start_turn=1,
            end_turn=5,
            content="Other NPC summary",
        )
        
        manager.add_summary(summary1)
        manager.add_summary(summary2)
        
        results = manager.get_summaries_by_owner("npc", "npc_1")
        
        assert len(results) == 1
        assert results[0].summary_id == "sum_1"

    def test_get_summaries_for_turn(self):
        manager = SummaryManager()
        summary1 = Summary(
            summary_id="sum_1",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=1,
            end_turn=5,
            content="Summary 1-5",
        )
        summary2 = Summary(
            summary_id="sum_2",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=6,
            end_turn=10,
            content="Summary 6-10",
        )
        
        manager.add_summary(summary1)
        manager.add_summary(summary2)
        
        results = manager.get_summaries_for_turn(3)
        
        assert len(results) == 1
        assert results[0].summary_id == "sum_1"

    def test_get_summaries_for_turn_overlapping_ranges(self):
        manager = SummaryManager()
        summary1 = Summary(
            summary_id="sum_1",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=1,
            end_turn=5,
            content="Summary 1",
        )
        summary2 = Summary(
            summary_id="sum_2",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=3,
            end_turn=7,
            content="Summary 2",
        )
        
        manager.add_summary(summary1)
        manager.add_summary(summary2)
        
        results = manager.get_summaries_for_turn(4)
        
        assert len(results) == 2


class TestSummaryOutputStability:
    """Test summary output stability (same input → same summary)."""

    def test_create_world_chronicle_produces_consistent_id(self):
        manager = SummaryManager()
        
        chronicle1 = manager.create_world_chronicle(
            start_turn=1,
            end_turn=5,
            content="Chronicle content",
        )
        chronicle2 = manager.create_world_chronicle(
            start_turn=1,
            end_turn=5,
            content="Chronicle content",
        )
        
        assert chronicle1.summary_id == chronicle2.summary_id

    def test_create_scene_summary_produces_consistent_id(self):
        manager = SummaryManager()
        
        scene1 = manager.create_scene_summary(
            scene_id="scene_1",
            start_turn=1,
            end_turn=5,
            content="Scene content",
        )
        scene2 = manager.create_scene_summary(
            scene_id="scene_1",
            start_turn=1,
            end_turn=5,
            content="Scene content",
        )
        
        assert scene1.summary_id == scene2.summary_id

    def test_create_session_summary_produces_consistent_id(self):
        manager = SummaryManager()
        
        session1 = manager.create_session_summary(
            session_id="session_1",
            start_turn=1,
            end_turn=5,
            content="Session content",
        )
        session2 = manager.create_session_summary(
            session_id="session_1",
            start_turn=1,
            end_turn=5,
            content="Session content",
        )
        
        assert session1.summary_id == session2.summary_id

    def test_create_npc_subjective_summary_produces_consistent_id(self):
        manager = SummaryManager()
        
        npc1 = manager.create_npc_subjective_summary(
            npc_id="npc_1",
            start_turn=1,
            end_turn=5,
            subjective_summary="NPC content",
        )
        npc2 = manager.create_npc_subjective_summary(
            npc_id="npc_1",
            start_turn=1,
            end_turn=5,
            subjective_summary="NPC content",
        )
        
        assert npc1.summary_id == npc2.summary_id

    def test_create_faction_summary_produces_consistent_id(self):
        manager = SummaryManager()
        
        faction1 = manager.create_faction_summary(
            faction_id="faction_1",
            start_turn=1,
            end_turn=5,
            content="Faction content",
        )
        faction2 = manager.create_faction_summary(
            faction_id="faction_1",
            start_turn=1,
            end_turn=5,
            content="Faction content",
        )
        
        assert faction1.summary_id == faction2.summary_id

    def test_create_player_journey_summary_produces_consistent_id(self):
        manager = SummaryManager()
        
        journey1 = manager.create_player_journey_summary(
            player_id="player_1",
            chapter="Chapter 1",
            start_turn=1,
            end_turn=5,
            content="Journey content",
        )
        journey2 = manager.create_player_journey_summary(
            player_id="player_1",
            chapter="Chapter 1",
            start_turn=1,
            end_turn=5,
            content="Journey content",
        )
        
        assert journey1.summary_id == journey2.summary_id

    def test_same_content_produces_same_result(self):
        manager = SummaryManager()
        
        chronicle = manager.create_world_chronicle(
            start_turn=1,
            end_turn=5,
            content="Same content",
            location_ids=["loc_1"],
            key_event_ids=["evt_1"],
            objective_facts=["Fact 1"],
        )
        
        retrieved = manager.get_summary(chronicle.summary_id)
        
        assert retrieved.content == "Same content"
        assert retrieved.location_ids == ["loc_1"]
        assert retrieved.key_event_ids == ["evt_1"]
        assert retrieved.objective_facts == ["Fact 1"]


class TestSummaryLengthConstraints:
    """Test summary length/content constraints."""

    def test_create_world_chronicle_with_long_content(self):
        manager = SummaryManager()
        long_content = "A" * 10000
        
        chronicle = manager.create_world_chronicle(
            start_turn=1,
            end_turn=5,
            content=long_content,
        )
        
        assert chronicle.content == long_content

    def test_create_scene_summary_with_many_open_threads(self):
        manager = SummaryManager()
        many_threads = [f"Thread {i}" for i in range(100)]
        
        scene = manager.create_scene_summary(
            scene_id="scene_1",
            start_turn=1,
            end_turn=5,
            content="Scene content",
            open_threads=many_threads,
        )
        
        assert len(scene.open_threads) == 100

    def test_create_session_summary_with_many_events(self):
        manager = SummaryManager()
        many_events = [f"Event {i}" for i in range(100)]
        
        session = manager.create_session_summary(
            session_id="session_1",
            start_turn=1,
            end_turn=5,
            content="Session content",
            major_events=many_events,
        )
        
        assert len(session.major_events) == 100

    def test_create_npc_subjective_summary_with_emotional_impression(self):
        manager = SummaryManager()
        
        npc_summary = manager.create_npc_subjective_summary(
            npc_id="npc_1",
            start_turn=1,
            end_turn=5,
            subjective_summary="NPC content",
            emotional_impression=EmotionalImpression(
                trust=0.8,
                suspicion=0.1,
                anxiety=0.2,
                affection=0.7,
            ),
        )
        
        assert npc_summary.emotional_impression.trust == 0.8
        assert npc_summary.emotional_impression.suspicion == 0.1

    def test_create_npc_subjective_summary_with_memory_strength(self):
        manager = SummaryManager()
        
        npc_summary = manager.create_npc_subjective_summary(
            npc_id="npc_1",
            start_turn=1,
            end_turn=5,
            subjective_summary="NPC content",
            memory_strength=0.6,
            distortion_level=0.2,
        )
        
        assert npc_summary.memory_strength == 0.6
        assert npc_summary.distortion_level == 0.2


class TestEmptyStateInput:
    """Test empty state input handling."""

    def test_create_world_chronicle_with_empty_content(self):
        manager = SummaryManager()
        
        chronicle = manager.create_world_chronicle(
            start_turn=1,
            end_turn=5,
            content="",
        )
        
        assert chronicle.content == ""

    def test_create_world_chronicle_with_empty_lists(self):
        manager = SummaryManager()
        
        chronicle = manager.create_world_chronicle(
            start_turn=1,
            end_turn=5,
            content="Content",
            location_ids=[],
            key_event_ids=[],
            objective_facts=[],
        )
        
        assert chronicle.location_ids == []
        assert chronicle.key_event_ids == []
        assert chronicle.objective_facts == []

    def test_create_scene_summary_with_empty_open_threads(self):
        manager = SummaryManager()
        
        scene = manager.create_scene_summary(
            scene_id="scene_1",
            start_turn=1,
            end_turn=5,
            content="Content",
            open_threads=[],
        )
        
        assert scene.open_threads == []

    def test_create_session_summary_with_empty_events(self):
        manager = SummaryManager()
        
        session = manager.create_session_summary(
            session_id="session_1",
            start_turn=1,
            end_turn=5,
            content="Content",
            player_actions=[],
            major_events=[],
        )
        
        assert session.player_actions == []
        assert session.major_events == []

    def test_get_recent_summaries_empty_manager(self):
        manager = SummaryManager()
        
        results = manager.get_recent_summaries()
        
        assert results == []

    def test_get_relevant_summaries_empty_manager(self):
        manager = SummaryManager()
        
        results = manager.get_relevant_summaries(current_turn=5)
        
        assert results == []

    def test_get_summaries_by_type_empty_manager(self):
        manager = SummaryManager()
        
        results = manager.get_summaries_by_type(SummaryType.WORLD_CHRONICLE)
        
        assert results == []

    def test_get_summaries_by_owner_empty_manager(self):
        manager = SummaryManager()
        
        results = manager.get_summaries_by_owner("npc", "npc_1")
        
        assert results == []


class TestSummaryRetrieval:
    """Test summary retrieval methods."""

    def test_get_recent_summaries_returns_most_recent(self):
        manager = SummaryManager()
        old = Summary(
            summary_id="sum_1",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=1,
            end_turn=5,
            content="Old",
        )
        new = Summary(
            summary_id="sum_2",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=6,
            end_turn=10,
            content="New",
        )
        
        manager.add_summary(old)
        manager.add_summary(new)
        
        results = manager.get_recent_summaries(limit=1)
        
        assert len(results) == 1
        assert results[0].summary_id == "sum_2"

    def test_get_recent_summaries_respects_limit(self):
        manager = SummaryManager()
        for i in range(10):
            manager.add_summary(Summary(
                summary_id=f"sum_{i}",
                summary_type=SummaryType.WORLD_CHRONICLE,
                start_turn=i,
                end_turn=i + 1,
                content=f"Summary {i}",
            ))
        
        results = manager.get_recent_summaries(limit=3)
        
        assert len(results) == 3

    def test_get_recent_summaries_filters_by_type(self):
        manager = SummaryManager()
        chronicle = Summary(
            summary_id="sum_1",
            summary_type=SummaryType.WORLD_CHRONICLE,
            start_turn=1,
            end_turn=5,
            content="Chronicle",
        )
        scene = Summary(
            summary_id="sum_2",
            summary_type=SummaryType.SCENE_SUMMARY,
            start_turn=1,
            end_turn=5,
            content="Scene",
            scene_id="scene_1",
        )
        
        manager.add_summary(chronicle)
        manager.add_summary(scene)
        
        results = manager.get_recent_summaries(
            limit=10,
            summary_type=SummaryType.WORLD_CHRONICLE,
        )
        
        assert len(results) == 1
        assert results[0].summary_type == SummaryType.WORLD_CHRONICLE

    def test_get_relevant_summaries_lookback(self):
        manager = SummaryManager()
        for i in range(20):
            manager.add_summary(Summary(
                summary_id=f"sum_{i}",
                summary_type=SummaryType.WORLD_CHRONICLE,
                start_turn=i,
                end_turn=i,
                content=f"Summary {i}",
            ))
        
        results = manager.get_relevant_summaries(
            current_turn=15,
            lookback_turns=5,
        )
        
        for r in results:
            assert r.end_turn >= 10


class TestSummaryTypes:
    """Test different summary type creation."""

    def test_create_world_chronicle(self):
        manager = SummaryManager()
        
        chronicle = manager.create_world_chronicle(
            start_turn=1,
            end_turn=5,
            content="World events",
            location_ids=["loc_1", "loc_2"],
            key_event_ids=["evt_1"],
            objective_facts=["Fact 1", "Fact 2"],
        )
        
        assert chronicle.summary_type == SummaryType.WORLD_CHRONICLE
        assert chronicle.location_ids == ["loc_1", "loc_2"]
        assert chronicle.objective_facts == ["Fact 1", "Fact 2"]

    def test_create_scene_summary(self):
        manager = SummaryManager()
        
        scene = manager.create_scene_summary(
            scene_id="scene_1",
            start_turn=1,
            end_turn=5,
            content="Scene events",
            open_threads=["Thread 1"],
            scene_phase="climax",
        )
        
        assert scene.summary_type == SummaryType.SCENE_SUMMARY
        assert scene.scene_id == "scene_1"
        assert scene.scene_phase == "climax"

    def test_create_session_summary(self):
        manager = SummaryManager()
        
        session = manager.create_session_summary(
            session_id="session_1",
            start_turn=1,
            end_turn=5,
            content="Session events",
            player_actions=["Action 1"],
            major_events=["Event 1"],
        )
        
        assert session.summary_type == SummaryType.SESSION_SUMMARY
        assert session.session_id == "session_1"
        assert session.player_actions == ["Action 1"]

    def test_create_npc_subjective_summary(self):
        manager = SummaryManager()
        
        npc = manager.create_npc_subjective_summary(
            npc_id="npc_1",
            start_turn=1,
            end_turn=5,
            subjective_summary="NPC perspective",
        )
        
        assert npc.summary_type == SummaryType.NPC_SUBJECTIVE
        assert npc.npc_id == "npc_1"
        assert npc.subjective_summary == "NPC perspective"

    def test_create_faction_summary(self):
        manager = SummaryManager()
        
        faction = manager.create_faction_summary(
            faction_id="faction_1",
            start_turn=1,
            end_turn=5,
            content="Faction events",
            known_events=["Event 1"],
            strategic_concerns=["Concern 1"],
        )
        
        assert faction.summary_type == SummaryType.FACTION_SUMMARY
        assert faction.faction_id == "faction_1"
        assert faction.known_events == ["Event 1"]

    def test_create_player_journey_summary(self):
        manager = SummaryManager()
        
        journey = manager.create_player_journey_summary(
            player_id="player_1",
            chapter="Chapter 1",
            start_turn=1,
            end_turn=5,
            content="Player journey",
            known_clues=["Clue 1"],
            unresolved_questions=["Question 1"],
        )
        
        assert journey.summary_type == SummaryType.PLAYER_JOURNEY
        assert journey.player_id == "player_1"
        assert journey.chapter == "Chapter 1"
        assert journey.known_clues == ["Clue 1"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

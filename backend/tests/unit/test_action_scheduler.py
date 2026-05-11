"""
Unit tests for ActionScheduler.

Tests cover:
- Queueing actions
- Conflicting actions for same resource
- Scene triggers collection
- Committed actions tracking
- Empty scheduler behavior
- Deterministic ordering
"""

import pytest
from datetime import datetime

from llm_rpg.core.action_scheduler import ActionScheduler
from llm_rpg.models.common import ProposedAction, CommittedAction
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    WorldTime,
    NPCState,
    PhysicalState,
    MentalState,
)


def make_world_time() -> WorldTime:
    return WorldTime(
        calendar="修仙历",
        season="春",
        day=1,
        period="辰时",
    )


def make_player_state() -> PlayerState:
    return PlayerState(
        entity_id="player_1",
        location_id="loc_1",
    )


def make_world_state() -> WorldState:
    return WorldState(
        entity_id="world_1",
        world_id="world_1",
        current_time=make_world_time(),
    )


def make_scene_state() -> CurrentSceneState:
    return CurrentSceneState(
        entity_id="scene_1",
        scene_id="scene_1",
        location_id="loc_1",
        active_actor_ids=["npc_1", "npc_2"],
    )


def make_canonical_state() -> CanonicalState:
    return CanonicalState(
        player_state=make_player_state(),
        world_state=make_world_state(),
        current_scene_state=make_scene_state(),
    )


def make_npc_state(npc_id: str, name: str = "NPC") -> NPCState:
    return NPCState(
        entity_id=npc_id,
        npc_id=npc_id,
        name=name,
        location_id="loc_1",
        physical_state=PhysicalState(),
        mental_state=MentalState(),
    )


def make_proposed_action(
    action_id: str,
    actor_id: str,
    target_ids: list = None,
    priority: float = 0.5,
    action_type: str = "move",
    summary: str = "test action",
) -> ProposedAction:
    return ProposedAction(
        action_id=action_id,
        actor_id=actor_id,
        action_type=action_type,
        target_ids=target_ids or [],
        summary=summary,
        priority=priority,
    )


class TestActionSchedulerInit:
    """Tests for ActionScheduler initialization."""

    def test_initialization(self):
        scheduler = ActionScheduler()
        assert scheduler is not None
        assert len(scheduler.get_action_queue()) == 0
        assert len(scheduler.get_committed_actions()) == 0

    def test_empty_scheduler_behavior(self):
        scheduler = ActionScheduler()
        
        queue = scheduler.get_action_queue()
        assert queue == []
        
        committed = scheduler.get_committed_actions()
        assert committed == []


class TestActionQueue:
    """Tests for action queueing."""

    def test_add_proposed_action(self):
        scheduler = ActionScheduler()
        action = make_proposed_action("act_1", "player")
        
        scheduler.add_proposed_action(action)
        
        queue = scheduler.get_action_queue()
        assert len(queue) == 1
        assert queue[0].action_id == "act_1"

    def test_add_multiple_actions(self):
        scheduler = ActionScheduler()
        
        for i in range(5):
            action = make_proposed_action(f"act_{i}", f"actor_{i}")
            scheduler.add_proposed_action(action)
        
        queue = scheduler.get_action_queue()
        assert len(queue) == 5

    def test_clear_action_queue(self):
        scheduler = ActionScheduler()
        
        for i in range(3):
            action = make_proposed_action(f"act_{i}", f"actor_{i}")
            scheduler.add_proposed_action(action)
        
        scheduler.clear_action_queue()
        
        queue = scheduler.get_action_queue()
        assert queue == []

    def test_get_action_queue_returns_copy(self):
        scheduler = ActionScheduler()
        action = make_proposed_action("act_1", "player")
        scheduler.add_proposed_action(action)
        
        queue = scheduler.get_action_queue()
        queue.clear()
        
        assert len(scheduler.get_action_queue()) == 1


class TestPriorityResolution:
    """Tests for priority-based ordering."""

    def test_resolve_priority_orders_by_priority(self):
        scheduler = ActionScheduler()
        
        action1 = make_proposed_action("act_1", "player", priority=0.3)
        action2 = make_proposed_action("act_2", "npc_1", priority=0.8)
        action3 = make_proposed_action("act_3", "npc_2", priority=0.5)
        
        resolved = scheduler.resolve_priority([action1, action2, action3])
        
        assert resolved[0].action_id == "act_2"
        assert resolved[1].action_id == "act_3"
        assert resolved[2].action_id == "act_1"

    def test_deterministic_ordering_same_input(self):
        scheduler = ActionScheduler()
        
        actions = [
            make_proposed_action("act_1", "player", priority=0.5),
            make_proposed_action("act_2", "npc_1", priority=0.5),
            make_proposed_action("act_3", "npc_2", priority=0.5),
        ]
        
        result1 = scheduler.resolve_priority(actions)
        result2 = scheduler.resolve_priority(actions)
        
        assert [a.action_id for a in result1] == [a.action_id for a in result2]


class TestConflictResolution:
    """Tests for conflict detection and resolution."""

    def test_conflicting_actions_same_target(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        action1 = make_proposed_action("act_1", "player", target_ids=["npc_1"])
        action2 = make_proposed_action("act_2", "npc_2", target_ids=["npc_1"])
        
        conflicts = scheduler._detect_conflicts([action1, action2])
        
        assert len(conflicts) == 1
        assert len(conflicts[0]) == 2

    def test_non_conflicting_actions_different_targets(self):
        scheduler = ActionScheduler()
        
        action1 = make_proposed_action("act_1", "player", target_ids=["npc_1"])
        action2 = make_proposed_action("act_2", "npc_2", target_ids=["npc_3"])
        
        conflicts = scheduler._detect_conflicts([action1, action2])
        
        assert len(conflicts) == 2
        assert all(len(c) == 1 for c in conflicts)

    def test_resolve_conflicts_picks_highest_priority(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        action1 = make_proposed_action("act_1", "player", target_ids=["npc_1"], priority=0.3)
        action2 = make_proposed_action("act_2", "npc_2", target_ids=["npc_1"], priority=0.8)
        
        resolved = scheduler.resolve_conflicts([action1, action2], state)
        
        assert len(resolved) == 1
        assert resolved[0].action_id == "act_2"

    def test_actions_conflict_detection(self):
        scheduler = ActionScheduler()
        
        action1 = make_proposed_action("act_1", "player", target_ids=["npc_1", "npc_2"])
        action2 = make_proposed_action("act_2", "npc_2", target_ids=["npc_2"])
        
        assert scheduler._actions_conflict(action1, action2) is True

    def test_actions_no_conflict_empty_targets(self):
        scheduler = ActionScheduler()
        
        action1 = make_proposed_action("act_1", "player", target_ids=[])
        action2 = make_proposed_action("act_2", "npc_1", target_ids=[])
        
        assert scheduler._actions_conflict(action1, action2) is False

    def test_multiple_conflict_groups(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        action1 = make_proposed_action("act_1", "player", target_ids=["npc_1"], priority=0.9)
        action2 = make_proposed_action("act_2", "npc_2", target_ids=["npc_1"], priority=0.3)
        action3 = make_proposed_action("act_3", "player", target_ids=["npc_3"], priority=0.5)
        action4 = make_proposed_action("act_4", "npc_2", target_ids=["npc_3"], priority=0.7)
        
        resolved = scheduler.resolve_conflicts([action1, action2, action3, action4], state)
        
        assert len(resolved) == 2
        winning_ids = {a.action_id for a in resolved}
        assert "act_1" in winning_ids
        assert "act_4" in winning_ids


class TestSceneTriggers:
    """Tests for scene trigger registration and collection."""

    def test_register_scene_trigger(self):
        scheduler = ActionScheduler()
        
        scheduler.register_scene_trigger(
            trigger_id="trigger_1",
            conditions=["condition_1"],
            event_candidate="event_1",
            priority=0.5,
        )
        
        assert "trigger_1" in scheduler._scene_triggers

    def test_collect_scene_triggers(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        scheduler.register_scene_trigger(
            trigger_id="trigger_1",
            conditions=["condition_1"],
            event_candidate="event_1",
            priority=0.3,
        )
        scheduler.register_scene_trigger(
            trigger_id="trigger_2",
            conditions=["condition_2"],
            event_candidate="event_2",
            priority=0.8,
        )
        
        triggered = scheduler.collect_scene_triggers(state)
        
        assert len(triggered) == 2
        assert triggered[0]["trigger_id"] == "trigger_2"

    def test_scene_triggers_ordered_by_priority(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        scheduler.register_scene_trigger("t1", [], "e1", priority=0.2)
        scheduler.register_scene_trigger("t2", [], "e2", priority=0.9)
        scheduler.register_scene_trigger("t3", [], "e3", priority=0.5)
        
        triggered = scheduler.collect_scene_triggers(state)
        
        assert triggered[0]["priority"] == 0.9
        assert triggered[1]["priority"] == 0.5
        assert triggered[2]["priority"] == 0.2


class TestCommittedActions:
    """Tests for committed action tracking."""

    def test_commit_action(self):
        scheduler = ActionScheduler()
        
        action = make_proposed_action("act_1", "player")
        committed = scheduler.commit_action(
            action=action,
            state_deltas=[{"path": "test", "old": None, "new": "value"}],
            event_ids=["evt_1"],
        )
        
        assert committed is not None
        assert committed.action_id == "act_1"
        assert len(committed.state_deltas) == 1
        assert committed.event_ids == ["evt_1"]

    def test_get_committed_actions(self):
        scheduler = ActionScheduler()
        
        action1 = make_proposed_action("act_1", "player")
        action2 = make_proposed_action("act_2", "npc_1")
        
        scheduler.commit_action(action1, [], [])
        scheduler.commit_action(action2, [], [])
        
        committed = scheduler.get_committed_actions()
        assert len(committed) == 2

    def test_clear_committed_actions(self):
        scheduler = ActionScheduler()
        
        action = make_proposed_action("act_1", "player")
        scheduler.commit_action(action, [], [])
        
        scheduler.clear_committed_actions()
        
        assert scheduler.get_committed_actions() == []

    def test_committed_action_preserves_proposed_data(self):
        scheduler = ActionScheduler()
        
        action = make_proposed_action(
            "act_1",
            "player",
            target_ids=["npc_1"],
            summary="attack enemy",
        )
        committed = scheduler.commit_action(action, [], [])
        
        assert committed.actor_id == "player"
        assert committed.target_ids == ["npc_1"]
        assert committed.summary == "attack enemy"


class TestCollectActors:
    """Tests for actor collection."""

    def test_collect_actors(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        actors = scheduler.collect_actors(state)
        
        assert "player" in actors
        assert "npc_1" in actors
        assert "npc_2" in actors

    def test_collect_actors_deduplicates(self):
        scheduler = ActionScheduler()
        state = CanonicalState(
            player_state=make_player_state(),
            world_state=make_world_state(),
            current_scene_state=CurrentSceneState(
                entity_id="scene_1",
                scene_id="scene_1",
                location_id="loc_1",
                active_actor_ids=["player", "npc_1"],
            ),
        )
        
        actors = scheduler.collect_actors(state)
        
        assert actors.count("player") == 1


class TestScheduleNPCActions:
    """Tests for NPC action scheduling."""

    def test_schedule_npc_actions_with_goals(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        npc = make_npc_state("npc_1", "Test NPC")
        npc.current_goal_ids = ["goal_1"]
        
        actions = scheduler.schedule_npc_actions([npc], state)
        
        assert len(actions) == 1
        assert actions[0].actor_id == "npc_1"

    def test_schedule_npc_actions_no_goals(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        npc = make_npc_state("npc_1", "Test NPC")
        npc.current_goal_ids = []
        
        actions = scheduler.schedule_npc_actions([npc], state)
        
        assert len(actions) == 0

    def test_schedule_multiple_npcs(self):
        scheduler = ActionScheduler()
        state = make_canonical_state()
        
        npc1 = make_npc_state("npc_1", "NPC 1")
        npc1.current_goal_ids = ["goal_1"]
        
        npc2 = make_npc_state("npc_2", "NPC 2")
        npc2.current_goal_ids = ["goal_2"]
        
        actions = scheduler.schedule_npc_actions([npc1, npc2], state)
        
        assert len(actions) == 2

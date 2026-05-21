"""
Unit tests for ConflictResolver - 5 conflict resolution scenarios.

1. NPC blocks player
2. Multi-character item competition
3. Target fled causing attack failure
4. Dialog interrupted by high-priority event
5. Quest stage conflict
"""

import pytest

from llm_rpg.core.conflict_resolver import ConflictResolver, ConflictResult
from llm_rpg.models.common import ProposedAction
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    WorldTime,
    NPCState,
    QuestState,
    PhysicalState,
    MentalState,
)


def make_world_time() -> WorldTime:
    return WorldTime(calendar="修仙历", season="春", day=1, period="辰时")


def make_player_state(location_id: str = "loc_1") -> PlayerState:
    return PlayerState(entity_id="player_1", location_id=location_id)


def make_world_state() -> WorldState:
    return WorldState(entity_id="world_1", world_id="world_1", current_time=make_world_time())


def make_scene_state() -> CurrentSceneState:
    return CurrentSceneState(
        entity_id="scene_1", scene_id="scene_1", location_id="loc_1",
        active_actor_ids=["npc_guard"],
    )


def make_npc_state(
    npc_id: str,
    name: str = "NPC",
    location_id: str = "loc_1",
    fatigue: float = 0.0,
) -> NPCState:
    return NPCState(
        entity_id=npc_id,
        npc_id=npc_id,
        name=name,
        location_id=location_id,
        physical_state=PhysicalState(fatigue=fatigue),
        mental_state=MentalState(),
    )


def make_canonical_state(
    npc_states: dict | None = None,
    player_location: str = "loc_1",
) -> CanonicalState:
    npcs = npc_states or {"npc_guard": make_npc_state("npc_guard", "守卫")}
    return CanonicalState(
        player_state=make_player_state(player_location),
        world_state=make_world_state(),
        current_scene_state=make_scene_state(),
        npc_states=npcs,
    )


def make_action(
    action_id: str,
    actor_id: str,
    action_type: str = "move",
    target_ids: list | None = None,
    priority: float = 0.5,
    summary: str = "test action",
    state_delta_candidates: list | None = None,
) -> ProposedAction:
    return ProposedAction(
        action_id=action_id,
        actor_id=actor_id,
        action_type=action_type,
        target_ids=target_ids or [],
        summary=summary,
        priority=priority,
        state_delta_candidates=state_delta_candidates or [],
    )


class TestNPCBlocksPlayer:
    """Scenario 1: NPC with higher priority blocks player action."""

    def test_npc_higher_priority_blocks_player_move(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        player_action = make_action("act_player", "player", "move", target_ids=["loc_2"], priority=0.3, summary="前往禁区")
        npc_action = make_action("act_npc", "npc_guard", "move", target_ids=["loc_2"], priority=0.8, summary="守卫巡逻")

        result = resolver.resolve_npc_block(player_action, npc_action, state)

        assert result.should_block is True
        assert "act_player" in result.blocked_actions
        assert "守卫" in result.narration

    def test_npc_lower_priority_does_not_block(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        player_action = make_action("act_player", "player", "move", priority=0.8)
        npc_action = make_action("act_npc", "npc_guard", "move", priority=0.3)

        result = resolver.resolve_npc_block(player_action, npc_action, state)

        assert result.should_block is False
        assert result.blocked_actions == []

    def test_npc_same_priority_does_not_block(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        player_action = make_action("act_player", "player", "move", priority=0.5)
        npc_action = make_action("act_npc", "npc_guard", "move", priority=0.5)

        result = resolver.resolve_npc_block(player_action, npc_action, state)

        assert result.should_block is False

    def test_npc_different_location_does_not_block(self):
        resolver = ConflictResolver()
        npcs = {
            "npc_far": make_npc_state("npc_far", "远处守卫", location_id="loc_99"),
        }
        state = make_canonical_state(npc_states=npcs)

        player_action = make_action("act_player", "player", "move", priority=0.3)
        npc_action = make_action("act_npc", "npc_far", "move", priority=0.9)

        result = resolver.resolve_npc_block(player_action, npc_action, state)

        assert result.should_block is False

    def test_npc_non_blocking_action_type_does_not_block(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        player_action = make_action("act_player", "player", "move", priority=0.3)
        npc_action = make_action("act_npc", "npc_guard", "talk", priority=0.9)

        result = resolver.resolve_npc_block(player_action, npc_action, state)

        assert result.should_block is False


class TestItemCompetition:
    """Scenario 2: Multiple characters compete for the same item."""

    def test_winner_determined_by_priority_and_dexterity(self):
        resolver = ConflictResolver()
        npcs = {
            "npc_fast": make_npc_state("npc_fast", "敏捷盗贼", fatigue=0.0),
            "npc_slow": make_npc_state("npc_slow", "疲惫战士", fatigue=0.8),
        }
        state = make_canonical_state(npc_states=npcs)

        action1 = make_action("act_1", "npc_fast", "take_item", target_ids=["item_sword"], priority=0.5)
        action2 = make_action("act_2", "npc_slow", "take_item", target_ids=["item_sword"], priority=0.5)

        result = resolver.resolve_item_competition([action1, action2], state)

        assert result.should_block is True
        assert "act_2" in result.blocked_actions
        assert "敏捷盗贼" in result.narration

    def test_single_action_no_competition(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        action = make_action("act_1", "player", "take_item", target_ids=["item_sword"])

        result = resolver.resolve_item_competition([action], state)

        assert result.should_block is False

    def test_empty_actions_no_competition(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        result = resolver.resolve_item_competition([], state)

        assert result.should_block is False

    def test_three_way_competition_blocks_two_losers(self):
        resolver = ConflictResolver()
        npcs = {
            "npc_a": make_npc_state("npc_a", "角色A", fatigue=0.1),
            "npc_b": make_npc_state("npc_b", "角色B", fatigue=0.5),
            "npc_c": make_npc_state("npc_c", "角色C", fatigue=0.9),
        }
        state = make_canonical_state(npc_states=npcs)

        action_a = make_action("act_a", "npc_a", "take_item", target_ids=["item_gem"], priority=0.5)
        action_b = make_action("act_b", "npc_b", "take_item", target_ids=["item_gem"], priority=0.5)
        action_c = make_action("act_c", "npc_c", "take_item", target_ids=["item_gem"], priority=0.5)

        result = resolver.resolve_item_competition([action_a, action_b, action_c], state)

        assert result.should_block is True
        assert len(result.blocked_actions) == 2
        assert "act_a" not in result.blocked_actions

    def test_priority_beats_dexterity(self):
        resolver = ConflictResolver()
        npcs = {
            "npc_slow_high_pri": make_npc_state("npc_slow_high_pri", "高优先慢者", fatigue=0.9),
            "npc_fast_low_pri": make_npc_state("npc_fast_low_pri", "低优先快者", fatigue=0.0),
        }
        state = make_canonical_state(npc_states=npcs)

        slow_high = make_action("act_slow", "npc_slow_high_pri", "take_item", target_ids=["item"], priority=0.9)
        fast_low = make_action("act_fast", "npc_fast_low_pri", "take_item", target_ids=["item"], priority=0.3)

        result = resolver.resolve_item_competition([slow_high, fast_low], state)

        assert "act_fast" in result.blocked_actions
        assert "act_slow" not in result.blocked_actions


class TestTargetFled:
    """Scenario 3: Target fled causing attack failure."""

    def test_target_fled_blocks_attack(self):
        resolver = ConflictResolver()
        npcs = {
            "npc_target": make_npc_state("npc_target", "逃跑者", location_id="loc_2"),
        }
        state = make_canonical_state(npc_states=npcs, player_location="loc_1")

        action = make_action("act_attack", "player", "attack", target_ids=["npc_target"], priority=0.8)

        result = resolver.resolve_target_fled(action, state)

        assert result.should_block is True
        assert "act_attack" in result.blocked_actions
        assert "逃跑者" in result.narration

    def test_target_same_location_attack_succeeds(self):
        resolver = ConflictResolver()
        npcs = {
            "npc_target": make_npc_state("npc_target", "目标", location_id="loc_1"),
        }
        state = make_canonical_state(npc_states=npcs, player_location="loc_1")

        action = make_action("act_attack", "player", "attack", target_ids=["npc_target"])

        result = resolver.resolve_target_fled(action, state)

        assert result.should_block is False

    def test_non_targeting_action_not_affected(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        action = make_action("act_move", "player", "move", target_ids=["loc_2"])

        result = resolver.resolve_target_fled(action, state)

        assert result.should_block is False

    def test_no_target_ids_not_affected(self):
        resolver = ConflictResolver()
        state = make_canonical_state()

        action = make_action("act_attack", "player", "attack", target_ids=[])

        result = resolver.resolve_target_fled(action, state)

        assert result.should_block is False

    def test_talk_target_fled_also_blocked(self):
        resolver = ConflictResolver()
        npcs = {
            "npc_target": make_npc_state("npc_target", "对话者", location_id="loc_far"),
        }
        state = make_canonical_state(npc_states=npcs, player_location="loc_1")

        action = make_action("act_talk", "player", "talk", target_ids=["npc_target"])

        result = resolver.resolve_target_fled(action, state)

        assert result.should_block is True


class TestDialogInterrupt:
    """Scenario 4: Dialog interrupted by high-priority event."""

    def test_combat_interrupts_dialog(self):
        resolver = ConflictResolver()

        dialog = make_action("act_talk", "player", "talk", target_ids=["npc_1"], priority=0.3)
        combat = make_action("act_attack", "npc_enemy", "attack", target_ids=["player"], priority=0.9)

        result = resolver.resolve_dialog_interrupt(dialog, combat)

        assert result.should_block is True
        assert "act_talk" in result.blocked_actions
        assert "战斗" in result.narration

    def test_low_priority_does_not_interrupt(self):
        resolver = ConflictResolver()

        dialog = make_action("act_talk", "player", "talk", priority=0.7)
        low_event = make_action("act_move", "npc_1", "move", priority=0.3)

        result = resolver.resolve_dialog_interrupt(dialog, low_event)

        assert result.should_block is False

    def test_non_dialog_action_not_interrupted(self):
        resolver = ConflictResolver()

        move_action = make_action("act_move", "player", "move", priority=0.3)
        combat = make_action("act_attack", "npc_enemy", "attack", priority=0.9)

        result = resolver.resolve_dialog_interrupt(move_action, combat)

        assert result.should_block is False

    def test_high_priority_non_combat_interrupts_dialog(self):
        resolver = ConflictResolver()

        dialog = make_action("act_talk", "player", "talk", priority=0.2)
        urgent_event = make_action("act_move", "npc_messenger", "move", priority=0.9)

        result = resolver.resolve_dialog_interrupt(dialog, urgent_event)

        assert result.should_block is True
        assert "突发事件" in result.narration

    def test_same_priority_no_interrupt(self):
        resolver = ConflictResolver()

        dialog = make_action("act_talk", "player", "talk", priority=0.5)
        same_event = make_action("act_attack", "npc_1", "attack", priority=0.5)

        result = resolver.resolve_dialog_interrupt(dialog, same_event)

        assert result.should_block is False


class TestQuestConflict:
    """Scenario 5: Quest stage conflict - invalid stage jumps rejected."""

    def test_invalid_stage_jump_blocked(self):
        resolver = ConflictResolver()

        quest_state = QuestState(
            entity_id="quest_1",
            quest_id="quest_1",
            name="寻仙之路",
            stage="stage_1",
        )
        quest_template = {
            "legal_transitions": [
                ["stage_1", "stage_2"],
                ["stage_2", "stage_3"],
            ],
        }
        action = make_action(
            "act_quest", "player", "quest_progress",
            state_delta_candidates=[{"to_stage": "stage_3"}],
        )

        result = resolver.resolve_quest_conflict(action, quest_state, quest_template)

        assert result.should_block is True
        assert "act_quest" in result.blocked_actions
        assert "stage_1" in result.narration
        assert "stage_3" in result.narration

    def test_valid_stage_transition_allowed(self):
        resolver = ConflictResolver()

        quest_state = QuestState(
            entity_id="quest_1",
            quest_id="quest_1",
            name="寻仙之路",
            stage="stage_1",
        )
        quest_template = {
            "legal_transitions": [
                ["stage_1", "stage_2"],
                ["stage_2", "stage_3"],
            ],
        }
        action = make_action(
            "act_quest", "player", "quest_progress",
            state_delta_candidates=[{"to_stage": "stage_2"}],
        )

        result = resolver.resolve_quest_conflict(action, quest_state, quest_template)

        assert result.should_block is False

    def test_non_quest_action_not_affected(self):
        resolver = ConflictResolver()

        quest_state = QuestState(
            entity_id="quest_1",
            quest_id="quest_1",
            name="寻仙之路",
            stage="stage_1",
        )
        action = make_action("act_move", "player", "move")

        result = resolver.resolve_quest_conflict(action, quest_state, {"legal_transitions": []})

        assert result.should_block is False

    def test_no_template_allows_transition(self):
        resolver = ConflictResolver()

        quest_state = QuestState(
            entity_id="quest_1",
            quest_id="quest_1",
            name="寻仙之路",
            stage="stage_1",
        )
        action = make_action(
            "act_quest", "player", "quest_progress",
            state_delta_candidates=[{"to_stage": "stage_99"}],
        )

        result = resolver.resolve_quest_conflict(action, quest_state, quest_template=None)

        assert result.should_block is False

    def test_empty_legal_transitions_allows_transition(self):
        resolver = ConflictResolver()

        quest_state = QuestState(
            entity_id="quest_1",
            quest_id="quest_1",
            name="寻仙之路",
            stage="stage_1",
        )
        action = make_action(
            "act_quest", "player", "quest_progress",
            state_delta_candidates=[{"to_stage": "stage_5"}],
        )

        result = resolver.resolve_quest_conflict(action, quest_state, {"legal_transitions": []})

        assert result.should_block is False

    def test_target_stage_from_target_ids_fallback(self):
        resolver = ConflictResolver()

        quest_state = QuestState(
            entity_id="quest_1",
            quest_id="quest_1",
            name="寻仙之路",
            stage="stage_1",
        )
        quest_template = {
            "legal_transitions": [
                ["stage_1", "stage_2"],
            ],
        }
        action = make_action(
            "act_quest", "player", "quest_progress",
            target_ids=["stage_2"],
        )

        result = resolver.resolve_quest_conflict(action, quest_state, quest_template)

        assert result.should_block is False

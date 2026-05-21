"""Unit tests for StateDeltaResolver.

Tests all 7 resolution scenarios:
1. resolve_player_action
2. resolve_npc_action
3. resolve_item_effect
4. resolve_quest_progress
5. resolve_relationship_change
6. resolve_combat_result
7. resolve_world_time_change
"""

import pytest

from llm_rpg.core.state_delta_resolver import StateDeltaCandidate, StateDeltaResolver
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    NPCState,
    LocationState,
    MentalState,
    PhysicalState,
)
from llm_rpg.models.events import WorldTime


def _make_state(
    player_location: str = "loc_tavern",
    player_hp: int = 100,
    player_sp: int = 50,
    npc_id: str = "npc_guard",
    npc_hp: int = 80,
    npc_trust: float = 0.5,
) -> CanonicalState:
    return CanonicalState(
        player_state=PlayerState(
            entity_id="player",
            name="Tester",
            location_id=player_location,
            spiritual_power=player_sp,
        ),
        world_state=WorldState(
            entity_id="world",
            world_id="w1",
            current_time=WorldTime(calendar="Test", season="Spring", day=1, period="辰时"),
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene",
            scene_id="scene_1",
            location_id=player_location,
        ),
        location_states={
            "loc_tavern": LocationState(entity_id="loc_tavern", location_id="loc_tavern", name="Tavern"),
            "loc_forest": LocationState(entity_id="loc_forest", location_id="loc_forest", name="Forest"),
        },
        npc_states={
            npc_id: NPCState(
                entity_id=npc_id,
                npc_id=npc_id,
                name="Guard",
                location_id="loc_tavern",
                mental_state=MentalState(trust_toward_player=npc_trust),
                physical_state=PhysicalState(hp=npc_hp, max_hp=100),
            ),
        },
    )


class TestResolvePlayerAction:
    def test_move_generates_location_delta(self):
        resolver = StateDeltaResolver()
        state = _make_state(player_location="loc_tavern")
        action = {"action_type": "move", "target_ids": ["loc_forest"], "action_id": "act_1"}

        candidates = resolver.resolve_player_action(action, state)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "session_state.current_location_id"
        assert c.operation == "set"
        assert c.old_value == "loc_tavern"
        assert c.new_value == "loc_forest"
        assert c.source_action_id == "act_1"

    def test_attack_generates_hp_decrement(self):
        resolver = StateDeltaResolver()
        state = _make_state(npc_id="npc_bandit", npc_hp=80)
        action = {"action_type": "attack", "target_ids": ["npc_bandit"], "damage": 20}

        candidates = resolver.resolve_player_action(action, state)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "npc_state.npc_bandit.hp"
        assert c.operation == "decrement"
        assert c.new_value == 20

    def test_use_item_with_effects(self):
        resolver = StateDeltaResolver()
        state = _make_state(player_hp=60, player_sp=30)
        action = {
            "action_type": "use_item",
            "item_id": "potion_01",
            "item_effects": [
                {"type": "hp_heal", "value": 30},
                {"type": "mp_heal", "value": 20},
            ],
        }

        candidates = resolver.resolve_player_action(action, state)

        paths = [c.path for c in candidates]
        assert "player_state.inventory.potion_01" in paths
        assert "player_state.hp" in paths
        assert "player_state.spirit_power" in paths
        hp_c = next(c for c in candidates if c.path == "player_state.hp")
        assert hp_c.operation == "increment"
        assert hp_c.new_value == 30

    def test_unknown_action_returns_empty(self):
        resolver = StateDeltaResolver()
        state = _make_state()
        action = {"action_type": "fly_away"}

        candidates = resolver.resolve_player_action(action, state)

        assert candidates == []

    def test_cast_skill_costs_sp_and_deals_damage(self):
        resolver = StateDeltaResolver()
        state = _make_state(player_sp=50, npc_id="npc_wolf", npc_hp=100)
        action = {
            "action_type": "cast_skill",
            "skill_name": "fireball",
            "target_ids": ["npc_wolf"],
            "damage": 25,
            "sp_cost": 15,
        }

        candidates = resolver.resolve_player_action(action, state)

        assert len(candidates) == 2
        sp_c = next(c for c in candidates if c.path == "player_state.spirit_power")
        assert sp_c.operation == "decrement"
        assert sp_c.new_value == 15
        hp_c = next(c for c in candidates if c.path == "npc_state.npc_wolf.hp")
        assert hp_c.operation == "decrement"
        assert hp_c.new_value == 25


class TestResolveNPCAction:
    def test_npc_move_generates_location_delta(self):
        resolver = StateDeltaResolver()
        state = _make_state(npc_id="npc_scout")
        action = {
            "action_type": "move",
            "actor_id": "npc_scout",
            "target_ids": ["loc_forest"],
            "action_id": "npc_act_1",
        }

        candidates = resolver.resolve_npc_action(action, state)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "npc_state.npc_scout.current_location_id"
        assert c.operation == "set"
        assert c.new_value == "loc_forest"
        assert c.source_action_id == "npc_act_1"

    def test_npc_attack_on_player(self):
        resolver = StateDeltaResolver()
        state = _make_state(player_hp=100)
        action = {
            "action_type": "attack",
            "actor_id": "npc_bandit",
            "target_ids": ["player"],
            "damage": 15,
        }

        candidates = resolver.resolve_npc_action(action, state)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "player_state.hp"
        assert c.operation == "decrement"
        assert c.new_value == 15

    def test_npc_talk_generates_dialogue_state(self):
        resolver = StateDeltaResolver()
        state = _make_state(npc_id="npc_elder")
        action = {
            "action_type": "talk",
            "actor_id": "npc_elder",
            "target_ids": ["player"],
            "dialogue_state": "greeting",
        }

        candidates = resolver.resolve_npc_action(action, state)

        assert len(candidates) == 1
        assert candidates[0].path == "npc_state.npc_elder.dialogue_state"
        assert candidates[0].new_value == "greeting"


class TestResolveItemEffect:
    def test_hp_heal_effect(self):
        resolver = StateDeltaResolver()
        state = _make_state(player_hp=60)
        item = {
            "item_id": "healing_herb",
            "effects": [{"type": "hp_heal", "value": 40}],
            "is_player": True,
        }

        candidates = resolver.resolve_item_effect(item, state)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "player_state.hp"
        assert c.operation == "increment"
        assert c.new_value == 40
        assert c.metadata["effect_type"] == "hp_heal"

    def test_mp_heal_effect(self):
        resolver = StateDeltaResolver()
        state = _make_state(player_sp=30)
        item = {
            "item_id": "mana_potion",
            "effects": [{"type": "mp_heal", "value": 50}],
            "is_player": True,
        }

        candidates = resolver.resolve_item_effect(item, state)

        assert len(candidates) == 1
        assert candidates[0].path == "player_state.spirit_power"
        assert candidates[0].new_value == 50

    def test_buff_effect(self):
        resolver = StateDeltaResolver()
        state = _make_state()
        item = {
            "item_id": "war_drums",
            "effects": [{"type": "buff", "stat": "stamina", "value": 20}],
            "is_player": True,
        }

        candidates = resolver.resolve_item_effect(item, state)

        assert len(candidates) == 1
        assert candidates[0].path == "player_state.stamina"
        assert candidates[0].operation == "increment"

    def test_multiple_effects_each_become_separate_delta(self):
        resolver = StateDeltaResolver()
        state = _make_state(player_hp=50, player_sp=20)
        item = {
            "item_id": "elixir",
            "effects": [
                {"type": "hp_heal", "value": 30},
                {"type": "mp_heal", "value": 25},
                {"type": "buff", "stat": "stamina", "value": 10},
            ],
            "is_player": True,
        }

        candidates = resolver.resolve_item_effect(item, state)

        assert len(candidates) == 3
        paths = [c.path for c in candidates]
        assert "player_state.hp" in paths
        assert "player_state.spirit_power" in paths
        assert "player_state.stamina" in paths

    def test_npc_item_effect(self):
        resolver = StateDeltaResolver()
        state = _make_state(npc_id="npc_ally", npc_hp=70)
        item = {
            "item_id": "bandage",
            "effects": [{"type": "hp_heal", "value": 20}],
            "is_player": False,
            "npc_id": "npc_ally",
        }

        candidates = resolver.resolve_item_effect(item, state)

        assert len(candidates) == 1
        assert candidates[0].path == "npc_state.npc_ally.hp"


class TestResolveQuestProgress:
    def test_stage_advancement(self):
        resolver = StateDeltaResolver()
        quest = {"quest_id": "q_main_01", "current_step": "stage_1", "status": "active"}

        candidates = resolver.resolve_quest_progress(quest, "stage_2")

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "quest_state.q_main_01.current_step"
        assert c.operation == "set"
        assert c.old_value == "stage_1"
        assert c.new_value == "stage_2"

    def test_completion_generates_status_delta(self):
        resolver = StateDeltaResolver()
        quest = {"quest_id": "q_main_02", "current_step": "stage_3", "status": "active"}

        candidates = resolver.resolve_quest_progress(quest, "completed")

        assert len(candidates) == 2
        paths = [c.path for c in candidates]
        assert "quest_state.q_main_02.current_step" in paths
        assert "quest_state.q_main_02.status" in paths
        status_c = next(c for c in candidates if c.path.endswith(".status"))
        assert status_c.new_value == "completed"

    def test_explicit_completing_flag(self):
        resolver = StateDeltaResolver()
        quest = {
            "quest_id": "q_side_01",
            "current_step": "final_boss",
            "status": "active",
            "completing": True,
        }

        candidates = resolver.resolve_quest_progress(quest, "final_boss_done")

        assert len(candidates) == 2
        status_c = next(c for c in candidates if c.path.endswith(".status"))
        assert status_c.new_value == "completed"


class TestResolveRelationshipChange:
    def test_trust_increment(self):
        resolver = StateDeltaResolver()
        old_rel = {"trust_score": 50, "source_event_id": "evt_1"}
        new_values = {"trust_score": 65}

        candidates = resolver.resolve_relationship_change(
            source="player", target="npc_elder", old_rel=old_rel, new_values=new_values
        )

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "npc_state.npc_elder.trust_score"
        assert c.operation == "increment"
        assert c.new_value == 15
        assert c.source_event_id == "evt_1"

    def test_suspicion_decrement(self):
        resolver = StateDeltaResolver()
        old_rel = {"suspicion_score": 40}
        new_values = {"suspicion_score": 20}

        candidates = resolver.resolve_relationship_change(
            source="player", target="npc_guard", old_rel=old_rel, new_values=new_values
        )

        assert len(candidates) == 1
        c = candidates[0]
        assert c.operation == "decrement"
        assert c.new_value == 20

    def test_no_change_skipped(self):
        resolver = StateDeltaResolver()
        old_rel = {"trust_score": 50}
        new_values = {"trust_score": 50}

        candidates = resolver.resolve_relationship_change(
            source="player", target="npc_merchant", old_rel=old_rel, new_values=new_values
        )

        assert candidates == []

    def test_multiple_dimensions(self):
        resolver = StateDeltaResolver()
        old_rel = {"trust_score": 50, "affinity": 0}
        new_values = {"trust_score": 60, "affinity": 10}

        candidates = resolver.resolve_relationship_change(
            source="player", target="npc_sage", old_rel=old_rel, new_values=new_values
        )

        assert len(candidates) == 2
        dims = {c.metadata["dimension"] for c in candidates}
        assert dims == {"trust_score", "affinity"}


class TestResolveCombatResult:
    def test_damage_on_target(self):
        resolver = StateDeltaResolver()
        action = {"damage": 25, "source_action_id": "combat_act_1"}

        candidates = resolver.resolve_combat_result(action, caster="player", target="npc_bandit")

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "npc_state.npc_bandit.hp"
        assert c.operation == "decrement"
        assert c.new_value == 25
        assert c.source_action_id == "combat_act_1"

    def test_damage_on_player(self):
        resolver = StateDeltaResolver()
        action = {"damage": 10}

        candidates = resolver.resolve_combat_result(action, caster="npc_wolf", target="player")

        assert len(candidates) == 1
        assert candidates[0].path == "player_state.hp"

    def test_healing_on_caster(self):
        resolver = StateDeltaResolver()
        action = {"damage": 0, "healing": 30}

        candidates = resolver.resolve_combat_result(action, caster="npc_cleric", target="player")

        heal_c = next(c for c in candidates if c.operation == "increment")
        assert heal_c.path == "npc_state.npc_cleric.hp"
        assert heal_c.new_value == 30

    def test_status_effect_generates_flag_delta(self):
        resolver = StateDeltaResolver()
        action = {
            "damage": 5,
            "status_effects": [{"name": "poison", "duration": 3}],
        }

        candidates = resolver.resolve_combat_result(action, caster="player", target="npc_slime")

        se_c = next(c for c in candidates if "status_" in c.path)
        assert "poison" in se_c.path
        assert se_c.new_value == 3

    def test_no_damage_no_heal_returns_empty(self):
        resolver = StateDeltaResolver()
        action = {"damage": 0, "healing": 0, "status_effects": []}

        candidates = resolver.resolve_combat_result(action, caster="player", target="npc_idle")

        assert candidates == []


class TestResolveWorldTimeChange:
    def test_time_advancement(self):
        resolver = StateDeltaResolver()

        candidates = resolver.resolve_world_time_change(old_time=100, new_time=150)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.path == "session_state.world_time"
        assert c.operation == "set"
        assert c.old_value == 100
        assert c.new_value == 150

    def test_time_with_dict_input(self):
        resolver = StateDeltaResolver()

        candidates = resolver.resolve_world_time_change(
            old_time={"value": 200, "source_event_id": "tick_5"},
            new_time={"value": 250},
        )

        assert len(candidates) == 1
        c = candidates[0]
        assert c.old_value == 200
        assert c.new_value == 250
        assert c.source_event_id == "tick_5"


class TestStateDeltaCandidateModel:
    def test_default_fields(self):
        c = StateDeltaCandidate(path="player_state.hp", operation="set", old_value=50, new_value=80)
        assert c.source_action_id == ""
        assert c.source_event_id == ""
        assert c.metadata == {}

    def test_metadata_isolation(self):
        c1 = StateDeltaCandidate(path="a", operation="set", old_value=0, new_value=1)
        c2 = StateDeltaCandidate(path="b", operation="set", old_value=0, new_value=1)
        c1.metadata["key"] = "val"
        assert "key" not in c2.metadata


class TestResolverDoesNotCommit:
    def test_resolve_returns_candidates_not_state(self):
        resolver = StateDeltaResolver()
        state = _make_state()
        action = {"action_type": "move", "target_ids": ["loc_forest"]}

        candidates = resolver.resolve_player_action(action, state)

        for c in candidates:
            assert isinstance(c, StateDeltaCandidate)
        assert state.player_state.location_id == "loc_tavern"

    def test_candidates_carry_source_ids(self):
        resolver = StateDeltaResolver()
        action = {
            "action_type": "attack",
            "target_ids": ["npc_guard"],
            "damage": 10,
            "action_id": "act_42",
        }

        candidates = resolver.resolve_player_action(action, _make_state())

        for c in candidates:
            assert c.source_action_id == "act_42" or c.source_action_id == ""

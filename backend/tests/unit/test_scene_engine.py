"""
Unit tests for Scene Engine.

Tests SceneEngine with scene triggers and state helpers.
"""

import pytest
from datetime import datetime

from llm_rpg.engines.scene_engine import (
    SceneEngine,
    Scene,
    SceneState,
    SceneTrigger,
    TriggerType,
)


class TestSceneEngine:
    """Tests for SceneEngine."""
    
    def test_engine_initialization(self):
        engine = SceneEngine()
        assert engine is not None
        assert len(engine.get_active_scenes()) == 0
    
    def test_create_scene(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Forest Encounter", location_id="forest")
        
        assert scene is not None
        assert scene.name == "Forest Encounter"
        assert scene.location_id == "forest"
        assert scene.scene_id.startswith("scene_")
        assert scene.state == SceneState.INACTIVE
    
    def test_register_scene(self):
        engine = SceneEngine()
        scene = Scene(
            scene_id="scene_test",
            name="Test Scene",
            location_id="test_location",
        )
        
        scene_id = engine.register_scene(scene)
        assert scene_id == "scene_test"
        assert engine.get_scene(scene_id) == scene
    
    def test_get_scene_not_found(self):
        engine = SceneEngine()
        assert engine.get_scene("nonexistent") is None
    
    def test_get_scenes_at_location(self):
        engine = SceneEngine()
        engine.create_scene(name="Scene 1", location_id="forest")
        engine.create_scene(name="Scene 2", location_id="forest")
        engine.create_scene(name="Scene 3", location_id="cave")
        
        forest_scenes = engine.get_scenes_at_location("forest")
        assert len(forest_scenes) == 2
        
        cave_scenes = engine.get_scenes_at_location("cave")
        assert len(cave_scenes) == 1
    
    def test_activate_scene(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        
        result = engine.activate_scene(scene.scene_id)
        assert result is True
        assert scene.state == SceneState.ACTIVE
        assert scene.activated_at is not None
    
    def test_activate_scene_not_found(self):
        engine = SceneEngine()
        result = engine.activate_scene("nonexistent")
        assert result is False
    
    def test_deactivate_scene(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        result = engine.deactivate_scene(scene.scene_id)
        assert result is True
        assert scene.state == SceneState.INACTIVE
    
    def test_complete_scene(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        engine.activate_scene(scene.scene_id)
        
        result = engine.complete_scene(scene.scene_id)
        assert result is True
        assert scene.state == SceneState.COMPLETED
        assert scene.completed_at is not None
    
    def test_get_active_scenes(self):
        engine = SceneEngine()
        scene1 = engine.create_scene(name="Scene 1")
        scene2 = engine.create_scene(name="Scene 2")
        engine.create_scene(name="Scene 3")
        
        engine.activate_scene(scene1.scene_id)
        engine.activate_scene(scene2.scene_id)
        
        active = engine.get_active_scenes()
        assert len(active) == 2
    
    def test_add_remove_actor(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        
        engine.add_actor_to_scene(scene.scene_id, "npc_123")
        assert "npc_123" in scene.active_actors
        
        engine.remove_actor_from_scene(scene.scene_id, "npc_123")
        assert "npc_123" not in scene.active_actors
    
    def test_block_unblock_path(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        
        engine.block_path(scene.scene_id, "north")
        assert "north" in scene.blocked_paths
        
        engine.unblock_path(scene.scene_id, "north")
        assert "north" not in scene.blocked_paths
    
    def test_scene_context(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        
        engine.set_scene_context(scene.scene_id, "enemy_level", 5)
        assert engine.get_scene_context(scene.scene_id, "enemy_level") == 5
        assert engine.get_scene_context(scene.scene_id, "nonexistent", "default") == "default"
    
    def test_unregister_scene(self):
        engine = SceneEngine()
        scene = engine.create_scene(name="Test Scene")
        scene_id = scene.scene_id
        
        result = engine.unregister_scene(scene_id)
        assert result is True
        assert engine.get_scene(scene_id) is None


class TestSceneTriggers:
    """Tests for scene trigger evaluation."""
    
    def test_location_trigger(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
        )
        
        scene = engine.create_scene(
            name="Forest Scene",
            location_id="forest",
            triggers=[trigger],
        )
        
        game_state = {
            "player_location": "forest",
        }
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered) == 1
        assert triggered[0].trigger_id == "trig_1"
    
    def test_time_trigger(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.TIME,
            conditions={"period": "子时"},
        )
        
        engine.create_scene(name="Night Scene", triggers=[trigger])
        
        game_state = {
            "world_time": {"period": "子时"},
        }
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered) == 1
    
    def test_quest_trigger(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.QUEST,
            conditions={"quest_id": "quest_1", "status": "completed"},
        )
        
        engine.create_scene(name="Quest Complete Scene", triggers=[trigger])
        
        game_state = {
            "quest_states": {
                "quest_1": {"status": "completed"},
            },
        }
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered) == 1
    
    def test_npc_state_trigger(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.NPC_STATE,
            conditions={"npc_id": "npc_1", "mood": "hostile"},
        )
        
        engine.create_scene(name="NPC Hostile Scene", triggers=[trigger])
        
        game_state = {
            "npc_states": {
                "npc_1": {"mood": "hostile"},
            },
        }
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered) == 1
    
    def test_trigger_once_only(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            once_only=True,
        )
        
        engine.create_scene(name="Forest Scene", triggers=[trigger])
        
        game_state = {"player_location": "forest"}
        
        triggered1 = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered1) == 1
        
        triggered2 = engine.evaluate_triggers(game_state, current_turn=2)
        assert len(triggered2) == 0
    
    def test_trigger_cooldown(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            once_only=False,
            cooldown_turns=3,
        )
        
        engine.create_scene(name="Forest Scene", triggers=[trigger])
        
        game_state = {"player_location": "forest"}
        
        triggered1 = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered1) == 1
        
        triggered2 = engine.evaluate_triggers(game_state, current_turn=2)
        assert len(triggered2) == 0
        
        triggered3 = engine.evaluate_triggers(game_state, current_turn=4)
        assert len(triggered3) == 1
    
    def test_trigger_disabled(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            enabled=False,
        )
        
        engine.create_scene(name="Forest Scene", triggers=[trigger])
        
        game_state = {"player_location": "forest"}
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered) == 0
    
    def test_trigger_priority(self):
        engine = SceneEngine()
        
        trigger1 = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            priority=1.0,
        )
        
        trigger2 = SceneTrigger(
            trigger_id="trig_2",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            priority=2.0,
        )
        
        engine.create_scene(name="Scene 1", triggers=[trigger1])
        engine.create_scene(name="Scene 2", triggers=[trigger2])
        
        game_state = {"player_location": "forest"}
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered) == 2
        assert triggered[0].trigger_id == "trig_2"
    
    def test_scripted_trigger(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.SCRIPTED,
            conditions={"should_trigger": True},
        )
        
        engine.create_scene(name="Scripted Scene", triggers=[trigger])
        
        game_state = {}
        
        triggered = engine.evaluate_triggers(game_state, current_turn=1)
        assert len(triggered) == 1
    
    def test_trigger_history(self):
        engine = SceneEngine()
        
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
        )
        
        scene = engine.create_scene(name="Forest Scene", triggers=[trigger])
        
        game_state = {"player_location": "forest"}
        engine.evaluate_triggers(game_state, current_turn=1)
        
        history = engine.get_trigger_history()
        assert len(history) == 1
        assert history[0]["trigger_id"] == "trig_1"
        assert history[0]["scene_id"] == scene.scene_id


class TestSceneSerialization:
    """Tests for scene serialization."""
    
    def test_scene_to_dict(self):
        scene = Scene(
            scene_id="scene_1",
            name="Test Scene",
            location_id="forest",
            state=SceneState.ACTIVE,
        )
        
        data = scene.to_dict()
        assert data["scene_id"] == "scene_1"
        assert data["name"] == "Test Scene"
        assert data["location_id"] == "forest"
        assert data["state"] == "active"
    
    def test_trigger_to_dict(self):
        trigger = SceneTrigger(
            trigger_id="trig_1",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
            priority=1.5,
        )
        
        data = trigger.to_dict()
        assert data["trigger_id"] == "trig_1"
        assert data["trigger_type"] == "location"
        assert data["conditions"]["location_id"] == "forest"
        assert data["priority"] == 1.5

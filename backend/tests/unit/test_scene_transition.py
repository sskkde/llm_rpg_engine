"""
Unit tests for SceneTransitionResolver.

Tests scene transitions, scene instances, and blocked paths.
"""

from datetime import datetime

from llm_rpg.engines.scene_transition import (
    SceneTransitionResolver,
    SceneInstance,
    TransitionResult,
)
from llm_rpg.engines.scene_engine import (
    SceneEngine,
    Scene,
    SceneTrigger,
    TriggerType,
)


class TestSceneInstance:
    """Tests for SceneInstance dataclass."""

    def test_scene_instance_creation(self):
        instance = SceneInstance(
            instance_id="instance_001",
            scene_id="scene_forest",
            location_id="forest",
            blocked_paths=["north", "east"],
        )
        
        assert instance.instance_id == "instance_001"
        assert instance.scene_id == "scene_forest"
        assert instance.location_id == "forest"
        assert instance.active is True
        assert "north" in instance.blocked_paths
        assert "east" in instance.blocked_paths

    def test_scene_instance_to_dict(self):
        instance = SceneInstance(
            instance_id="instance_001",
            scene_id="scene_forest",
            location_id="forest",
            blocked_paths=["north"],
            context={"difficulty": "hard"},
        )
        
        data = instance.to_dict()
        assert data["instance_id"] == "instance_001"
        assert data["scene_id"] == "scene_forest"
        assert data["location_id"] == "forest"
        assert data["active"] is True
        assert data["blocked_paths"] == ["north"]
        assert data["context"]["difficulty"] == "hard"


class TestSceneTransitionResolver:
    """Tests for SceneTransitionResolver."""

    def test_resolver_initialization(self):
        resolver = SceneTransitionResolver()
        assert resolver is not None
        assert len(resolver.get_active_instances()) == 0

    def test_create_scene_instance(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
            blocked_paths=["north", "east"],
        )
        
        assert instance is not None
        assert instance.scene_id == "scene_forest"
        assert instance.location_id == "forest"
        assert instance.instance_id.startswith("instance_")
        assert "north" in instance.blocked_paths
        assert "east" in instance.blocked_paths

    def test_get_scene_instance(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
        )
        
        retrieved = resolver.get_scene_instance(instance.instance_id)
        assert retrieved is not None
        assert retrieved.scene_id == "scene_forest"

    def test_get_scene_instance_not_found(self):
        resolver = SceneTransitionResolver()
        assert resolver.get_scene_instance("nonexistent") is None

    def test_get_instances_at_location(self):
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_forest_1",
            location_id="forest",
        )
        resolver.create_scene_instance(
            scene_id="scene_forest_2",
            location_id="forest",
        )
        resolver.create_scene_instance(
            scene_id="scene_cave",
            location_id="cave",
        )
        
        forest_instances = resolver.get_instances_at_location("forest")
        assert len(forest_instances) == 2
        
        cave_instances = resolver.get_instances_at_location("cave")
        assert len(cave_instances) == 1

    def test_deactivate_scene_instance(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
            blocked_paths=["north"],
        )
        
        result = resolver.deactivate_scene_instance(instance.instance_id)
        assert result is True
        assert instance.active is False
        assert instance.deactivated_at is not None
        assert not resolver.is_path_blocked("north")

    def test_deactivate_scene_instance_not_found(self):
        resolver = SceneTransitionResolver()
        result = resolver.deactivate_scene_instance("nonexistent")
        assert result is False

    def test_remove_scene_instance(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
        )
        
        result = resolver.remove_scene_instance(instance.instance_id)
        assert result is True
        assert resolver.get_scene_instance(instance.instance_id) is None


class TestBlockedPaths:
    """Tests for blocked path management."""

    def test_blocked_path_on_instance_creation(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
            blocked_paths=["north", "to_cave"],
        )
        
        assert resolver.is_path_blocked("north")
        assert resolver.is_path_blocked("to_cave")
        assert not resolver.is_path_blocked("south")

    def test_get_blocking_instance(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            blocked_paths=["north"],
        )
        
        blocking = resolver.get_blocking_instance("north")
        assert blocking is not None
        assert blocking.scene_id == "scene_forest"

    def test_block_path_manually(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
        )
        
        resolver.block_path(instance.instance_id, "north")
        
        assert resolver.is_path_blocked("north")
        assert "north" in instance.blocked_paths

    def test_block_path_instance_not_found(self):
        resolver = SceneTransitionResolver()
        result = resolver.block_path("nonexistent", "north")
        assert result is False

    def test_unblock_path(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            blocked_paths=["north"],
        )
        
        assert resolver.is_path_blocked("north")
        
        result = resolver.unblock_path("north")
        assert result is True
        assert not resolver.is_path_blocked("north")
        assert "north" not in instance.blocked_paths

    def test_unblock_path_not_blocked(self):
        resolver = SceneTransitionResolver()
        result = resolver.unblock_path("north")
        assert result is False

    def test_blocked_paths_cleared_on_deactivation(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            blocked_paths=["north", "east"],
        )
        
        assert resolver.is_path_blocked("north")
        assert resolver.is_path_blocked("east")
        
        resolver.deactivate_scene_instance(instance.instance_id)
        
        assert not resolver.is_path_blocked("north")
        assert not resolver.is_path_blocked("east")

    def test_get_all_blocked_paths(self):
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_forest",
            blocked_paths=["north", "east"],
        )
        
        blocked = resolver.get_all_blocked_paths()
        assert "north" in blocked
        assert "east" in blocked
        assert blocked["north"] == instance.instance_id


class TestTransitionLogic:
    """Tests for scene transition logic."""

    def test_check_transition_blocked_path(self):
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_forest",
            blocked_paths=["to_cave"],
        )
        
        game_state = {"player_location": "forest"}
        result = resolver.check_transition(game_state, target_location="to_cave")
        
        assert not result.can_transition
        assert result.blocked_reason is not None
        assert "to_cave" in result.blocked_paths

    def test_check_transition_allowed(self):
        resolver = SceneTransitionResolver()
        
        game_state = {"player_location": "forest"}
        result = resolver.check_transition(game_state, target_location="plains")
        
        assert result.can_transition
        assert result.blocked_reason is None

    def test_can_move_to_blocked(self):
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
            blocked_paths=["to_cave"],
        )
        
        can_move, reason = resolver.can_move_to("forest", "to_cave", {})
        
        assert can_move is False
        assert reason is not None
        assert "blocked" in reason.lower()

    def test_can_move_to_allowed(self):
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_forest",
            location_id="forest",
            blocked_paths=["to_cave"],
        )
        
        can_move, reason = resolver.can_move_to("forest", "plains", {})
        
        assert can_move is True
        assert reason is None

    def test_resolve_transition_blocked(self):
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_forest",
            blocked_paths=["to_cave"],
        )
        
        game_state = {"player_location": "forest"}
        result, instance = resolver.resolve_transition(
            game_state,
            current_turn=1,
            target_location="to_cave",
        )
        
        assert result == TransitionResult.BLOCKED
        assert instance is None


class TestSceneEngineIntegration:
    """Tests for SceneEngine integration."""

    def test_resolve_transition_with_scene_engine(self):
        scene_engine = SceneEngine()
        resolver = SceneTransitionResolver(scene_engine)
        
        trigger = SceneTrigger(
            trigger_id="trig_forest",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
        )
        
        scene = scene_engine.create_scene(
            name="Forest Encounter",
            location_id="forest",
            triggers=[trigger],
        )
        
        game_state = {"player_location": "forest"}
        result, instance = resolver.resolve_transition(
            game_state,
            current_turn=1,
        )
        
        assert result == TransitionResult.SUCCESS
        assert instance is not None
        assert instance.scene_id == scene.scene_id

    def test_resolve_transition_no_trigger(self):
        scene_engine = SceneEngine()
        resolver = SceneTransitionResolver(scene_engine)
        
        game_state = {"player_location": "forest"}
        result, instance = resolver.resolve_transition(
            game_state,
            current_turn=1,
        )
        
        assert result == TransitionResult.NO_TRANSITION
        assert instance is None

    def test_set_scene_engine(self):
        resolver = SceneTransitionResolver()
        scene_engine = SceneEngine()
        
        resolver.set_scene_engine(scene_engine)
        
        assert resolver._scene_engine is scene_engine


class TestBlockedPathPreventsMovement:
    """Integration tests for blocked path preventing movement."""

    def test_blocked_path_prevents_movement(self):
        """
        Test that a blocked path prevents player movement.
        
        Given a scene instance with blocked_paths,
        When a player tries to move to a blocked location,
        Then the movement should be blocked.
        """
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_blocked_path",
            location_id="forest",
            blocked_paths=["to_cave", "north"],
        )
        
        assert resolver.is_path_blocked("to_cave")
        assert resolver.is_path_blocked("north")
        
        can_move_to_cave, reason_cave = resolver.can_move_to("forest", "to_cave", {})
        assert can_move_to_cave is False
        assert reason_cave is not None
        assert "blocked" in reason_cave.lower()
        
        can_move_north, _ = resolver.can_move_to("forest", "north", {})
        assert can_move_north is False
        
        can_move_south, reason_south = resolver.can_move_to("forest", "south", {})
        assert can_move_south is True
        assert reason_south is None

    def test_blocked_path_prevents_movement_via_check_transition(self):
        """
        Test that check_transition respects blocked paths.
        """
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_ambush",
            location_id="forest",
            blocked_paths=["exit", "to_village"],
        )
        
        game_state = {"player_location": "forest"}
        
        result_blocked = resolver.check_transition(game_state, target_location="exit")
        assert not result_blocked.can_transition
        assert "exit" in result_blocked.blocked_paths
        
        result_allowed = resolver.check_transition(game_state, target_location="to_mountain")
        assert result_allowed.can_transition

    def test_blocked_path_prevents_movement_after_scene_activation(self):
        """
        Test blocked paths work with full scene activation flow.
        """
        scene_engine = SceneEngine()
        resolver = SceneTransitionResolver(scene_engine)
        
        trigger = SceneTrigger(
            trigger_id="trig_ambush",
            trigger_type=TriggerType.LOCATION,
            conditions={"location_id": "forest"},
        )
        
        scene = Scene(
            scene_id="scene_ambush",
            name="Forest Ambush",
            location_id="forest",
            triggers=[trigger],
            blocked_paths=["north", "south", "east"],
        )
        scene_engine.register_scene(scene)
        
        game_state = {"player_location": "forest"}
        result, instance = resolver.resolve_transition(game_state, current_turn=1)
        
        assert result == TransitionResult.SUCCESS
        assert instance is not None
        
        assert resolver.is_path_blocked("north")
        assert resolver.is_path_blocked("south")
        assert resolver.is_path_blocked("east")
        assert not resolver.is_path_blocked("west")
        
        can_move_north, _ = resolver.can_move_to("forest", "north", {})
        assert can_move_north is False
        
        can_move_west, _ = resolver.can_move_to("forest", "west", {})
        assert can_move_west is True

    def test_blocked_path_cleared_when_scene_deactivated(self):
        """
        Test that blocked paths are cleared when scene instance is deactivated.
        """
        resolver = SceneTransitionResolver()
        
        instance = resolver.create_scene_instance(
            scene_id="scene_temp_block",
            blocked_paths=["bridge"],
        )
        
        assert resolver.is_path_blocked("bridge")
        
        resolver.deactivate_scene_instance(instance.instance_id)
        
        assert not resolver.is_path_blocked("bridge")
        
        can_move, reason = resolver.can_move_to("forest", "bridge", {})
        assert can_move is True
        assert reason is None


class TestResolverUtilities:
    """Tests for utility methods."""

    def test_clear_all(self):
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_1",
            blocked_paths=["north"],
        )
        resolver.create_scene_instance(
            scene_id="scene_2",
            blocked_paths=["south"],
        )
        
        assert len(resolver.get_active_instances()) == 2
        assert resolver.is_path_blocked("north")
        
        resolver.clear_all()
        
        assert len(resolver.get_active_instances()) == 0
        assert not resolver.is_path_blocked("north")
        assert not resolver.is_path_blocked("south")

    def test_get_stats(self):
        resolver = SceneTransitionResolver()
        
        resolver.create_scene_instance(
            scene_id="scene_1",
            location_id="forest",
            blocked_paths=["north"],
        )
        resolver.create_scene_instance(
            scene_id="scene_2",
            location_id="cave",
            blocked_paths=["south", "east"],
        )
        
        stats = resolver.get_stats()
        
        assert stats["total_instances"] == 2
        assert stats["active_instances"] == 2
        assert stats["blocked_paths_count"] == 3
        assert stats["locations_with_instances"] == 2

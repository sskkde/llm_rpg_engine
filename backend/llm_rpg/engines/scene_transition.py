"""
Scene Transition Resolver

Handles scene transitions based on trigger_conditions, creates scene_instances,
and manages blocked_paths to prevent movement through certain paths.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .scene_engine import SceneEngine


class TransitionResult(str, Enum):
    """Result of a scene transition attempt."""
    SUCCESS = "success"
    BLOCKED = "blocked"
    NO_TRANSITION = "no_transition"
    INVALID_SCENE = "invalid_scene"


@dataclass
class SceneInstance:
    """
    Represents an active instance of a scene in the game world.
    
    Scene instances are created when a scene is activated and track
    the runtime state of that scene occurrence.
    """
    instance_id: str
    scene_id: str
    location_id: str | None = None
    activated_at: datetime = field(default_factory=datetime.now)
    deactivated_at: datetime | None = None
    active: bool = True
    blocked_paths: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "scene_id": self.scene_id,
            "location_id": self.location_id,
            "activated_at": self.activated_at.isoformat(),
            "deactivated_at": self.deactivated_at.isoformat() if self.deactivated_at else None,
            "active": self.active,
            "blocked_paths": self.blocked_paths,
            "context": self.context,
        }


@dataclass
class TransitionCheckResult:
    """Result of checking if a transition is possible."""
    can_transition: bool
    target_scene_id: str | None = None
    blocked_reason: str | None = None
    blocked_paths: list[str] = field(default_factory=list)


class SceneTransitionResolver:
    """
    Resolves scene transitions and manages blocked paths.
    
    Responsibilities:
    - Evaluate trigger_conditions to determine scene transitions
    - Create scene_instances when scenes are activated
    - Track and enforce blocked_paths to prevent movement
    - Integrate with SceneEngine for scene lifecycle management
    
    Blocked paths prevent player movement through specific directions
    or to specific locations while a scene is active.
    """
    
    def __init__(self, scene_engine: "SceneEngine | None" = None):
        """
        Initialize the resolver.
        
        Args:
            scene_engine: Optional SceneEngine instance for scene management.
        """
        self._scene_engine: "SceneEngine | None" = scene_engine
        self._scene_instances: dict[str, SceneInstance] = {}
        self._location_instances: dict[str, list[str]] = {}
        self._global_blocked_paths: dict[str, str] = {}
    
    def set_scene_engine(self, scene_engine: "SceneEngine") -> None:
        """Set or update the SceneEngine reference."""
        self._scene_engine = scene_engine
    
    # -------------------------------------------------------------------------
    # Scene Instance Management
    # -------------------------------------------------------------------------
    
    def create_scene_instance(
        self,
        scene_id: str,
        location_id: str | None = None,
        blocked_paths: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> SceneInstance:
        """
        Create a new scene instance for an active scene.
        
        Args:
            scene_id: The scene ID to create an instance for.
            location_id: Optional location where the scene is active.
            blocked_paths: Paths blocked by this scene instance.
            context: Additional context for the scene instance.
            
        Returns:
            The created SceneInstance.
        """
        instance_id = f"instance_{uuid.uuid4().hex[:12]}"
        
        instance = SceneInstance(
            instance_id=instance_id,
            scene_id=scene_id,
            location_id=location_id,
            blocked_paths=blocked_paths or [],
            context=context or {},
        )
        
        self._scene_instances[instance_id] = instance
        
        if location_id:
            if location_id not in self._location_instances:
                self._location_instances[location_id] = []
            self._location_instances[location_id].append(instance_id)
        
        for path in instance.blocked_paths:
            self._global_blocked_paths[path] = instance_id
        
        return instance
    
    def get_scene_instance(self, instance_id: str) -> SceneInstance | None:
        """Get a scene instance by ID."""
        return self._scene_instances.get(instance_id)
    
    def get_instances_at_location(self, location_id: str) -> list[SceneInstance]:
        """Get all active scene instances at a location."""
        instance_ids = self._location_instances.get(location_id, [])
        return [
            self._scene_instances[iid] 
            for iid in instance_ids 
            if iid in self._scene_instances and self._scene_instances[iid].active
        ]
    
    def get_active_instances(self) -> list[SceneInstance]:
        """Get all active scene instances."""
        return [inst for inst in self._scene_instances.values() if inst.active]
    
    def deactivate_scene_instance(self, instance_id: str) -> bool:
        """
        Deactivate a scene instance.
        
        This removes blocked paths associated with the instance.
        
        Args:
            instance_id: The instance ID to deactivate.
            
        Returns:
            True if deactivated, False if not found.
        """
        instance = self._scene_instances.get(instance_id)
        if not instance:
            return False
        
        instance.active = False
        instance.deactivated_at = datetime.now()
        
        for path in instance.blocked_paths:
            if self._global_blocked_paths.get(path) == instance_id:
                del self._global_blocked_paths[path]
        
        return True
    
    def remove_scene_instance(self, instance_id: str) -> bool:
        """
        Remove a scene instance entirely.
        
        Args:
            instance_id: The instance ID to remove.
            
        Returns:
            True if removed, False if not found.
        """
        instance = self._scene_instances.get(instance_id)
        if not instance:
            return False
        
        self.deactivate_scene_instance(instance_id)
        
        del self._scene_instances[instance_id]
        
        if instance.location_id and instance.location_id in self._location_instances:
            if instance_id in self._location_instances[instance.location_id]:
                self._location_instances[instance.location_id].remove(instance_id)
        
        return True
    
    # -------------------------------------------------------------------------
    # Blocked Path Management
    # -------------------------------------------------------------------------
    
    def is_path_blocked(self, path: str) -> bool:
        """
        Check if a path is currently blocked.
        
        Args:
            path: The path to check (e.g., "north", "to_forest", "exit").
            
        Returns:
            True if the path is blocked, False otherwise.
        """
        return path in self._global_blocked_paths
    
    def get_blocking_instance(self, path: str) -> SceneInstance | None:
        """
        Get the scene instance blocking a path.
        
        Args:
            path: The path to check.
            
        Returns:
            The SceneInstance blocking the path, or None if not blocked.
        """
        instance_id = self._global_blocked_paths.get(path)
        if instance_id:
            return self._scene_instances.get(instance_id)
        return None
    
    def get_all_blocked_paths(self) -> dict[str, str]:
        """
        Get all currently blocked paths.
        
        Returns:
            Dict mapping blocked paths to their blocking instance IDs.
        """
        return self._global_blocked_paths.copy()
    
    def block_path(self, instance_id: str, path: str) -> bool:
        """
        Block a path for a scene instance.
        
        Args:
            instance_id: The scene instance ID.
            path: The path to block.
            
        Returns:
            True if blocked, False if instance not found.
        """
        instance = self._scene_instances.get(instance_id)
        if not instance:
            return False
        
        if path not in instance.blocked_paths:
            instance.blocked_paths.append(path)
        
        self._global_blocked_paths[path] = instance_id
        return True
    
    def unblock_path(self, path: str) -> bool:
        """
        Unblock a path.
        
        Args:
            path: The path to unblock.
            
        Returns:
            True if unblocked, False if not blocked.
        """
        if path not in self._global_blocked_paths:
            return False
        
        instance_id = self._global_blocked_paths[path]
        del self._global_blocked_paths[path]
        
        instance = self._scene_instances.get(instance_id)
        if instance and path in instance.blocked_paths:
            instance.blocked_paths.remove(path)
        
        return True
    
    # -------------------------------------------------------------------------
    # Scene Transition Logic
    # -------------------------------------------------------------------------
    
    def check_transition(
        self,
        game_state: dict[str, Any],
        target_location: str | None = None,
    ) -> TransitionCheckResult:
        """
        Check if a scene transition is possible.
        
        This evaluates trigger_conditions and blocked_paths to determine
        if the player can transition to a new scene or location.
        
        Args:
            game_state: Current game state including player location.
            target_location: Optional target location to check.
            
        Returns:
            TransitionCheckResult with transition details.
        """
        if target_location and self.is_path_blocked(target_location):
            blocking_instance = self.get_blocking_instance(target_location)
            return TransitionCheckResult(
                can_transition=False,
                blocked_reason=f"Path to '{target_location}' is blocked by scene: {blocking_instance.scene_id if blocking_instance else 'unknown'}",
                blocked_paths=[target_location],
            )
        
        if self._scene_engine:
            current_location = game_state.get("player_location")
            if current_location:
                location_instances = self.get_instances_at_location(current_location)
                for instance in location_instances:
                    for blocked_path in instance.blocked_paths:
                        if target_location and blocked_path == target_location:
                            return TransitionCheckResult(
                                can_transition=False,
                                target_scene_id=instance.scene_id,
                                blocked_reason=f"Path '{target_location}' is blocked by active scene",
                                blocked_paths=[target_location],
                            )
        
        return TransitionCheckResult(
            can_transition=True,
            target_scene_id=None,
        )
    
    def resolve_transition(
        self,
        game_state: dict[str, Any],
        current_turn: int,
        target_location: str | None = None,
    ) -> tuple[TransitionResult, SceneInstance | None]:
        """
        Resolve a scene transition based on trigger_conditions.
        
        This method:
        1. Checks if the transition is blocked
        2. Evaluates scene triggers via SceneEngine
        3. Creates scene_instances for activated scenes
        
        Args:
            game_state: Current game state.
            current_turn: Current turn number.
            target_location: Optional target location for movement.
            
        Returns:
            Tuple of (TransitionResult, optional SceneInstance if created).
        """
        transition_check = self.check_transition(game_state, target_location)
        
        if not transition_check.can_transition:
            return (TransitionResult.BLOCKED, None)
        
        if not self._scene_engine:
            return (TransitionResult.NO_TRANSITION, None)
        
        triggered = self._scene_engine.evaluate_triggers(game_state, current_turn)
        
        if not triggered:
            return (TransitionResult.NO_TRANSITION, None)
        
        top_trigger = triggered[0]
        
        for scene in self._scene_engine._scenes.values():
            if top_trigger in scene.triggers:
                scene_id = scene.scene_id
                break
        else:
            return (TransitionResult.NO_TRANSITION, None)
        
        success = self._scene_engine.activate_scene(scene_id)
        if not success:
            return (TransitionResult.INVALID_SCENE, None)
        
        scene = self._scene_engine.get_scene(scene_id)
        if not scene:
            return (TransitionResult.INVALID_SCENE, None)
        
        instance = self.create_scene_instance(
            scene_id=scene_id,
            location_id=scene.location_id,
            blocked_paths=scene.blocked_paths,
            context={
                "trigger_id": top_trigger.trigger_id,
                "trigger_type": top_trigger.trigger_type.value,
                "activated_turn": current_turn,
            },
        )
        
        return (TransitionResult.SUCCESS, instance)
    
    def can_move_to(
        self,
        from_location: str,
        to_location: str,
        game_state: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """
        Check if movement from one location to another is allowed.
        
        This checks both global blocked paths and location-specific
        scene instance blocked paths.
        
        Args:
            from_location: Current location.
            to_location: Target location.
            game_state: Current game state.
            
        Returns:
            Tuple of (can_move, blocked_reason).
        """
        if self.is_path_blocked(to_location):
            blocking = self.get_blocking_instance(to_location)
            reason = f"Path to '{to_location}' is blocked"
            if blocking:
                reason += f" by scene '{blocking.scene_id}'"
            return (False, reason)
        
        from_instances = self.get_instances_at_location(from_location)
        for instance in from_instances:
            if to_location in instance.blocked_paths:
                return (
                    False, 
                    f"Movement to '{to_location}' blocked by scene '{instance.scene_id}'"
                )
        
        return (True, None)
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def clear_all(self) -> None:
        """Clear all scene instances and blocked paths."""
        self._scene_instances.clear()
        self._location_instances.clear()
        self._global_blocked_paths.clear()
    
    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the resolver state."""
        return {
            "total_instances": len(self._scene_instances),
            "active_instances": len(self.get_active_instances()),
            "blocked_paths_count": len(self._global_blocked_paths),
            "locations_with_instances": len(self._location_instances),
        }

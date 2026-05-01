"""
Mode Controller

Manages game mode switching (exploration, combat, dialogue).
Handles mode transitions and validation.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime


class GameMode(str, Enum):
    """Game mode types."""
    EXPLORATION = "exploration"
    COMBAT = "combat"
    DIALOGUE = "dialogue"
    CUTSCENE = "cutscene"
    MENU = "menu"


class ModeTransitionError(Exception):
    """Raised when mode transition is invalid."""
    pass


@dataclass
class ModeState:
    """State for a specific game mode."""
    mode: GameMode
    entered_at: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)
    allowed_actions: List[str] = field(default_factory=list)
    blocked_actions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mode": self.mode.value,
            "entered_at": self.entered_at.isoformat(),
            "context": self.context,
            "allowed_actions": self.allowed_actions,
            "blocked_actions": self.blocked_actions,
        }


class ModeController:
    """
    Manages game mode transitions and state.
    
    Features:
    - Mode switching with validation
    - Mode-specific action filtering
    - Transition history
    - Context preservation
    """
    
    # Valid mode transitions
    VALID_TRANSITIONS: Dict[GameMode, List[GameMode]] = {
        GameMode.EXPLORATION: [GameMode.COMBAT, GameMode.DIALOGUE, GameMode.CUTSCENE, GameMode.MENU],
        GameMode.COMBAT: [GameMode.EXPLORATION, GameMode.DIALOGUE, GameMode.CUTSCENE],
        GameMode.DIALOGUE: [GameMode.EXPLORATION, GameMode.COMBAT, GameMode.CUTSCENE],
        GameMode.CUTSCENE: [GameMode.EXPLORATION, GameMode.COMBAT, GameMode.DIALOGUE],
        GameMode.MENU: [GameMode.EXPLORATION],
    }
    
    # Mode-specific action sets
    MODE_ACTIONS: Dict[GameMode, Dict[str, List[str]]] = {
        GameMode.EXPLORATION: {
            "allowed": ["move", "inspect", "talk", "use_item", "interact", "wait"],
            "blocked": [],
        },
        GameMode.COMBAT: {
            "allowed": ["attack", "defend", "use_skill", "use_item", "flee"],
            "blocked": ["move", "talk", "inspect"],
        },
        GameMode.DIALOGUE: {
            "allowed": ["say", "ask", "end_dialogue"],
            "blocked": ["move", "attack", "inspect", "use_item"],
        },
        GameMode.CUTSCENE: {
            "allowed": ["skip", "continue"],
            "blocked": ["move", "attack", "talk", "inspect", "use_item"],
        },
        GameMode.MENU: {
            "allowed": ["select", "back", "confirm"],
            "blocked": ["move", "attack", "talk", "inspect", "use_item"],
        },
    }
    
    def __init__(self):
        self._current_mode = GameMode.EXPLORATION
        self._mode_stack: List[ModeState] = []
        self._transition_history: List[Dict[str, Any]] = []
        self._mode_contexts: Dict[GameMode, Dict[str, Any]] = {
            mode: {} for mode in GameMode
        }
        self._transition_callbacks: Dict[tuple, List[Callable]] = {}
        self._max_history_size = 100
    
    def get_current_mode(self) -> GameMode:
        """Get current game mode."""
        return self._current_mode
    
    def get_current_state(self) -> ModeState:
        """Get current mode state."""
        if self._mode_stack:
            return self._mode_stack[-1]
        return ModeState(mode=self._current_mode)
    
    def can_transition_to(self, target_mode: GameMode) -> bool:
        """Check if transition to target mode is valid."""
        return target_mode in self.VALID_TRANSITIONS.get(self._current_mode, [])
    
    def transition_to(
        self,
        target_mode: GameMode,
        context: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> ModeState:
        """
        Transition to a new game mode.
        
        Args:
            target_mode: The mode to transition to
            context: Optional context to pass to new mode
            force: If True, bypass transition validation
            
        Returns:
            The new mode state
            
        Raises:
            ModeTransitionError: If transition is invalid and force=False
        """
        if not force and not self.can_transition_to(target_mode):
            raise ModeTransitionError(
                f"Invalid transition from {self._current_mode.value} to {target_mode.value}"
            )
        
        # Save current mode state
        if self._mode_stack:
            current_state = self._mode_stack[-1]
            self._mode_contexts[self._current_mode] = current_state.context
        
        # Record transition
        transition_record = {
            "from_mode": self._current_mode.value,
            "to_mode": target_mode.value,
            "timestamp": datetime.now().isoformat(),
            "forced": force,
            "context_keys": list(context.keys()) if context else [],
        }
        self._transition_history.append(transition_record)
        self._cleanup_history()
        
        # Execute transition callbacks
        transition_key = (self._current_mode, target_mode)
        if transition_key in self._transition_callbacks:
            for callback in self._transition_callbacks[transition_key]:
                callback(self._current_mode, target_mode, context)
        
        # Create new mode state
        actions = self.MODE_ACTIONS.get(target_mode, {"allowed": [], "blocked": []})
        new_state = ModeState(
            mode=target_mode,
            context=context or self._mode_contexts.get(target_mode, {}),
            allowed_actions=actions.get("allowed", []),
            blocked_actions=actions.get("blocked", []),
        )
        
        self._mode_stack.append(new_state)
        self._current_mode = target_mode
        
        return new_state
    
    def push_mode(self, mode: GameMode, context: Optional[Dict[str, Any]] = None) -> ModeState:
        """
        Push a new mode onto the stack (preserving current mode).
        
        Args:
            mode: The mode to push
            context: Optional context
            
        Returns:
            The new mode state
        """
        return self.transition_to(mode, context)
    
    def pop_mode(self) -> Optional[ModeState]:
        """
        Pop the current mode and return to previous.
        
        Returns:
            The restored mode state, or None if stack is empty
        """
        if not self._mode_stack:
            return None
        
        # Remove current mode
        self._mode_stack.pop()
        
        if self._mode_stack:
            # Restore previous mode
            previous_state = self._mode_stack[-1]
            self._current_mode = previous_state.mode
            return previous_state
        else:
            # Default to exploration
            self._current_mode = GameMode.EXPLORATION
            return ModeState(mode=GameMode.EXPLORATION)
    
    def is_action_allowed(self, action: str) -> bool:
        """Check if an action is allowed in current mode."""
        state = self.get_current_state()
        
        if state.blocked_actions and action in state.blocked_actions:
            return False
        
        if state.allowed_actions and action not in state.allowed_actions:
            return False
        
        return True
    
    def get_allowed_actions(self) -> List[str]:
        """Get list of allowed actions in current mode."""
        return self.get_current_state().allowed_actions
    
    def get_blocked_actions(self) -> List[str]:
        """Get list of blocked actions in current mode."""
        return self.get_current_state().blocked_actions
    
    def set_mode_context(self, key: str, value: Any) -> None:
        """Set a context value for current mode."""
        if self._mode_stack:
            self._mode_stack[-1].context[key] = value
        else:
            self._mode_contexts[self._current_mode][key] = value
    
    def get_mode_context(self, key: str, default: Any = None) -> Any:
        """Get a context value from current mode."""
        if self._mode_stack:
            return self._mode_stack[-1].context.get(key, default)
        return self._mode_contexts[self._current_mode].get(key, default)
    
    def get_full_context(self) -> Dict[str, Any]:
        """Get full context of current mode."""
        if self._mode_stack:
            return self._mode_stack[-1].context.copy()
        return self._mode_contexts[self._current_mode].copy()
    
    def register_transition_callback(
        self,
        from_mode: GameMode,
        to_mode: GameMode,
        callback: Callable
    ) -> None:
        """Register a callback for a specific mode transition."""
        key = (from_mode, to_mode)
        if key not in self._transition_callbacks:
            self._transition_callbacks[key] = []
        self._transition_callbacks[key].append(callback)
    
    def get_transition_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get mode transition history."""
        return self._transition_history[-limit:]
    
    def _cleanup_history(self) -> None:
        """Clean up old transition history."""
        if len(self._transition_history) > self._max_history_size:
            self._transition_history = self._transition_history[-self._max_history_size:]
    
    def reset(self) -> None:
        """Reset mode controller to initial state."""
        self._current_mode = GameMode.EXPLORATION
        self._mode_stack.clear()
        self._transition_history.clear()
        self._mode_contexts = {mode: {} for mode in GameMode}

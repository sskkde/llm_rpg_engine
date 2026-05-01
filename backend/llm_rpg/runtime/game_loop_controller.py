"""
Game Loop Controller

Manages the main game loop lifecycle.
Coordinates between different runtime components.
"""

import asyncio
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime


class LoopState(str, Enum):
    """Game loop states."""
    STOPPED = "stopped"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    SHUTTING_DOWN = "shutting_down"


class GameLoopError(Exception):
    """Raised when game loop encounters an error."""
    pass


@dataclass
class LoopTick:
    """Represents a single game loop tick."""
    tick_number: int
    timestamp: datetime
    delta_time: float
    game_id: str
    turn_index: int
    mode: str


class GameLoopController:
    """
    Manages the main game loop lifecycle.
    
    Coordinates between:
    - TurnOrchestrator (turn processing)
    - ModeController (mode switching)
    - TransactionManager (state management)
    - RetryController (fault tolerance)
    """
    
    def __init__(self):
        self._state = LoopState.STOPPED
        self._tick_number = 0
        self._last_tick_time: Optional[datetime] = None
        self._game_id: Optional[str] = None
        self._tick_rate = 1.0
        self._running = False
        self._tick_handlers: List[Callable[[LoopTick], None]] = []
        self._state_change_handlers: List[Callable[[LoopState, LoopState], None]] = []
        self._tick_history: List[LoopTick] = []
        self._max_history = 100
    
    def initialize(self, game_id: str, tick_rate: float = 1.0) -> None:
        """Initialize the game loop for a game session."""
        if self._state != LoopState.STOPPED:
            raise GameLoopError("Game loop already initialized")
        
        self._game_id = game_id
        self._tick_rate = tick_rate
        self._tick_number = 0
        self._last_tick_time = None
        self._tick_history.clear()
        self._set_state(LoopState.INITIALIZING)
    
    def start(self) -> None:
        """Start the game loop."""
        if self._state == LoopState.STOPPED:
            raise GameLoopError("Game loop not initialized")
        if self._state == LoopState.RUNNING:
            raise GameLoopError("Game loop already running")
        
        self._running = True
        self._set_state(LoopState.RUNNING)
        self._last_tick_time = datetime.now()
    
    def pause(self) -> None:
        """Pause the game loop."""
        if self._state != LoopState.RUNNING:
            raise GameLoopError("Cannot pause - game loop not running")
        
        self._set_state(LoopState.PAUSED)
    
    def resume(self) -> None:
        """Resume the game loop."""
        if self._state != LoopState.PAUSED:
            raise GameLoopError("Cannot resume - game loop not paused")
        
        self._last_tick_time = datetime.now()
        self._set_state(LoopState.RUNNING)
    
    def stop(self) -> None:
        """Stop the game loop."""
        if self._state == LoopState.STOPPED:
            return
        
        self._set_state(LoopState.SHUTTING_DOWN)
        self._running = False
        self._set_state(LoopState.STOPPED)
    
    def tick(self, mode: str, turn_index: int) -> LoopTick:
        """
        Execute a single game loop tick.
        
        Args:
            mode: Current game mode
            turn_index: Current turn index
            
        Returns:
            The tick information
        """
        now = datetime.now()
        
        if self._last_tick_time:
            delta = (now - self._last_tick_time).total_seconds()
        else:
            delta = 0.0
        
        self._tick_number += 1
        
        tick = LoopTick(
            tick_number=self._tick_number,
            timestamp=now,
            delta_time=delta,
            game_id=self._game_id or "",
            turn_index=turn_index,
            mode=mode,
        )
        
        self._last_tick_time = now
        self._tick_history.append(tick)
        self._cleanup_history()
        
        for handler in self._tick_handlers:
            handler(tick)
        
        return tick
    
    def get_state(self) -> LoopState:
        """Get current loop state."""
        return self._state
    
    def is_running(self) -> bool:
        """Check if loop is running."""
        return self._state == LoopState.RUNNING
    
    def is_paused(self) -> bool:
        """Check if loop is paused."""
        return self._state == LoopState.PAUSED
    
    def get_tick_number(self) -> int:
        """Get current tick number."""
        return self._tick_number
    
    def register_tick_handler(self, handler: Callable[[LoopTick], None]) -> None:
        """Register a handler to be called on each tick."""
        self._tick_handlers.append(handler)
    
    def unregister_tick_handler(self, handler: Callable[[LoopTick], None]) -> None:
        """Unregister a tick handler."""
        if handler in self._tick_handlers:
            self._tick_handlers.remove(handler)
    
    def register_state_change_handler(
        self, handler: Callable[[LoopState, LoopState], None]
    ) -> None:
        """Register a handler for state changes."""
        self._state_change_handlers.append(handler)
    
    def get_tick_history(self, limit: int = 50) -> List[LoopTick]:
        """Get tick history."""
        return self._tick_history[-limit:]
    
    def _set_state(self, new_state: LoopState) -> None:
        """Set loop state and notify handlers."""
        old_state = self._state
        self._state = new_state
        
        for handler in self._state_change_handlers:
            handler(old_state, new_state)
    
    def _cleanup_history(self) -> None:
        """Clean up old tick history."""
        if len(self._tick_history) > self._max_history:
            self._tick_history = self._tick_history[-self._max_history:]
    
    def reset(self) -> None:
        """Reset the game loop controller."""
        self.stop()
        self._tick_number = 0
        self._last_tick_time = None
        self._game_id = None
        self._tick_history.clear()
        self._tick_handlers.clear()
        self._state_change_handlers.clear()

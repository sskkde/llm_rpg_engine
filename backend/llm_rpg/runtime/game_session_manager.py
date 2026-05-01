"""
Game Session Manager

Manages game session lifecycle including creation, loading, saving, and cleanup.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SessionState(str, Enum):
    """Game session states."""
    CREATED = "created"
    LOADING = "loading"
    ACTIVE = "active"
    SAVING = "saving"
    PAUSED = "paused"
    ENDED = "ended"


class SessionError(Exception):
    """Raised when session operation fails."""
    pass


class GameSession:
    """Represents a game session."""
    
    def __init__(self, session_id: str, game_id: str, user_id: str, name: str = ""):
        self.session_id = session_id
        self.game_id = game_id
        self.user_id = user_id
        self.name = name or f"Session {session_id[:8]}"
        self.state = SessionState.CREATED
        self.created_at = datetime.now()
        self.last_active_at = datetime.now()
        self.current_turn = 0
        self.metadata: Dict[str, Any] = {}
        self.tags: List[str] = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary."""
        return {
            "session_id": self.session_id,
            "game_id": self.game_id,
            "user_id": self.user_id,
            "name": self.name,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
            "current_turn": self.current_turn,
            "metadata": self.metadata,
            "tags": self.tags,
        }


class GameSessionManager:
    """
    Manages game session lifecycle.
    
    Responsibilities:
    - Session creation
    - Session loading/saving
    - Session state tracking
    - Session cleanup
    """
    
    def __init__(self):
        self._sessions: Dict[str, GameSession] = {}
        self._user_sessions: Dict[str, List[str]] = {}
        self._game_sessions: Dict[str, List[str]] = {}
    
    def create_session(
        self,
        game_id: str,
        user_id: str,
        name: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> GameSession:
        """
        Create a new game session.
        
        Args:
            game_id: The game ID
            user_id: The user ID
            name: Optional session name
            metadata: Optional session metadata
            
        Returns:
            The created session
        """
        session_id = f"sess_{uuid.uuid4().hex[:16]}"
        session = GameSession(session_id, game_id, user_id, name)
        
        if metadata:
            session.metadata = metadata
        
        self._sessions[session_id] = session
        
        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = []
        self._user_sessions[user_id].append(session_id)
        
        if game_id not in self._game_sessions:
            self._game_sessions[game_id] = []
        self._game_sessions[game_id].append(session_id)
        
        return session
    
    def get_session(self, session_id: str) -> Optional[GameSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def load_session(self, session_id: str) -> GameSession:
        """
        Load a session for play.
        
        Args:
            session_id: The session ID to load
            
        Returns:
            The loaded session
            
        Raises:
            SessionError: If session not found
        """
        session = self._sessions.get(session_id)
        if not session:
            raise SessionError(f"Session not found: {session_id}")
        
        session.state = SessionState.LOADING
        session.state = SessionState.ACTIVE
        session.last_active_at = datetime.now()
        
        return session
    
    def save_session(self, session_id: str) -> bool:
        """
        Save a session.
        
        Args:
            session_id: The session ID to save
            
        Returns:
            True if saved successfully
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.state = SessionState.SAVING
        session.last_active_at = datetime.now()
        session.state = SessionState.ACTIVE
        
        return True
    
    def pause_session(self, session_id: str) -> bool:
        """Pause a session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        if session.state == SessionState.ACTIVE:
            session.state = SessionState.PAUSED
            return True
        return False
    
    def resume_session(self, session_id: str) -> bool:
        """Resume a paused session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        if session.state == SessionState.PAUSED:
            session.state = SessionState.ACTIVE
            session.last_active_at = datetime.now()
            return True
        return False
    
    def end_session(self, session_id: str) -> bool:
        """End a session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.state = SessionState.ENDED
        return True
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        del self._sessions[session_id]
        
        if session.user_id in self._user_sessions:
            if session_id in self._user_sessions[session.user_id]:
                self._user_sessions[session.user_id].remove(session_id)
        
        if session.game_id in self._game_sessions:
            if session_id in self._game_sessions[session.game_id]:
                self._game_sessions[session.game_id].remove(session_id)
        
        return True
    
    def update_turn(self, session_id: str, turn_index: int) -> bool:
        """Update the current turn for a session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.current_turn = turn_index
        session.last_active_at = datetime.now()
        return True
    
    def list_user_sessions(self, user_id: str) -> List[GameSession]:
        """List all sessions for a user."""
        session_ids = self._user_sessions.get(user_id, [])
        return [self._sessions[sid] for sid in session_ids if sid in self._sessions]
    
    def list_game_sessions(self, game_id: str) -> List[GameSession]:
        """List all sessions for a game."""
        session_ids = self._game_sessions.get(game_id, [])
        return [self._sessions[sid] for sid in session_ids if sid in self._sessions]
    
    def list_active_sessions(self) -> List[GameSession]:
        """List all active sessions."""
        return [
            session for session in self._sessions.values()
            if session.state == SessionState.ACTIVE
        ]
    
    def cleanup_inactive_sessions(self, max_age_hours: int = 24) -> int:
        """Clean up inactive sessions older than specified hours."""
        now = datetime.now()
        to_remove = []
        
        for session_id, session in self._sessions.items():
            age = (now - session.last_active_at).total_seconds() / 3600
            if age > max_age_hours and session.state != SessionState.ACTIVE:
                to_remove.append(session_id)
        
        for session_id in to_remove:
            self.delete_session(session_id)
        
        return len(to_remove)

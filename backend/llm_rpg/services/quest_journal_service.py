"""Quest Journal Service — player-visible quest state management.

Provides reveal/list/filter operations for the quest journal UI.
All operations are deterministic — no LLM calls.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from ..storage.models import SessionQuestStateModel
from ..storage.repositories import SessionQuestStateRepository


class QuestJournalService:
    """Service for managing player-visible quest states.

    Handles quest discovery/reveal mechanics and visibility filtering.
    Completed/failed quests are auto-promoted to 'discovered' visibility.
    """

    def __init__(self, db: DBSession):
        self._db = db
        self._repo = SessionQuestStateRepository(db)

    def reveal_quest(
        self,
        session_id: str,
        quest_template_id: str,
        source_event_id: Optional[str] = None,
        initial_step: Optional[int] = None,
    ) -> SessionQuestStateModel:
        """Set player_visibility='discovered' and revealed_at=now().

        Idempotent: if already discovered, returns existing state unchanged.
        Auto-promotes completed/failed quests to discovered visibility.

        Args:
            session_id: The game session ID
            quest_template_id: The quest template ID to reveal
            source_event_id: Optional event that triggered the reveal
            initial_step: Optional step number to set as last_revealed_step_no

        Returns:
            The updated SessionQuestStateModel

        Raises:
            ValueError: If quest state not found for session
        """
        quest_state = self._repo.get_by_session_and_quest(
            session_id, quest_template_id
        )

        if quest_state is None:
            raise ValueError(
                f"Quest state not found: session={session_id}, quest={quest_template_id}"
            )

        if quest_state.status in ("completed", "failed"):
            if quest_state.player_visibility != "discovered":
                quest_state.player_visibility = "discovered"
                if quest_state.revealed_at is None:
                    quest_state.revealed_at = datetime.now(timezone.utc)
                self._db.commit()
                self._db.refresh(quest_state)
            return quest_state

        if quest_state.player_visibility == "discovered":
            return quest_state

        quest_state.player_visibility = "discovered"
        quest_state.revealed_at = datetime.now(timezone.utc)

        if source_event_id is not None:
            quest_state.reveal_source_event_id = source_event_id

        if initial_step is not None:
            quest_state.last_revealed_step_no = initial_step

        self._db.commit()
        self._db.refresh(quest_state)

        return quest_state

    def reveal_objective(
        self,
        session_id: str,
        quest_template_id: str,
        step_no: int,
        source_event_id: Optional[str] = None,
    ) -> SessionQuestStateModel:
        """Update last_revealed_step_no to max(current, step_no).

        Also ensures player_visibility is 'discovered'.

        Args:
            session_id: The game session ID
            quest_template_id: The quest template ID
            step_no: The step number to reveal
            source_event_id: Optional event that triggered the reveal

        Returns:
            The updated SessionQuestStateModel

        Raises:
            ValueError: If quest state not found for session
        """
        quest_state = self._repo.get_by_session_and_quest(
            session_id, quest_template_id
        )

        if quest_state is None:
            raise ValueError(
                f"Quest state not found: session={session_id}, quest={quest_template_id}"
            )

        if quest_state.player_visibility != "discovered":
            quest_state.player_visibility = "discovered"
            quest_state.revealed_at = datetime.now(timezone.utc)

        current_revealed = quest_state.last_revealed_step_no or 0
        quest_state.last_revealed_step_no = max(current_revealed, step_no)

        if source_event_id is not None:
            quest_state.reveal_source_event_id = source_event_id

        self._db.commit()
        self._db.refresh(quest_state)

        return quest_state

    def list_visible_quests(
        self,
        session_id: str,
        status: Optional[str] = None,
    ) -> List[SessionQuestStateModel]:
        """Return quests where player_visibility != 'hidden'.

        Args:
            session_id: The game session ID
            status: Optional filter by quest status (active, completed, failed, etc.)

        Returns:
            List of visible SessionQuestStateModel objects
        """
        all_states = self._repo.get_by_session(session_id)

        visible = [
            qs for qs in all_states
            if qs.player_visibility != "hidden"
        ]

        if status is not None:
            visible = [qs for qs in visible if qs.status == status]

        return visible

    def get_visible_quest_detail(
        self,
        session_id: str,
        quest_template_id: str,
    ) -> Optional[SessionQuestStateModel]:
        """Return quest detail if player_visibility != 'hidden', else None.

        Args:
            session_id: The game session ID
            quest_template_id: The quest template ID

        Returns:
            SessionQuestStateModel if visible, None otherwise
        """
        quest_state = self._repo.get_by_session_and_quest(
            session_id, quest_template_id
        )

        if quest_state is None:
            return None

        if quest_state.player_visibility == "hidden":
            return None

        return quest_state

    def hide_quest(
        self,
        session_id: str,
        quest_template_id: str,
    ) -> SessionQuestStateModel:
        """Set player_visibility='hidden'. Admin/debug only.

        Args:
            session_id: The game session ID
            quest_template_id: The quest template ID to hide

        Returns:
            The updated SessionQuestStateModel

        Raises:
            ValueError: If quest state not found for session
        """
        quest_state = self._repo.get_by_session_and_quest(
            session_id, quest_template_id
        )

        if quest_state is None:
            raise ValueError(
                f"Quest state not found: session={session_id}, quest={quest_template_id}"
            )

        quest_state.player_visibility = "hidden"
        self._db.commit()
        self._db.refresh(quest_state)

        return quest_state

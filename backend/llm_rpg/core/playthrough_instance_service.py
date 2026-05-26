"""
Playthrough Instance service helpers.

Creates a PlaythroughInstance from a published StoryPackageVersion,
links it to a SessionModel, calls existing initialize_session_story_state,
and optionally creates a baseline snapshot when INSTANCE_SNAPSHOT_ENABLED=true.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session as DBSession

from ..core.feature_flags import instance_snapshot_enabled, story_package_instance_enabled
from ..storage.models import PlaythroughInstanceModel, StoryPackageVersionModel, SessionModel
from ..storage.repositories import (
    PlaythroughInstanceRepository,
    StoryPackageVersionRepository,
    SessionRepository,
)
from ..core.session_initialization import initialize_session_story_state


class PlaythroughInstanceError(Exception):
    """Raised when a playthrough instance operation fails."""

    def __init__(self, message: str, instance_id: Optional[str] = None):
        self.instance_id = instance_id
        super().__init__(message)


class InstantiateResult:
    """Result container for a successful instantiation."""

    def __init__(
        self,
        playthrough_instance_id: str,
        session_id: str,
        baseline_snapshot_id: Optional[str] = None,
    ):
        self.playthrough_instance_id = playthrough_instance_id
        self.session_id = session_id
        self.baseline_snapshot_id = baseline_snapshot_id


def create_playthrough_from_version(
    db: DBSession,
    version_id: str,
    user_id: Optional[str] = None,
    config_json: Optional[Dict[str, Any]] = None,
) -> InstantiateResult:
    """
    Instantiate a published StoryPackageVersion as a PlaythroughInstance.

    Steps:
    1. Validate the version is published.
    2. Create PlaythroughInstanceModel.
    3. Create SessionModel linked to the instance.
    4. Call initialize_session_story_state for baseline rows.
    5. Link session as root_session_id on the instance.
    6. If INSTANCE_SNAPSHOT_ENABLED=true, create a baseline snapshot.
    7. If baseline snapshot was created, set baseline_snapshot_id on instance.

    Args:
        db: SQLAlchemy session.
        version_id: ID of the published StoryPackageVersion.
        user_id: Optional user ID to own the instance and session.
        config_json: Optional runtime config for the instance.

    Returns:
        InstantiateResult with instance, session, and optional snapshot IDs.

    Raises:
        PlaythroughInstanceError: If version not found or not published.
    """
    spv_repo = StoryPackageVersionRepository(db)
    spv = spv_repo.get_by_id(version_id)

    if spv is None:
        raise PlaythroughInstanceError(
            f"Story package version not found: {version_id}",
        )

    if spv.status != "published":
        raise PlaythroughInstanceError(
            f"Cannot instantiate version in status '{spv.status}'; must be 'published'",
        )

    world_id = spv.world_id
    if world_id is None:
        raise PlaythroughInstanceError(
            f"Story package version {version_id} has no world_id; cannot instantiate",
        )

    # Create PlaythroughInstanceModel
    pi_repo = PlaythroughInstanceRepository(db)
    pi_data = {
        "story_package_version_id": version_id,
        "world_id": world_id,
        "user_id": user_id,
        "config_json": config_json or {},
        "instance_status": "active",
    }
    pi = pi_repo.create(pi_data)

    # Create SessionModel linked to the instance
    session_repo = SessionRepository(db)
    session_data = {
        "user_id": user_id or "system",
        "world_id": world_id,
        "status": "active",
        "playthrough_instance_id": pi.id,
        "story_package_version_id": version_id,
        "session_type": "instance",
        "runtime_status": "running",
    }
    session = session_repo.create(session_data)

    # Link session as root_session_id on the instance
    pi_repo.update(pi.id, {"root_session_id": session.id})

    # Initialize baseline story state rows (idempotent)
    initialize_session_story_state(db, session.id)

    # Baseline snapshot: only when INSTANCE_SNAPSHOT_ENABLED=true
    baseline_snapshot_id = None
    if instance_snapshot_enabled():
        from ..core.instance_snapshot_service import create_baseline_snapshot
        baseline_snap = create_baseline_snapshot(
            db,
            playthrough_instance_id=pi.id,
            session_id=session.id,
        )
        baseline_snapshot_id = baseline_snap.id

        # Set baseline_snapshot_id and current_snapshot_id on instance
        pi_repo.update(pi.id, {
            "baseline_snapshot_id": baseline_snapshot_id,
            "current_snapshot_id": baseline_snapshot_id,
        })

        # Set entry_snapshot_id on session
        session_repo.update(session.id, {
            "entry_snapshot_id": baseline_snapshot_id,
        })

    return InstantiateResult(
        playthrough_instance_id=pi.id,
        session_id=session.id,
        baseline_snapshot_id=baseline_snapshot_id,
    )
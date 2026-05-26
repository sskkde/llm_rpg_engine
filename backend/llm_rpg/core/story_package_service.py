"""
Story Package Version service helpers.

Provides create, get, publish, and content-pack bridge operations for
StoryPackageVersionModel. All operations are additive and feature-flag
safe — existing save/session flows are unaffected.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from ..storage.models import StoryPackageVersionModel
from ..storage.repositories import StoryPackageVersionRepository


class StoryPackageVersionError(Exception):
    """Raised when a story package version operation fails."""

    def __init__(self, message: str, version_id: Optional[str] = None):
        self.version_id = version_id
        super().__init__(message)


def create_story_package_version(
    db: DBSession,
    story_package_id: str,
    version: str,
    world_id: Optional[str] = None,
    manifest_json: Optional[Dict[str, Any]] = None,
    editor_schema_version: Optional[str] = None,
    source_hash: Optional[str] = None,
) -> StoryPackageVersionModel:
    """
    Create a new draft StoryPackageVersion.

    Args:
        db: SQLAlchemy session.
        story_package_id: Logical package identifier.
        version: Semantic version string (e.g. "1.0.0").
        world_id: Optional FK to the world this version targets.
        manifest_json: Optional manifest payload.
        editor_schema_version: Optional editor schema version tag.
        source_hash: Optional hash of source content for dedup.

    Returns:
        The newly created StoryPackageVersionModel (status="draft").

    Raises:
        StoryPackageVersionError: If a version with the same
            story_package_id + version already exists.
    """
    repo = StoryPackageVersionRepository(db)

    existing = repo.get_by_story_package_and_version(story_package_id, version)
    if existing is not None:
        raise StoryPackageVersionError(
            f"Version {story_package_id}/{version} already exists",
            version_id=existing.id,
        )

    data = {
        "story_package_id": story_package_id,
        "version": version,
        "status": "draft",
        "world_id": world_id,
        "manifest_json": manifest_json or {},
        "editor_schema_version": editor_schema_version,
        "source_hash": source_hash,
    }
    return repo.create(data)


def get_story_package_version(
    db: DBSession,
    version_id: str,
) -> Optional[StoryPackageVersionModel]:
    """
    Retrieve a StoryPackageVersion by ID.

    Returns None if not found.
    """
    repo = StoryPackageVersionRepository(db)
    return repo.get_by_id(version_id)


def get_published_version(
    db: DBSession,
    story_package_id: str,
) -> Optional[StoryPackageVersionModel]:
    """
    Retrieve the latest published version for a package.

    Returns None if no published version exists.
    """
    repo = StoryPackageVersionRepository(db)
    return repo.get_latest_published(story_package_id)


def publish_story_package_version(
    db: DBSession,
    version_id: str,
) -> StoryPackageVersionModel:
    """
    Publish a draft StoryPackageVersion.

    Sets status to "published" and published_at to now.

    Args:
        db: SQLAlchemy session.
        version_id: ID of the version to publish.

    Returns:
        The updated StoryPackageVersionModel.

    Raises:
        StoryPackageVersionError: If version not found or not in draft status.
    """
    repo = StoryPackageVersionRepository(db)
    spv = repo.get_by_id(version_id)

    if spv is None:
        raise StoryPackageVersionError(
            f"Story package version not found: {version_id}",
            version_id=version_id,
        )

    if spv.status != "draft":
        raise StoryPackageVersionError(
            f"Cannot publish version in status '{spv.status}'; must be 'draft'",
            version_id=version_id,
        )

    update_data = {
        "status": "published",
        "published_at": datetime.now(),
    }
    return repo.update(version_id, update_data)


def build_manifest_snapshot_from_content_pack(
    pack_id: str,
    pack_name: str,
    pack_version: str,
    source_files: Optional[List[str]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a minimal manifest JSON payload from content-pack metadata.

    This does not import the pack — it only captures enough metadata
    to populate StoryPackageVersion.manifest_json for authoring/reference.

    Args:
        pack_id: Content pack logical ID.
        pack_name: Human-readable pack name.
        pack_version: Pack semantic version.
        source_files: Optional list of source YAML filenames.
        extra_metadata: Optional additional metadata dict.

    Returns:
        A manifest dict suitable for manifest_json.
    """
    manifest: Dict[str, Any] = {
        "pack_id": pack_id,
        "pack_name": pack_name,
        "pack_version": pack_version,
    }
    if source_files:
        manifest["source_files"] = source_files
    if extra_metadata:
        manifest["extra_metadata"] = extra_metadata
    return manifest


def build_manifest_from_content_pack_definition(
    pack: "ContentPackDefinition",
    source_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a full manifest JSON payload from a ContentPackDefinition.

    Captures pack id/version/name, source file refs, entity counts,
    and optional source_hash for dedup. Does not import the pack.

    Args:
        pack: A loaded ContentPackDefinition from the content loader.
        source_hash: Optional pre-computed hash of source YAML content.

    Returns:
        A manifest dict suitable for StoryPackageVersion.manifest_json.
    """
    manifest: Dict[str, Any] = {
        "pack_id": pack.manifest.id,
        "pack_name": pack.manifest.name,
        "pack_version": pack.manifest.version,
        "entity_counts": {
            "factions": len(pack.factions),
            "plot_beats": len(pack.plot_beats),
        },
    }

    if pack.file_refs is not None:
        source_files: Dict[str, List[str]] = {}
        for field_name in (
            "factions", "plot_beats", "npcs",
            "locations", "items", "quests",
        ):
            files = getattr(pack.file_refs, field_name, None)
            if files:
                source_files[field_name] = files
        if source_files:
            manifest["source_files"] = source_files

    if pack.metadata:
        manifest["pack_metadata"] = pack.metadata

    if source_hash:
        manifest["source_hash"] = source_hash

    return manifest


def compute_source_hash_from_pack_dir(pack_dir: Path) -> str:
    """
    Compute a deterministic SHA-256 hash from all YAML files in a pack dir.

    Reads each .yaml file, concatenates their contents in sorted filename
    order, and returns the hex digest. Useful for source_hash dedup.

    Args:
        pack_dir: Path to the content pack directory.

    Returns:
        SHA-256 hex digest string.
    """
    yaml_files = sorted(pack_dir.glob("*.yaml"))
    combined = ""
    for yaml_path in yaml_files:
        combined += yaml_path.read_text(encoding="utf-8")
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def create_version_from_content_pack(
    db: DBSession,
    pack_dir: Path,
    world_id: Optional[str] = None,
    editor_schema_version: Optional[str] = "1.0",
) -> StoryPackageVersionModel:
    """
    Create a draft StoryPackageVersion from a content-pack directory.

    Loads the pack, builds a manifest from its definition, computes a
    source hash, and creates a version row. Does not import any entities.

    Args:
        db: SQLAlchemy session.
        pack_dir: Path to the content pack directory.
        world_id: Optional FK to the world this version targets.
        editor_schema_version: Optional editor schema version tag.

    Returns:
        The newly created draft StoryPackageVersionModel.

    Raises:
        StoryPackageVersionError: If loading fails or version already exists.
    """
    from ..content.loader import load_content_pack, ContentPackLoadError

    try:
        pack = load_content_pack(pack_dir)
    except ContentPackLoadError as e:
        raise StoryPackageVersionError(
            f"Failed to load content pack: {e}",
        )

    source_hash = compute_source_hash_from_pack_dir(pack_dir)
    manifest = build_manifest_from_content_pack_definition(
        pack, source_hash=source_hash,
    )

    return create_story_package_version(
        db,
        story_package_id=pack.manifest.id,
        version=pack.manifest.version,
        world_id=world_id,
        manifest_json=manifest,
        editor_schema_version=editor_schema_version,
        source_hash=source_hash,
    )
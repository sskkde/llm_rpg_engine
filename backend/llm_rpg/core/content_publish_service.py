"""Atomic publishing and immutable loading for ``content_v1`` packs."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..content.compiler import CompiledBundle, compile_pack_v2, compute_runtime_hash
from ..content.loader_v2 import capture_pack_bytes, compute_source_hash, load_pack_v2
from ..content.validator_v2 import validate_pack_v2
from ..models.content_v2 import ContentV2Error
from ..storage.models import (
    ItemTemplateModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    StoryPackageVersionModel,
    WorldModel,
    generate_uuid,
)
from .turn_unit_of_work import TurnUnitOfWork


class ContentPublishError(Exception):
    def __init__(self, code: str, message: str, *, path: str = "") -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(f"{code}{f' at {path}' if path else ''}: {message}")


@dataclass(frozen=True)
class PublishDryRun:
    package_id: str
    pack_version: str
    source_hash: str
    runtime_hash: str
    bundle_schema_version: int
    engine_rules_version: int
    counts: Mapping[str, int]
    ref_map: Mapping[str, str]


@dataclass(frozen=True)
class PublishResult:
    version_id: str
    world_id: str
    runtime_hash: str
    source_hash: str
    created: bool


def _content_error(error: ContentV2Error) -> ContentPublishError:
    return ContentPublishError(error.code, error.message, path=error.path)


def _load_captured_pack(pack_dir: Path, files: Mapping[str, bytes]):
    """Parse a private copy of the one captured source snapshot.

    ``load_pack_v2`` owns its own capture API. Copying the captured bytes into a
    temporary directory lets it perform its normal strict parse without ever
    rereading a mutable authoring directory after its source hash was computed.
    """
    with tempfile.TemporaryDirectory(prefix="content-v1-captured-") as temp_dir:
        captured_dir = Path(temp_dir)
        for filename, content in files.items():
            (captured_dir / filename).write_bytes(content)
        try:
            return load_pack_v2(captured_dir)
        except ContentV2Error as error:
            raise _content_error(error) from error


def _counts(pack) -> dict[str, int]:
    return {
        "worlds": 1,
        "locations": len(pack.locations),
        "npcs": len(pack.characters),
        "items": len(pack.items),
        "quests": len(pack.quests),
        "routes": len(pack.routes),
        "rules": len(pack.rules),
        "schedules": len(pack.schedules),
        "goals": len(pack.goals),
        "recipes": len(pack.recipes),
        "knowledge_rules": len(pack.knowledge_rules),
        "plot_beats": len(pack.plot_beats),
        "factions": len(pack.factions),
    }


def _compile(pack, source_hash: str) -> CompiledBundle:
    issues = validate_pack_v2(pack)
    if issues:
        issue = issues[0]
        raise ContentPublishError(issue.code, issue.message, path=issue.path)
    try:
        return compile_pack_v2(pack, source_hash=source_hash)
    except ContentV2Error as error:
        raise _content_error(error) from error


def dry_run_content_pack(pack_dir: Path) -> PublishDryRun:
    """Validate and compile one captured pack snapshot without touching a DB."""
    try:
        files = capture_pack_bytes(Path(pack_dir))
        source_hash = compute_source_hash(files)
        pack = _load_captured_pack(Path(pack_dir), files)
    except ContentV2Error as error:
        raise _content_error(error) from error
    compiled = _compile(pack, source_hash)
    return PublishDryRun(
        package_id=pack.manifest.id,
        pack_version=pack.manifest.version,
        source_hash=source_hash,
        runtime_hash=compiled.runtime_hash,
        bundle_schema_version=compiled.bundle_schema_version,
        engine_rules_version=compiled.engine_rules_version,
        counts=MappingProxyType(_counts(pack)),
        ref_map=MappingProxyType(dict(compiled.ref_map)),
    )


def _stable_ref(package_id: str, object_id: str) -> str:
    return f"{package_id}/{object_id}"


def _mapped_id(
    kind: str,
    content_package_id: str,
    object_id: str,
    ref_map: Mapping[str, str],
    story_package_id: str,
    version: str,
) -> str:
    """Use compiler identity plus persisted version scope and an explicit kind prefix."""
    stable_ref = _stable_ref(content_package_id, object_id)
    mapped = ref_map.get(stable_ref)
    if mapped is None:
        raise ContentPublishError(
            "CONTENT_BINDING_MISMATCH",
            f"compiled reference map is missing {stable_ref!r}",
            path=stable_ref,
        )
    # The compiler ref UUID is deterministic for the authored pack version. The
    # length-prefixed SPV identity also covers publish-time version overrides;
    # the kind prefix makes cross-kind collisions impossible by construction.
    return (
        f"content-v1:{kind}:{mapped}:"
        f"{len(story_package_id)}:{story_package_id}:{len(version)}:{version}"
    )


def _location_order(locations: list[dict]) -> list[dict]:
    """Topologically order parent locations for immediate SQLite FK checks."""
    pending = {location["id"]: location for location in locations}
    resolved: set[str] = set()
    ordered: list[dict] = []
    while pending:
        ready = sorted(
            object_id
            for object_id, location in pending.items()
            if location.get("parent_id") is None or location["parent_id"] in resolved
        )
        if not ready:
            raise ContentPublishError(
                "CONTENT_DANGLING_REF",
                "location parent links contain a cycle",
                path="locations.parent_id",
            )
        for object_id in ready:
            ordered.append(pending.pop(object_id))
            resolved.add(object_id)
    return ordered


def _version_code(package_id: str, version: str) -> str:
    # Length-prefixing makes the package/version pair unambiguous and injective.
    return f"content-v1:{len(package_id)}:{package_id}:{len(version)}:{version}"


def _make_manifest(pack, source_hash: str, files: Mapping[str, bytes]) -> dict:
    file_fields = {
        "characters": "npcs",
        "locations": "locations",
        "items": "items",
        "quests": "quests",
        "factions": "factions",
        "plot_beats": "plot_beats",
    }
    source_files = {
        field: [f"{field_name}.yaml"]
        for field_name, field in file_fields.items()
        if f"{field_name}.yaml" in files
    }
    counts = _counts(pack)
    return {
        "pack_id": pack.manifest.id,
        "pack_name": pack.manifest.name,
        "pack_version": pack.manifest.version,
        "entity_counts": counts,
        "source_files": source_files,
        "source_hash": source_hash,
    }


def _check_existing_binding(db: Session, spv: StoryPackageVersionModel) -> str:
    if not spv.world_id:
        raise ContentPublishError(
            "CONTENT_BINDING_MISMATCH",
            "matching content version has no materialized world",
            path=spv.id,
        )
    world = db.get(WorldModel, spv.world_id)
    bound_worlds = db.query(WorldModel).filter_by(story_package_version_id=spv.id).all()
    profile = (world.ruleset_json or {}).get("content_profile") if world is not None else None
    if (
        world is None
        or world.story_package_version_id != spv.id
        or len(bound_worlds) != 1
        or bound_worlds[0].id != world.id
        or not isinstance(profile, dict)
        or profile.get("id") != "content_v1"
        or profile.get("runtime_hash") != spv.runtime_hash
    ):
        raise ContentPublishError(
            "CONTENT_BINDING_MISMATCH",
            "story package version and world are not bound bidirectionally",
            path=spv.id,
        )
    return world.id


def publish_content_pack_version(
    db: Session,
    *,
    pack_dir: Path,
    story_package_id: str | None = None,
    version: str | None = None,
    world_id: str | None = None,
) -> PublishResult:
    """Publish a v2 pack and its independent materialization atomically."""
    resolved_package_id: str | None = None
    resolved_version: str | None = None
    compiled: CompiledBundle | None = None
    deferred_error: ContentPublishError | None = None
    result: PublishResult | None = None
    try:
        with TurnUnitOfWork(db, guard_commits=True) as uow:
            files = capture_pack_bytes(Path(pack_dir))
            source_hash = compute_source_hash(files)
            pack = _load_captured_pack(Path(pack_dir), files)
            compiled = _compile(pack, source_hash)
            resolved_package_id = story_package_id or pack.manifest.id
            resolved_version = version or pack.manifest.version

            # Existing rows are serialized on databases supporting FOR UPDATE;
            # SQLite ignores the clause, with the unique key as its final arbiter.
            existing = db.execute(
                select(StoryPackageVersionModel)
                .where(
                    StoryPackageVersionModel.story_package_id == resolved_package_id,
                    StoryPackageVersionModel.version == resolved_version,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if existing is not None:
                if existing.runtime_hash != compiled.runtime_hash:
                    deferred_error = ContentPublishError(
                        "CONTENT_VERSION_CONFLICT",
                        f"{resolved_package_id}/{resolved_version} already exists with different content",
                        path=f"{resolved_package_id}/{resolved_version}",
                    )
                elif existing.runtime_bundle_json is None:
                    deferred_error = ContentPublishError(
                        "CONTENT_BUNDLE_MISSING",
                        "matching version row has no stored runtime bundle",
                        path=existing.id,
                    )
                else:
                    try:
                        stored_hash = compute_runtime_hash(existing.runtime_bundle_json)
                    except (TypeError, ValueError) as error:
                        deferred_error = ContentPublishError(
                            "CONTENT_HASH_MISMATCH",
                            f"stored runtime bundle cannot be hashed: {error}",
                            path=existing.id,
                        )
                    else:
                        if stored_hash != existing.runtime_hash:
                            deferred_error = ContentPublishError(
                                "CONTENT_HASH_MISMATCH",
                                "stored runtime bundle hash does not match existing version",
                                path=existing.id,
                            )
                    if deferred_error is None:
                        try:
                            bound_world_id = _check_existing_binding(db, existing)
                        except ContentPublishError as error:
                            deferred_error = error
                        else:
                            result = PublishResult(
                                version_id=existing.id,
                                world_id=bound_world_id,
                                runtime_hash=existing.runtime_hash,
                                source_hash=existing.source_hash or source_hash,
                                created=False,
                            )
            else:
                scoped_world_code = _version_code(resolved_package_id, resolved_version)
                if db.query(WorldModel).filter(WorldModel.code == scoped_world_code).first() is not None:
                    raise ContentPublishError(
                        "CONTENT_WORLD_ALREADY_BOUND",
                        "a world with this package/version code already exists without its version row",
                        path=scoped_world_code,
                    )
                new_world_id = world_id or generate_uuid()
                if db.get(WorldModel, new_world_id) is not None:
                    raise ContentPublishError(
                        "CONTENT_WORLD_ALREADY_BOUND",
                        "publisher will not reuse an existing world id",
                        path=new_world_id,
                    )

                spv = StoryPackageVersionModel(
                    id=generate_uuid(),
                    story_package_id=resolved_package_id,
                    version=resolved_version,
                    status="draft",
                    world_id=None,
                    manifest_json=_make_manifest(pack, source_hash, files),
                    editor_schema_version="content_v1",
                    source_hash=source_hash,
                    runtime_bundle_json=compiled.runtime_bundle,
                    runtime_hash=compiled.runtime_hash,
                    runtime_schema_version=compiled.bundle_schema_version,
                )
                db.add(spv)
                db.flush()

                world = WorldModel(
                    id=new_world_id,
                    code=scoped_world_code,
                    name=pack.world.name,
                    genre=pack.world.genre,
                    lore_summary=pack.world.lore_summary,
                    status=pack.world.status,
                    story_package_version_id=spv.id,
                    ruleset_json={
                        "content_profile": {
                            "id": "content_v1",
                            "schema_version": compiled.bundle_schema_version,
                            "engine_rules_version": compiled.engine_rules_version,
                            "runtime_hash": compiled.runtime_hash,
                        }
                    },
                )
                db.add(world)
                db.flush()
                spv.world_id = world.id

                package_id = pack.manifest.id
                runtime_bundle = compiled.runtime_bundle
                location_ids = {
                    item["id"]: _mapped_id("location", package_id, item["id"], compiled.ref_map, resolved_package_id, resolved_version)
                    for item in runtime_bundle["locations"]
                }
                character_ids = {
                    item["id"]: _mapped_id("npc", package_id, item["id"], compiled.ref_map, resolved_package_id, resolved_version)
                    for item in runtime_bundle["characters"]
                }
                item_ids = {
                    item["id"]: _mapped_id("item", package_id, item["id"], compiled.ref_map, resolved_package_id, resolved_version)
                    for item in runtime_bundle["items"]
                }
                quest_ids = {
                    item["id"]: _mapped_id("quest", package_id, item["id"], compiled.ref_map, resolved_package_id, resolved_version)
                    for item in runtime_bundle["quests"]
                }

                location_rows = []
                for definition in _location_order(runtime_bundle["locations"]):
                    parent_id = definition.get("parent_id")
                    location_rows.append(LocationModel(
                        id=location_ids[definition["id"]],
                        world_id=world.id,
                        code=definition["id"],
                        name=definition["name"],
                        description=definition.get("description", ""),
                        tags=definition.get("tags", []),
                        access_rules=definition.get("access_rules", {}),
                        parent_location_id=location_ids[parent_id] if parent_id else None,
                    ))
                db.add_all(location_rows)
                db.flush()

                for definition in runtime_bundle["characters"]:
                    db.add(NPCTemplateModel(
                        id=character_ids[definition["id"]],
                        world_id=world.id,
                        code=definition["id"],
                        name=definition["name"],
                        role_type="character",
                        public_identity=definition.get("public_identity", ""),
                        personality=definition.get("personality", ""),
                        background_bio=definition.get("description", ""),
                        initial_location_id=location_ids[definition["initial_location_id"]],
                    ))
                for definition in runtime_bundle["items"]:
                    db.add(ItemTemplateModel(
                        id=item_ids[definition["id"]],
                        world_id=world.id,
                        code=definition["id"],
                        name=definition["name"],
                        item_type=definition["item_type"],
                        description=definition.get("description", ""),
                        stackable_flag=False,
                        effects_json={},
                    ))
                for definition in runtime_bundle["quests"]:
                    db.add(QuestTemplateModel(
                        id=quest_ids[definition["id"]],
                        world_id=world.id,
                        code=definition["id"],
                        name=definition["name"],
                        quest_type="content_v1",
                        summary=definition.get("description", ""),
                        visibility="hidden",
                        step_conditions_json=[
                            {
                                "id": step["id"],
                                "location_id": location_ids[step["location_id"]],
                            }
                            for step in definition["steps"]
                        ],
                    ))
                db.flush()

                spv.status = "published"
                spv.published_at = datetime.now()
                db.flush()
                bound_worlds = db.execute(
                    select(WorldModel).where(WorldModel.story_package_version_id == spv.id)
                ).scalars().all()
                if (
                    spv.world_id != world.id
                    or world.story_package_version_id != spv.id
                    or len(bound_worlds) != 1
                    or bound_worlds[0].id != world.id
                ):
                    raise ContentPublishError(
                        "CONTENT_BINDING_MISMATCH",
                        "published version and materialized world binding is inconsistent",
                        path=spv.id,
                    )
                result = PublishResult(
                    version_id=spv.id,
                    world_id=world.id,
                    runtime_hash=compiled.runtime_hash,
                    source_hash=source_hash,
                    created=True,
                )

            # Matching-version validation is read-only. Defer its domain error
            # until after UoW exit so it cannot roll back the caller's transaction.
            if deferred_error is None:
                # Exactly one service-level commit; repository/direct commits inside
                # this managed scope have been reduced to flushes.
                uow.allow_commit()
                db.commit()
        if deferred_error is not None:
            raise deferred_error
        if result is None:
            raise RuntimeError("publish completed without a result")
        return result
    except IntegrityError as error:
        # The unique (story_package_id, version) constraint closes the gap when
        # concurrent transactions both observe no row before either insert.
        db.rollback()
        existing = None
        if resolved_package_id is not None and resolved_version is not None:
            existing = db.execute(
                select(StoryPackageVersionModel).where(
                    StoryPackageVersionModel.story_package_id == resolved_package_id,
                    StoryPackageVersionModel.version == resolved_version,
                )
            ).scalar_one_or_none()
        if existing is not None:
            if compiled is not None and existing.runtime_hash == compiled.runtime_hash:
                return PublishResult(
                    version_id=existing.id,
                    world_id=_check_existing_binding(db, existing),
                    runtime_hash=existing.runtime_hash,
                    source_hash=existing.source_hash or "",
                    created=False,
                )
            raise ContentPublishError(
                "CONTENT_VERSION_CONFLICT",
                f"{existing.story_package_id}/{existing.version} already exists with different content",
                path=f"{existing.story_package_id}/{existing.version}",
            ) from error
        raise
    except ContentV2Error as error:
        raise _content_error(error) from error


def load_published_bundle(db: Session, *, version_id: str) -> tuple[dict, str]:
    """Load and verify the immutable runtime artifact saved on an SPV row."""
    spv = db.get(StoryPackageVersionModel, version_id)
    if spv is None or spv.runtime_bundle_json is None:
        raise ContentPublishError(
            "CONTENT_BUNDLE_MISSING",
            f"runtime bundle is missing for version {version_id}",
            path=version_id,
        )
    if spv.status != "published":
        raise ContentPublishError(
            "CONTENT_VERSION_NOT_PUBLISHED",
            f"version {version_id} is not published",
            path=version_id,
        )
    try:
        actual_hash = compute_runtime_hash(spv.runtime_bundle_json)
    except (TypeError, ValueError) as error:
        raise ContentPublishError(
            "CONTENT_HASH_MISMATCH",
            f"stored runtime bundle cannot be hashed: {error}",
            path=version_id,
        ) from error
    if actual_hash != spv.runtime_hash:
        raise ContentPublishError(
            "CONTENT_HASH_MISMATCH",
            f"stored runtime bundle hash does not match version {version_id}",
            path=version_id,
        )
    return spv.runtime_bundle_json, spv.runtime_hash


def assert_version_content_mutable(db: Session, version_id: str) -> None:
    """Reject mutations to a version once it has been published.

    Read persisted state without autoflushing so a caller cannot first stage a
    status downgrade in the identity map and then use this guard to unfreeze it.
    ``published_at`` keeps the freeze in place if metadata later changes status.
    """
    with db.no_autoflush:
        persisted = (
            db.query(StoryPackageVersionModel.status, StoryPackageVersionModel.published_at)
            .filter(StoryPackageVersionModel.id == version_id)
            .one_or_none()
        )
    if persisted is not None and (
        persisted.status == "published" or persisted.published_at is not None
    ):
        raise ContentPublishError(
            "CONTENT_FROZEN_VERSION",
            f"published content version {version_id} is immutable",
            path=version_id,
        )


def assert_world_content_mutable(db: Session, world_id: str) -> None:
    """Apply the published-version freeze through the world's persisted binding."""
    with db.no_autoflush:
        version_id = (
            db.query(WorldModel.story_package_version_id)
            .filter(WorldModel.id == world_id)
            .scalar()
        )
    if version_id:
        assert_version_content_mutable(db, version_id)


def assert_template_content_mutable(db: Session, template: object) -> None:
    """Reject changes to a semantic template row belonging to a frozen world."""
    world_id = template if isinstance(template, str) else getattr(template, "world_id", None)
    if world_id:
        assert_world_content_mutable(db, world_id)


def assert_content_pack_mutable(db: Session, pack: object) -> None:
    """Guard every legacy semantic template the importer may upsert."""
    for collection_name in ("factions", "plot_beats"):
        for template in getattr(pack, collection_name, ()) or ():
            assert_template_content_mutable(db, template)

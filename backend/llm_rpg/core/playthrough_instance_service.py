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
from ..storage.models import (
    ItemTemplateModel,
    LocationModel,
    NPCTemplateModel,
    PlaythroughInstanceModel,
    QuestTemplateModel,
    SessionInventoryItemModel,
    ScheduledEventModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionStateModel,
    StoryPackageVersionModel,
    UserModel,
    WorldModel,
    generate_uuid,
)
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


def _world_templates_by_code(db: DBSession, model, world_id: str, section: str) -> dict[str, Any]:
    rows = db.query(model).filter(model.world_id == world_id).all()
    result = {row.code: row for row in rows}
    if len(result) != len(rows):
        from .content_publish_service import ContentPublishError

        raise ContentPublishError(
            "CONTENT_BINDING_MISMATCH",
            f"materialized {section} codes are not unique in world {world_id}",
            path=world_id,
        )
    return result


def _initialize_content_v1_state(
    db: DBSession,
    *,
    session_id: str,
    rules: Any,
    runtime_hash: str,
    engine_rules_version: int,
    locations_by_code: dict[str, LocationModel],
    npcs_by_code: dict[str, NPCTemplateModel],
    items_by_code: dict[str, ItemTemplateModel],
) -> None:
    """Persist a content_v1-only baseline and its finite initial schedule."""
    from ..models.content_v2 import CONTENT_PROFILE_ID
    from .content_runtime import (
        CONTENT_RUN_STATE_SCHEMA_VERSION,
        ContentRunState,
        decode_content_step_conditions,
        encode_content_step_conditions,
        is_content_conditions,
        merge_content_run_state,
        read_content_run_state,
    )
    from .content_publish_service import ContentPublishError

    initial_state = rules.initial_state()
    initial_steps = tuple(rules.initial_steps())
    player_location = initial_state.player_location_code
    if player_location not in locations_by_code:
        raise ContentPublishError(
            "CONTENT_BINDING_MISMATCH",
            f"initial player location {player_location!r} is not materialized",
            path=f"{session_id}.initial_state.player.location_id",
        )

    session_state = db.query(SessionStateModel).filter_by(session_id=session_id).one_or_none()
    existing_run_state = read_content_run_state(
        session_state.global_flags_json if session_state is not None else None,
        expected_binding_hash=runtime_hash,
    )
    is_new_run_state = existing_run_state is None
    if is_new_run_state:
        run_state = ContentRunState(
            schema_version=CONTENT_RUN_STATE_SCHEMA_VERSION,
            profile_id=CONTENT_PROFILE_ID,
            binding_hash=runtime_hash,
            engine_rules_version=engine_rules_version,
            logical_tick=initial_state.logical_tick,
            next_event_seq=0,
            rules_fired={},
            flags=dict(initial_state.flags),
            route_overrides=dict(initial_state.route_overrides),
            pending_steps=tuple(step.step_key for step in initial_steps),
        )
        global_flags = merge_content_run_state(
            session_state.global_flags_json if session_state is not None else None,
            run_state,
        )
        if session_state is None:
            session_state = SessionStateModel(
                id=generate_uuid(),
                session_id=session_id,
                current_time=f"tick:{initial_state.logical_tick}",
                time_phase="content_v1",
                current_location_id=locations_by_code[player_location].id,
                active_mode="exploration",
                global_flags_json=global_flags,
            )
            db.add(session_state)
        else:
            session_state.current_time = f"tick:{initial_state.logical_tick}"
            session_state.time_phase = "content_v1"
            session_state.current_location_id = locations_by_code[player_location].id
            session_state.global_flags_json = global_flags
    else:
        run_state = existing_run_state

    player_state = db.query(SessionPlayerStateModel).filter_by(session_id=session_id).one_or_none()
    if player_state is None:
        player_state = SessionPlayerStateModel(
            id=generate_uuid(),
            session_id=session_id,
            realm_stage="炼气一层",
            hp=100 if initial_state.player_alive else 0,
            max_hp=100,
            stamina=100,
            spirit_power=100,
            relation_bias_json={},
            conditions_json=[],
        )
        db.add(player_state)
    elif is_new_run_state:
        player_state.hp = 100 if initial_state.player_alive else 0

    npc_states = db.query(SessionNPCStateModel).filter_by(session_id=session_id).all()
    npc_states_by_template = {row.npc_template_id: row for row in npc_states}
    for code, template in npcs_by_code.items():
        location_code = initial_state.npc_positions.get(code)
        if location_code not in locations_by_code or code not in initial_state.npc_alive:
            raise ContentPublishError(
                "CONTENT_BINDING_MISMATCH",
                f"initial character state for {code!r} is incomplete or not materialized",
                path=f"{session_id}.characters.{code}",
            )
        state = npc_states_by_template.get(template.id)
        if state is None:
            state = SessionNPCStateModel(
                id=generate_uuid(),
                session_id=session_id,
                npc_template_id=template.id,
                current_location_id=locations_by_code[location_code].id,
                trust_score=50,
                suspicion_score=0,
                status_flags={"alive": initial_state.npc_alive[code]},
                short_memory_summary=None,
                hidden_plan_state=None,
            )
            db.add(state)
            npc_states_by_template[template.id] = state
        elif is_new_run_state:
            state.current_location_id = locations_by_code[location_code].id
            status_flags = dict(state.status_flags or {})
            status_flags["alive"] = initial_state.npc_alive[code]
            state.status_flags = status_flags

    for item_code, item in initial_state.item_instances.items():
        template = items_by_code.get(item_code)
        if template is None:
            raise ContentPublishError(
                "CONTENT_BINDING_MISMATCH",
                f"initial item {item_code!r} is not materialized",
                path=f"{session_id}.items.{item_code}",
            )
        existing_item = db.query(SessionInventoryItemModel).filter_by(
            session_id=session_id,
            instance_key=item_code,
        ).one_or_none()
        if existing_item is not None:
            continue
        if item.owner_type == "player":
            owner_ref_id = "player"
        elif item.owner_type == "location":
            if item.owner_ref not in locations_by_code:
                raise ContentPublishError(
                    "CONTENT_BINDING_MISMATCH",
                    f"initial item location {item.owner_ref!r} is not materialized",
                    path=f"{session_id}.items.{item_code}.owner",
                )
            owner_ref_id = locations_by_code[item.owner_ref].id
        elif item.owner_type == "character":
            npc_template = npcs_by_code.get(item.owner_ref)
            npc_state = npc_states_by_template.get(npc_template.id) if npc_template else None
            if npc_state is None:
                raise ContentPublishError(
                    "CONTENT_BINDING_MISMATCH",
                    f"initial item character {item.owner_ref!r} is not materialized",
                    path=f"{session_id}.items.{item_code}.owner",
                )
            owner_ref_id = npc_state.id
        else:
            raise ContentPublishError(
                "CONTENT_BINDING_MISMATCH",
                f"unsupported initial item owner type {item.owner_type!r}",
                path=f"{session_id}.items.{item_code}.owner",
            )
        db.add(SessionInventoryItemModel(
            id=generate_uuid(),
            session_id=session_id,
            item_template_id=template.id,
            owner_type=item.owner_type,
            owner_ref_id=owner_ref_id,
            quantity=item.quantity,
            instance_key=item_code,
        ))

    if is_new_run_state:
        existing_step_keys = set()
        for row in db.query(ScheduledEventModel).filter_by(session_id=session_id).all():
            if is_content_conditions(row.trigger_conditions_json):
                existing_step_keys.add(decode_content_step_conditions(row.trigger_conditions_json).step_key)
        for step in initial_steps:
            if step.step_key in existing_step_keys:
                continue
            db.add(ScheduledEventModel(
                id=generate_uuid(),
                session_id=session_id,
                event_template_id=None,
                trigger_time=None,
                trigger_conditions_json=encode_content_step_conditions(step),
                status="pending",
            ))


def create_content_v1_instance(
    db: DBSession,
    *,
    user_id: str,
    version_id: str,
    story_package_id: str | None = None,
    config_json: dict | None = None,
) -> dict:
    """Create an independent, transactionally initialized content_v1 instance."""
    from ..content.runtime_models import build_compiled_rules
    from .content_publish_service import ContentPublishError, load_published_bundle
    from .content_rules import CompiledContentRules
    from .turn_unit_of_work import TurnUnitOfWork

    with TurnUnitOfWork(db, guard_commits=True) as uow:
        bundle, runtime_hash = load_published_bundle(db, version_id=version_id)
        data = build_compiled_rules(bundle, binding_hash=runtime_hash)
        rules = CompiledContentRules(data)
        spv = db.get(StoryPackageVersionModel, version_id)
        if spv is None:  # load_published_bundle already checks; retain a closed guard.
            raise ContentPublishError("CONTENT_BUNDLE_MISSING", f"version {version_id} is missing", path=version_id)
        if story_package_id is not None and spv.story_package_id != story_package_id:
            raise ContentPublishError(
                "CONTENT_VERSION_PACKAGE_MISMATCH",
                f"version {version_id} does not belong to package {story_package_id!r}",
                path=version_id,
            )
        if not user_id or db.get(UserModel, user_id) is None:
            raise ContentPublishError(
                "CONTENT_BINDING_MISMATCH",
                f"instance owner {user_id!r} does not exist",
                path="user_id",
            )
        if not spv.world_id:
            raise ContentPublishError(
                "CONTENT_BINDING_MISMATCH",
                f"published version {version_id} has no world",
                path=version_id,
            )
        world = db.get(WorldModel, spv.world_id)
        profile = (world.ruleset_json or {}).get("content_profile") if world is not None else None
        bound_worlds = db.query(WorldModel).filter_by(story_package_version_id=version_id).all()
        if (
            world is None
            or world.story_package_version_id != spv.id
            or len(bound_worlds) != 1
            or bound_worlds[0].id != world.id
            or not isinstance(profile, dict)
            or profile.get("id") != "content_v1"
            or profile.get("runtime_hash") != runtime_hash
            or profile.get("schema_version") != spv.runtime_schema_version
        ):
            raise ContentPublishError(
                "CONTENT_BINDING_MISMATCH",
                f"world and published version {version_id} do not have a valid binding",
                path=version_id,
            )
        engine_rules_version = profile.get("engine_rules_version")
        bundle_schema_version = profile["schema_version"]

        locations_by_code = _world_templates_by_code(db, LocationModel, world.id, "locations")
        npcs_by_code = _world_templates_by_code(db, NPCTemplateModel, world.id, "characters")
        items_by_code = _world_templates_by_code(db, ItemTemplateModel, world.id, "items")
        quests_by_code = _world_templates_by_code(db, QuestTemplateModel, world.id, "quests")
        required_codes = (
            ("locations", set(locations_by_code), {item["id"] for item in bundle.get("locations", [])}),
            ("characters", set(npcs_by_code), {item["id"] for item in bundle.get("characters", [])}),
            ("items", set(items_by_code), {item["id"] for item in bundle.get("items", [])}),
            ("quests", set(quests_by_code), {item["id"] for item in bundle.get("quests", [])}),
        )
        for section, actual, expected in required_codes:
            if actual != expected:
                raise ContentPublishError(
                    "CONTENT_BINDING_MISMATCH",
                    f"materialized {section} do not match the published bundle",
                    path=f"{version_id}.{section}",
                )

        safe_config = dict(config_json or {})
        safe_config["__content_binding"] = {
            "runtime_hash": runtime_hash,
            "bundle_schema_version": bundle_schema_version,
            "engine_rules_version": engine_rules_version,
            "version_id": version_id,
        }
        pi = PlaythroughInstanceModel(
            id=generate_uuid(),
            story_package_version_id=version_id,
            world_id=world.id,
            user_id=user_id,
            config_json=safe_config,
            instance_status="active",
        )
        db.add(pi)
        db.flush()

        session = SessionModel(
            id=generate_uuid(),
            user_id=user_id,
            world_id=world.id,
            status="active",
            playthrough_instance_id=pi.id,
            story_package_version_id=version_id,
            session_type="instance",
            runtime_status="running",
        )
        db.add(session)
        db.flush()
        pi.root_session_id = session.id
        db.flush()

        _initialize_content_v1_state(
            db,
            session_id=session.id,
            rules=rules,
            runtime_hash=runtime_hash,
            engine_rules_version=engine_rules_version,
            locations_by_code=locations_by_code,
            npcs_by_code=npcs_by_code,
            items_by_code=items_by_code,
        )
        db.flush()

        if instance_snapshot_enabled():
            from .instance_snapshot_service import create_baseline_snapshot

            baseline_snapshot = create_baseline_snapshot(
                db,
                playthrough_instance_id=pi.id,
                session_id=session.id,
            )
            pi.baseline_snapshot_id = baseline_snapshot.id
            pi.current_snapshot_id = baseline_snapshot.id
            session.entry_snapshot_id = baseline_snapshot.id
            db.flush()

        result = {
            "instance_id": pi.id,
            "session_id": session.id,
            "world_id": world.id,
            "version_id": spv.id,
            "runtime_hash": runtime_hash,
        }
        uow.allow_commit()
        db.commit()
        return result
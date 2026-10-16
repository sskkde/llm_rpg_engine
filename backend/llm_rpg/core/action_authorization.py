"""Phase 2: reference and permission checks for LLM proposals.

This module turns a *validated contract* (``contract_version=2`` DTO) into a
:class:`AuthorizedAction`, or rejects it with a restricted-audit detail code.

Hard rules it enforces:

* A model may only reference stable IDs that this turn's context supplied. The
  engine never trusts a string that merely *looks* like an identifier.
* Identity namespaces are explicit: a session-state NPC id, an NPC template code
  and a location code are different kinds and are resolved by different lookups.
  They are never conflated by string similarity.
* The player's production actions carry an explicit ``PlayerPerspective`` built
  from this session's committed state, so a hidden/undiscovered location cannot
  be reached merely because the model guessed its id.
* Targets must exist, belong to this world/session, be present and alive, and be
  visible/interactive. Visibility is decided by the engine; the model cannot
  promote a private result into a public fact.
* Event and recommended-action references are bound to this turn; a reference id
  is not itself an execution grant.

The module produces pure data: it never writes to the database and never commits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..models.action_contract import (
    NPCActionV2,
    NPC_ACTION_ALIASES,
    PlayerIntentV2,
    SceneEventV2,
    WorldTickV2,
)
from ..models.perspectives import PlayerPerspective
from ..models.states import CanonicalState
from ..rules.action_schema import (
    ActionPermission,
    ActorRole,
    TimePolicy,
    normalize_production_action_type,
    resolve_production_permission,
)
from ..storage.models import LocationModel, SessionNPCStateModel
from ..storage.repositories import (
    LocationRepository,
    NPCTemplateRepository,
    SessionNPCStateRepository,
)
from .action_reason import ActionDetailCode, ActionReasonCode, public_reason_for_detail

#: Location tags / types that mark a place as concealed. A concealed place is
#: only reachable once the engine recorded a persistent discovery marker for it.
CONCEALED_LOCATION_TAGS = frozenset({"hidden", "secret", "concealed", "locked", "forbidden"})
CONCEALED_LOCATION_TYPES = frozenset({"hidden", "secret", "concealed"})

#: NPC status flags that make an NPC unavailable as a target.
UNAVAILABLE_NPC_STATUSES = frozenset({"dead", "missing", "gone", "removed"})


@dataclass(frozen=True)
class AuthorizedAction:
    """A pure-data, engine-checked authorization result.

    Carrying the resolved references here is what lets the resolution layer stop
    looking at model text: everything below has already been checked against the
    committed state and the current session.
    """

    actor_id: str
    actor_role: ActorRole
    action_type: str
    handler: str
    time_policy: TimePolicy
    # Resolved references
    target_location_id: Optional[str] = None
    target_location_code: Optional[str] = None
    target_npc_id: Optional[str] = None
    target_npc_template_id: Optional[str] = None
    target_npc_name: Optional[str] = None
    topic: Optional[str] = None
    utterance: Optional[str] = None
    visible_to_player: bool = True
    used_memory_ids: Tuple[str, ...] = ()
    referenced_event_ids: Tuple[str, ...] = ()
    recommended_actions: Tuple[str, ...] = ()
    display_hint: Optional[str] = None
    summary: Optional[str] = None
    visible_motivation: Optional[str] = None
    # Provenance for restricted audit (never returned to clients)
    provenance: Tuple[ActionDetailCode, ...] = ()
    permission: Optional[ActionPermission] = None

    @property
    def has_physical_effect(self) -> bool:
        """Whether this action can change authoritative state.

        Only the movement handler changes state in this phase; every other
        authorized action is speech, observation or waiting.
        """
        return self.handler == "player_move"


@dataclass(frozen=True)
class AuthorizationOutcome:
    """Outcome of authorizing one proposal."""

    action: Optional[AuthorizedAction] = None
    detail_code: Optional[ActionDetailCode] = None
    detail_message: str = ""

    @property
    def authorized(self) -> bool:
        """Whether an :class:`AuthorizedAction` was produced."""
        return self.action is not None

    @property
    def public_reason(self) -> Optional[ActionReasonCode]:
        """The coarse, non-disclosing public reason code (``None`` if authorized)."""
        if self.authorized:
            return None
        return public_reason_for_detail(self.detail_code) or ActionReasonCode.INVALID_PARAMS


def _reject(detail: ActionDetailCode, message: str = "") -> AuthorizationOutcome:
    return AuthorizationOutcome(detail_code=detail, detail_message=message)


@dataclass(frozen=True)
class AuthorizationContext:
    """Everything the authorizer may read. Built once per turn from committed state."""

    db: Session
    session_id: str
    world_id: str
    turn_no: int
    canonical_state: CanonicalState
    current_location_id: Optional[str] = None
    #: Session-state NPC ids the model was offered for this turn's context.
    visible_npc_ids: FrozenSet[str] = field(default_factory=frozenset)
    #: Memory ids actually supplied to this NPC decision (``None`` = none supplied).
    available_memory_ids: Optional[FrozenSet[str]] = None
    #: Engine event ids this turn may be referenced by world/scene proposals.
    allowed_event_ids: FrozenSet[str] = field(default_factory=frozenset)
    #: The engine's legal recommended actions for this turn.
    legal_recommended_actions: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Canonical keys and identity mapping
# ---------------------------------------------------------------------------


def location_canonical_key(location: LocationModel) -> str:
    """The key this location uses inside ``CanonicalState.location_states``."""
    return location.code or location.id


def npc_canonical_key(npc_template: Any) -> str:
    """The key this NPC uses inside ``CanonicalState.npc_states``."""
    return getattr(npc_template, "code", None) or npc_template.id


def public_map_location_keys(ctx: AuthorizationContext) -> FrozenSet[str]:
    """Keys of this world's *open* map locations.

    The compatibility rule for player movement is: the current location, the
    existing public map and persistent discovery markers are reachable; only a
    concealed location needs a discovery marker of its own. "Public/concealed" is
    decided by the location's own data (tags, type, declared discovery rules), never
    by model text, so a model can neither widen nor narrow the open map.
    """
    keys: set[str] = set()
    for location in LocationRepository(ctx.db).get_by_world(ctx.world_id):
        if _location_is_concealed(location):
            continue
        keys.add(location.id)
        canonical_key = location_canonical_key(location)
        if canonical_key:
            keys.add(canonical_key)
    return frozenset(keys)


def build_player_perspective(ctx: AuthorizationContext) -> PlayerPerspective:
    """Build the explicit player perspective for this session.

    ``discovered_locations`` is the union of the current location, this world's
    existing public map, the canonical ``LocationState.known_to_player`` markers and
    the persistent ``discovered_<key>`` player flags. Those are the only discovery
    sources; no new discovery DSL is introduced, and a concealed location stays
    absent until the engine records one of those markers for it.
    """
    discovered: List[str] = []
    if ctx.current_location_id:
        discovered.append(ctx.current_location_id)

    discovered.extend(public_map_location_keys(ctx))

    for key, loc_state in (ctx.canonical_state.location_states or {}).items():
        if getattr(loc_state, "known_to_player", False):
            discovered.append(key)
            if getattr(loc_state, "location_id", None):
                discovered.append(loc_state.location_id)

    flags = getattr(ctx.canonical_state.player_state, "flags", None) or {}
    for flag_key, flag_value in flags.items():
        if flag_value and flag_key.startswith("discovered_"):
            discovered.append(flag_key[len("discovered_"):])

    return PlayerPerspective(
        perspective_id=f"player:{ctx.session_id}",
        owner_id="player",
        discovered_locations=sorted(set(discovered)),
    )


def _discovered_keys(ctx: AuthorizationContext) -> FrozenSet[str]:
    return frozenset(build_player_perspective(ctx).discovered_locations)


def _location_is_concealed(location: LocationModel) -> bool:
    tags = {str(tag).lower() for tag in (location.tags or [])}
    if tags & CONCEALED_LOCATION_TAGS:
        return True
    location_type = (location.location_type or "").lower()
    if location_type in CONCEALED_LOCATION_TYPES:
        return True
    # A location that declares discovery rules is not part of the open map.
    return bool(location.discovery_rules_json)


def location_is_reachable(
    ctx: AuthorizationContext,
    location: LocationModel,
) -> Tuple[bool, Optional[ActionDetailCode]]:
    """Whether the player may select this location, and why not when they may not.

    Compatibility rule (plan section 3.3): the current location, the existing
    public map and persistent discovery markers are reachable; a concealed
    location is not reachable until the engine has recorded a discovery marker
    for it.
    """
    canonical_key = location_canonical_key(location)
    if ctx.current_location_id and ctx.current_location_id in (location.id, canonical_key):
        return True, None

    discovered = _discovered_keys(ctx)
    if location.id in discovered or canonical_key in discovered:
        return True, None

    if _location_is_concealed(location):
        return False, ActionDetailCode.LOCATION_NOT_DISCOVERED

    return True, None


def resolve_location_reference(
    ctx: AuthorizationContext,
    reference: str,
) -> Tuple[Optional[LocationModel], Optional[ActionDetailCode]]:
    """Resolve a location id-or-code inside this session's world.

    The reference is never matched by string similarity: an id is looked up as an
    id, a code as a code, and a world mismatch is reported as such.
    """
    if not reference:
        return None, ActionDetailCode.ENTITY_NOT_FOUND

    location_repo = LocationRepository(ctx.db)
    by_id = location_repo.get_by_id(reference)
    if by_id is not None:
        if by_id.world_id != ctx.world_id:
            return None, ActionDetailCode.ENTITY_WRONG_WORLD
        return by_id, None

    by_code = location_repo.get_by_code(ctx.world_id, reference)
    if by_code is not None:
        return by_code, None

    # The reference may be a code that exists in another world: report the world
    # mismatch explicitly rather than pretending the entity does not exist.
    for other in ctx.db.query(LocationModel).filter(LocationModel.code == reference).all():
        if other.world_id != ctx.world_id:
            return None, ActionDetailCode.ENTITY_WRONG_WORLD

    return None, ActionDetailCode.ENTITY_NOT_FOUND


def resolve_npc_reference(
    ctx: AuthorizationContext,
    reference: str,
) -> Tuple[Optional[SessionNPCStateModel], Optional[ActionDetailCode]]:
    """Resolve an NPC reference in the session-state id namespace.

    Only session-state ids are accepted here. An NPC template code is a different
    namespace and must go through :func:`resolve_npc_template_reference`; mixing
    the two would let a model address an NPC that is not in this session.
    """
    if not reference:
        return None, ActionDetailCode.ENTITY_NOT_FOUND

    npc_state_repo = SessionNPCStateRepository(ctx.db)
    row = npc_state_repo.get_by_id(reference)
    if row is None:
        return None, ActionDetailCode.ENTITY_NOT_FOUND
    if row.session_id != ctx.session_id:
        return None, ActionDetailCode.ENTITY_WRONG_SESSION
    return row, None


def resolve_npc_template_reference(
    ctx: AuthorizationContext,
    reference: str,
) -> Tuple[Optional[SessionNPCStateModel], Optional[ActionDetailCode]]:
    """Resolve an NPC template code/id to this session's NPC state row."""
    if not reference:
        return None, ActionDetailCode.ENTITY_NOT_FOUND

    template_repo = NPCTemplateRepository(ctx.db)
    template = template_repo.get_by_id(reference)
    if template is None:
        template = template_repo.get_by_code(ctx.world_id, reference)
    if template is None:
        return None, ActionDetailCode.ENTITY_NOT_FOUND
    if template.world_id != ctx.world_id:
        return None, ActionDetailCode.ENTITY_WRONG_WORLD

    row = SessionNPCStateRepository(ctx.db).get_by_session_and_npc(
        ctx.session_id, template.id
    )
    if row is None:
        return None, ActionDetailCode.ENTITY_WRONG_SESSION
    return row, None


def npc_is_available(
    ctx: AuthorizationContext,
    npc_state: SessionNPCStateModel,
) -> Tuple[bool, Optional[ActionDetailCode]]:
    """Whether an NPC state row may act or be addressed in this turn."""
    if npc_state.session_id != ctx.session_id:
        return False, ActionDetailCode.ENTITY_WRONG_SESSION

    status_flags = npc_state.status_flags or {}
    status = str(status_flags.get("status", "alive")).lower()
    if status in UNAVAILABLE_NPC_STATUSES:
        return False, ActionDetailCode.ENTITY_NOT_ALIVE

    return True, None


def npc_is_visible_to_player(
    ctx: AuthorizationContext,
    npc_state: SessionNPCStateModel,
) -> Tuple[bool, Optional[ActionDetailCode]]:
    """Whether the player may address this NPC: same scene, alive, engine-visible."""
    available, detail = npc_is_available(ctx, npc_state)
    if not available:
        return False, detail

    if not ctx.current_location_id or npc_state.current_location_id != ctx.current_location_id:
        return False, ActionDetailCode.ENTITY_NOT_PRESENT

    if npc_state.id not in ctx.visible_npc_ids:
        # Present in the session but not offered as visible this turn: the engine
        # decides visibility, so the reference is refused rather than promoted.
        return False, ActionDetailCode.ENTITY_NOT_VISIBLE

    return True, None


def resolve_npc_by_name(
    ctx: AuthorizationContext,
    name: str,
) -> Tuple[Optional[SessionNPCStateModel], Optional[ActionDetailCode]]:
    """Deterministically resolve a player-written NPC name within this session.

    Duplicate names are **not** resolved arbitrarily: an ambiguous name returns
    ``ENTITY_NOT_VISIBLE`` so the caller can ask the player to be specific instead
    of silently picking the first match.
    """
    needle = (name or "").strip()
    if not needle:
        return None, ActionDetailCode.ENTITY_NOT_FOUND

    template_repo = NPCTemplateRepository(ctx.db)
    matches: List[SessionNPCStateModel] = []
    for row in SessionNPCStateRepository(ctx.db).get_by_session(ctx.session_id):
        template = template_repo.get_by_id(row.npc_template_id)
        if template is None:
            continue
        candidates = {template.name, template.code}
        if needle in {str(candidate) for candidate in candidates if candidate}:
            matches.append(row)

    if not matches:
        return None, ActionDetailCode.ENTITY_NOT_FOUND
    if len(matches) > 1:
        return None, ActionDetailCode.ENTITY_NOT_VISIBLE
    return matches[0], None


# ---------------------------------------------------------------------------
# Authorization entry points
# ---------------------------------------------------------------------------


def _authorize_actor_action(
    ctx: AuthorizationContext,
    role: ActorRole,
    action_type: str,
    *,
    actor_id: str,
) -> Tuple[Optional[ActionPermission], Optional[AuthorizationOutcome]]:
    """Shared gate: the (role, action) pair must have a production grant."""
    permission = resolve_production_permission(role, action_type)
    if permission is None:
        return None, _reject(
            ActionDetailCode.ACTION_NOT_AUTHORIZED,
            f"no production grant for role={role.value} action={action_type!r}",
        )
    return permission, None


def authorize_player_intent(
    ctx: AuthorizationContext,
    contract: PlayerIntentV2,
) -> AuthorizationOutcome:
    """Authorize a production player intent."""
    intent = contract.intent
    raw_action_type = intent.action_type
    action_type = normalize_production_action_type(raw_action_type)

    permission, rejection = _authorize_actor_action(
        ctx, ActorRole.player, action_type, actor_id="player"
    )
    if rejection is not None:
        return rejection
    assert permission is not None

    if action_type == "move":
        reference = getattr(intent, "target_location_id", None)
        if reference is None:
            # A move without a target is an explicit ambiguity, handled by the
            # caller as a zero-time clarification rather than a rejection.
            return _reject(
                ActionDetailCode.MISSING_TARGET,
                "move intent without a target location",
            )
        location, detail = resolve_location_reference(ctx, reference)
        if location is None:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_FOUND, reference)
        reachable, detail = location_is_reachable(ctx, location)
        if not reachable:
            return _reject(detail or ActionDetailCode.LOCATION_NOT_DISCOVERED, reference)
        return AuthorizationOutcome(action=AuthorizedAction(
            actor_id="player",
            actor_role=ActorRole.player,
            action_type=action_type,
            handler=permission.handler,
            time_policy=permission.time_policy,
            target_location_id=location.id,
            target_location_code=location_canonical_key(location),
            provenance=(ActionDetailCode.DOMAIN_RULE_BLOCKED,),
            permission=permission,
        ))

    if action_type == "talk":
        reference = getattr(intent, "target_npc_id", None)
        topic = getattr(intent, "topic", None)
        if reference is None:
            # An untargeted talk is only an attempt facing the current scene.
            return AuthorizationOutcome(action=AuthorizedAction(
                actor_id="player",
                actor_role=ActorRole.player,
                action_type=action_type,
                handler=permission.handler,
                time_policy=permission.time_policy,
                topic=topic,
                permission=permission,
            ))
        row, detail = resolve_npc_reference(ctx, reference)
        if row is None:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_FOUND, reference)
        visible, detail = npc_is_visible_to_player(ctx, row)
        if not visible:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_VISIBLE, reference)
        return AuthorizationOutcome(action=AuthorizedAction(
            actor_id="player",
            actor_role=ActorRole.player,
            action_type=action_type,
            handler=permission.handler,
            time_policy=permission.time_policy,
            target_npc_id=row.id,
            target_npc_template_id=row.npc_template_id,
            topic=topic,
            permission=permission,
        ))

    if action_type == "inspect":
        reference = getattr(intent, "target_npc_id", None)
        if reference is None:
            return AuthorizationOutcome(action=AuthorizedAction(
                actor_id="player",
                actor_role=ActorRole.player,
                action_type=action_type,
                handler=permission.handler,
                time_policy=permission.time_policy,
                permission=permission,
            ))
        row, detail = resolve_npc_reference(ctx, reference)
        if row is None:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_FOUND, reference)
        visible, detail = npc_is_visible_to_player(ctx, row)
        if not visible:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_VISIBLE, reference)
        return AuthorizationOutcome(action=AuthorizedAction(
            actor_id="player",
            actor_role=ActorRole.player,
            action_type=action_type,
            handler=permission.handler,
            time_policy=permission.time_policy,
            target_npc_id=row.id,
            target_npc_template_id=row.npc_template_id,
            permission=permission,
        ))

    # idle: no business parameters at all
    return AuthorizationOutcome(action=AuthorizedAction(
        actor_id="player",
        actor_role=ActorRole.player,
        action_type=action_type,
        handler=permission.handler,
        time_policy=permission.time_policy,
        permission=permission,
    ))


def resolve_location_text_reference(
    ctx: AuthorizationContext,
    text: str,
) -> Tuple[Optional[LocationModel], Optional[ActionDetailCode]]:
    """Deterministically resolve player-written location text.

    The player's own words are the one place where a name or alias may be used, and
    the deterministic alias table resolves it in this world only. This is *not* a
    loosening for model output: a model may only reference the stable ids the
    context supplied.
    """
    from .movement_handler import _resolve_location_code

    candidate = (text or "").strip()
    if not candidate:
        return None, ActionDetailCode.ENTITY_NOT_FOUND

    code = _resolve_location_code(candidate)
    if code:
        location = LocationRepository(ctx.db).get_by_code(ctx.world_id, code)
        if location is not None:
            return location, None

    return resolve_location_reference(ctx, candidate)


def authorize_deterministic_player_intent(
    ctx: AuthorizationContext,
    action_type: str,
    target: Optional[str],
) -> AuthorizationOutcome:
    """Authorize a deterministically parsed player input.

    When no model contract is available, the deterministic parser is the only
    source of the action, and it must pass through *the same* authorization chain:
    no target or parameter from a rejected proposal may be reused, and an
    unsupported action must still answer unsupported.
    """
    canonical_action = normalize_production_action_type(action_type or "unknown")
    permission, rejection = _authorize_actor_action(
        ctx, ActorRole.player, canonical_action, actor_id="player"
    )
    if rejection is not None:
        return rejection
    assert permission is not None

    if canonical_action == "move":
        if not target:
            return _reject(
                ActionDetailCode.MISSING_TARGET,
                "move intent without a target location",
            )
        location, detail = resolve_location_text_reference(ctx, target)
        if location is None:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_FOUND, target)
        reachable, detail = location_is_reachable(ctx, location)
        if not reachable:
            return _reject(detail or ActionDetailCode.LOCATION_NOT_DISCOVERED, target)
        return AuthorizationOutcome(action=AuthorizedAction(
            actor_id="player",
            actor_role=ActorRole.player,
            action_type=canonical_action,
            handler=permission.handler,
            time_policy=permission.time_policy,
            target_location_id=location.id,
            target_location_code=location_canonical_key(location),
            provenance=(ActionDetailCode.ENTITY_NOT_FOUND,),
            permission=permission,
        ))

    if canonical_action in ("talk", "inspect"):
        if not target:
            return AuthorizationOutcome(action=AuthorizedAction(
                actor_id="player",
                actor_role=ActorRole.player,
                action_type=canonical_action,
                handler=permission.handler,
                time_policy=permission.time_policy,
                permission=permission,
            ))
        row, detail = resolve_npc_by_name(ctx, target)
        if row is None:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_FOUND, target)
        visible, detail = npc_is_visible_to_player(ctx, row)
        if not visible:
            return _reject(detail or ActionDetailCode.ENTITY_NOT_VISIBLE, target)
        return AuthorizationOutcome(action=AuthorizedAction(
            actor_id="player",
            actor_role=ActorRole.player,
            action_type=canonical_action,
            handler=permission.handler,
            time_policy=permission.time_policy,
            target_npc_id=row.id,
            target_npc_template_id=row.npc_template_id,
            permission=permission,
        ))

    # idle and any other authorized action without business parameters
    return AuthorizationOutcome(action=AuthorizedAction(
        actor_id="player",
        actor_role=ActorRole.player,
        action_type=canonical_action,
        handler=permission.handler,
        time_policy=permission.time_policy,
        permission=permission,
    ))


def authorize_npc_action(
    ctx: AuthorizationContext,
    contract: NPCActionV2,
    *,
    npc_id: str,
    npc_template_id: str,
    npc_name: Optional[str] = None,
) -> AuthorizationOutcome:
    """Authorize a production NPC action.

    The actor is bound by the server: ``npc_id``/``npc_template_id`` come from the
    stage's own iteration over the session's active NPCs, never from the wire.
    """
    raw_action_type = contract.action.action_type
    action_type = NPC_ACTION_ALIASES.get(raw_action_type, raw_action_type)

    permission, rejection = _authorize_actor_action(
        ctx, ActorRole.npc, action_type, actor_id=npc_id
    )
    if rejection is not None:
        return rejection
    assert permission is not None

    npc_state_repo = SessionNPCStateRepository(ctx.db)
    npc_state = npc_state_repo.get_by_id(npc_id)
    if npc_state is None:
        return _reject(ActionDetailCode.ACTOR_NOT_BOUND, npc_id)
    if npc_state.session_id != ctx.session_id:
        return _reject(ActionDetailCode.ENTITY_WRONG_SESSION, npc_id)
    if npc_state.npc_template_id != npc_template_id:
        # The stage's binding must match the persisted row; a mismatch means the
        # caller tried to act as a different identity.
        return _reject(ActionDetailCode.ACTOR_IMPERSONATION, npc_id)
    available, detail = npc_is_available(ctx, npc_state)
    if not available:
        return _reject(detail or ActionDetailCode.ENTITY_NOT_ALIVE, npc_id)

    # Memory references must be exactly the set the engine supplied this call.
    allowed_memory_ids = ctx.available_memory_ids or frozenset()
    used_memory_ids = tuple(contract.used_memory_ids or ())
    for memory_id in used_memory_ids:
        if memory_id not in allowed_memory_ids:
            return _reject(ActionDetailCode.MEMORY_ID_NOT_AVAILABLE, memory_id)

    target_id: Optional[str] = None
    target_template_id: Optional[str] = None
    target_name: Optional[str] = None
    wire_target = getattr(contract.action, "target_id", None)
    if wire_target:
        target_row, detail = resolve_npc_reference(ctx, wire_target)
        if target_row is None:
            # The NPC may be addressing the player rather than another NPC.
            if wire_target not in ("player", "player_self"):
                return _reject(detail or ActionDetailCode.ENTITY_NOT_FOUND, wire_target)
        else:
            target_available, detail = npc_is_available(ctx, target_row)
            if not target_available:
                return _reject(detail or ActionDetailCode.ENTITY_NOT_ALIVE, wire_target)
            # An NPC may only address someone who is actually in its scene: being in
            # the same session and alive is not enough (plan section 3.3 requires a
            # present, visible/interactive target).
            if (
                not npc_state.current_location_id
                or target_row.current_location_id != npc_state.current_location_id
            ):
                return _reject(ActionDetailCode.ENTITY_NOT_PRESENT, wire_target)
            target_id = target_row.id
            target_template_id = target_row.npc_template_id

    # Visibility ceiling is decided by the server and the wire can only *narrow* it.
    # Only co-located, alive NPCs reach this point (the stage iterates the session's
    # active NPCs at the current location), so the ceiling is "player visible"; a
    # model that answers visible_to_player=true can never widen it beyond that, and a
    # model that answers false only hides its own action.
    visibility_ceiling = bool(
        ctx.current_location_id
        and npc_state.current_location_id == ctx.current_location_id
    )
    visible_to_player = bool(contract.visible_to_player) and visibility_ceiling

    return AuthorizationOutcome(action=AuthorizedAction(
        actor_id=npc_id,
        actor_role=ActorRole.npc,
        action_type=action_type,
        handler=permission.handler,
        time_policy=permission.time_policy,
        target_npc_id=target_id,
        target_npc_template_id=target_template_id,
        target_npc_name=target_name or npc_name,
        utterance=getattr(contract.action, "utterance", None),
        visible_to_player=visible_to_player,
        used_memory_ids=used_memory_ids,
        summary=contract.summary,
        visible_motivation=contract.visible_motivation,
        permission=permission,
    ))


def authorize_world_tick(
    ctx: AuthorizationContext,
    contract: WorldTickV2,
) -> AuthorizationOutcome:
    """Authorize a world-stage proposal: reference-only, engine-bound."""
    referenced: List[str] = []
    for event_id in contract.referenced_event_ids or ():
        if event_id not in ctx.allowed_event_ids:
            return _reject(ActionDetailCode.EVENT_REFERENCE_FOREIGN, event_id)
        referenced.append(event_id)

    return AuthorizationOutcome(action=AuthorizedAction(
        actor_id="world_engine",
        actor_role=ActorRole.world,
        action_type="reference",
        handler="world_reference",
        time_policy=TimePolicy.NONE,
        referenced_event_ids=tuple(referenced),
        display_hint=contract.display_hint,
    ))


def authorize_scene_event(
    ctx: AuthorizationContext,
    contract: SceneEventV2,
) -> AuthorizationOutcome:
    """Authorize a scene-stage proposal: reference-only, engine-bound.

    Unknown recommended actions are dropped rather than fabricated; the engine's
    deterministic list remains the fallback, so the model can select but never
    invent a player-facing hint.
    """
    referenced: List[str] = []
    for event_id in contract.referenced_event_ids or ():
        if event_id not in ctx.allowed_event_ids:
            return _reject(ActionDetailCode.EVENT_REFERENCE_FOREIGN, event_id)
        referenced.append(event_id)

    legal = list(ctx.legal_recommended_actions or ())
    selected: List[str] = []
    for candidate in contract.recommended_actions or ():
        if candidate in legal and candidate not in selected:
            selected.append(candidate)

    return AuthorizationOutcome(action=AuthorizedAction(
        actor_id="scene_engine",
        actor_role=ActorRole.scene,
        action_type="reference",
        handler="scene_reference",
        time_policy=TimePolicy.NONE,
        referenced_event_ids=tuple(referenced),
        recommended_actions=tuple(selected),
        display_hint=contract.display_hint,
    ))


def authorized_event_ids(planned_events: Sequence[Any]) -> FrozenSet[str]:
    """Engine event ids a world/scene proposal may reference this turn.

    Only *this turn's* planned engine events count: a reference id is bound to the
    turn it was produced in, so an id from an earlier turn is not a grant.
    """
    ids: List[str] = []
    for planned in planned_events or ():
        event_id = getattr(planned, "id", None)
        if event_id:
            ids.append(event_id)
    return frozenset(ids)


__all__ = [
    "CONCEALED_LOCATION_TAGS",
    "CONCEALED_LOCATION_TYPES",
    "UNAVAILABLE_NPC_STATUSES",
    "AuthorizedAction",
    "AuthorizationOutcome",
    "AuthorizationContext",
    "location_canonical_key",
    "npc_canonical_key",
    "build_player_perspective",
    "public_map_location_keys",
    "location_is_reachable",
    "resolve_location_reference",
    "resolve_location_text_reference",
    "resolve_npc_reference",
    "resolve_npc_template_reference",
    "resolve_npc_by_name",
    "npc_is_available",
    "npc_is_visible_to_player",
    "authorize_player_intent",
    "authorize_deterministic_player_intent",
    "authorize_npc_action",
    "authorize_world_tick",
    "authorize_scene_event",
    "authorized_event_ids",
]

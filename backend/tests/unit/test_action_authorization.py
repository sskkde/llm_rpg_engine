"""Phase 2 unit coverage: reference and permission checks for LLM proposals.

Scope (see ``.omo/plans/phase2-llm-authority.md`` sections 3.1-3.3 and 5):

* the strict production contract rejects every shape that tries to carry
  executable fields (deltas, effects, actor/session/audit identity, versions);
* a model may only reference stable ids this turn's context supplied, and the
  identity namespaces (session-state NPC id, NPC template code, location code) are
  never conflated;
* the entity matrix: NPC-A impersonating B, another session's or world's entity,
  an undiscovered/concealed location, a departed/dead NPC, and forged event or
  recommended-action ids are all refused;
* the actor role decides the authorized action surface, so a declared-but-
  unauthorized action is ``unsupported`` rather than silently executed.

The tests build a small in-memory SQLite world directly, so they exercise the
authorization layer without going through the turn service.
"""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.action_authorization import (
    AuthorizationContext,
    authorize_deterministic_player_intent,
    authorize_npc_action,
    authorize_player_intent,
    authorize_scene_event,
    authorize_world_tick,
    build_player_perspective,
    location_is_reachable,
    resolve_location_reference,
    resolve_npc_by_name,
    resolve_npc_reference,
)
from llm_rpg.core.action_reason import (
    ActionDetailCode,
    ActionReasonCode,
    public_reason_for_detail,
)
from llm_rpg.llm.strict_contract import ContractViolation, validate_production_contract
from llm_rpg.models.action_contract import (
    NPCActionV2,
    PlayerIntentV2,
    SceneEventV2,
    WorldTickV2,
)
from llm_rpg.models.events import WorldTime
from llm_rpg.models.states import (
    CanonicalState,
    CurrentSceneState,
    PlayerState,
    WorldState,
)
from llm_rpg.rules.action_schema import (
    ActorRole,
    is_action_authorized,
    resolve_production_permission,
)
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    SaveSlotModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    UserModel,
    WorldModel,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def world(db):
    suffix = uuid.uuid4().hex[:8]
    user = UserModel(
        id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid",
        password_hash="x", is_admin=False,
    )
    world = WorldModel(
        id=f"w-{suffix}", code=f"w-{suffix}", name="测试世界", genre="xianxia", status="active",
    )
    db.add_all([user, world])
    db.flush()
    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="第一章")
    slot = SaveSlotModel(id=f"s-{suffix}", user_id=user.id, slot_number=1, name="存档")
    session = SessionModel(
        id=f"session-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id,
        current_chapter_id=chapter.id, status="active",
    )
    db.add_all([chapter, slot, session])
    db.flush()

    square = LocationModel(
        id=f"loc-square-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="square", name="宗门广场", tags=["public", "starting_point"],
        access_rules={"always_accessible": True},
    )
    hall = LocationModel(
        id=f"loc-hall-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="trial_hall", name="试炼堂", tags=["public", "quest_hub"],
        access_rules={"always_accessible": True},
    )
    vault = LocationModel(
        id=f"loc-vault-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="secret_vault", name="秘藏", tags=["secret"],
        access_rules={"always_accessible": True},
    )
    other_world = WorldModel(
        id=f"w2-{suffix}", code=f"w2-{suffix}", name="别的世界", genre="xianxia", status="active",
    )
    foreign_loc = LocationModel(
        id=f"loc-foreign-{suffix}", world_id=other_world.id,
        code="foreign_place", name="外界之地", tags=["public"],
        access_rules={"always_accessible": True},
    )
    guide = NPCTemplateModel(
        id=f"npc-guide-{suffix}", world_id=world.id, code="guide", name="向导",
        role_type="guide", is_major_npc=True,
    )
    rival = NPCTemplateModel(
        id=f"npc-rival-{suffix}", world_id=world.id, code="rival", name="对手",
        role_type="guard", is_major_npc=False,
    )
    hermit = NPCTemplateModel(
        id=f"npc-hermit-{suffix}", world_id=world.id, code="hermit", name="隐者",
        role_type="hermit", is_major_npc=False,
    )
    wanderer = NPCTemplateModel(
        id=f"npc-wanderer-{suffix}", world_id=world.id, code="wanderer", name="游者",
        role_type="wanderer", is_major_npc=False,
    )
    foreign_npc = NPCTemplateModel(
        id=f"npc-foreign-{suffix}", world_id=other_world.id, code="foreign", name="外人",
        role_type="guide",
    )
    db.add_all([
        square, hall, vault, other_world, foreign_loc,
        guide, rival, hermit, wanderer, foreign_npc,
    ])
    db.flush()

    # ``session_npc_states`` is unique per (session, template): each NPC identity has
    # exactly one state row, so the dead/away cases need distinct identities.
    guide_state = SessionNPCStateModel(
        id=f"snpc-guide-{suffix}", session_id=session.id, npc_template_id=guide.id,
        current_location_id=square.id, status_flags={"status": "alive", "mood": "calm"},
    )
    rival_state = SessionNPCStateModel(
        id=f"snpc-rival-{suffix}", session_id=session.id, npc_template_id=rival.id,
        current_location_id=square.id, status_flags={"status": "alive", "mood": "tense"},
    )
    dead_state = SessionNPCStateModel(
        id=f"snpc-dead-{suffix}", session_id=session.id, npc_template_id=hermit.id,
        current_location_id=square.id, status_flags={"status": "dead"},
    )
    away_state = SessionNPCStateModel(
        id=f"snpc-away-{suffix}", session_id=session.id, npc_template_id=wanderer.id,
        current_location_id=hall.id, status_flags={"status": "alive"},
    )
    db.add_all([guide_state, rival_state, dead_state, away_state])
    db.flush()

    db.add(SessionStateModel(
        id=f"ss-{suffix}", session_id=session.id, current_location_id=square.id,
        current_time="第1日 辰时", time_phase="辰时", active_mode="exploration",
    ))
    db.commit()

    return {
        "world": world,
        "other_world": other_world,
        "session": session,
        "square": square,
        "hall": hall,
        "vault": vault,
        "foreign_loc": foreign_loc,
        "guide": guide,
        "rival": rival,
        "hermit": hermit,
        "wanderer": wanderer,
        "foreign_npc": foreign_npc,
        "guide_state": guide_state,
        "rival_state": rival_state,
        "dead_state": dead_state,
        "away_state": away_state,
    }


def _canonical_state(current_location_id=None):
    """Minimal valid canonical state, for contexts that only need DB lookups."""
    return CanonicalState(
        world_state=WorldState(
            entity_id="w1", world_id="w1",
            current_time=WorldTime(calendar="修仙历", season="春", day=1, period="辰时"),
        ),
        player_state=PlayerState(
            entity_id="p1", name="玩家", location_id=current_location_id or "unknown"
        ),
        current_scene_state=CurrentSceneState(
            entity_id="s1", scene_id="s1", location_id=current_location_id or "unknown",
            active_actor_ids=["p1"],
        ),
    )


def _ctx(db, world, *, current_location_id=None, visible_npc_ids=(), available_memory_ids=None,
         allowed_event_ids=(), legal_recommended_actions=()):
    return AuthorizationContext(
        db=db,
        session_id=world["session"].id,
        world_id=world["world"].id,
        turn_no=1,
        canonical_state=_canonical_state(current_location_id),
        current_location_id=current_location_id,
        visible_npc_ids=frozenset(visible_npc_ids),
        available_memory_ids=(
            None if available_memory_ids is None else frozenset(available_memory_ids)
        ),
        allowed_event_ids=frozenset(allowed_event_ids),
        legal_recommended_actions=tuple(legal_recommended_actions),
    )


def _player_intent(**intent):
    return PlayerIntentV2(contract_version=2, intent=intent)


# ---------------------------------------------------------------------------
# Strict production contract
# ---------------------------------------------------------------------------


class TestStrictProductionContract:
    def test_minimal_idle_intent_is_accepted(self):
        contract = validate_production_contract(
            "input_intent", json.dumps({"contract_version": 2, "intent": {"action_type": "idle"}})
        )
        assert isinstance(contract, PlayerIntentV2)
        assert contract.intent.action_type == "idle"

    @pytest.mark.parametrize(
        "payload,expected",
        [
            (
                {"contract_version": 2, "intent": {"action_type": "idle"}, "state_deltas": []},
                "contract_schema_violation",
            ),
            (
                {"contract_version": 2, "intent": {"action_type": "move", "effects": {"hp": 0}}},
                "contract_schema_violation",
            ),
            (
                {"contract_version": 1, "intent": {"action_type": "idle"}},
                "contract_version_mismatch",
            ),
            (
                {"intent": {"action_type": "idle"}},
                "contract_version_mismatch",
            ),
            (
                {
                    "contract_version": 2,
                    "intent": {"action_type": "idle"},
                    "audit": {"source_engine": "world_engine"},
                },
                "contract_schema_violation",
            ),
            (
                {
                    "contract_version": 2,
                    "intent": {"action_type": "idle"},
                    "actor_id": "player",
                    "session_id": "other",
                },
                "contract_schema_violation",
            ),
            (
                {"contract_version": 2, "intent": {"action_type": "attack", "target": "x", "damage": 99}},
                "contract_schema_violation",
            ),
        ],
    )
    def test_forbidden_fields_and_versions_are_refused(self, payload, expected):
        with pytest.raises(ContractViolation) as excinfo:
            validate_production_contract("input_intent", json.dumps(payload))
        assert excinfo.value.code.value == expected

    def test_duplicate_keys_are_refused(self):
        raw = (
            '{"contract_version":2,"intent":{"action_type":"idle"},'
            '"confidence":0.5,"confidence":0.9}'
        )
        with pytest.raises(ContractViolation) as excinfo:
            validate_production_contract("input_intent", raw)
        assert excinfo.value.code.value == "contract_duplicate_key"

    def test_nested_duplicate_keys_are_refused(self):
        raw = '{"contract_version":2,"intent":{"action_type":"talk","topic":"a","topic":"b"}}'
        with pytest.raises(ContractViolation) as excinfo:
            validate_production_contract("input_intent", raw)
        assert excinfo.value.code.value == "contract_duplicate_key"

    def test_non_finite_constant_is_refused(self):
        raw = '{"contract_version":2,"intent":{"action_type":"idle"},"confidence":NaN}'
        with pytest.raises(ContractViolation) as excinfo:
            validate_production_contract("input_intent", raw)
        assert excinfo.value.code.value == "contract_invalid_constant"

    def test_single_whole_response_code_fence_is_stripped(self):
        fenced = "```json\n" + json.dumps({"contract_version": 2, "text": "你好"}) + "\n```"
        assert validate_production_contract("narration", fenced).text == "你好"

    def test_surrounding_prose_is_refused(self):
        raw = "好的，结果如下：\n" + json.dumps({"contract_version": 2, "text": "x"})
        with pytest.raises(ContractViolation) as excinfo:
            validate_production_contract("narration", raw)
        assert excinfo.value.code.value == "contract_not_json"

    def test_empty_output_is_refused(self):
        with pytest.raises(ContractViolation) as excinfo:
            validate_production_contract("narration", "   ")
        assert excinfo.value.code.value == "contract_empty_output"

    def test_world_and_scene_wire_carry_no_free_facts(self):
        """The world/scene contracts cannot express candidate events or deltas."""
        for model in (WorldTickV2, SceneEventV2):
            fields = set(model.model_fields)
            assert "candidate_events" not in fields
            assert "state_deltas" not in fields
            assert "effects" not in fields
            assert "elapsed_minutes" not in fields
            assert "time_delta_turns" not in fields

    def test_npc_wire_carries_no_identity_or_memory_authoring(self):
        fields = set(NPCActionV2.model_fields)
        for forbidden in (
            "npc_id", "state_deltas", "new_memory_candidates", "decision_audit",
            "hidden_motivation", "affected_entities", "visibility",
        ):
            assert forbidden not in fields, f"NPC wire must not carry {forbidden!r}"


# ---------------------------------------------------------------------------
# Action registry / role surface
# ---------------------------------------------------------------------------


class TestActionRegistry:
    def test_declared_actions_are_not_all_authorized(self):
        from llm_rpg.rules.action_schema import declared_action_types

        declared = declared_action_types()
        authorized = {
            action_type
            for (role, action_type) in __import__(
                "llm_rpg.rules.action_schema", fromlist=["PRODUCTION_ACTION_PERMISSIONS"]
            ).PRODUCTION_ACTION_PERMISSIONS
            if role is ActorRole.player
        }
        assert {"attack", "use_item", "take_item", "give_item", "cast_skill"} <= declared
        assert not ({"attack", "use_item", "take_item"} & authorized)

    @pytest.mark.parametrize(
        "role,action_type,expected",
        [
            (ActorRole.player, "move", True),
            (ActorRole.player, "talk", True),
            (ActorRole.player, "inspect", True),
            (ActorRole.player, "idle", True),
            (ActorRole.player, "attack", False),
            (ActorRole.player, "interact", False),
            (ActorRole.player, "unknown", False),
            (ActorRole.player, "quest_progress", False),
            (ActorRole.npc, "observe", True),
            (ActorRole.npc, "idle", True),
            (ActorRole.npc, "talk", True),
            (ActorRole.npc, "dialogue", True),
            (ActorRole.npc, "refuse", True),
            (ActorRole.npc, "attack", False),
            (ActorRole.npc, "move", False),
        ],
    )
    def test_role_surface(self, role, action_type, expected):
        assert is_action_authorized(role, action_type) is expected

    def test_dialogue_is_a_wire_alias_of_talk(self):
        assert resolve_production_permission(ActorRole.npc, "dialogue").handler == "npc_talk"


# ---------------------------------------------------------------------------
# Entity / reference matrix
# ---------------------------------------------------------------------------


class TestReferenceMatrix:
    def test_valid_move_to_public_location_is_authorized(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_player_intent(
            ctx, _player_intent(action_type="move", target_location_id=world["hall"].id)
        )
        assert outcome.authorized
        assert outcome.action.handler == "player_move"
        assert outcome.action.target_location_code == "trial_hall"

    def test_current_location_is_reachable(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        assert location_is_reachable(ctx, world["square"])[0] is True

    def test_concealed_location_is_not_reachable(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        reachable, detail = location_is_reachable(ctx, world["vault"])
        assert reachable is False
        assert detail is ActionDetailCode.LOCATION_NOT_DISCOVERED

    def test_guessing_a_concealed_location_id_is_refused(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_player_intent(
            ctx, _player_intent(action_type="move", target_location_id=world["vault"].id)
        )
        assert not outcome.authorized
        assert outcome.public_reason is ActionReasonCode.TARGET_UNAVAILABLE
        # The public code must not disclose that the location exists at all.
        assert "secret" not in (outcome.detail_message or "")

    def test_another_worlds_location_is_refused(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        location, detail = resolve_location_reference(ctx, world["foreign_loc"].id)
        assert location is None
        assert detail is ActionDetailCode.ENTITY_WRONG_WORLD

    def test_unknown_location_is_refused(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_player_intent(
            ctx, _player_intent(action_type="move", target_location_id="loc-does-not-exist")
        )
        assert not outcome.authorized
        assert outcome.public_reason is ActionReasonCode.TARGET_UNAVAILABLE

    def test_move_without_target_is_a_missing_target_not_a_success(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_player_intent(ctx, _player_intent(action_type="move"))
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.MISSING_TARGET

    def test_talk_to_visible_npc_is_authorized(self, db, world):
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id},
        )
        outcome = authorize_player_intent(
            ctx,
            _player_intent(
                action_type="talk", target_npc_id=world["guide_state"].id, topic="宗门规矩"
            ),
        )
        assert outcome.authorized
        assert outcome.action.handler == "player_talk"
        assert outcome.action.target_npc_template_id == world["guide"].id

    def test_talk_to_absent_npc_is_refused(self, db, world):
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id},
        )
        outcome = authorize_player_intent(
            ctx, _player_intent(action_type="talk", target_npc_id=world["away_state"].id)
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.ENTITY_NOT_PRESENT

    def test_talk_to_dead_npc_is_refused(self, db, world):
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["dead_state"].id},
        )
        outcome = authorize_player_intent(
            ctx, _player_intent(action_type="talk", target_npc_id=world["dead_state"].id)
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.ENTITY_NOT_ALIVE

    def test_talk_to_npc_not_offered_as_visible_is_refused(self, db, world):
        """Present but not engine-visible: the model cannot promote visibility."""
        ctx = _ctx(db, world, current_location_id=world["square"].id, visible_npc_ids=set())
        outcome = authorize_player_intent(
            ctx, _player_intent(action_type="talk", target_npc_id=world["guide_state"].id)
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.ENTITY_NOT_VISIBLE

    def test_npc_template_code_is_not_a_session_state_id(self, db, world):
        """Identity namespaces are not conflated: a template code is not an actor id."""
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        row, detail = resolve_npc_reference(ctx, world["guide"].code)
        assert row is None
        assert detail is ActionDetailCode.ENTITY_NOT_FOUND

    def test_ambiguous_player_written_name_is_not_resolved_arbitrarily(self, db, world):
        """Duplicate names must not silently pick the first match."""
        duplicate = NPCTemplateModel(
            id=f"npc-dup-{uuid.uuid4().hex[:6]}", world_id=world["world"].id,
            code="guide2", name="向导", role_type="guide",
        )
        db.add(duplicate)
        db.flush()
        db.add(SessionNPCStateModel(
            id=f"snpc-dup-{uuid.uuid4().hex[:6]}", session_id=world["session"].id,
            npc_template_id=duplicate.id, current_location_id=world["square"].id,
            status_flags={"status": "alive"},
        ))
        db.commit()

        ctx = _ctx(db, world, current_location_id=world["square"].id)
        row, detail = resolve_npc_by_name(ctx, "向导")
        assert row is None
        assert detail is ActionDetailCode.ENTITY_NOT_VISIBLE

    def test_unsupported_action_is_reported_as_unsupported(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_player_intent(
            ctx, _player_intent(action_type="attack", target="向导")
        )
        assert not outcome.authorized
        assert outcome.public_reason is ActionReasonCode.UNSUPPORTED
        assert outcome.detail_code is ActionDetailCode.ACTION_NOT_AUTHORIZED

    def test_npc_may_not_address_an_npc_in_another_scene(self, db, world):
        """Being in the same session and alive is not enough: the target must be present."""
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id},
        )
        contract = NPCActionV2(
            contract_version=2,
            action={"action_type": "talk", "target_id": world["away_state"].id,
                    "utterance": "你过来"},
            summary="向导朝远处喊话",
        )
        outcome = authorize_npc_action(
            ctx, contract,
            npc_id=world["guide_state"].id, npc_template_id=world["guide"].id,
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.ENTITY_NOT_PRESENT

    def test_npc_may_address_a_present_npc(self, db, world):
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id, world["rival_state"].id},
        )
        contract = NPCActionV2(
            contract_version=2,
            action={"action_type": "talk", "target_id": world["rival_state"].id,
                    "utterance": "退后"},
            summary="向导警告对手",
        )
        outcome = authorize_npc_action(
            ctx, contract,
            npc_id=world["guide_state"].id, npc_template_id=world["guide"].id,
        )
        assert outcome.authorized
        assert outcome.action.target_npc_id == world["rival_state"].id

    def test_npc_visibility_ceiling_cannot_be_widened_by_the_model(self, db, world):
        """The model may only narrow visibility; the server decides the ceiling."""
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id},
        )
        contract = NPCActionV2(
            contract_version=2, action={"action_type": "observe"},
            summary="向导观察", visible_to_player=True,
        )
        outcome = authorize_npc_action(
            ctx, contract,
            npc_id=world["guide_state"].id, npc_template_id=world["guide"].id,
        )
        assert outcome.authorized
        assert outcome.action.visible_to_player is True

        # The same action asked to be hidden stays hidden (narrowing is allowed).
        hidden = authorize_npc_action(
            ctx,
            NPCActionV2(
                contract_version=2, action={"action_type": "observe"},
                summary="向导暗中观察", visible_to_player=False,
            ),
            npc_id=world["guide_state"].id, npc_template_id=world["guide"].id,
        )
        assert hidden.authorized
        assert hidden.action.visible_to_player is False

    def test_npc_actor_cannot_impersonate_another_npc(self, db, world):
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id, world["rival_state"].id},
        )
        contract = NPCActionV2(
            contract_version=2, action={"action_type": "observe"}, summary="观察"
        )
        outcome = authorize_npc_action(
            ctx, contract,
            npc_id=world["rival_state"].id,
            npc_template_id=world["guide"].id,  # bound id does not match the row
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.ACTOR_IMPERSONATION

    def test_npc_actor_must_be_bound_to_a_real_session_row(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        contract = NPCActionV2(
            contract_version=2, action={"action_type": "idle"}, summary="等待"
        )
        outcome = authorize_npc_action(
            ctx, contract, npc_id="snpc-does-not-exist", npc_template_id=world["guide"].id
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.ACTOR_NOT_BOUND

    def test_npc_memory_reference_outside_the_supplied_set_is_refused(self, db, world):
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id},
            available_memory_ids={"mem-1"},
        )
        contract = NPCActionV2(
            contract_version=2, action={"action_type": "idle"}, summary="回想",
            used_memory_ids=["mem-2"],
        )
        outcome = authorize_npc_action(
            ctx, contract,
            npc_id=world["guide_state"].id, npc_template_id=world["guide"].id,
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.MEMORY_ID_NOT_AVAILABLE

    def test_empty_available_memory_set_permits_no_reference(self, db, world):
        """An empty/absent available set must not be treated as "no constraint"."""
        ctx = _ctx(
            db, world,
            current_location_id=world["square"].id,
            visible_npc_ids={world["guide_state"].id},
            available_memory_ids=None,
        )
        contract = NPCActionV2(
            contract_version=2, action={"action_type": "idle"}, summary="回想",
            used_memory_ids=["any-memory-id"],
        )
        outcome = authorize_npc_action(
            ctx, contract,
            npc_id=world["guide_state"].id, npc_template_id=world["guide"].id,
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.MEMORY_ID_NOT_AVAILABLE

    def test_forged_world_event_reference_is_refused(self, db, world):
        ctx = _ctx(db, world, allowed_event_ids={"real-event"})
        outcome = authorize_world_tick(
            ctx, WorldTickV2(contract_version=2, referenced_event_ids=["forged-event"])
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.EVENT_REFERENCE_FOREIGN

    def test_world_reference_to_this_turns_event_is_authorized(self, db, world):
        ctx = _ctx(db, world, allowed_event_ids={"real-event"})
        outcome = authorize_world_tick(
            ctx, WorldTickV2(contract_version=2, referenced_event_ids=["real-event"])
        )
        assert outcome.authorized
        assert outcome.action.referenced_event_ids == ("real-event",)

    def test_scene_invented_recommended_action_is_dropped(self, db, world):
        ctx = _ctx(
            db, world,
            legal_recommended_actions=("前往试炼堂", "与向导交谈"),
        )
        outcome = authorize_scene_event(
            ctx,
            SceneEventV2(
                contract_version=2,
                recommended_actions=["前往试炼堂", "凭空捏造的行动", "与向导交谈"],
            ),
        )
        assert outcome.authorized
        assert outcome.action.recommended_actions == ("前往试炼堂", "与向导交谈")

    def test_forged_scene_event_reference_is_refused(self, db, world):
        ctx = _ctx(db, world, allowed_event_ids={"real-event"})
        outcome = authorize_scene_event(
            ctx, SceneEventV2(contract_version=2, referenced_event_ids=["nope"])
        )
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.EVENT_REFERENCE_FOREIGN


# ---------------------------------------------------------------------------
# Perspective and deterministic fallback
# ---------------------------------------------------------------------------


class TestPerspectiveAndFallback:
    def test_perspective_is_explicit_and_includes_the_public_map(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        perspective = build_player_perspective(ctx)
        assert perspective.owner_id == "player"
        discovered = set(perspective.discovered_locations)
        assert world["square"].id in discovered
        assert world["hall"].id in discovered
        # A concealed location is absent until a discovery marker records it.
        assert world["vault"].id not in discovered

    def test_perspective_includes_persistent_discovery_flag(self, db, world):
        state = _canonical_state(world["square"].id)
        state.player_state.flags = {f"discovered_{world['vault'].id}": True}
        ctx = AuthorizationContext(
            db=db, session_id=world["session"].id, world_id=world["world"].id, turn_no=1,
            canonical_state=state, current_location_id=world["square"].id,
        )
        assert world["vault"].id in set(build_player_perspective(ctx).discovered_locations)

    def test_deterministic_move_resolves_a_player_written_alias(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_deterministic_player_intent(ctx, "move", "试炼堂")
        assert outcome.authorized
        assert outcome.action.target_location_code == "trial_hall"

    def test_deterministic_move_to_unknown_place_is_refused(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_deterministic_player_intent(ctx, "move", "不存在的地方")
        assert not outcome.authorized
        assert outcome.public_reason is ActionReasonCode.TARGET_UNAVAILABLE

    def test_deterministic_move_without_target_reports_missing_target(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_deterministic_player_intent(ctx, "move", None)
        assert not outcome.authorized
        assert outcome.detail_code is ActionDetailCode.MISSING_TARGET

    def test_deterministic_unsupported_action_stays_unsupported(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_deterministic_player_intent(ctx, "attack", None)
        assert not outcome.authorized
        assert outcome.public_reason is ActionReasonCode.UNSUPPORTED

    def test_deterministic_move_into_a_concealed_place_is_refused(self, db, world):
        ctx = _ctx(db, world, current_location_id=world["square"].id)
        outcome = authorize_deterministic_player_intent(ctx, "move", world["vault"].id)
        assert not outcome.authorized
        assert outcome.public_reason is ActionReasonCode.TARGET_UNAVAILABLE


class TestPublicReasonMapping:
    @pytest.mark.parametrize(
        "detail,expected",
        [
            (ActionDetailCode.ACTION_NOT_AUTHORIZED, ActionReasonCode.UNSUPPORTED),
            (ActionDetailCode.NO_HANDLER, ActionReasonCode.UNSUPPORTED),
            (ActionDetailCode.ENTITY_NOT_FOUND, ActionReasonCode.TARGET_UNAVAILABLE),
            (ActionDetailCode.ENTITY_NOT_VISIBLE, ActionReasonCode.TARGET_UNAVAILABLE),
            (ActionDetailCode.ENTITY_WRONG_WORLD, ActionReasonCode.TARGET_UNAVAILABLE),
            (ActionDetailCode.LOCATION_NOT_DISCOVERED, ActionReasonCode.TARGET_UNAVAILABLE),
            (ActionDetailCode.MISSING_TARGET, ActionReasonCode.INVALID_PARAMS),
            (ActionDetailCode.CONTRACT_NOT_JSON, ActionReasonCode.CONTRACT_FAILURE),
            (ActionDetailCode.CONTRACT_VERSION_MISMATCH, ActionReasonCode.CONTRACT_FAILURE),
        ],
    )
    def test_detail_maps_to_the_coarse_public_code(self, detail, expected):
        assert public_reason_for_detail(detail) is expected

    def test_public_reason_codes_are_exactly_the_four_documented_ones(self):
        assert {code.value for code in ActionReasonCode} == {
            "unsupported", "invalid_params", "target_unavailable", "contract_failure",
        }

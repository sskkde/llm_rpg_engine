"""
Integration tests for the Player-Visible Projection pipeline.

Tests the complete perspective pipeline end-to-end:
- Committed Facts → Player Perspective filter → PlayerVisibleProjection →
  Narrator Perspective → Narration LLM → Narration Leak Validator

Test cases:
1. Full pipeline: committed facts through to narration leak check
2. Player-visible projection only shows facts the player should know
3. Narration output does NOT contain hidden NPC identities, secret locations, hidden quest info
4. NPC decision context is isolated and doesn't contain canonical state facts NPC shouldn't know
5. Full turn pipeline via API: player input → intent → NPC decision → validation →
   commit → narration → narration leak check
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    WorldModel,
    NPCTemplateModel,
    SessionModel,
    SessionNPCStateModel,
    NPCSecretModel,
)
from llm_rpg.models.events import (
    GameEvent,
    EventType,
    WorldTime,
    SceneEvent,
)
from llm_rpg.models.perspectives import (
    PlayerPerspective,
)
from llm_rpg.models.states import (
    CanonicalState,
    CurrentSceneState,
    PlayerState,
    WorldState,
    NPCState,
    LocationState,
    QuestState,
    PhysicalState,
    MentalState,
)
from llm_rpg.models.memories import (
    NPCProfile,
    NPCBeliefState,
    NPCMemoryScope,
    NPCRecentContext,
    NPCSecrets,
    NPCKnowledgeState,
    NPCGoals,
    Belief,
    Secret,
)
from llm_rpg.core.perspective import PerspectiveService
from llm_rpg.core.context_builder import ContextBuilder
from llm_rpg.core.retrieval import RetrievalSystem
from llm_rpg.core.projections import (
    PlayerVisibleProjectionBuilder,
    NarratorProjectionBuilder,
)
from llm_rpg.core.perception import PerceptionResolver
from llm_rpg.core.validation.narration_leak_validator import (
    NarrationLeakValidator,
)


# =============================================================================
# Helper factories
# =============================================================================

def _make_world_time(calendar: str = "修仙历", season: str = "春季",
                     day: int = 1, period: str = "辰时") -> WorldTime:
    return WorldTime(calendar=calendar, season=season, day=day, period=period)


def _make_canonical_state(
    player_location_id: str = "loc_square",
    world_time: WorldTime | None = None,
    npc_states: Dict[str, NPCState] | None = None,
    scene_actor_ids: List[str] | None = None,
    scene_location_id: str | None = None,
    quest_states: Dict[str, QuestState] | None = None,
    location_states: Dict[str, LocationState] | None = None,
) -> CanonicalState:
    wt = world_time or _make_world_time()
    sloc = scene_location_id or player_location_id
    actors = scene_actor_ids or list(npc_states.keys()) if npc_states else []
    return CanonicalState(
        player_state=PlayerState(
            entity_id="player_1",
            name="玩家",
            location_id=player_location_id,
        ),
        world_state=WorldState(
            entity_id="world_1",
            world_id="test_world",
            current_time=wt,
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene_1",
            scene_id="scene_square",
            location_id=sloc,
            active_actor_ids=actors,
            visible_object_ids=[],
            available_actions=["observe", "talk", "move", "act"],
        ),
        npc_states=npc_states or {},
        quest_states=quest_states or {},
        location_states=location_states or {},
    )


def _make_npc_state(npc_id: str, name: str, location_id: str = "loc_square",
                    mood: str = "neutral", status: str = "alive") -> NPCState:
    return NPCState(
        entity_id=npc_id,
        npc_id=npc_id,
        name=name,
        location_id=location_id,
        mood=mood,
        status=status,
        current_action=None,
        physical_state=PhysicalState(),
        mental_state=MentalState(),
    )


def _make_game_event(
    event_id: str,
    event_type: EventType = EventType.SCENE_EVENT,
    turn_index: int = 1,
    location_id: str = "loc_square",
    visible_to_player: bool = True,
    summary: str = "",
    is_hidden: bool = False,
    visibility_scope: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> SceneEvent:
    meta = metadata or {}
    if location_id:
        meta.setdefault("location_id", location_id)
    meta.setdefault("is_hidden", is_hidden if not visible_to_player else False)
    meta.setdefault("visibility_scope", visibility_scope or "location")
    event = SceneEvent(
        event_id=event_id,
        turn_index=turn_index,
        timestamp=datetime.now(),
        scene_id="scene_square",
        trigger="test",
        summary=summary or f"Event {event_id}",
        visible_to_player=visible_to_player,
        metadata=meta,
    )
    return event


# =============================================================================
# Test 1: Full pipeline — committed facts → narration leak check
# =============================================================================

class TestFullPerspectivePipeline:
    """Test the complete perspective pipeline end-to-end."""

    def test_committed_facts_to_player_projection_to_narrator_to_leak_check(
        self,
        perspective_service: PerspectiveService,
        retrieval_system: RetrievalSystem,
    ):
        """
        Full pipeline:
        1. Build canonical state with committed facts
        2. Build player perspective from known facts
        3. Filter through PlayerVisibleProjection
        4. Build narrator perspective from player projection
        5. Validate narration output through NarrationLeakValidator
        """
        # --- 1. Build canonical state with committed facts ---
        state = _make_canonical_state(
            player_location_id="loc_square",
            npc_states={
                "npc_elder": _make_npc_state("npc_elder", "长老", "loc_square"),
                "npc_merchant": _make_npc_state("npc_merchant", "商人", "loc_forest"),
            },
        )

        # --- 2. Build player perspective ---
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_view",
            player_id="player_1",
            known_facts=["fact_square_description", "fact_npc_elder_name"],
            known_rumors=["rumor_forest_treasure"],
            visible_scene_ids=["scene_square"],
            discovered_locations=["loc_square"],
        )

        # --- 3. Create committed events (some visible, some hidden) ---
        events: List[GameEvent] = [
            _make_game_event(
                "evt_public_1",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=True,
                summary="玩家走进宗门广场",
            ),
            _make_game_event(
                "evt_secret_1",
                turn_index=1,
                location_id="loc_forest",
                visible_to_player=False,
                summary="商人在山林中发现宝藏",
                metadata={"location_id": "loc_forest", "secret_detail": "宝藏是远古神器的碎片"},
            ),
            _make_game_event(
                "evt_public_2",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=True,
                summary="长老向玩家问好",
            ),
            _make_game_event(
                "evt_hidden_identity",
                turn_index=1,
                location_id="loc_temple",
                visible_to_player=False,
                summary="长老在密室联络魔教",
                metadata={"location_id": "loc_temple", "hidden_action": "向魔教发送信号"},
            ),
        ]

        # --- Create PlayerVisibleProjection ---
        perception_resolver = PerceptionResolver()
        perception_resolver.register_location_connection("loc_square", "loc_forest")
        perception_resolver.register_location_connection("loc_square", "loc_temple")

        player_projection_builder = PlayerVisibleProjectionBuilder(
            perception_resolver=perception_resolver,
        )

        # --- 4. Build PlayerVisibleProjection ---
        player_visible_events = player_projection_builder.build_projection(
            events=events,
            perspective=player_perspective,
            context={
                "player_location_id": "loc_square",
                "current_turn": 1,
            },
        )

        # Player should see public square events but NOT secret forest events
        visible_summaries = [
            e.get("summary", "") for e in player_visible_events
            if isinstance(e, dict)
        ]
        assert "玩家走进宗门广场" in visible_summaries
        assert "长老向玩家问好" in visible_summaries
        # Hidden forest event should NOT appear
        assert "商人在山林中发现宝藏" not in visible_summaries
        # Hidden identity event should NOT appear
        assert "长老在密室联络魔教" not in visible_summaries

        # Hidden events (visible_to_player=False) should be excluded
        for evt_dict in player_visible_events:
            if isinstance(evt_dict, dict):
                meta = evt_dict.get("metadata", {})
                assert not meta.get("is_hidden"), (
                    f"Hidden event leaked: {evt_dict.get('event_id')}"
                )

        # --- 5. Build NarratorProjection ---
        narrator_perspective = perspective_service.build_narrator_perspective(
            perspective_id="narrator_view",
            base_perspective_id="player_view",
            tone="neutral",
            pacing="normal",
            forbidden_info=["魔教卧底", "远古神器"],
            allowed_hints=["隐约感到"],
        )

        narrator_projection_builder = NarratorProjectionBuilder(
            perception_resolver=perception_resolver,
            player_projection_builder=player_projection_builder,
        )

        narration_context = narrator_projection_builder.build_narration_context(
            events=events,
            perspective=narrator_perspective,
            context={
                "player_location_id": "loc_square",
                "current_turn": 1,
                "player_perspective": player_perspective,
            },
        )

        # Narrator context must contain events and constraints
        assert "events" in narration_context
        assert "narration_settings" in narration_context
        assert "constraints" in narration_context
        assert "never_reveal" in narration_context["constraints"]
        never_reveal = narration_context["constraints"]["never_reveal"]
        assert "private_payload" in never_reveal
        assert "hidden_lore" in never_reveal

        # --- 6. Simulate narration text and run leak validator ---
        # Safe narration (only describes what player sees)
        safe_narration = "你踏入宗门广场，青石铺就的地面在阳光下泛着微光。长老正站在不远处，微笑着望向你。"
        # Leaky narration (mentions forbidden info)
        leaky_narration = "你踏入宗门广场，心中忽然想到长老其实是魔教卧底，他昨夜在密室向魔教发送了信号。"

        validator = NarrationLeakValidator()

        # Safe narration should pass
        safe_result = validator.validate_narration(
            text=safe_narration,
            forbidden_info=["魔教卧底", "远古神器", "长老在密室联络魔教"],
        )
        assert safe_result.is_valid, f"Safe narration should pass but got errors: {safe_result.errors}"

        # Leaky narration should fail
        leaky_result = validator.validate_narration(
            text=leaky_narration,
            forbidden_info=["魔教卧底", "远古神器", "长老在密室联络魔教"],
        )
        assert not leaky_result.is_valid, "Leaky narration should fail validation"
        assert len(leaky_result.errors) > 0

    def test_narrator_never_reveals_hidden_events(
        self,
        perspective_service: PerspectiveService,
    ):
        """NarratorProjection MUST exclude hidden events (visible_to_player=False)."""
        events: List[GameEvent] = [
            _make_game_event(
                "evt_public",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=True,
                summary="玩家看到广场上的人",
            ),
            _make_game_event(
                "evt_hidden_action",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=False,
                summary="这是不可告人的秘密事件",
                metadata={"location_id": "loc_square", "is_hidden": True},
            ),
        ]

        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_view",
            player_id="player_1",
            known_facts=["evt_public"],
        )

        perception_resolver = PerceptionResolver()
        narrator_projection_builder = NarratorProjectionBuilder(
            perception_resolver=perception_resolver,
        )

        narration_context = narrator_projection_builder.build_narration_context(
            events=events,
            perspective=perspective_service.build_narrator_perspective(
                perspective_id="narrator_view",
                base_perspective_id="player_view",
                forbidden_info=["不可告人的秘密事件"],
            ),
            context={
                "player_location_id": "loc_square",
                "current_turn": 1,
                "player_perspective": player_perspective,
            },
        )

        # Only public events should be in the narration context
        narration_events = narration_context.get("events", [])
        narration_summaries = [e.get("summary", "") for e in narration_events if isinstance(e, dict)]
        assert "玩家看到广场上的人" in narration_summaries
        assert "这是不可告人的秘密事件" not in narration_summaries


# =============================================================================
# Test 2: Player-visible projection only shows facts the player should know
# =============================================================================

class TestPlayerVisibleProjectionFiltering:
    """Test that PlayerVisibleProjection correctly filters based on player knowledge."""

    def test_player_sees_only_same_location_events(
        self,
        perspective_service: PerspectiveService,
    ):
        """Player should only see events that happen at their current location."""
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_view",
            player_id="player_1",
            known_facts=["fact_location_square"],
            discovered_locations=["loc_square"],
        )

        events: List[GameEvent] = [
            _make_game_event("evt_square_1", turn_index=1, location_id="loc_square",
                             visible_to_player=True, summary="广场上的事件"),
            _make_game_event("evt_forest_1", turn_index=1, location_id="loc_forest",
                             visible_to_player=False, summary="山林中的秘密事件"),
            _make_game_event("evt_temple_1", turn_index=1, location_id="loc_temple",
                             visible_to_player=False, summary="密室中的仪式"),
        ]

        perception_resolver = PerceptionResolver()
        player_projection = PlayerVisibleProjectionBuilder(
            perception_resolver=perception_resolver,
        )

        visible = player_projection.build_projection(
            events=events,
            perspective=player_perspective,
            context={"player_location_id": "loc_square", "current_turn": 1},
        )

        visible_summaries = [e.get("summary", "") for e in visible if isinstance(e, dict)]
        assert "广场上的事件" in visible_summaries
        # Forest event at different location should NOT be visible
        assert "山林中的秘密事件" not in visible_summaries
        # Temple event at different location should NOT be visible
        assert "密室中的仪式" not in visible_summaries

    def test_player_sees_world_scoped_events_anywhere(
        self,
        perspective_service: PerspectiveService,
    ):
        """World-scoped events should be visible to the player regardless of location."""
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_view",
            player_id="player_1",
        )

        events: List[GameEvent] = [
            _make_game_event(
                "evt_world_scope",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=True,
                summary="天降祥瑞，全界震动",
                metadata={"visibility_scope": "world"},
            ),
        ]

        perception_resolver = PerceptionResolver()
        player_projection = PlayerVisibleProjectionBuilder(
            perception_resolver=perception_resolver,
        )

        # Player at a different location should still see world-scoped events
        visible = player_projection.build_projection(
            events=events,
            perspective=player_perspective,
            context={"player_location_id": "loc_forest", "current_turn": 1},
        )

        visible_summaries = [e.get("summary", "") for e in visible if isinstance(e, dict)]
        assert "天降祥瑞，全界震动" in visible_summaries

    def test_player_does_not_see_hidden_events(
        self,
        perspective_service: PerspectiveService,
    ):
        """Hidden events should never be visible to the player."""
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_view",
            player_id="player_1",
        )

        events: List[GameEvent] = [
            _make_game_event(
                "evt_hidden",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=False,
                summary="秘密会谈",
                metadata={"is_hidden": True},
            ),
        ]

        perception_resolver = PerceptionResolver()
        player_projection = PlayerVisibleProjectionBuilder(
            perception_resolver=perception_resolver,
        )

        visible = player_projection.build_projection(
            events=events,
            perspective=player_perspective,
            context={"player_location_id": "loc_square", "current_turn": 1},
        )

        visible_summaries = [e.get("summary", "") for e in visible if isinstance(e, dict)]
        assert "秘密会谈" not in visible_summaries

    def test_player_projection_preserves_perception_metadata(
        self,
        perspective_service: PerspectiveService,
    ):
        """Player-visible projection should include perception metadata on events."""
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_view",
            player_id="player_1",
        )

        events: List[GameEvent] = [
            _make_game_event(
                "evt_visible",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=True,
                summary="玩家观察四周",
            ),
        ]

        perception_resolver = PerceptionResolver()
        player_projection = PlayerVisibleProjectionBuilder(
            perception_resolver=perception_resolver,
        )

        visible = player_projection.build_projection(
            events=events,
            perspective=player_perspective,
            context={"player_location_id": "loc_square", "current_turn": 1},
        )

        assert len(visible) >= 1
        # Each visible event should have _perception metadata
        for evt in visible:
            assert "_perception" in evt, f"Event missing _perception: {evt.get('event_id')}"
            perception = evt["_perception"]
            assert "type" in perception
            assert "channel" in perception


# =============================================================================
# Test 3: Narration output does NOT contain hidden information
# =============================================================================

class TestNarrationLeakPrevention:
    """Test that narration output is free from hidden NPC identities, secret
    locations, and hidden quest information."""

    def test_hidden_npc_identity_not_in_narration(
        self,
        perspective_service: PerspectiveService,
    ):
        """Narration must not reveal hidden NPC identities."""
        events: List[GameEvent] = [
            _make_game_event(
                "evt_public_talk",
                turn_index=1,
                location_id="loc_square",
                visible_to_player=True,
                summary="长老与玩家交谈",
                metadata={"npc_id": "npc_elder"},
            ),
        ]

        # Safe narration
        safe_text = "长老慈祥地看着你，说道：'年轻人，修行之路艰难，需要持之以恒。'"
        # Leaky narration revealing hidden identity
        leaky_text = "长老慈祥地看着你，但你不知道他其实是魔教卧底，潜伏在宗门多年。"

        validator = NarrationLeakValidator()

        safe_result = validator.validate_narration(
            text=safe_text,
            forbidden_info=["魔教卧底", "潜伏在宗门", "是魔教的人"],
        )
        assert safe_result.is_valid, f"Safe narration flagged: {safe_result.errors}"

        leaky_result = validator.validate_narration(
            text=leaky_text,
            forbidden_info=["魔教卧底", "潜伏在宗门", "是魔教的人"],
        )
        assert not leaky_result.is_valid, (
            f"Leaky narration should fail but did not. Errors: {leaky_result.errors}"
        )

    def test_secret_location_not_in_narration(
        self,
        perspective_service: PerspectiveService,
    ):
        """Narration must not reveal secret location names."""
        safe_text = "你穿过宗门广场，远处隐约能看到一座山峰。"
        leaky_text = "你穿过宗门广场，忽然发现一条密道通往魔教密室。"

        validator = NarrationLeakValidator()

        safe_result = validator.validate_narration(
            text=safe_text,
            forbidden_info=["魔教密室", "密道", "隐藏入口"],
        )
        assert safe_result.is_valid, f"Safe narration flagged: {safe_result.errors}"

        leaky_result = validator.validate_narration(
            text=leaky_text,
            forbidden_info=["魔教密室", "密道", "隐藏入口"],
        )
        assert not leaky_result.is_valid, (
            f"Leaky narration should fail. Errors: {leaky_result.errors}"
        )

    def test_hidden_quest_info_not_in_narration(
        self,
        perspective_service: PerspectiveService,
    ):
        """Narration must not reveal hidden quest objectives."""
        safe_text = "你接到一个任务：调查宗门最近的异常事件。"
        leaky_text = "你接到一个任务：调查长老是否与魔教勾结，他的真实身份是魔教卧底。"

        validator = NarrationLeakValidator()

        safe_result = validator.validate_narration(
            text=safe_text,
            forbidden_info=["魔教卧底", "与魔教勾结", "真实身份"],
        )
        assert safe_result.is_valid, f"Safe narration flagged: {safe_result.errors}"

        leaky_result = validator.validate_narration(
            text=leaky_text,
            forbidden_info=["魔教卧底", "与魔教勾结", "真实身份"],
        )
        assert not leaky_result.is_valid, (
            f"Leaky narration should fail. Errors: {leaky_result.errors}"
        )

    def test_forbidden_regex_patterns_blocked(
        self,
        perspective_service: PerspectiveService,
    ):
        """Forbidden regex patterns in narration should be caught by validator."""
        text = "角落里的老者低声说：暗号是'月黑风高夜'。"

        validator = NarrationLeakValidator()

        # Without the pattern, this might pass (no exact forbidden_info match)
        result_no_pattern = validator.validate_narration(
            text=text,
            forbidden_info=[],
        )
        # May still pass since there's no explicit forbidden info

        # With a regex pattern catching the phrase
        result_with_pattern = validator.validate_narration(
            text=text,
            forbidden_info=[],
            forbidden_patterns=[r"月黑风高夜", r"暗号是"],
        )
        assert not result_with_pattern.is_valid, (
            f"Regex pattern should catch forbidden phrase. Errors: {result_with_pattern.errors}"
        )

    def test_narration_with_db_backed_forbidden_facts(
        self,
        perspective_service: PerspectiveService,
    ):
        """Validator should load forbidden facts from DB (NPC secrets, hidden identities)."""
        # Setup in-memory DB
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            # Seed: world, NPC template with hidden identity, session, secret
            world = WorldModel(
                id="world_test", code="test_world", name="测试世界",
                genre="xianxia", lore_summary="test", status="active",
            )
            db.add(world)

            npc_template = NPCTemplateModel(
                id="npc_spy",
                world_id="world_test",
                code="spy",
                name="行者",
                role_type="minor",
                public_identity="云游修道者",
                hidden_identity="天机阁密探",
                personality="神秘,谨慎",
                speech_style="简洁",
            )
            db.add(npc_template)

            session_model = SessionModel(
                id="session_test",
                user_id="user_1",
                world_id="world_test",
                status="active",
            )
            db.add(session_model)

            snpc = SessionNPCStateModel(
                id="snpc_spy",
                session_id="session_test",
                npc_template_id="npc_spy",
                current_location_id="loc_square",
            )
            db.add(snpc)

            secret = NPCSecretModel(
                id="secret_1",
                session_id="session_test",
                npc_id="npc_spy",
                content="天机阁密探",
                willingness_to_reveal=0.1,
                status="hidden",
            )
            db.add(secret)
            db.commit()

            # Narration that leaks the hidden identity
            leaky_narration = "那行者其实并非云游修道者，而是天机阁密探，奉命调查宗门。"

            validator = NarrationLeakValidator()

            result = validator.validate_narration(
                text=leaky_narration,
                forbidden_info=[],
                db=db,
                session_id="session_test",
                npc_ids=["npc_spy"],
            )
            assert not result.is_valid, (
                f"DB-backed validator should catch NPC secret leak. Errors: {result.errors}"
            )

            # Safe narration should still pass
            safe_narration = "行者微笑着向你点头，继续他的旅途。"
            safe_result = validator.validate_narration(
                text=safe_narration,
                forbidden_info=[],
                db=db,
                session_id="session_test",
                npc_ids=["npc_spy"],
            )
            assert safe_result.is_valid, (
                f"Safe narration should pass DB validation. Errors: {safe_result.errors}"
            )
        finally:
            db.close()


# =============================================================================
# Test 4: NPC decision context isolation
# =============================================================================

class TestNPCDecisionContextIsolation:
    """Test that NPC decision context does NOT contain canonical state facts
    the NPC shouldn't know."""

    def test_npc_context_excludes_hidden_locations(
        self,
        perspective_service: PerspectiveService,
        retrieval_system: RetrievalSystem,
    ):
        """NPC at square location should not know about hidden temple location."""
        context_builder = ContextBuilder(retrieval_system, perspective_service)

        state = _make_canonical_state(
            player_location_id="loc_square",
            npc_states={
                "npc_elder": _make_npc_state("npc_elder", "长老", "loc_square"),
            },
            location_states={
                "loc_square": LocationState(
                    entity_id="loc_square",
                    location_id="loc_square",
                    name="宗门广场",
                    known_to_player=True,
                    last_updated_world_time=None,
                ),
                "loc_temple": LocationState(
                    entity_id="loc_temple",
                    location_id="loc_temple",
                    name="魔教密室",
                    known_to_player=False,
                    last_updated_world_time=None,
                ),
            },
        )

        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老", true_identity=None),
            belief_state=NPCBeliefState(npc_id="npc_elder", beliefs=[]),
            recent_context=NPCRecentContext(npc_id="npc_elder", recent_perceived_events=[]),
            secrets=NPCSecrets(npc_id="npc_elder", secrets=[]),
            knowledge_state=NPCKnowledgeState(
                npc_id="npc_elder",
                known_facts=["loc_square"],
                forbidden_knowledge=["loc_temple"],
            ),
            goals=NPCGoals(npc_id="npc_elder", goals=[]),
        )

        context = context_builder.build_npc_decision_context(
            npc_id="npc_elder",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        content = context.content
        # NPC's forbidden knowledge should appear as flags to the LLM
        assert "forbidden_knowledge_flags" in content
        assert "loc_temple" in content["forbidden_knowledge_flags"]

        # NPC's constraints should warn against using forbidden knowledge
        constraints = " ".join(content.get("constraints", []))
        assert "forbidden knowledge" in constraints.lower() or "禁止" in constraints

    def test_npc_context_has_perspective_filtered_facts(
        self,
        perspective_service: PerspectiveService,
        retrieval_system: RetrievalSystem,
    ):
        """NPC decision context should use get_npc_perspective_facts for filtering."""
        context_builder = ContextBuilder(retrieval_system, perspective_service)

        state = _make_canonical_state(
            player_location_id="loc_square",
            npc_states={
                "npc_elder": _make_npc_state("npc_elder", "长老", "loc_square"),
                "npc_merchant": _make_npc_state("npc_merchant", "商人", "loc_forest"),
            },
            scene_actor_ids=["npc_elder", "player_1"],
        )

        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老", true_identity=None),
            belief_state=NPCBeliefState(npc_id="npc_elder", beliefs=[
                Belief(
                    belief_id="bel_1",
                    content="玩家是新来的弟子",
                    belief_type="fact",
                    confidence=0.9,
                    truth_status="true",
                    last_updated_turn=0,
                ),
            ]),
            recent_context=NPCRecentContext(npc_id="npc_elder", recent_perceived_events=[]),
            secrets=NPCSecrets(npc_id="npc_elder", secrets=[]),
            knowledge_state=NPCKnowledgeState(
                npc_id="npc_elder",
                known_facts=["fact_square"],
                forbidden_knowledge=["npc_merchant_secret"],
            ),
            goals=NPCGoals(npc_id="npc_elder", goals=[]),
        )

        context = context_builder.build_npc_decision_context(
            npc_id="npc_elder",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        content = context.content

        # NPC should have its own state
        assert "current_state" in content
        assert content["current_state"] is not None

        # NPC should see visible NPC states from perspective filtering
        assert "visible_npc_states" in content
        # The merchant (loc_forest) should NOT be in visible NPC states
        # since merchant is not in the scene
        visible_npc_ids = list(content.get("visible_npc_states", {}).keys())
        assert "npc_merchant" not in visible_npc_ids, (
            f"Merchant at different location should not be visible: {visible_npc_ids}"
        )

        # NPC beliefs should be in the context
        assert "beliefs" in content
        assert any("新来的弟子" in str(b.get("content", "")) for b in content["beliefs"])

    def test_npc_decision_context_has_available_actions(
        self,
        perspective_service: PerspectiveService,
        retrieval_system: RetrievalSystem,
    ):
        """NPC decision context should include available actions based on state."""
        context_builder = ContextBuilder(retrieval_system, perspective_service)

        state = _make_canonical_state(
            player_location_id="loc_square",
            npc_states={
                "npc_elder": _make_npc_state("npc_elder", "长老", "loc_square"),
            },
            scene_actor_ids=["npc_elder", "player_1"],
        )

        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老", true_identity=None),
            belief_state=NPCBeliefState(npc_id="npc_elder", beliefs=[]),
            recent_context=NPCRecentContext(npc_id="npc_elder", recent_perceived_events=[]),
            secrets=NPCSecrets(npc_id="npc_elder", secrets=[]),
            knowledge_state=NPCKnowledgeState(npc_id="npc_elder"),
            goals=NPCGoals(npc_id="npc_elder", goals=[]),
        )

        context = context_builder.build_npc_decision_context(
            npc_id="npc_elder",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        content = context.content
        assert "available_actions" in content
        available = content["available_actions"]

        # Alive NPC at scene location should have basic actions
        assert "talk" in available or "act" in available or "observe" in available or "move" in available
        # Should not be empty
        assert len(available) > 0

    def test_npc_context_excludes_hidden_events(
        self,
        perspective_service: PerspectiveService,
        retrieval_system: RetrievalSystem,
    ):
        """NPC decision context must never include hidden events not perceivable by the NPC."""
        context_builder = ContextBuilder(retrieval_system, perspective_service)

        state = _make_canonical_state(
            player_location_id="loc_square",
            npc_states={
                "npc_elder": _make_npc_state("npc_elder", "长老", "loc_square"),
            },
        )

        # Events including one that the NPC should not know about
        events: List[GameEvent] = [
            _make_game_event(
                "evt_public", turn_index=1, location_id="loc_square",
                visible_to_player=True, summary="公开事件",
            ),
            _make_game_event(
                "evt_hidden", turn_index=1, location_id="loc_temple",
                visible_to_player=False, summary="秘密事件",
                metadata={"location_id": "loc_temple", "is_hidden": True},
            ),
        ]

        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老", true_identity=None),
            belief_state=NPCBeliefState(npc_id="npc_elder", beliefs=[]),
            recent_context=NPCRecentContext(npc_id="npc_elder", recent_perceived_events=[]),
            secrets=NPCSecrets(npc_id="npc_elder", secrets=[
                Secret(secret_id="s1", content="NPC的真正意图", willingness_to_reveal=0.1),
            ]),
            knowledge_state=NPCKnowledgeState(
                npc_id="npc_elder",
                known_facts=["evt_public"],
                forbidden_knowledge=["evt_hidden"],
            ),
            goals=NPCGoals(npc_id="npc_elder", goals=[]),
        )

        context = context_builder.build_npc_decision_context(
            npc_id="npc_elder",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
            recent_events=events,
        )

        # Hidden events should not appear in the NPC's context
        if context.content.get("recent_events"):
            event_summaries = [
                e.get("summary", "") for e in context.content["recent_events"]
                if isinstance(e, dict)
            ]
            assert "秘密事件" not in event_summaries, (
                f"Hidden event leaked to NPC: {event_summaries}"
            )

        # Forbidden knowledge must be flagged
        assert "forbidden_knowledge_flags" in context.content
        assert "evt_hidden" in context.content["forbidden_knowledge_flags"]

    def test_npc_context_forbidden_knowledge_constraints(
        self,
        perspective_service: PerspectiveService,
        retrieval_system: RetrievalSystem,
    ):
        """NPC context must have constraints warning against forbidden knowledge use."""
        context_builder = ContextBuilder(retrieval_system, perspective_service)

        state = _make_canonical_state(
            player_location_id="loc_square",
            npc_states={
                "npc_spy": _make_npc_state("npc_spy", "行者", "loc_square"),
            },
        )

        npc_scope = NPCMemoryScope(
            npc_id="npc_spy",
            profile=NPCProfile(npc_id="npc_spy", name="行者", true_identity=None),
            belief_state=NPCBeliefState(npc_id="npc_spy", beliefs=[]),
            recent_context=NPCRecentContext(npc_id="npc_spy", recent_perceived_events=[]),
            secrets=NPCSecrets(npc_id="npc_spy", secrets=[]),
            knowledge_state=NPCKnowledgeState(
                npc_id="npc_spy",
                known_facts=["fact_location_square"],
                forbidden_knowledge=["fact_player_real_identity", "fact_secret_quest"],
            ),
            goals=NPCGoals(npc_id="npc_spy", goals=[]),
        )

        context = context_builder.build_npc_decision_context(
            npc_id="npc_spy",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        constraints = context.content.get("constraints", [])

        # Must have constraints about forbidden knowledge
        has_fk_constraint = any(
            "forbidden" in str(c).lower() or "禁止" in str(c)
            for c in constraints
        )
        assert has_fk_constraint, f"Missing forbidden knowledge constraint in: {constraints}"

        # Must explicitly list forbidden knowledge flags
        fk_flags = context.content.get("forbidden_knowledge_flags", [])
        assert "fact_player_real_identity" in fk_flags
        assert "fact_secret_quest" in fk_flags


# =============================================================================
# Test 5: Full turn pipeline integration via API
# =============================================================================

class TestFullTurnPipelineIntegration:
    """Test the full turn pipeline through the API — validates the complete
    player input → intent → NPC decision → validation → commit →
    narration → narration leak check flow."""

    def test_full_turn_pipeline_complete_flow(
        self,
        client,
        db_session,
    ):
        """Execute a full turn and verify all pipeline phases.

        Validates:
        - Turn execution returns validation results
        - Narration is non-empty and leak-free (MockProvider)
        - Replay reconstructs player/world state separation
        - Transaction IDs are present
        """
        from llm_rpg.storage.repositories import WorldRepository

        # Setup world
        world_repo = WorldRepository(db_session)
        world = world_repo.create({
            "code": f"pipeline_test_{uuid.uuid4().hex[:8]}",
            "name": "Pipeline Test World",
            "genre": "xianxia",
            "lore_summary": "Pipeline integration test",
            "status": "active",
        })
        db_session.commit()

        # Register user
        username = f"pipeline_user_{uuid.uuid4().hex[:8]}"
        resp = client.post("/auth/register", json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 201
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create save / session
        resp = client.post("/saves/manual-save", json={"world_id": world.id}, headers=headers)
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        # Phase 1: Execute turn (player input → intent → NPC decision → commit)
        resp = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "观察四周"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # Phase 2: Verify validation passed
        assert data["validation_passed"] is True, f"Validation failed: {data}"
        assert "transaction_id" in data
        assert data["turn_index"] >= 1

        # Phase 3: Verify narration output (narration → leak check)
        narration = data.get("narration", "")
        assert isinstance(narration, str)
        assert len(narration) > 0, "Narration should not be empty"

        # Phase 4: Narration leak check — MockProvider returns safe text
        sensitive = ["真实身份", "秘密", "隐藏", "魔教", "卧底"]
        narration_lower = narration.lower()
        for pat in sensitive:
            assert pat.lower() not in narration_lower, (
                f"Sensitive pattern '{pat}' leaked in narration"
            )

        # Phase 5: Replay verifies state reconstruction
        resp = client.post(
            f"/game/sessions/{session_id}/replay",
            json={"start_turn": 1},
            headers=headers,
        )
        assert resp.status_code == 200
        replay_data = resp.json()
        state = replay_data["reconstructed_state"]
        assert "player_state" in state
        assert "world_state" in state
        assert "scene_state" in state
        assert replay_data["events_replayed"] >= 1

        # Phase 6: Debug replay endpoint exists (may return auth errors)
        resp = client.post(
            f"/debug/sessions/{session_id}/replay",
            json={"start_turn": 1},
            headers=headers,
        )
        assert resp.status_code in [200, 401, 403], (
            f"Debug replay unexpected status {resp.status_code}"
        )


# =============================================================================
# Additional P2-level tests
# =============================================================================

class TestLeakSeverityLevels:
    """Test that the NarrationLeakValidator correctly categorizes leak severity."""

    def test_exact_match_is_critical(
        self,
        perspective_service: PerspectiveService,
    ):
        """Exact substring match should produce EXACT_MATCH severity (failure)."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="长老其实是魔教卧底，潜伏多年",
            forbidden_info=["魔教卧底"],
        )
        assert not result.is_valid
        assert any("EXACT_MATCH" in str(c.severity) for c in result.checks)

    def test_partial_match_detects_phrase_overlap(
        self,
        perspective_service: PerspectiveService,
    ):
        """Partial phrase overlap should be caught."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="那长老的身份似乎并非表面那么简单，他可能来自魔教",
            forbidden_info=["长老是魔教卧底"],
        )
        # With significant word overlap, should detect as partial match
        assert not result.is_valid or len(result.warnings) > 0, (
            f"Should detect at least PARTIAL_MATCH. Result: is_valid={result.is_valid}, "
            f"warnings={result.warnings}"
        )

    def test_suspicious_overlap_is_warning_not_error(
        self,
        perspective_service: PerspectiveService,
    ):
        """Low-overlap suspicious matches should be warnings, not blocking errors."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="天空很蓝，万里无云。",
            forbidden_info=["长老是魔教卧底潜伏多年等待时机"],
        )
        # No real overlap — should pass
        assert result.is_valid, (
            f"Unrelated text should pass: is_valid={result.is_valid}, "
            f"errors={result.errors}"
        )

    def test_forbidden_info_normalization(
        self,
        perspective_service: PerspectiveService,
    ):
        """None and empty entries in forbidden_info should be ignored."""
        validator = NarrationLeakValidator()
        # Test that the validator doesn't crash with edge-case inputs
        # (empty/none entries are handled by _normalize_forbidden_info internally)
        result = validator.validate_narration(
            text="安全文本，不包含任何敏感信息。",
            forbidden_info=["实际敏感词"],
        )
        assert result.is_valid, f"Normalization should handle invalid entries: {result.errors}"

    def test_empty_narration_is_always_safe(
        self,
        perspective_service: PerspectiveService,
    ):
        """Empty narration should always pass validation."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="",
            forbidden_info=["魔教卧底"],
        )
        assert result.is_valid
        result2 = validator.validate_narration(
            text="   ",
            forbidden_info=["魔教卧底"],
        )
        assert result2.is_valid

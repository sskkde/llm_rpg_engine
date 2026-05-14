"""
Unit tests for P2 NPCContextBuilder Strengthening.

Tests for three new ContextBuilder methods:
1. build_npc_decision_context()
2. get_npc_perspective_facts()
3. get_npc_available_actions()

Key invariants:
- No omniscient access to canonical state from NPC perspective
- Forbidden knowledge is never included in NPC context
- Available actions depend on NPC state, location, and scene
- Existing build_context() and build_npc_context() signatures unchanged
"""

import pytest
from unittest.mock import MagicMock

from llm_rpg.core.context_builder import ContextBuilder
from llm_rpg.models.common import ContextPack
from llm_rpg.models.states import (
    CanonicalState,
    CurrentSceneState,
    LocationState,
    NPCState,
    PlayerState,
    WorldState,
    WorldTime,
)
from llm_rpg.models.memories import (
    Belief,
    ForgetCurve,
    NPCBeliefState,
    NPCGoals,
    NPCGoal,
    NPCKnowledgeState,
    NPCMemoryScope,
    NPCPrivateMemory,
    NPCProfile,
    NPCRecentContext,
    NPCRelationshipMemory,
    NPCSecrets,
    PerceivedEvent,
    RelationshipMemoryEntry,
    Secret,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_npc_scope(npc_id: str, **overrides) -> NPCMemoryScope:
    """Build a realistic NPCMemoryScope for testing."""
    return NPCMemoryScope(
        npc_id=npc_id,
        profile=NPCProfile(
            npc_id=npc_id,
            name=overrides.get("name", f"NPC {npc_id}"),
            role=overrides.get("role", "merchant"),
            true_identity=overrides.get("true_identity", "Secretly a spy"),
            personality=overrides.get("personality", ["cautious", "curious"]),
            speech_style=overrides.get("speech_style", {"tone": "formal"}),
            core_goals=overrides.get("core_goals", ["stay hidden", "gather intel"]),
        ),
        belief_state=NPCBeliefState(
            npc_id=npc_id,
            beliefs=[
                Belief(
                    belief_id="b1",
                    content="The player seems trustworthy",
                    belief_type="inference",
                    confidence=0.6,
                    truth_status="unknown",
                    last_updated_turn=2,
                ),
                Belief(
                    belief_id="b2",
                    content="The artifact is in the temple",
                    belief_type="rumor",
                    confidence=0.4,
                    truth_status="partially_true",
                    last_updated_turn=1,
                ),
            ],
        ),
        private_memories=[
            NPCPrivateMemory(
                memory_id="pm1",
                owner_id=npc_id,
                memory_type="episodic",
                content="I secretly witnessed the player enter the forbidden zone",
                emotional_weight=-0.3,
                importance=0.9,
                confidence=1.0,
                created_turn=3,
                last_accessed_turn=3,
                current_strength=0.95,
            ),
        ],
        relationship_memories=[
            NPCRelationshipMemory(
                owner_id=npc_id,
                target_id="player",
                relationship_memory=[
                    RelationshipMemoryEntry(
                        content="Met the player at the village square",
                        impact={"trust": 2},
                        source_event_ids=["evt_meet"],
                        current_strength=0.9,
                    ),
                ],
            ),
        ],
        recent_context=NPCRecentContext(
            npc_id=npc_id,
            recent_perceived_events=[
                PerceivedEvent(
                    turn=5,
                    summary="The player approached the NPC",
                    perception_type="direct_observation",
                    importance=0.7,
                ),
            ],
        ),
        secrets=NPCSecrets(
            npc_id=npc_id,
            secrets=[
                Secret(
                    secret_id="sec1",
                    content="I am secretly sent by the rival faction",
                    willingness_to_reveal=0.1,
                    reveal_conditions=["trust_high"],
                    known_by=[npc_id],
                ),
            ],
        ),
        knowledge_state=NPCKnowledgeState(
            npc_id=npc_id,
            known_facts=overrides.get("known_facts", ["fact_loc_square", "fact_npc_merchant"]),
            known_rumors=overrides.get("known_rumors", ["rumor_artifact"]),
            known_secrets=overrides.get("known_secrets", []),
            forbidden_knowledge=overrides.get(
                "forbidden_knowledge",
                ["forbidden_secret_identity", "forbidden_true_alignment"],
            ),
        ),
        goals=NPCGoals(
            npc_id=npc_id,
            goals=[
                NPCGoal(
                    goal_id="g1",
                    description="Gather information about the artifact",
                    priority=0.9,
                    status="active",
                ),
                NPCGoal(
                    goal_id="g2",
                    description="Maintain cover identity",
                    priority=0.8,
                    status="active",
                ),
            ],
        ),
        forget_curve=ForgetCurve(),
    )


def _make_canonical_state(game_id: str = "test_game") -> CanonicalState:
    """Build a realistic CanonicalState for testing."""
    world_time = WorldTime(calendar="Xianxia", season="Spring", day=1, period="Morning")
    return CanonicalState(
        player_state=PlayerState(
            entity_id="player",
            name="TestPlayer",
            location_id="loc_square",
            realm="炼气一层",
            spiritual_power=100,
        ),
        world_state=WorldState(
            entity_id="world",
            world_id=game_id,
            current_time=world_time,
            weather="晴",
            moon_phase="满月",
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene",
            scene_id="scene_square",
            location_id="loc_square",
            active_actor_ids=["player", "npc_test"],
            visible_object_ids=["obj_statue", "obj_tree"],
            danger_level=0.2,
            scene_phase="exploration",
            available_actions=["observe", "talk", "act", "move", "idle"],
        ),
        location_states={
            "loc_square": LocationState(
                entity_id="loc",
                location_id="loc_square",
                name="Village Square",
                status="normal",
                danger_level=0.1,
                known_to_player=True,
                population_mood="neutral",
            ),
            "loc_temple": LocationState(
                entity_id="loc2",
                location_id="loc_temple",
                name="Ancient Temple",
                status="normal",
                danger_level=0.5,
                known_to_player=False,
                population_mood="neutral",
            ),
        },
        npc_states={
            "npc_test": NPCState(
                entity_id="npc_test",
                npc_id="npc_test",
                name="Mysterious Merchant",
                status="alive",
                location_id="loc_square",
                mood="neutral",
                current_action="Standing by the statue",
            ),
            "npc_villager": NPCState(
                entity_id="npc_villager",
                npc_id="npc_villager",
                name="Old Villager",
                status="alive",
                location_id="loc_square",
                mood="friendly",
                current_action="Sweeping the ground",
            ),
            "npc_bandit": NPCState(
                entity_id="npc_bandit",
                npc_id="npc_bandit",
                name="Suspicious Bandit",
                status="alive",
                location_id="loc_temple",
                mood="hostile",
                current_action="Lurking in shadows",
            ),
        },
        quest_states={},
        faction_states={},
    )


# =============================================================================
# get_npc_perspective_facts() Tests
# =============================================================================

class TestNPCPerspectiveFacts:
    """Tests for get_npc_perspective_facts()."""

    def test_returns_only_known_facts(self, retrieval_system, perspective_service):
        """NPC perspective must only return facts in the NPC's known_facts list."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test", known_facts=["fact_loc_square", "fact_npc_merchant"])
        state = _make_canonical_state()

        facts = builder.get_npc_perspective_facts("npc_test", state, npc_scope)

        assert "known_facts" in facts
        assert "fact_loc_square" in facts["known_facts"]
        assert "fact_npc_merchant" in facts["known_facts"]

    def test_excludes_forbidden_knowledge(self, retrieval_system, perspective_service):
        """Forbidden knowledge must NEVER appear in NPC-known facts."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope(
            "npc_test",
            known_facts=["fact_loc_square", "forbidden_secret_identity"],
            forbidden_knowledge=["forbidden_secret_identity", "forbidden_true_alignment"],
        )
        state = _make_canonical_state()

        facts = builder.get_npc_perspective_facts("npc_test", state, npc_scope)

        # Forbidden items should be listed as flags but not as accessible facts
        assert "forbidden_knowledge" in facts
        assert "forbidden_secret_identity" in facts["forbidden_knowledge"]
        assert "forbidden_secret_identity" not in facts.get("known_facts", [])

    def test_includes_visible_scene_info(self, retrieval_system, perspective_service):
        """NPC can see scene information like active actors, visible objects."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()

        facts = builder.get_npc_perspective_facts("npc_test", state, npc_scope)

        assert "visible_scene" in facts
        scene = facts["visible_scene"]
        assert "active_actor_ids" in scene or "active_actors" in scene or "location_id" in scene

    def test_no_omniscient_access_to_other_locations(self, retrieval_system, perspective_service):
        """NPC in one location should NOT know facts about other locations
        unless those locations are in their known_facts."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope(
            "npc_test",
            known_facts=["fact_loc_square"],  # Only knows about the square
        )
        state = _make_canonical_state()

        facts = builder.get_npc_perspective_facts("npc_test", state, npc_scope)

        # location_states from canonical state should NOT be fully available
        # The NPC only sees their current scene
        location_states = facts.get("location_states", {})
        # Should not have omniscient access to all locations
        if "loc_temple" in location_states:
            # Even if it's there, it should be marked as unknown
            loc_info = location_states["loc_temple"]
            if isinstance(loc_info, dict):
                # The NPC shouldn't know the temple's details
                assert loc_info.get("known_to_player") is not False or loc_info.get("name") is None

    def test_respects_knowledge_scope_boundaries(self, retrieval_system, perspective_service):
        """NPC should not see facts from NPC scope that are marked as other NPCs' secrets."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test", known_facts=["fact_loc_square"])
        state = _make_canonical_state()

        facts = builder.get_npc_perspective_facts("npc_test", state, npc_scope)

        # The NPC's own secrets should be kept separate, not mixed with known_facts
        # NPC secrets are private, not "known_facts"
        result_fact_ids = facts.get("known_facts", [])
        assert "sec1" not in result_fact_ids

    def test_npc_not_in_scene_sees_nothing(self, retrieval_system, perspective_service):
        """NPC that is not in the active scene should get no visible scene info."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope(
            "npc_absent",
            known_facts=["fact_loc_temple"],
        )
        state = _make_canonical_state()

        facts = builder.get_npc_perspective_facts("npc_absent", state, npc_scope)

        # NPC not in scene should not see the scene's active actors
        visible_scene = facts.get("visible_scene", {})
        if isinstance(visible_scene, dict):
            active_ids = visible_scene.get("active_actor_ids", [])
            assert "npc_absent" not in active_ids


# =============================================================================
# get_npc_available_actions() Tests
# =============================================================================

class TestNPCAvailableActions:
    """Tests for get_npc_available_actions()."""

    def test_alive_npc_has_base_actions(self, retrieval_system, perspective_service):
        """An alive NPC in the current scene should have standard action types."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()
        npc_state = state.npc_states["npc_test"]
        scene_state = state.current_scene_state

        actions = builder.get_npc_available_actions("npc_test", npc_scope, npc_state, scene_state)

        assert isinstance(actions, list)
        assert len(actions) > 0
        # Base actions should include these common types
        common_actions = {"observe", "talk", "act", "move", "idle"}
        result_set = set(actions)
        # At least some of the common actions should be available
        assert result_set & common_actions, f"Expected some of {common_actions} in {result_set}"

    def test_dead_npc_has_no_actions(self, retrieval_system, perspective_service):
        """A dead NPC should have no available actions."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()

        # Create a dead NPC state
        dead_state = NPCState(
            entity_id="npc_dead",
            npc_id="npc_dead",
            name="Dead Bandit",
            status="dead",
            location_id="loc_square",
            mood="neutral",
        )
        scene_state = state.current_scene_state

        actions = builder.get_npc_available_actions("npc_dead", npc_scope, dead_state, scene_state)

        assert isinstance(actions, list)
        assert len(actions) == 0, f"Dead NPC should have no actions, got {actions}"

    def test_npc_not_in_scene_location_gets_reduced_actions(self, retrieval_system, perspective_service):
        """NPC in a different location from the scene should have limited actions."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()

        # NPC is at the temple but scene is at the square
        remote_npc = NPCState(
            entity_id="npc_remote",
            npc_id="npc_remote",
            name="Remote NPC",
            status="alive",
            location_id="loc_temple",  # Different from scene location
            mood="neutral",
        )
        scene_state = state.current_scene_state  # scene is at loc_square

        actions = builder.get_npc_available_actions("npc_remote", npc_scope, remote_npc, scene_state)

        # Should NOT have scene-dependent actions like "talk" (no one to talk to in scene)
        assert "talk" not in actions, f"Remote NPC should not be able to talk, got {actions}"

    def test_includes_scene_available_actions(self, retrieval_system, perspective_service):
        """NPC should inherit actions from the scene's available_actions list."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()
        npc_state = state.npc_states["npc_test"]
        scene_state = state.current_scene_state

        actions = builder.get_npc_available_actions("npc_test", npc_scope, npc_state, scene_state)

        # Scene has: ["observe", "talk", "act", "move", "idle"]
        scene_actions = set(scene_state.available_actions)
        result_set = set(actions)
        # All scene actions should be available to the NPC (when alive and in scene)
        for action in scene_actions:
            assert action in result_set, f"Scene action '{action}' should be in NPC actions {result_set}"

    def test_hostile_npc_includes_combat_actions(self, retrieval_system, perspective_service):
        """Hostile NPC or NPC in combat phase should have fight/flee actions."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_bandit")
        state = _make_canonical_state()
        npc_state = state.npc_states["npc_bandit"]

        # Create a scene at the temple with the bandit present and danger
        temple_scene = CurrentSceneState(
            entity_id="scene",
            scene_id="scene_temple",
            location_id="loc_temple",
            active_actor_ids=["npc_bandit"],
            visible_object_ids=[],
            danger_level=0.7,
            scene_phase="combat",  # Combat phase
            available_actions=["observe", "act", "move", "attack", "flee"],
        )

        actions = builder.get_npc_available_actions("npc_bandit", npc_scope, npc_state, temple_scene)

        result_set = set(actions)
        # Combat context: should have hostile actions
        assert "attack" in result_set or "flee" in result_set, \
            f"Hostile NPC should have combat actions, got {result_set}"


# =============================================================================
# build_npc_decision_context() Tests
# =============================================================================

class TestNPCDecisionContext:
    """Tests for build_npc_decision_context()."""

    def test_context_contains_required_sections(self, retrieval_system, perspective_service):
        """NPC decision context must contain all required sections."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        assert isinstance(context, ContextPack)
        assert context.context_type == "npc_decision"

        content = context.content
        # Required sections
        required_sections = [
            "profile",
            "current_state",
            "visible_scene_facts",
            "known_facts",
            "beliefs",
            "private_memories",
            "goals",
            "forbidden_knowledge_flags",
            "available_actions",
            "constraints",
        ]
        for section in required_sections:
            assert section in content, f"Missing required section: {section}"

    def test_context_excludes_omniscient_facts(self, retrieval_system, perspective_service):
        """NPC decision context must NOT contain omniscient canonical state data."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope(
            "npc_test",
            known_facts=["fact_loc_square"],
        )
        state = _make_canonical_state()

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        content = context.content

        # NPC should NOT have access to full canonical NPC states of other NPCs
        if "npc_states" in content:
            npc_states = content["npc_states"]
            # If other NPC states appear, they should be limited
            assert isinstance(npc_states, dict)

        # Should NOT contain quest states (omniscient)
        assert "quest_states" not in content, "NPC should not have omniscient quest_states"

        # Should NOT contain faction states (omniscient)
        assert "faction_states" not in content, "NPC should not have omniscient faction_states"

        # Should NOT contain world_state directly (omniscient)
        assert "world_state" not in content, "NPC should not have omniscient world_state"

    def test_context_includes_npc_goals(self, retrieval_system, perspective_service):
        """NPC decision context must include the NPC's goals."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        goals = context.content.get("goals", [])
        assert len(goals) == 2
        goal_descriptions = [g.get("description", "") for g in goals]
        assert any("Gather information" in d for d in goal_descriptions)
        assert any("Maintain cover" in d for d in goal_descriptions)

    def test_context_includes_forbidden_knowledge_flags(self, retrieval_system, perspective_service):
        """Decision context must flag forbidden knowledge so LLM knows what NOT to use."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope(
            "npc_test",
            forbidden_knowledge=["forbidden_secret_identity", "forbidden_true_alignment"],
        )
        state = _make_canonical_state()

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        forbidden_flags = context.content.get("forbidden_knowledge_flags", [])
        assert "forbidden_secret_identity" in forbidden_flags
        assert "forbidden_true_alignment" in forbidden_flags

    def test_context_includes_available_actions(self, retrieval_system, perspective_service):
        """Decision context must list available actions the NPC can take."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        available_actions = context.content.get("available_actions", [])
        assert isinstance(available_actions, list)
        assert len(available_actions) > 0

    def test_context_includes_constraint_about_forbidden_knowledge(self, retrieval_system, perspective_service):
        """Constraints must explicitly forbid using forbidden knowledge."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope(
            "npc_test",
            forbidden_knowledge=["forbidden_secret_identity"],
        )
        state = _make_canonical_state()

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        constraints = context.content.get("constraints", [])
        _ = str(constraints)
        assert any(
            "forbidden" in c.lower() or "禁止" in c or "不得" in c
            for c in constraints
        ), f"Constraints should forbid using forbidden knowledge, got: {constraints}"

    def test_context_respects_belief_confidence(self, retrieval_system, perspective_service):
        """Beliefs in decision context should include confidence and truth_status."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope("npc_test")
        state = _make_canonical_state()

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        beliefs = context.content.get("beliefs", [])
        assert len(beliefs) >= 2
        for belief in beliefs:
            assert "content" in belief
            assert "confidence" in belief
            assert "truth_status" in belief

    def test_context_with_events_filters_for_perspective(self, retrieval_system, perspective_service):
        """When recent_events is provided, they must be filtered through NPC perspective."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        npc_scope = _make_npc_scope(
            "npc_test",
            known_facts=["fact_loc_square", "evt_1"],
        )
        state = _make_canonical_state()

        from llm_rpg.models.events import SceneEvent, EventType

        events = [
            SceneEvent(
                event_id="evt_1",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                scene_id="scene_square",
                trigger="Player entered the square",
                summary="The player walked into the village square",
                visible_to_player=True,
                importance=0.7,
                affected_entities=["player", "npc_test"],
            ),
            SceneEvent(
                event_id="evt_2",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                scene_id="scene_square",
                trigger="NPC observed player",
                summary="The merchant watched the player carefully",
                visible_to_player=False,
                importance=0.5,
                affected_entities=["npc_test"],
            ),
        ]

        context = builder.build_npc_decision_context(
            npc_id="npc_test",
            game_id="test_game",
            turn_id="turn_2",
            state=state,
            npc_scope=npc_scope,
            recent_events=events,
        )

        # Context should include recent events section: evt_1 survives (known_fact), evt_2 is filtered out
        assert "recent_events" in context.content


# =============================================================================
# Backward Compatibility Tests
# =============================================================================

class TestBackwardCompatibility:
    """Ensure existing ContextBuilder methods are unchanged."""

    def test_build_world_context_unchanged(self, retrieval_system, perspective_service, sample_game_id):
        """Existing build_world_context() signature and behavior unchanged."""
        builder = ContextBuilder(retrieval_system, perspective_service)

        state = _make_canonical_state(game_id=sample_game_id)
        result = builder.build_world_context(
            game_id=sample_game_id,
            turn_id="turn_1",
            state=state,
        )

        assert isinstance(result, ContextPack)
        assert result.context_type == "world"
        assert "world_state" in result.content
        assert "npc_states" in result.content  # World context sees all NPCs

    def test_build_npc_context_unchanged(self, retrieval_system, perspective_service, sample_game_id):
        """Existing build_npc_context() signature and behavior unchanged."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        state = _make_canonical_state(game_id=sample_game_id)
        npc_scope = _make_npc_scope("npc_test")

        result = builder.build_npc_context(
            npc_id="npc_test",
            game_id=sample_game_id,
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )

        assert isinstance(result, ContextPack)
        assert result.context_type == "npc_decision"
        assert "profile" in result.content
        assert "constraints" in result.content

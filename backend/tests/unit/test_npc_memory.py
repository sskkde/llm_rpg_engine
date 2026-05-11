"""
Unit tests for NPCMemoryManager.

Tests memory decay/forgetting semantics, NPC memory stores and retrieves facts,
hidden/private info not leaked in NPC memory context, and memory bounds.
"""

import pytest

from llm_rpg.core.npc_memory import NPCMemoryManager
from llm_rpg.models.memories import (
    MemoryType,
    MemorySourceType,
    NPCProfile,
    ForgetCurve,
)


class TestNPCMemoryScopeCreation:
    """Test NPC memory scope creation."""

    def test_create_npc_scope_creates_scope(self):
        manager = NPCMemoryManager()
        
        scope = manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        assert scope is not None
        assert scope.npc_id == "npc_1"
        assert scope.profile.name == "Test NPC"

    def test_create_npc_scope_with_initial_goals(self):
        manager = NPCMemoryManager()
        
        from llm_rpg.models.memories import NPCGoal
        goals = [NPCGoal(goal_id="goal_1", description="Test goal")]
        
        scope = manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
            initial_goals=goals,
        )
        
        assert len(scope.goals.goals) == 1
        assert scope.goals.goals[0].description == "Test goal"

    def test_get_scope_returns_created_scope(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        scope = manager.get_scope("npc_1")
        
        assert scope is not None
        assert scope.npc_id == "npc_1"

    def test_get_scope_returns_none_for_unknown_npc(self):
        manager = NPCMemoryManager()
        
        scope = manager.get_scope("unknown_npc")
        
        assert scope is None


class TestNPCMemoryStoreAndRetrieve:
    """Test NPC memory stores and retrieves facts."""

    def test_add_memory_stores_memory(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        memory = manager.add_memory(
            npc_id="npc_1",
            content="Player helped me",
            memory_type=MemoryType.EPISODIC,
            current_turn=1,
        )
        
        assert memory is not None
        assert memory.content == "Player helped me"
        assert memory.memory_type == MemoryType.EPISODIC

    def test_add_memory_appears_in_scope(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_memory(
            npc_id="npc_1",
            content="Player helped me",
            memory_type=MemoryType.EPISODIC,
            current_turn=1,
        )
        
        scope = manager.get_scope("npc_1")
        assert len(scope.private_memories) == 1
        assert scope.private_memories[0].content == "Player helped me"

    def test_add_multiple_memories(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_memory(npc_id="npc_1", content="Memory 1", current_turn=1)
        manager.add_memory(npc_id="npc_1", content="Memory 2", current_turn=2)
        manager.add_memory(npc_id="npc_1", content="Memory 3", current_turn=3)
        
        scope = manager.get_scope("npc_1")
        assert len(scope.private_memories) == 3

    def test_add_memory_with_source_event_ids(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        memory = manager.add_memory(
            npc_id="npc_1",
            content="Observed event",
            source_event_ids=["evt_1", "evt_2"],
            current_turn=1,
        )
        
        assert memory.source_event_ids == ["evt_1", "evt_2"]

    def test_add_memory_with_importance(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        memory = manager.add_memory(
            npc_id="npc_1",
            content="Important event",
            importance=0.9,
            current_turn=1,
        )
        
        assert memory.importance == 0.9

    def test_add_memory_with_emotional_weight(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        memory = manager.add_memory(
            npc_id="npc_1",
            content="Emotional event",
            emotional_weight=0.8,
            current_turn=1,
        )
        
        assert memory.emotional_weight == 0.8


class TestNPCBeliefManagement:
    """Test NPC belief management."""

    def test_add_belief_stores_belief(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        belief = manager.add_belief(
            npc_id="npc_1",
            content="Player is trustworthy",
            belief_type="fact",
            confidence=0.8,
            current_turn=1,
        )
        
        assert belief is not None
        assert belief.content == "Player is trustworthy"
        assert belief.confidence == 0.8

    def test_add_belief_appears_in_scope(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_belief(
            npc_id="npc_1",
            content="Player is trustworthy",
            current_turn=1,
        )
        
        scope = manager.get_scope("npc_1")
        assert len(scope.belief_state.beliefs) == 1

    def test_add_belief_with_source_event(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        belief = manager.add_belief(
            npc_id="npc_1",
            content="Player helped the village",
            source_event_ids=["evt_1"],
            current_turn=1,
        )
        
        assert belief.source_event_ids == ["evt_1"]


class TestNPCSecretManagement:
    """Test NPC secret management - hidden/private info."""

    def test_add_secret_stores_secret(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        secret = manager.add_secret(
            npc_id="npc_1",
            content="I am actually a spy",
            willingness_to_reveal=0.1,
        )
        
        assert secret is not None
        assert secret.content == "I am actually a spy"
        assert secret.willingness_to_reveal == 0.1

    def test_add_secret_appears_in_scope(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_secret(
            npc_id="npc_1",
            content="Secret identity",
        )
        
        scope = manager.get_scope("npc_1")
        assert len(scope.secrets.secrets) == 1

    def test_secret_not_in_known_facts(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_secret(npc_id="npc_1", content="Secret")
        
        scope = manager.get_scope("npc_1")
        assert "secret" not in scope.knowledge_state.known_facts

    def test_secret_not_in_memory_context(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_secret(npc_id="npc_1", content="I am a spy")
        manager.add_memory(
            npc_id="npc_1",
            content="Normal memory",
            current_turn=1,
        )
        
        memories = manager.get_memories_for_context("npc_1", current_turn=1)
        
        for mem in memories:
            assert "spy" not in mem.content.lower()


class TestMemoryDecay:
    """Test memory decay/forgetting semantics."""

    def test_compute_memory_strength_with_recent_access(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        from llm_rpg.models.memories import Memory
        memory = Memory(
            memory_id="mem_1",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="Recent memory",
            importance=0.8,
            emotional_weight=0.5,
            created_turn=1,
            last_accessed_turn=1,
        )
        
        strength = manager.compute_memory_strength(memory, current_turn=1)
        
        assert strength >= 0.0
        assert strength <= 1.0

    def test_compute_memory_strength_decays_with_time(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
            initial_goals=[],
        )
        scope = manager.get_scope("npc_1")
        scope.forget_curve = ForgetCurve(time_decay=0.1)
        
        from llm_rpg.models.memories import Memory
        memory = Memory(
            memory_id="mem_1",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="Old memory",
            importance=0.5,
            emotional_weight=0.0,
            created_turn=1,
            last_accessed_turn=1,
        )
        
        recent_strength = manager.compute_memory_strength(memory, current_turn=1)
        old_strength = manager.compute_memory_strength(memory, current_turn=10)
        
        assert old_strength < recent_strength

    def test_compute_memory_strength_bounded(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        from llm_rpg.models.memories import Memory
        memory = Memory(
            memory_id="mem_1",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="Memory",
            importance=0.5,
            created_turn=1,
            last_accessed_turn=1,
        )
        
        strength = manager.compute_memory_strength(memory, current_turn=100)
        
        assert strength >= 0.0
        assert strength <= 1.0

    def test_get_memories_for_context_filters_by_strength(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_memory(
            npc_id="npc_1",
            content="Important memory",
            importance=0.9,
            current_turn=1,
        )
        manager.add_memory(
            npc_id="npc_1",
            content="Unimportant memory",
            importance=0.1,
            current_turn=1,
        )
        
        memories = manager.get_memories_for_context(
            npc_id="npc_1",
            current_turn=1,
            min_strength=0.5,
        )
        
        assert all(m.current_strength >= 0.5 for m in memories)

    def test_get_memories_for_context_respects_limit(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        for i in range(20):
            manager.add_memory(
                npc_id="npc_1",
                content=f"Memory {i}",
                importance=0.8,
                current_turn=1,
            )
        
        memories = manager.get_memories_for_context(
            npc_id="npc_1",
            current_turn=1,
            limit=5,
        )
        
        assert len(memories) <= 5


class TestMemoryBounds:
    """Test memory bounds (no infinite growth)."""

    def test_recent_perceived_events_bounded(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        for i in range(30):
            manager.add_perceived_event(
                npc_id="npc_1",
                turn=i,
                summary=f"Event {i}",
            )
        
        scope = manager.get_scope("npc_1")
        assert len(scope.recent_context.recent_perceived_events) <= 20

    def test_get_memories_for_context_returns_empty_for_unknown_npc(self):
        manager = NPCMemoryManager()
        
        memories = manager.get_memories_for_context("unknown_npc", current_turn=1)
        
        assert memories == []

    def test_compute_memory_strength_returns_default_for_unknown_scope(self):
        manager = NPCMemoryManager()
        
        from llm_rpg.models.memories import Memory
        memory = Memory(
            memory_id="mem_1",
            owner_type="npc",
            owner_id="unknown_npc",
            memory_type=MemoryType.EPISODIC,
            content="Memory",
            importance=0.5,
            current_strength=0.7,
            created_turn=1,
            last_accessed_turn=1,
        )
        
        strength = manager.compute_memory_strength(memory, current_turn=1)
        
        assert strength == 0.7


class TestRelationshipMemory:
    """Test relationship memory management."""

    def test_add_relationship_memory_creates_entry(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_relationship_memory(
            npc_id="npc_1",
            target_id="player",
            content="Player helped me",
            impact={"trust": 1, "favor": 1},
        )
        
        scope = manager.get_scope("npc_1")
        assert len(scope.relationship_memories) == 1
        assert scope.relationship_memories[0].target_id == "player"

    def test_add_relationship_memory_appends_to_existing(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_relationship_memory(
            npc_id="npc_1",
            target_id="player",
            content="First interaction",
            impact={"trust": 1},
        )
        manager.add_relationship_memory(
            npc_id="npc_1",
            target_id="player",
            content="Second interaction",
            impact={"trust": 1},
        )
        
        scope = manager.get_scope("npc_1")
        assert len(scope.relationship_memories) == 1
        assert len(scope.relationship_memories[0].relationship_memory) == 2


class TestKnowledgeState:
    """Test knowledge state management."""

    def test_update_knowledge_adds_known_facts(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.update_knowledge(
            npc_id="npc_1",
            known_facts=["fact_1", "fact_2"],
        )
        
        scope = manager.get_scope("npc_1")
        assert "fact_1" in scope.knowledge_state.known_facts
        assert "fact_2" in scope.knowledge_state.known_facts

    def test_update_knowledge_adds_known_rumors(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.update_knowledge(
            npc_id="npc_1",
            known_rumors=["rumor_1"],
        )
        
        scope = manager.get_scope("npc_1")
        assert "rumor_1" in scope.knowledge_state.known_rumors

    def test_update_knowledge_adds_forbidden_knowledge(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.update_knowledge(
            npc_id="npc_1",
            forbidden_knowledge=["forbidden_1"],
        )
        
        scope = manager.get_scope("npc_1")
        assert "forbidden_1" in scope.knowledge_state.forbidden_knowledge


class TestGoalManagement:
    """Test goal management."""

    def test_add_goal_stores_goal(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        goal = manager.add_goal(
            npc_id="npc_1",
            description="Protect the village",
            priority=0.8,
        )
        
        assert goal is not None
        assert goal.description == "Protect the village"
        assert goal.priority == 0.8

    def test_add_goal_appears_in_scope(self):
        manager = NPCMemoryManager()
        manager.create_npc_scope(
            npc_id="npc_1",
            profile=NPCProfile(npc_id="npc_1", name="Test NPC"),
        )
        
        manager.add_goal(npc_id="npc_1", description="Goal 1")
        manager.add_goal(npc_id="npc_1", description="Goal 2")
        
        scope = manager.get_scope("npc_1")
        assert len(scope.goals.goals) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

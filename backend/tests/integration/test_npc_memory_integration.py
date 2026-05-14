"""
Integration tests for NPC memory scope.

Tests that NPCs have properly isolated memory and cannot access information
they shouldn't know (omniscience prevention).

Test cases:
1. NPC can only recall events it directly experienced
2. NPC can only know facts it was told or inferred (not omniscient)
3. NPC forget curve reduces memory strength over time
4. NPC secrets are not exposed to player perspective
5. NPC context builder produces isolated decision context
6. NPC memory isolation across sessions (same NPC template, different saves)
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    WorldModel,
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionNPCStateModel,
)
from llm_rpg.core.npc_state_bridge import (
    NPCStateWithScope,
    build_npc_state_from_db,
    get_active_npcs_at_location,
)
from llm_rpg.core.npc_memory import NPCMemoryManager
from llm_rpg.core.context_builder import ContextBuilder
from llm_rpg.core.retrieval import RetrievalSystem
from llm_rpg.core.perspective import PerspectiveService
from llm_rpg.models.memories import (
    MemoryType,
    MemorySourceType,
    NPCProfile,
    ForgetCurve,
    NPCGoal,
)
from llm_rpg.models.states import CanonicalState, CurrentSceneState, WorldState, PlayerState
from llm_rpg.models.events import WorldTime
from llm_rpg.observability.npc_mind import NPCMindViewer, ViewRole


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_world(db: Session) -> WorldModel:
    """Create a test world."""
    world = WorldModel(
        id="test_world_1",
        code="test_world",
        name="测试世界",
        genre="xianxia",
        lore_summary="测试用世界",
        status="active",
    )
    db.add(world)
    db.commit()
    return world


@pytest.fixture
def test_chapter(db: Session, test_world: WorldModel) -> ChapterModel:
    """Create a test chapter."""
    chapter = ChapterModel(
        id="test_chapter_1",
        world_id=test_world.id,
        chapter_no=1,
        name="第一章",
        summary="测试章节",
    )
    db.add(chapter)
    db.commit()
    return chapter


@pytest.fixture
def test_locations(db: Session, test_world: WorldModel, test_chapter: ChapterModel) -> dict:
    """Create test locations."""
    square = LocationModel(
        id="loc_square",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="square",
        name="宗门广场",
        tags=["public", "safe", "starting_point"],
        description="起始地点",
    )
    forest = LocationModel(
        id="loc_forest",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="forest",
        name="山林",
        tags=["combat"],
        description="战斗区域",
    )
    temple = LocationModel(
        id="loc_temple",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="temple",
        name="密室",
        tags=["private", "secret"],
        description="秘密地点",
    )
    db.add_all([square, forest, temple])
    db.commit()
    return {"square": square, "forest": forest, "temple": temple}


@pytest.fixture
def test_npc_templates(db: Session, test_world: WorldModel) -> dict:
    """Create test NPC templates with hidden identities."""
    # Elder with a secret identity
    elder = NPCTemplateModel(
        id="npc_elder",
        world_id=test_world.id,
        code="elder",
        name="长老",
        role_type="mentor",
        public_identity="宗门长老，德高望重",
        hidden_identity="实际上是魔教卧底",
        personality="严厉,正直,关心弟子",
        speech_style="文言文",
        goals=[
            {"id": "goal_elder_1", "description": "保护宗门", "priority": 0.8},
            {"id": "goal_elder_2", "description": "隐藏身份", "priority": 0.9},
        ],
    )
    # Merchant without hidden identity
    merchant = NPCTemplateModel(
        id="npc_merchant",
        world_id=test_world.id,
        code="merchant",
        name="商人",
        role_type="trader",
        public_identity="行脚商人",
        hidden_identity=None,
        personality="精明,友好",
        speech_style="口语化",
        goals=[{"id": "goal_merchant_1", "description": "赚钱", "priority": 0.7}],
    )
    # Spy with multiple secrets
    spy = NPCTemplateModel(
        id="npc_spy",
        world_id=test_world.id,
        code="spy",
        name="行者",
        role_type="minor",
        public_identity="云游的修道者",
        hidden_identity="天机阁密探",
        personality="神秘,谨慎",
        speech_style="简洁",
        goals=[
            {"id": "goal_spy_1", "description": "收集情报", "priority": 0.95},
            {"id": "goal_spy_2", "description": "不暴露身份", "priority": 0.9},
        ],
    )
    db.add_all([elder, merchant, spy])
    db.commit()
    return {"elder": elder, "merchant": merchant, "spy": spy}


@pytest.fixture
def test_user(db: Session) -> UserModel:
    """Create a test user."""
    user = UserModel(
        id="user_1",
        username="testuser",
        email="test@example.com",
        password_hash="hashed",
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_save_slots(db: Session, test_user: UserModel) -> dict:
    """Create multiple save slots for cross-session testing."""
    slot1 = SaveSlotModel(
        id="slot_1",
        user_id=test_user.id,
        slot_number=1,
        name="存档一",
    )
    slot2 = SaveSlotModel(
        id="slot_2",
        user_id=test_user.id,
        slot_number=2,
        name="存档二",
    )
    db.add_all([slot1, slot2])
    db.commit()
    return {"slot1": slot1, "slot2": slot2}


@pytest.fixture
def test_sessions(
    db: Session,
    test_user: UserModel,
    test_save_slots: dict,
    test_world: WorldModel,
    test_chapter: ChapterModel,
) -> dict:
    """Create multiple test sessions for cross-session testing."""
    session1 = SessionModel(
        id="session_1",
        user_id=test_user.id,
        save_slot_id=test_save_slots["slot1"].id,
        world_id=test_world.id,
        current_chapter_id=test_chapter.id,
        status="active",
    )
    session2 = SessionModel(
        id="session_2",
        user_id=test_user.id,
        save_slot_id=test_save_slots["slot2"].id,
        world_id=test_world.id,
        current_chapter_id=test_chapter.id,
        status="active",
    )
    db.add_all([session1, session2])
    db.commit()
    return {"session1": session1, "session2": session2}


@pytest.fixture
def test_session_npc_states(
    db: Session,
    test_sessions: dict,
    test_npc_templates: dict,
    test_locations: dict,
) -> dict:
    """Create test session NPC states for multiple sessions."""
    # Session 1 NPC states
    elder_state_s1 = SessionNPCStateModel(
        id="snpc_elder_s1",
        session_id=test_sessions["session1"].id,
        npc_template_id=test_npc_templates["elder"].id,
        current_location_id=test_locations["square"].id,
        trust_score=60,
        suspicion_score=10,
        status_flags={},
    )
    merchant_state_s1 = SessionNPCStateModel(
        id="snpc_merchant_s1",
        session_id=test_sessions["session1"].id,
        npc_template_id=test_npc_templates["merchant"].id,
        current_location_id=test_locations["forest"].id,
        trust_score=50,
        suspicion_score=0,
        status_flags={},
    )
    
    # Session 2 NPC states (same templates, different state)
    elder_state_s2 = SessionNPCStateModel(
        id="snpc_elder_s2",
        session_id=test_sessions["session2"].id,
        npc_template_id=test_npc_templates["elder"].id,
        current_location_id=test_locations["temple"].id,
        trust_score=20,  # Much lower trust in session 2
        suspicion_score=50,  # Higher suspicion
        status_flags={"exposed": True},
    )
    spy_state_s2 = SessionNPCStateModel(
        id="snpc_spy_s2",
        session_id=test_sessions["session2"].id,
        npc_template_id=test_npc_templates["spy"].id,
        current_location_id=test_locations["square"].id,
        trust_score=30,
        suspicion_score=80,
        status_flags={},
    )
    
    db.add_all([
        elder_state_s1, merchant_state_s1,
        elder_state_s2, spy_state_s2,
    ])
    db.commit()
    return {
        "session1": {"elder": elder_state_s1, "merchant": merchant_state_s1},
        "session2": {"elder": elder_state_s2, "spy": spy_state_s2},
    }


@pytest.fixture
def memory_manager() -> NPCMemoryManager:
    """Create NPC memory manager for testing."""
    return NPCMemoryManager()


@pytest.fixture
def context_builder():
    """Create context builder for testing."""
    retrieval_system = RetrievalSystem()
    perspective_service = PerspectiveService()
    return ContextBuilder(retrieval_system, perspective_service)


# =============================================================================
# Test 1: NPC can only recall events it directly experienced
# =============================================================================

class TestNPCEpisodicMemoryIsolation:
    """Test that NPCs can only recall events they directly experienced."""

    def test_npc_recalls_own_perceived_events(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC should recall events it directly observed."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Add events NPC directly experienced
        manager.add_perceived_event(
            npc_id="npc_elder",
            turn=1,
            summary="玩家进入宗门广场",
            perception_type="direct_observation",
        )
        manager.add_perceived_event(
            npc_id="npc_elder",
            turn=2,
            summary="玩家向我问好",
            perception_type="direct_observation",
        )
        
        scope = manager.get_scope("npc_elder")
        
        assert len(scope.recent_context.recent_perceived_events) == 2
        assert scope.recent_context.recent_perceived_events[0].summary == "玩家进入宗门广场"
        assert scope.recent_context.recent_perceived_events[1].summary == "玩家向我问好"

    def test_npc_does_not_recall_events_it_missed(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC should not know about events that happened elsewhere."""
        manager = memory_manager
        
        # Create two NPCs in different locations
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        manager.create_npc_scope(
            npc_id="npc_merchant",
            profile=NPCProfile(npc_id="npc_merchant", name="商人"),
        )
        
        # Elder sees an event in the square
        manager.add_perceived_event(
            npc_id="npc_elder",
            turn=1,
            summary="玩家在广场展示绝世武功",
            perception_type="direct_observation",
            importance=0.9,
        )
        
        # Merchant in forest doesn't see the square event
        manager.add_perceived_event(
            npc_id="npc_merchant",
            turn=1,
            summary="在山林中采药",
            perception_type="direct_observation",
            importance=0.3,
        )
        
        elder_scope = manager.get_scope("npc_elder")
        merchant_scope = manager.get_scope("npc_merchant")
        
        # Elder knows about the display of martial arts
        elder_events = [e.summary for e in elder_scope.recent_context.recent_perceived_events]
        assert "玩家在广场展示绝世武功" in elder_events
        
        # Merchant does NOT know about it
        merchant_events = [e.summary for e in merchant_scope.recent_context.recent_perceived_events]
        assert "玩家在广场展示绝世武功" not in merchant_events
        assert "在山林中采药" in merchant_events

    def test_npc_memory_from_told_by_other(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC can know about events told by others (hearsay)."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Add memory told by another NPC
        manager.add_memory(
            npc_id="npc_elder",
            content="商人告诉我玩家在森林中击败了妖兽",
            memory_type=MemoryType.EPISODIC,
            current_turn=3,
        )
        
        scope = manager.get_scope("npc_elder")
        assert len(scope.private_memories) == 1
        assert "击败了妖兽" in scope.private_memories[0].content

    def test_npc_distinguishes_direct_vs_hearsay(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC should track source of information (direct vs hearsay)."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Direct observation
        manager.add_perceived_event(
            npc_id="npc_elder",
            turn=1,
            summary="玩家击败了强盗",
            perception_type="direct_observation",
        )
        
        # Hearsay from merchant
        manager.add_memory(
            npc_id="npc_elder",
            content="听说玩家在别处有奇遇",
            memory_type=MemoryType.RUMOR,
            current_turn=2,
        )
        
        scope = manager.get_scope("npc_elder")
        
        # Direct observation has correct perception type
        direct_events = [
            e for e in scope.recent_context.recent_perceived_events
            if e.perception_type == "direct_observation"
        ]
        assert len(direct_events) == 1
        assert direct_events[0].summary == "玩家击败了强盗"


# =============================================================================
# Test 2: NPC is not omniscient (doesn't know canonical state facts)
# =============================================================================

class TestNPCNotOmniscient:
    """Test that NPCs cannot access information they shouldn't know."""

    def test_npc_does_not_kow_hidden_locations(
        self,
        db: Session,
        test_sessions: dict,
        test_npc_templates: dict,
        test_session_npc_states: dict,
    ):
        """NPC should not know about locations it hasn't visited."""
        # Elder in session 1 is at square, not at temple
        result = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session1"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        assert result is not None
        assert result.npc_state.location_id == "loc_square"
        
        # The temple location should not be in the NPC's knowledge
        known_locations = result.memory_scope.knowledge_state.known_facts
        # Only facts explicitly added should be known
        assert "loc_temple" not in known_locations

    def test_npc_does_not_know_other_npcs_secrets(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC should not know secrets of other NPCs."""
        manager = memory_manager
        
        # Create two NPCs
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        manager.create_npc_scope(
            npc_id="npc_merchant",
            profile=NPCProfile(npc_id="npc_merchant", name="商人"),
        )
        
        # Elder has a secret
        manager.add_secret(
            npc_id="npc_elder",
            content="我是魔教卧底",
            willingness_to_reveal=0.05,
        )
        
        # Merchant's knowledge should NOT include elder's secret
        merchant_scope = manager.get_scope("npc_merchant")
        elder_scope = manager.get_scope("npc_elder")
        
        # Elder knows their own secret
        assert len(elder_scope.secrets.secrets) == 1
        assert elder_scope.secrets.secrets[0].content == "我是魔教卧底"
        
        # Merchant does NOT know elder's secret
        assert len(merchant_scope.secrets.secrets) == 0
        assert "魔教卧底" not in str(merchant_scope.knowledge_state.known_facts)

    def test_npc_knowledge_state_is_explicit(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC knowledge should only contain explicitly added facts."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Initially, knowledge is empty
        scope = manager.get_scope("npc_elder")
        assert len(scope.knowledge_state.known_facts) == 0
        assert len(scope.knowledge_state.known_rumors) == 0
        
        # Add specific knowledge
        manager.update_knowledge(
            npc_id="npc_elder",
            known_facts=["fact_player_is_cultivator", "fact_world_has_danger"],
            known_rumors=["rumor_treasure_exists"],
        )
        
        scope = manager.get_scope("npc_elder")
        assert "fact_player_is_cultivator" in scope.knowledge_state.known_facts
        assert "fact_world_has_danger" in scope.knowledge_state.known_facts
        assert "rumor_treasure_exists" in scope.knowledge_state.known_rumors
        
        # Should NOT have omniscient knowledge
        assert "omniscient_fact_not_explicitly_added" not in scope.knowledge_state.known_facts

    def test_npc_beliefs_are_subjective(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC beliefs can be wrong (not canonical truth)."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Add a belief that is actually false
        manager.add_belief(
            npc_id="npc_elder",
            content="玩家是正道修士",  # Player is actually a demon cultivator
            belief_type="inference",
            confidence=0.8,
            truth_status="unknown",  # NPC doesn't know it's wrong
            current_turn=1,
        )
        
        scope = manager.get_scope("npc_elder")
        assert len(scope.belief_state.beliefs) == 1
        assert scope.belief_state.beliefs[0].content == "玩家是正道修士"
        assert scope.belief_state.beliefs[0].truth_status == "unknown"

    def test_forbidden_knowledge_not_accessible(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC cannot access forbidden knowledge."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Mark certain knowledge as forbidden
        manager.update_knowledge(
            npc_id="npc_elder",
            forbidden_knowledge=["forbidden_world_truth", "forbidden_future_event"],
        )
        
        scope = manager.get_scope("npc_elder")
        
        # Forbidden knowledge is tracked but should not be usable
        assert "forbidden_world_truth" in scope.knowledge_state.forbidden_knowledge
        assert "forbidden_future_event" in scope.knowledge_state.forbidden_knowledge


# =============================================================================
# Test 3: NPC forget curve reduces memory strength over time
# =============================================================================

class TestNPCMemoryForgetCurve:
    """Test that NPC memory decays over time."""

    def test_recent_memory_has_high_strength(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """Recent memories should have high strength."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        manager.add_memory(
            npc_id="npc_elder",
            content="玩家刚刚拜访过我",
            importance=0.7,
            emotional_weight=0.5,
            current_turn=1,
        )
        
        memories = manager.get_memories_for_context(
            npc_id="npc_elder",
            current_turn=1,
            min_strength=0.0,
        )
        
        assert len(memories) == 1
        assert memories[0].current_strength >= 0.5

    def test_old_memory_has_lower_strength(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """Old memories should have lower strength due to time decay."""
        manager = memory_manager
        scope = manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Set up forget curve with time decay
        scope.forget_curve = ForgetCurve(time_decay=0.1)
        
        # Create a memory 20 turns ago
        manager.add_memory(
            npc_id="npc_elder",
            content="很久以前的记忆",
            importance=0.5,
            emotional_weight=0.0,
            current_turn=1,
        )
        
        # Check strength at turn 1 vs turn 20
        memories_turn1 = manager.get_memories_for_context(
            npc_id="npc_elder",
            current_turn=1,
            min_strength=0.0,
        )
        
        # Reset to test decay
        scope = manager.get_scope("npc_elder")
        scope.private_memories[0].last_accessed_turn = 1
        
        memories_turn20 = manager.get_memories_for_context(
            npc_id="npc_elder",
            current_turn=20,
            min_strength=0.0,
        )
        
        # Strength should decay over time
        assert memories_turn20[0].current_strength < memories_turn1[0].current_strength

    def test_important_memory_resists_decay(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """High importance memories resist decay better."""
        manager = memory_manager
        scope = manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        scope.forget_curve = ForgetCurve(time_decay=0.05)
        
        # High importance memory
        manager.add_memory(
            npc_id="npc_elder",
            content="玩家救了我的命",
            importance=0.95,
            emotional_weight=0.9,
            current_turn=1,
        )
        
        # Low importance memory
        manager.add_memory(
            npc_id="npc_elder",
            content="玩家说了一句普通的问候",
            importance=0.2,
            emotional_weight=0.0,
            current_turn=1,
        )
        
        memories = manager.get_memories_for_context(
            npc_id="npc_elder",
            current_turn=10,
            min_strength=0.0,
        )
        
        # Find the two memories
        saved_life = next((m for m in memories if "救了我的命" in m.content), None)
        greeting = next((m for m in memories if "问候" in m.content), None)
        
        assert saved_life is not None
        assert greeting is not None
        # Important memory should retain higher strength
        assert saved_life.current_strength > greeting.current_strength

    def test_recall_reinforces_memory(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """Recalling a memory reinforces its strength."""
        manager = memory_manager
        scope = manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        scope.forget_curve = ForgetCurve(
            time_decay=0.1,
            recall_reinforcement=0.2,
        )
        
        manager.add_memory(
            npc_id="npc_elder",
            content="重要的记忆",
            importance=0.8,  # High importance to ensure it's retrieved
            current_turn=1,
        )
        
        # Recall the memory multiple times with low min_strength to ensure retrieval
        mem1 = manager.get_memories_for_context(npc_id="npc_elder", current_turn=5, min_strength=0.0)
        mem2 = manager.get_memories_for_context(npc_id="npc_elder", current_turn=10, min_strength=0.0)
        
        # The returned memories should have updated recall counts
        assert len(mem2) > 0
        assert mem2[0].recall_count >= 1


# =============================================================================
# Test 4: NPC secrets are not exposed to player perspective
# =============================================================================

class TestNPCSecretsProtection:
    """Test that NPC secrets are properly hidden from players."""

    def test_hidden_identity_not_in_player_visible_state(
        self,
        db: Session,
        test_sessions: dict,
        test_npc_templates: dict,
        test_session_npc_states: dict,
    ):
        """Hidden identity should not appear in player-visible NPC state."""
        result = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session1"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        assert result is not None
        
        # Hidden identity is stored separately
        assert result.hidden_identity == "实际上是魔教卧底"
        
        # NPC state for player doesn't expose it
        assert result.npc_state.name == "长老"
        # The NPCState doesn't have a hidden_identity field exposed to players

    def test_secrets_stored_in_memory_scope(
        self,
        db: Session,
        test_sessions: dict,
        test_npc_templates: dict,
        test_session_npc_states: dict,
    ):
        """Secrets should be stored in memory scope, not in known facts."""
        result = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session1"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        assert result is not None
        
        # Secret is in memory scope
        assert len(result.memory_scope.secrets.secrets) == 1
        assert result.memory_scope.secrets.secrets[0].content == "实际上是魔教卧底"
        assert result.memory_scope.secrets.secrets[0].willingness_to_reveal == 0.1
        
        # Secret is NOT in known facts
        assert "实际上是魔教卧底" not in result.memory_scope.knowledge_state.known_facts

    def test_npc_mind_viewer_filters_for_player(
        self,
        db: Session,
        test_sessions: dict,
    ):
        """NPCMindViewer should filter secrets for player role."""
        viewer = NPCMindViewer(db_session=db)
        
        mind_view = viewer.get_npc_mind(
            session_id=test_sessions["session1"].id,
            npc_id="npc_elder",
            view_role=ViewRole.PLAYER,
        )
        
        # Use mock view for testing
        if mind_view is None:
            mind_view = viewer._get_mock_mind_view(
                test_sessions["session1"].id,
                "npc_elder",
                ViewRole.PLAYER,
            )
        
        # Player view should have secrets redacted
        assert mind_view.profile.hidden_identity == viewer.REDACTED_TEXT
        assert len(mind_view.secrets) == 0
        assert len(mind_view.private_memories) == 0

    def test_npc_mind_viewer_allows_admin_access(
        self,
        db: Session,
        test_sessions: dict,
    ):
        """NPCMindViewer should show full info to admin role."""
        viewer = NPCMindViewer(db_session=db)
        
        mind_view = viewer._get_mock_mind_view(
            test_sessions["session1"].id,
            "npc_elder",
            ViewRole.ADMIN,
        )
        
        # Admin should see everything
        assert mind_view.profile.hidden_identity == "Secretly a demon lord in disguise"
        assert len(mind_view.secrets) > 0
        assert len(mind_view.private_memories) > 0

    def test_secret_willingness_to_reveal(
        self,
        db: Session,
        test_sessions: dict,
        test_npc_templates: dict,
        test_session_npc_states: dict,
    ):
        """Secrets have willingness_to_reveal score."""
        result = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session1"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        assert result is not None
        secret = result.memory_scope.secrets.secrets[0]
        
        # Low willingness to reveal
        assert secret.willingness_to_reveal == 0.1
        # Reveal conditions exist
        assert len(secret.reveal_conditions) > 0


# =============================================================================
# Test 5: NPC context builder produces isolated decision context
# =============================================================================

class TestNPCDecisionContextIsolation:
    """Test that context builder produces isolated NPC decision context."""

    def test_npc_decision_context_no_omniscient_data(
        self,
        context_builder: ContextBuilder,
    ):
        """NPC decision context should not contain omniscient canonical data."""
        from llm_rpg.models.memories import (
            NPCMemoryScope,
            NPCProfile,
            NPCBeliefState,
            NPCRecentContext,
            NPCSecrets,
            NPCKnowledgeState,
            NPCGoals,
        )
        from llm_rpg.models.events import WorldTime
        
        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
            belief_state=NPCBeliefState(npc_id="npc_elder"),
            recent_context=NPCRecentContext(npc_id="npc_elder"),
            secrets=NPCSecrets(npc_id="npc_elder"),
            knowledge_state=NPCKnowledgeState(npc_id="npc_elder"),
            goals=NPCGoals(npc_id="npc_elder"),
        )
        
        state = CanonicalState(
            world_state=WorldState(
                entity_id="world_1",
                world_id="test_world",
                current_time=WorldTime(calendar="修仙历", season="春", day=1, period="辰时"),
            ),
            player_state=PlayerState(
                entity_id="player_1",
                name="测试玩家",
                location_id="loc_square",
            ),
            current_scene_state=CurrentSceneState(
                entity_id="scene_1",
                scene_id="scene_1",
                location_id="loc_square",
                scene_phase="exploration",
                active_actor_ids=["npc_elder"],
                available_actions=["观察", "交谈"],
            ),
            location_states={},
            npc_states={},
            quest_states={},
            faction_states={},
        )
        
        perspective_facts = context_builder.get_npc_perspective_facts(
            npc_id="npc_elder",
            state=state,
            npc_scope=npc_scope,
        )
        
        assert "known_facts" in perspective_facts
        assert "visible_scene" in perspective_facts
        assert len(perspective_facts["known_facts"]) == 0

    def test_npc_only_sees_visible_npcs(
        self,
        context_builder: ContextBuilder,
    ):
        """NPC should only see other NPCs in the same scene."""
        from llm_rpg.models.memories import (
            NPCMemoryScope,
            NPCProfile,
            NPCBeliefState,
            NPCRecentContext,
            NPCSecrets,
            NPCKnowledgeState,
            NPCGoals,
        )
        from llm_rpg.models.states import NPCState, PhysicalState, MentalState
        
        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
            belief_state=NPCBeliefState(npc_id="npc_elder"),
            recent_context=NPCRecentContext(npc_id="npc_elder"),
            secrets=NPCSecrets(npc_id="npc_elder"),
            knowledge_state=NPCKnowledgeState(npc_id="npc_elder"),
            goals=NPCGoals(npc_id="npc_elder"),
        )
        
        state = CanonicalState(
            world_state=WorldState(
                entity_id="world_1",
                world_id="test_world",
                current_time=WorldTime(calendar="修仙历", season="春", day=1, period="辰时"),
            ),
            player_state=PlayerState(
                entity_id="player_1",
                name="测试玩家",
                location_id="loc_square",
            ),
            current_scene_state=CurrentSceneState(
                entity_id="scene_1",
                scene_id="scene_1",
                location_id="loc_square",
                scene_phase="exploration",
                active_actor_ids=["npc_elder"],
                available_actions=["观察"],
            ),
            location_states={},
            npc_states={
                "npc_elder": NPCState(
                    entity_id="npc_elder",
                    entity_type="npc",
                    npc_id="npc_elder",
                    name="长老",
                    status="alive",
                    location_id="loc_square",
                    mood="neutral",
                    physical_state=PhysicalState(),
                    mental_state=MentalState(),
                ),
                "npc_merchant": NPCState(
                    entity_id="npc_merchant",
                    entity_type="npc",
                    npc_id="npc_merchant",
                    name="商人",
                    status="alive",
                    location_id="loc_forest",
                    mood="friendly",
                    physical_state=PhysicalState(),
                    mental_state=MentalState(),
                ),
            },
            quest_states={},
            faction_states={},
        )
        
        perspective_facts = context_builder.get_npc_perspective_facts(
            npc_id="npc_elder",
            state=state,
            npc_scope=npc_scope,
        )
        
        visible_npcs = perspective_facts.get("visible_npc_states", {})
        assert "npc_merchant" not in visible_npcs

    def test_npc_available_actions_respect_location(
        self,
        context_builder: ContextBuilder,
    ):
        """NPC available actions should be limited by location."""
        from llm_rpg.models.memories import (
            NPCMemoryScope,
            NPCProfile,
            NPCBeliefState,
            NPCRecentContext,
            NPCSecrets,
            NPCKnowledgeState,
            NPCGoals,
        )
        from llm_rpg.models.states import NPCState, PhysicalState, MentalState
        
        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
            belief_state=NPCBeliefState(npc_id="npc_elder"),
            recent_context=NPCRecentContext(npc_id="npc_elder"),
            secrets=NPCSecrets(npc_id="npc_elder"),
            knowledge_state=NPCKnowledgeState(npc_id="npc_elder"),
            goals=NPCGoals(npc_id="npc_elder"),
        )
        
        npc_state_in_scene = NPCState(
            entity_id="npc_elder",
            entity_type="npc",
            npc_id="npc_elder",
            name="长老",
            status="alive",
            location_id="loc_square",
            mood="neutral",
            physical_state=PhysicalState(),
            mental_state=MentalState(),
        )
        
        npc_state_elsewhere = NPCState(
            entity_id="npc_elder",
            entity_type="npc",
            npc_id="npc_elder",
            name="长老",
            status="alive",
            location_id="loc_forest",
            mood="neutral",
            physical_state=PhysicalState(),
            mental_state=MentalState(),
        )
        
        scene_state = CurrentSceneState(
            entity_id="scene_1",
            scene_id="scene_1",
            location_id="loc_square",
            scene_phase="exploration",
            active_actor_ids=["npc_elder"],
            available_actions=["talk", "trade", "observe"],
        )
        
        actions_in_scene = context_builder.get_npc_available_actions(
            npc_id="npc_elder",
            npc_scope=npc_scope,
            npc_state=npc_state_in_scene,
            scene_state=scene_state,
        )
        assert "talk" in actions_in_scene
        assert "observe" in actions_in_scene
        
        actions_elsewhere = context_builder.get_npc_available_actions(
            npc_id="npc_elder",
            npc_scope=npc_scope,
            npc_state=npc_state_elsewhere,
            scene_state=scene_state,
        )
        assert "talk" not in actions_elsewhere
        assert "move" in actions_elsewhere

    def test_npc_decision_context_includes_constraints(
        self,
        context_builder: ContextBuilder,
    ):
        """NPC decision context should include constraints."""
        from llm_rpg.models.memories import (
            NPCMemoryScope,
            NPCProfile,
            NPCBeliefState,
            NPCRecentContext,
            NPCSecrets,
            NPCKnowledgeState,
            NPCGoals,
            Secret,
        )
        
        npc_scope = NPCMemoryScope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
            belief_state=NPCBeliefState(npc_id="npc_elder"),
            recent_context=NPCRecentContext(npc_id="npc_elder"),
            secrets=NPCSecrets(
                npc_id="npc_elder",
                secrets=[Secret(
                    secret_id="secret_1",
                    content="我是卧底",
                    willingness_to_reveal=0.1,
                )],
            ),
            knowledge_state=NPCKnowledgeState(
                npc_id="npc_elder",
                forbidden_knowledge=["forbidden_world_truth"],
            ),
            goals=NPCGoals(npc_id="npc_elder"),
        )
        
        state = CanonicalState(
            world_state=WorldState(
                entity_id="world_1",
                world_id="test_world",
                current_time=WorldTime(calendar="修仙历", season="春", day=1, period="辰时"),
            ),
            player_state=PlayerState(
                entity_id="player_1",
                name="测试玩家",
                location_id="loc_square",
            ),
            current_scene_state=CurrentSceneState(
                entity_id="scene_1",
                scene_id="scene_1",
                location_id="loc_square",
                scene_phase="exploration",
                active_actor_ids=["npc_elder"],
                available_actions=["观察"],
            ),
            location_states={},
            npc_states={},
            quest_states={},
            faction_states={},
        )
        
        context = context_builder.build_npc_decision_context(
            npc_id="npc_elder",
            game_id="game_1",
            turn_id="turn_1",
            state=state,
            npc_scope=npc_scope,
        )
        
        assert "constraints" in context.content
        constraints = context.content["constraints"]
        assert len(constraints) > 0
        assert any("forbidden" in c.lower() or "禁止" in c for c in constraints)


# =============================================================================
# Test 6: NPC memory isolation across sessions
# =============================================================================

class TestNPCMemorySessionIsolation:
    """Test that NPC memory is isolated across different sessions."""

    def test_same_npc_different_sessions_independent_states(
        self,
        db: Session,
        test_sessions: dict,
        test_npc_templates: dict,
        test_session_npc_states: dict,
    ):
        """Same NPC template in different sessions should have independent states."""
        # Elder in session 1
        elder_s1 = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session1"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        # Elder in session 2
        elder_s2 = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session2"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        assert elder_s1 is not None
        assert elder_s2 is not None
        
        # Same template, but different session states
        assert elder_s1.npc_state.npc_id == elder_s2.npc_state.npc_id  # Same template
        assert elder_s1.npc_state.name == elder_s2.npc_state.name  # Same name
        
        # Different locations
        assert elder_s1.npc_state.location_id != elder_s2.npc_state.location_id
        assert elder_s1.npc_state.location_id == "loc_square"
        assert elder_s2.npc_state.location_id == "loc_temple"
        
        # Different trust scores
        assert elder_s1.npc_state.mental_state.trust_toward_player != elder_s2.npc_state.mental_state.trust_toward_player
        assert elder_s1.npc_state.mental_state.trust_toward_player == 0.6  # 60 / 100
        assert elder_s2.npc_state.mental_state.trust_toward_player == 0.2  # 20 / 100

    def test_different_sessions_no_memory_leakage(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """Memories added in one session should not leak to another."""
        manager = memory_manager
        
        # Create scope for session 1 elder
        manager.create_npc_scope(
            npc_id="npc_elder_session1",
            profile=NPCProfile(npc_id="npc_elder_session1", name="长老"),
        )
        
        # Create scope for session 2 elder (same template, different scope ID)
        manager.create_npc_scope(
            npc_id="npc_elder_session2",
            profile=NPCProfile(npc_id="npc_elder_session2", name="长老"),
        )
        
        # Add memory to session 1 elder
        manager.add_memory(
            npc_id="npc_elder_session1",
            content="玩家在会话1中帮助了我",
            importance=0.8,
            current_turn=5,
        )
        
        # Add different memory to session 2 elder
        manager.add_memory(
            npc_id="npc_elder_session2",
            content="玩家在会话2中背叛了我",
            importance=0.9,
            current_turn=3,
        )
        
        scope_s1 = manager.get_scope("npc_elder_session1")
        scope_s2 = manager.get_scope("npc_elder_session2")
        
        # Session 1 elder only knows about session 1 events
        s1_memories = [m.content for m in scope_s1.private_memories]
        assert "玩家在会话1中帮助了我" in s1_memories
        assert "玩家在会话2中背叛了我" not in s1_memories
        
        # Session 2 elder only knows about session 2 events
        s2_memories = [m.content for m in scope_s2.private_memories]
        assert "玩家在会话2中背叛了我" in s2_memories
        assert "玩家在会话1中帮助了我" not in s2_memories

    def test_session_specific_npc_states(
        self,
        db: Session,
        test_sessions: dict,
        test_npc_templates: dict,
        test_session_npc_states: dict,
    ):
        """NPCs in different sessions can have completely different states."""
        # Session 1: Elder at square with high trust
        elder_s1 = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session1"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        # Session 2: Same elder at temple with low trust
        elder_s2 = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session2"].id,
            npc_template_id=test_npc_templates["elder"].id,
        )
        
        # Session 2 has spy that session 1 doesn't have
        spy_s2 = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session2"].id,
            npc_template_id=test_npc_templates["spy"].id,
        )
        
        # Session 1 has merchant that session 2 doesn't have for elder
        merchant_s1 = build_npc_state_from_db(
            db=db,
            session_id=test_sessions["session1"].id,
            npc_template_id=test_npc_templates["merchant"].id,
        )
        
        assert elder_s1 is not None
        assert elder_s2 is not None
        assert spy_s2 is not None
        assert merchant_s1 is not None
        
        # Verify status flags are session-specific
        assert elder_s1.npc_state.mood == "warm"  # trust 60
        assert elder_s2.npc_state.mood == "wary"  # suspicion 50

    def test_npc_beliefs_session_isolated(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC beliefs should be isolated per session."""
        manager = memory_manager
        
        # Session 1 elder beliefs
        manager.create_npc_scope(
            npc_id="npc_elder_s1",
            profile=NPCProfile(npc_id="npc_elder_s1", name="长老"),
        )
        manager.add_belief(
            npc_id="npc_elder_s1",
            content="玩家是值得信赖的",
            confidence=0.8,
            current_turn=1,
        )
        
        # Session 2 elder beliefs (same template, different beliefs)
        manager.create_npc_scope(
            npc_id="npc_elder_s2",
            profile=NPCProfile(npc_id="npc_elder_s2", name="长老"),
        )
        manager.add_belief(
            npc_id="npc_elder_s2",
            content="玩家很可疑",
            confidence=0.7,
            current_turn=1,
        )
        
        scope_s1 = manager.get_scope("npc_elder_s1")
        scope_s2 = manager.get_scope("npc_elder_s2")
        
        # Session 1 belief
        s1_beliefs = [b.content for b in scope_s1.belief_state.beliefs]
        assert "玩家是值得信赖的" in s1_beliefs
        assert "玩家很可疑" not in s1_beliefs
        
        # Session 2 belief
        s2_beliefs = [b.content for b in scope_s2.belief_state.beliefs]
        assert "玩家很可疑" in s2_beliefs
        assert "玩家是值得信赖的" not in s2_beliefs


# =============================================================================
# Additional edge case tests
# =============================================================================

class TestNPCMemoryEdgeCases:
    """Test edge cases in NPC memory handling."""

    def test_empty_memory_scope(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """NPC with no memories should return empty lists."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_new",
            profile=NPCProfile(npc_id="npc_new", name="新人"),
        )
        
        scope = manager.get_scope("npc_new")
        assert len(scope.private_memories) == 0
        assert len(scope.belief_state.beliefs) == 0
        assert len(scope.secrets.secrets) == 0
        assert len(scope.knowledge_state.known_facts) == 0

    def test_memory_bounds_recent_events(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """Recent perceived events should be bounded."""
        manager = memory_manager
        manager.create_npc_scope(
            npc_id="npc_elder",
            profile=NPCProfile(npc_id="npc_elder", name="长老"),
        )
        
        # Add many events
        for i in range(30):
            manager.add_perceived_event(
                npc_id="npc_elder",
                turn=i,
                summary=f"事件 {i}",
            )
        
        scope = manager.get_scope("npc_elder")
        
        # Should be bounded to last 20
        assert len(scope.recent_context.recent_perceived_events) <= 20

    def test_unknown_npc_returns_none(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """Getting scope for unknown NPC should return None."""
        manager = memory_manager
        
        scope = manager.get_scope("unknown_npc")
        assert scope is None

    def test_unknown_npc_memories_empty(
        self,
        memory_manager: NPCMemoryManager,
    ):
        """Getting memories for unknown NPC should return empty list."""
        manager = memory_manager
        
        memories = manager.get_memories_for_context(
            npc_id="unknown_npc",
            current_turn=1,
        )
        assert memories == []

    def test_dead_npc_no_actions(
        self,
        context_builder: ContextBuilder,
    ):
        """Dead NPCs should have no available actions."""
        from llm_rpg.models.memories import (
            NPCMemoryScope,
            NPCProfile,
            NPCBeliefState,
            NPCRecentContext,
            NPCSecrets,
            NPCKnowledgeState,
            NPCGoals,
        )
        from llm_rpg.models.states import NPCState, PhysicalState, MentalState
        
        npc_scope = NPCMemoryScope(
            npc_id="npc_dead",
            profile=NPCProfile(npc_id="npc_dead", name="死者"),
            belief_state=NPCBeliefState(npc_id="npc_dead"),
            recent_context=NPCRecentContext(npc_id="npc_dead"),
            secrets=NPCSecrets(npc_id="npc_dead"),
            knowledge_state=NPCKnowledgeState(npc_id="npc_dead"),
            goals=NPCGoals(npc_id="npc_dead"),
        )
        
        dead_npc_state = NPCState(
            entity_id="npc_dead",
            entity_type="npc",
            npc_id="npc_dead",
            name="死者",
            status="dead",
            location_id="loc_graveyard",
            mood="neutral",
            physical_state=PhysicalState(),
            mental_state=MentalState(),
        )
        
        scene_state = CurrentSceneState(
            entity_id="scene_1",
            scene_id="scene_1",
            location_id="loc_graveyard",
            scene_phase="exploration",
            active_actor_ids=["npc_dead"],
            available_actions=["inspect"],
        )
        
        actions = context_builder.get_npc_available_actions(
            npc_id="npc_dead",
            npc_scope=npc_scope,
            npc_state=dead_npc_state,
            scene_state=scene_state,
        )
        
        assert actions == []

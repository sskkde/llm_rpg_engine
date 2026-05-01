"""
Integration tests for content seeding functionality.

Tests that the seed script correctly populates the database with:
- 1 world
- 3 chapters
- 5+ core NPC templates
- 10 locations/scenes
- Quests/steps
- Event templates
- Prompt templates
- Items
- 3 endings
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.repositories import (
    WorldRepository,
    ChapterRepository,
    LocationRepository,
    NPCTemplateRepository,
    ItemTemplateRepository,
    QuestTemplateRepository,
    QuestStepRepository,
    EventTemplateRepository,
    PromptTemplateRepository,
)
from llm_rpg.scripts.seed_content import seed_all_content, verify_seed_counts
from llm_rpg.main import app


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_engine):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seeded_db(db_engine):
    """Fixture that returns a database session with seeded content."""
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        ids = seed_all_content(db)
        yield db, ids
    finally:
        db.close()


class TestSeedCounts:
    """Test that seeded content meets documented requirements."""
    
    def test_seed_counts_match_docs(self, seeded_db):
        """Verify seeded content matches GDD requirements."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        counts = verify_seed_counts(db, world_id)
        
        assert counts["worlds"] == 1, f"Expected 1 world, got {counts['worlds']}"
        assert counts["chapters"] >= 3, f"Expected at least 3 chapters, got {counts['chapters']}"
        assert counts["locations"] >= 10, f"Expected at least 10 locations, got {counts['locations']}"
        assert counts["npcs"] >= 5, f"Expected at least 5 NPCs, got {counts['npcs']}"
        assert counts["items"] >= 5, f"Expected at least 5 items, got {counts['items']}"
        assert counts["endings"] >= 3, f"Expected at least 3 endings, got {counts['endings']}"
    
    def test_world_exists(self, seeded_db):
        """Verify world was created with correct data."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        world_repo = WorldRepository(db)
        world = world_repo.get_by_id(world_id)
        
        assert world is not None
        assert world.code == "cultivation_trial_world"
        assert world.name == "修仙试炼世界"
        assert world.genre == "xianxia"
        assert world.status == "active"
    
    def test_chapters_created(self, seeded_db):
        """Verify 3 chapters were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        chapter_repo = ChapterRepository(db)
        chapters = chapter_repo.get_by_world(world_id)
        
        assert len(chapters) == 3
        
        chapter_names = [c.name for c in chapters]
        assert "初入宗门" in chapter_names
        assert "异变初现" in chapter_names
        assert "真相揭露" in chapter_names
        
        chapter_nos = [c.chapter_no for c in chapters]
        assert sorted(chapter_nos) == [1, 2, 3]
    
    def test_locations_created(self, seeded_db):
        """Verify 10+ locations were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        location_repo = LocationRepository(db)
        locations = location_repo.get_by_world(world_id)
        
        assert len(locations) >= 10
        
        location_codes = [loc.code for loc in locations]
        expected_codes = [
            "square", "residence", "trial_hall", "herb_garden",
            "library", "forest", "cliff", "secret_gate", "core", "inner_library"
        ]
        for code in expected_codes:
            assert code in location_codes, f"Location '{code}' not found"
    
    def test_npcs_created(self, seeded_db):
        """Verify 5+ NPC templates were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        npc_repo = NPCTemplateRepository(db)
        npcs = npc_repo.get_by_world(world_id)
        
        assert len(npcs) >= 5
        
        npc_codes = [npc.code for npc in npcs]
        expected_codes = [
            "senior_sister", "male_competitor", "female_competitor",
            "mysterious", "elder", "master"
        ]
        for code in expected_codes:
            assert code in npc_codes, f"NPC '{code}' not found"
    
    def test_items_created(self, seeded_db):
        """Verify items were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        item_repo = ItemTemplateRepository(db)
        items = item_repo.get_by_world(world_id)
        
        assert len(items) >= 5
        
        item_codes = [item.code for item in items]
        expected_codes = [
            "spirit_stone", "healing_herb", "gate_key",
            "sect_badge", "ancient_scroll"
        ]
        for code in expected_codes:
            assert code in item_codes, f"Item '{code}' not found"
    
    def test_quests_created(self, seeded_db):
        """Verify quests with steps were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        quest_repo = QuestTemplateRepository(db)
        quests = quest_repo.get_by_world(world_id)
        
        assert len(quests) >= 4
        
        quest_codes = [q.code for q in quests]
        expected_codes = [
            "first_trial", "investigate_anomaly",
            "uncover_truth", "help_senior_sister"
        ]
        for code in expected_codes:
            assert code in quest_codes, f"Quest '{code}' not found"
    
    def test_quest_steps_created(self, seeded_db):
        """Verify quest steps were created for each quest."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        quest_repo = QuestTemplateRepository(db)
        step_repo = QuestStepRepository(db)
        quests = quest_repo.get_by_world(world_id)
        
        for quest in quests:
            if quest.quest_type == "ending":
                continue
            steps = step_repo.get_by_quest(quest.id)
            assert len(steps) >= 1, f"Quest '{quest.code}' has no steps"
    
    def test_event_templates_created(self, seeded_db):
        """Verify event templates were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        event_repo = EventTemplateRepository(db)
        events = event_repo.get_by_world(world_id)
        
        assert len(events) >= 5
        
        event_codes = [e.code for e in events]
        expected_codes = [
            "welcome_to_sect", "strange_occurrence", "confrontation",
            "random_combat", "herb_gathering", "library_discovery"
        ]
        for code in expected_codes:
            assert code in event_codes, f"Event '{code}' not found"
    
    def test_prompt_templates_created(self, seeded_db):
        """Verify prompt templates were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        prompt_repo = PromptTemplateRepository(db)
        
        narration_prompts = prompt_repo.get_by_type("narration", world_id)
        dialogue_prompts = prompt_repo.get_by_type("npc_dialogue", world_id)
        intent_prompts = prompt_repo.get_by_type("intent_parsing", world_id)
        
        assert len(narration_prompts) >= 1, "No narration prompts found"
        assert len(dialogue_prompts) >= 1, "No dialogue prompts found"
        assert len(intent_prompts) >= 1, "No intent parsing prompts found"
    
    def test_endings_created(self, seeded_db):
        """Verify 3 endings were created."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        quest_repo = QuestTemplateRepository(db)
        quests = quest_repo.get_by_world(world_id)
        
        endings = [q for q in quests if q.quest_type == "ending"]
        assert len(endings) >= 3, f"Expected at least 3 endings, got {len(endings)}"
        
        ending_codes = [e.code for e in endings]
        expected_endings = ["good_ending", "bittersweet_ending", "secret_ending"]
        for code in expected_endings:
            assert code in ending_codes, f"Ending '{code}' not found"


class TestSeedIdempotency:
    """Test that seeding is idempotent (running twice doesn't create duplicates)."""
    
    def test_seed_idempotent(self, db_session):
        """Running seed twice should not create duplicates."""
        # First seed
        ids1 = seed_all_content(db_session)
        world_id = ids1["world_id"]
        
        counts1 = verify_seed_counts(db_session, world_id)
        
        # Second seed (should be idempotent)
        ids2 = seed_all_content(db_session)
        counts2 = verify_seed_counts(db_session, world_id)
        
        # Verify counts are the same
        assert counts1["chapters"] == counts2["chapters"]
        assert counts1["locations"] == counts2["locations"]
        assert counts1["npcs"] == counts2["npcs"]
        assert counts1["items"] == counts2["items"]
        assert counts1["quests"] == counts2["quests"]
        assert counts1["events"] == counts2["events"]
        assert counts1["endings"] == counts2["endings"]
        
        # Verify world_id is the same
        assert ids1["world_id"] == ids2["world_id"]


class TestWorldAPI:
    """Test the world state API endpoint."""
    
    def test_get_world_state_returns_metadata(self, client, db_engine):
        """GET /world/state should return world metadata from DB."""
        # Seed content first
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            ids = seed_all_content(db)
            world_id = ids["world_id"]
        finally:
            db.close()
        
        response = client.get("/world/state")
        assert response.status_code == 200
        
        data = response.json()
        assert "world" in data
        assert "chapters" in data
        assert "locations" in data
        assert "npcs" in data
        
        world = data["world"]
        assert world["code"] == "cultivation_trial_world"
        assert world["name"] == "修仙试炼世界"
        assert world["genre"] == "xianxia"
        
        assert len(data["chapters"]) >= 3
        assert len(data["locations"]) >= 10
        assert len(data["npcs"]) >= 5
    
    def test_get_world_state_not_hardcoded(self, client, db_engine):
        """World state should come from DB, not hardcoded constants."""
        # Seed content
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            ids = seed_all_content(db)
            world_id = ids["world_id"]
            
            # Update world in DB
            world_repo = WorldRepository(db)
            world_repo.update(world_id, {"name": "Updated World Name"})
            db.commit()
        finally:
            db.close()
        
        response = client.get("/world/state")
        assert response.status_code == 200
        
        data = response.json()
        assert data["world"]["name"] == "Updated World Name"


class TestWorldContentDetails:
    """Test that world content has proper details."""
    
    def test_chapter_start_conditions(self, seeded_db):
        """Chapters should have start conditions."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        chapter_repo = ChapterRepository(db)
        chapters = chapter_repo.get_by_world(world_id)
        
        for chapter in chapters:
            assert chapter.start_conditions is not None
            assert isinstance(chapter.start_conditions, dict)
    
    def test_location_access_rules(self, seeded_db):
        """Locations should have access rules."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        location_repo = LocationRepository(db)
        locations = location_repo.get_by_world(world_id)
        
        for location in locations:
            assert location.access_rules is not None
            assert isinstance(location.access_rules, dict)
    
    def test_npc_hidden_identities(self, seeded_db):
        """NPCs should have hidden identities for plot twists."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        npc_repo = NPCTemplateRepository(db)
        npcs = npc_repo.get_by_world(world_id)
        
        npc_with_hidden = [npc for npc in npcs if npc.hidden_identity]
        assert len(npc_with_hidden) >= 1, "At least one NPC should have a hidden identity"
        
        elder = next((npc for npc in npcs if npc.code == "elder"), None)
        assert elder is not None
        assert elder.hidden_identity == "幕后黑手"
    
    def test_item_effects(self, seeded_db):
        """Items should have effects defined."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        item_repo = ItemTemplateRepository(db)
        items = item_repo.get_by_world(world_id)
        
        for item in items:
            assert item.effects_json is not None
            assert isinstance(item.effects_json, dict)
    
    def test_quest_visibility(self, seeded_db):
        """Quests should have proper visibility settings."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        quest_repo = QuestTemplateRepository(db)
        quests = quest_repo.get_by_world(world_id)
        
        visible_quests = [q for q in quests if q.visibility == "visible"]
        hidden_quests = [q for q in quests if q.visibility == "hidden"]
        
        assert len(visible_quests) >= 1, "Should have visible quests"
        assert len(hidden_quests) >= 1, "Should have hidden quests"
    
    def test_event_trigger_conditions(self, seeded_db):
        """Events should have trigger conditions."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        event_repo = EventTemplateRepository(db)
        events = event_repo.get_by_world(world_id)
        
        for event in events:
            assert event.trigger_conditions is not None
            assert isinstance(event.trigger_conditions, dict)
    
    def test_prompt_content(self, seeded_db):
        """Prompts should have template content."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        prompt_repo = PromptTemplateRepository(db)
        prompts = prompt_repo.get_by_type("narration", world_id)
        
        assert len(prompts) >= 1
        for prompt in prompts:
            assert prompt.content is not None
            assert len(prompt.content) > 0
            assert "{{" in prompt.content, "Prompt should have template variables"


class TestSeedRelationships:
    """Test that seeded content has proper relationships."""
    
    def test_locations_linked_to_chapters(self, seeded_db):
        """Locations should be linked to chapters."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        chapter_repo = ChapterRepository(db)
        location_repo = LocationRepository(db)
        
        chapters = chapter_repo.get_by_world(world_id)
        locations = location_repo.get_by_world(world_id)
        
        # Some locations should have chapter links
        locations_with_chapters = [loc for loc in locations if loc.chapter_id is not None]
        assert len(locations_with_chapters) >= 5
        
        # Each chapter should have some locations
        for chapter in chapters:
            chapter_locations = location_repo.get_by_chapter(chapter.id)
            assert len(chapter_locations) >= 1, f"Chapter {chapter.name} has no locations"
    
    def test_quest_steps_linked_to_quests(self, seeded_db):
        """Quest steps should be linked to their quests."""
        db, ids = seeded_db
        world_id = ids["world_id"]
        
        quest_repo = QuestTemplateRepository(db)
        step_repo = QuestStepRepository(db)
        quests = quest_repo.get_by_world(world_id)
        
        for quest in quests:
            if quest.quest_type == "ending":
                continue
            steps = step_repo.get_by_quest(quest.id)
            for step in steps:
                assert step.quest_template_id == quest.id
                assert step.step_no >= 1

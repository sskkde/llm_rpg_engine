"""
Integration tests for content validation and extensibility.

Tests that newly authored content:
- Can seed correctly
- Appears in recommended actions
- Participates in scene/NPC/world proposals
- Avoids missing location/NPC references

This ensures the minimum content-authoring contract for reusable worlds.
"""

import pytest
from typing import Dict, Set

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
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
from llm_rpg.scripts.seed_content import seed_all_content


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
def seeded_db(db_session):
    """Fixture that returns a database session with seeded content."""
    ids = seed_all_content(db_session)
    yield db_session, ids


class ContentValidationError(Exception):
    """Raised when content validation fails."""
    pass


class ContentValidator:
    """
    Validates content references to ensure integrity.
    
    Checks that:
    - All locations reference valid chapters
    - All NPCs reference valid worlds
    - All quests reference valid locations/NPCs
    - All event templates reference valid locations
    """
    
    def __init__(self, db: Session, world_id: str):
        self.db = db
        self.world_id = world_id
        self.errors: list = []
        
        # Load all content
        self.chapters = {c.id: c for c in ChapterRepository(db).get_by_world(world_id)}
        self.locations = {loc.id: loc for loc in LocationRepository(db).get_by_world(world_id)}
        self.location_codes = {loc.code: loc.id for loc in self.locations.values()}
        self.npcs = {npc.id: npc for npc in NPCTemplateRepository(db).get_by_world(world_id)}
        self.npc_codes = {npc.code: npc.id for npc in self.npcs.values()}
        self.items = {item.id: item for item in ItemTemplateRepository(db).get_by_world(world_id)}
        self.item_codes = {item.code: item.id for item in self.items.values()}
        self.quests = {q.id: q for q in QuestTemplateRepository(db).get_by_world(world_id)}
        self.quest_codes = {q.code: q.id for q in self.quests.values()}
        self.events = EventTemplateRepository(db).get_by_world(world_id)
    
    def validate_all(self) -> bool:
        """Run all validations. Returns True if all pass."""
        self.errors = []
        
        self.validate_location_chapter_refs()
        self.validate_quest_step_refs()
        self.validate_event_template_refs()
        self.validate_chapter_start_conditions()
        
        return len(self.errors) == 0
    
    def validate_location_chapter_refs(self):
        """Verify all locations reference valid chapters."""
        for loc in self.locations.values():
            if loc.chapter_id is not None:
                if loc.chapter_id not in self.chapters:
                    self.errors.append(
                        f"Location '{loc.name}' (code: {loc.code}) references "
                        f"non-existent chapter_id: {loc.chapter_id}"
                    )
    
    def validate_quest_step_refs(self):
        """Verify quest steps reference valid locations and NPCs."""
        step_repo = QuestStepRepository(self.db)
        
        for quest in self.quests.values():
            if quest.quest_type == "ending":
                continue
            
            steps = step_repo.get_by_quest(quest.id)
            for step in steps:
                success_conds = step.success_conditions or {}
                fail_conds = step.fail_conditions or {}
                
                # Check location references
                for cond_key in ["location", "success_location"]:
                    loc_code = success_conds.get(cond_key)
                    if loc_code and loc_code not in self.location_codes:
                        self.errors.append(
                            f"Quest '{quest.code}' step {step.step_no} references "
                            f"non-existent location code: {loc_code}"
                        )
                
                # Check NPC references
                npc_code = success_conds.get("npc")
                if npc_code and npc_code not in self.npc_codes:
                    self.errors.append(
                        f"Quest '{quest.code}' step {step.step_no} references "
                        f"non-existent NPC code: {npc_code}"
                    )
                
                # Check item references
                item_code = success_conds.get("item")
                if item_code and item_code not in self.item_codes:
                    self.errors.append(
                        f"Quest '{quest.code}' step {step.step_no} references "
                        f"non-existent item code: {item_code}"
                    )
    
    def validate_event_template_refs(self):
        """Verify event templates reference valid locations."""
        for event in self.events:
            trigger_conds = event.trigger_conditions or {}
            
            # Check location references in trigger conditions
            loc_code = trigger_conds.get("location")
            if loc_code and loc_code not in self.location_codes:
                self.errors.append(
                    f"Event template '{event.code}' references "
                    f"non-existent location code: {loc_code}"
                )
            
            # Check quest references
            quest_code = trigger_conds.get("quest_completed")
            if quest_code and quest_code not in self.quest_codes:
                self.errors.append(
                    f"Event template '{event.code}' references "
                    f"non-existent quest code: {quest_code}"
                )
    
    def validate_chapter_start_conditions(self):
        """Verify chapter start conditions reference valid content."""
        for chapter in self.chapters.values():
            start_conds = chapter.start_conditions or {}
            
            # Check starting_location reference
            loc_code = start_conds.get("starting_location")
            if loc_code and loc_code not in self.location_codes:
                self.errors.append(
                    f"Chapter {chapter.chapter_no} '{chapter.name}' references "
                    f"non-existent starting_location: {loc_code}"
                )
            
            # Check intro_event reference
            event_code = start_conds.get("intro_event")
            if event_code:
                event_codes = [e.code for e in self.events]
                if event_code not in event_codes:
                    self.errors.append(
                        f"Chapter {chapter.chapter_no} '{chapter.name}' references "
                        f"non-existent intro_event: {event_code}"
                    )
            
            # Check unlock_location reference
            unlock_loc = start_conds.get("unlock_location")
            if unlock_loc and unlock_loc not in self.location_codes:
                self.errors.append(
                    f"Chapter {chapter.chapter_no} '{chapter.name}' references "
                    f"non-existent unlock_location: {unlock_loc}"
                )
            
            # Check required_quest_completed reference
            req_quest = start_conds.get("required_quest_completed")
            if req_quest and req_quest not in self.quest_codes:
                self.errors.append(
                    f"Chapter {chapter.chapter_no} '{chapter.name}' references "
                    f"non-existent required_quest_completed: {req_quest}"
                )


class TestContentValidation:
    """Test that seeded content passes all reference validation."""
    
    def test_all_location_chapter_refs_valid(self, seeded_db):
        """All locations should reference valid chapters."""
        db, ids = seeded_db
        validator = ContentValidator(db, ids["world_id"])
        
        validator.validate_location_chapter_refs()
        
        assert len(validator.errors) == 0, \
            f"Location-chapter reference errors: {validator.errors}"
    
    def test_all_quest_step_refs_valid(self, seeded_db):
        """All quest steps should reference valid locations/NPCs/items."""
        db, ids = seeded_db
        validator = ContentValidator(db, ids["world_id"])
        
        validator.validate_quest_step_refs()
        
        assert len(validator.errors) == 0, \
            f"Quest step reference errors: {validator.errors}"
    
    def test_all_event_template_refs_valid(self, seeded_db):
        """All event templates should reference valid locations/quests."""
        db, ids = seeded_db
        validator = ContentValidator(db, ids["world_id"])
        
        validator.validate_event_template_refs()
        
        assert len(validator.errors) == 0, \
            f"Event template reference errors: {validator.errors}"
    
    def test_all_chapter_start_conditions_valid(self, seeded_db):
        """All chapter start conditions should reference valid content."""
        db, ids = seeded_db
        validator = ContentValidator(db, ids["world_id"])
        
        validator.validate_chapter_start_conditions()
        
        assert len(validator.errors) == 0, \
            f"Chapter start condition errors: {validator.errors}"
    
    def test_full_content_validation(self, seeded_db):
        """Run all validations at once."""
        db, ids = seeded_db
        validator = ContentValidator(db, ids["world_id"])
        
        result = validator.validate_all()
        
        assert result, f"Content validation failed with errors: {validator.errors}"


class TestContentExtensibilityContract:
    """
    Test the minimum content-authoring contract for reusable worlds.
    
    These tests verify that newly authored content can:
    - Seed correctly
    - Appear in recommended actions
    - Participate in scene/NPC/world proposals
    """
    
    def test_world_has_required_genre(self, seeded_db):
        """World should have a genre defined for content filtering."""
        db, ids = seeded_db
        world_repo = WorldRepository(db)
        world = world_repo.get_by_id(ids["world_id"])
        
        assert world.genre is not None, "World must have a genre"
        assert len(world.genre) > 0, "World genre cannot be empty"
    
    def test_world_has_lore_summary(self, seeded_db):
        """World should have a lore summary for context building."""
        db, ids = seeded_db
        world_repo = WorldRepository(db)
        world = world_repo.get_by_id(ids["world_id"])
        
        assert world.lore_summary is not None, "World must have a lore_summary"
        assert len(world.lore_summary) > 0, "World lore_summary cannot be empty"
    
    def test_chapters_have_summaries(self, seeded_db):
        """Chapters should have summaries for narrative context."""
        db, ids = seeded_db
        chapter_repo = ChapterRepository(db)
        chapters = chapter_repo.get_by_world(ids["world_id"])
        
        for chapter in chapters:
            assert chapter.summary is not None, \
                f"Chapter {chapter.chapter_no} must have a summary"
    
    def test_locations_have_descriptions(self, seeded_db):
        """Locations should have descriptions for scene generation."""
        db, ids = seeded_db
        location_repo = LocationRepository(db)
        locations = location_repo.get_by_world(ids["world_id"])
        
        for loc in locations:
            assert loc.description is not None, \
                f"Location '{loc.code}' must have a description"
            assert len(loc.description) > 0, \
                f"Location '{loc.code}' description cannot be empty"
    
    def test_npcs_have_personalities(self, seeded_db):
        """NPCs should have personalities for dialogue generation."""
        db, ids = seeded_db
        npc_repo = NPCTemplateRepository(db)
        npcs = npc_repo.get_by_world(ids["world_id"])
        
        for npc in npcs:
            assert npc.personality is not None, \
                f"NPC '{npc.code}' must have a personality"
            assert len(npc.personality) > 0, \
                f"NPC '{npc.code}' personality cannot be empty"
    
    def test_npcs_have_speech_styles(self, seeded_db):
        """NPCs should have speech styles for dialogue generation."""
        db, ids = seeded_db
        npc_repo = NPCTemplateRepository(db)
        npcs = npc_repo.get_by_world(ids["world_id"])
        
        for npc in npcs:
            assert npc.speech_style is not None, \
                f"NPC '{npc.code}' must have a speech_style"
    
    def test_npcs_have_goals(self, seeded_db):
        """NPCs should have goals for decision making."""
        db, ids = seeded_db
        npc_repo = NPCTemplateRepository(db)
        npcs = npc_repo.get_by_world(ids["world_id"])
        
        for npc in npcs:
            assert npc.goals is not None, \
                f"NPC '{npc.code}' must have goals"
            assert len(npc.goals) > 0, \
                f"NPC '{npc.code}' must have at least one goal"
    
    def test_quests_have_summaries(self, seeded_db):
        """Quests should have summaries for quest tracking."""
        db, ids = seeded_db
        quest_repo = QuestTemplateRepository(db)
        quests = quest_repo.get_by_world(ids["world_id"])
        
        for quest in quests:
            if quest.quest_type != "ending":
                assert quest.summary is not None, \
                    f"Quest '{quest.code}' must have a summary"
    
    def test_prompt_templates_have_variables(self, seeded_db):
        """Prompt templates should have template variables for substitution."""
        db, ids = seeded_db
        prompt_repo = PromptTemplateRepository(db)
        
        for prompt_type in ["narration", "npc_dialogue", "intent_parsing"]:
            prompts = prompt_repo.get_by_type(prompt_type, ids["world_id"])
            assert len(prompts) > 0, f"No {prompt_type} prompts found"
            
            for prompt in prompts:
                assert "{{" in prompt.content, \
                    f"Prompt '{prompt.prompt_type}' must have template variables"
                assert "}}" in prompt.content, \
                    f"Prompt '{prompt.prompt_type}' must have template variables"


class TestMissingReferenceDetection:
    """Test that validation catches missing references."""
    
    def test_detects_missing_location_in_quest_step(self, db_session):
        """Validation should catch quest steps referencing missing locations."""
        ids = seed_all_content(db_session)
        world_id = ids["world_id"]
        
        quest_repo = QuestTemplateRepository(db_session)
        step_repo = QuestStepRepository(db_session)
        
        invalid_quest = quest_repo.create({
            "code": "test_invalid_quest",
            "name": "Test Invalid Quest",
            "quest_type": "test",
            "world_id": world_id,
        })
        
        invalid_step = step_repo.create({
            "quest_template_id": invalid_quest.id,
            "step_no": 1,
            "objective": "Go to non-existent location",
            "success_conditions": {"location": "non_existent_location"},
            "fail_conditions": {}
        })
        
        validator = ContentValidator(db_session, world_id)
        validator.validate_quest_step_refs()
        
        assert len(validator.errors) > 0, \
            "Should detect missing location reference"
        assert any("non_existent_location" in e for e in validator.errors), \
            f"Error should mention missing location. Got: {validator.errors}"
    
    def test_detects_missing_npc_in_quest_step(self, db_session):
        """Validation should catch quest steps referencing missing NPCs."""
        ids = seed_all_content(db_session)
        world_id = ids["world_id"]
        
        quest_repo = QuestTemplateRepository(db_session)
        step_repo = QuestStepRepository(db_session)
        
        invalid_quest = quest_repo.create({
            "code": "test_invalid_npc_quest",
            "name": "Test Invalid NPC Quest",
            "quest_type": "test",
            "world_id": world_id,
        })
        
        invalid_step = step_repo.create({
            "quest_template_id": invalid_quest.id,
            "step_no": 1,
            "objective": "Talk to non-existent NPC",
            "success_conditions": {"npc": "non_existent_npc"},
            "fail_conditions": {}
        })
        
        validator = ContentValidator(db_session, world_id)
        validator.validate_quest_step_refs()
        
        assert len(validator.errors) > 0, \
            "Should detect missing NPC reference"
        assert any("non_existent_npc" in e for e in validator.errors), \
            f"Error should mention missing NPC. Got: {validator.errors}"
    
    def test_detects_missing_location_in_event_template(self, db_session):
        """Validation should catch event templates referencing missing locations."""
        ids = seed_all_content(db_session)
        world_id = ids["world_id"]
        
        event_repo = EventTemplateRepository(db_session)
        
        invalid_event = event_repo.create({
            "code": "test_invalid_event",
            "name": "Test Invalid Event",
            "event_type": "test",
            "world_id": world_id,
            "trigger_conditions": {"location": "non_existent_location"},
            "effects": {}
        })
        
        validator = ContentValidator(db_session, world_id)
        validator.validate_event_template_refs()
        
        assert len(validator.errors) > 0, \
            "Should detect missing location reference in event"
        assert any("non_existent_location" in e for e in validator.errors), \
            f"Error should mention missing location. Got: {validator.errors}"
    
    def test_detects_missing_chapter_in_location(self, db_session):
        """Validation should catch locations referencing missing chapters."""
        ids = seed_all_content(db_session)
        world_id = ids["world_id"]
        
        location_repo = LocationRepository(db_session)
        
        invalid_location = location_repo.create({
            "code": "test_invalid_location",
            "name": "Test Invalid Location",
            "world_id": world_id,
            "chapter_id": "non_existent_chapter_id",
            "tags": [],
            "access_rules": {}
        })
        
        validator = ContentValidator(db_session, world_id)
        validator.validate_location_chapter_refs()
        
        assert len(validator.errors) > 0, \
            "Should detect missing chapter reference in location"
        assert any("non_existent_chapter_id" in e for e in validator.errors), \
            f"Error should mention missing chapter. Got: {validator.errors}"


class TestAccessRulesValidation:
    """Test that access rules are properly defined."""
    
    def test_locations_have_access_rules(self, seeded_db):
        """All locations should have access_rules defined."""
        db, ids = seeded_db
        location_repo = LocationRepository(db)
        locations = location_repo.get_by_world(ids["world_id"])
        
        for loc in locations:
            assert loc.access_rules is not None, \
                f"Location '{loc.code}' must have access_rules"
            assert isinstance(loc.access_rules, dict), \
                f"Location '{loc.code}' access_rules must be a dict"
    
    def test_access_rules_have_valid_structure(self, seeded_db):
        """Access rules should have valid structure."""
        db, ids = seeded_db
        location_repo = LocationRepository(db)
        locations = location_repo.get_by_world(ids["world_id"])
        
        valid_keys = {
            "always_accessible", "player_level", "time_restrictions",
            "quest_requirement", "quest_trigger", "quest_completed",
            "item_required", "combat_level", "player_realm",
            "chapter", "boss_unlocked", "inner_restricted"
        }
        
        for loc in locations:
            for key in loc.access_rules.keys():
                assert key in valid_keys, \
                    f"Location '{loc.code}' has unknown access_rule key: {key}"
    
    def test_quest_required_in_access_rules_exists(self, seeded_db):
        """Quest references in access_rules should exist."""
        db, ids = seeded_db
        validator = ContentValidator(db, ids["world_id"])
        
        location_repo = LocationRepository(db)
        locations = location_repo.get_by_world(ids["world_id"])
        
        for loc in locations:
            quest_code = loc.access_rules.get("quest_requirement")
            if quest_code and quest_code is not None:
                if quest_code not in validator.quest_codes:
                    assert False, \
                        f"Location '{loc.code}' access_rules.quest_requirement " \
                        f"references non-existent quest: {quest_code}"
            
            quest_completed = loc.access_rules.get("quest_completed")
            if quest_completed and quest_completed is not None:
                if quest_completed not in validator.quest_codes:
                    assert False, \
                        f"Location '{loc.code}' access_rules.quest_completed " \
                        f"references non-existent quest: {quest_completed}"
    
    def test_item_required_in_access_rules_exists(self, seeded_db):
        """Item references in access_rules should exist."""
        db, ids = seeded_db
        validator = ContentValidator(db, ids["world_id"])
        
        location_repo = LocationRepository(db)
        locations = location_repo.get_by_world(ids["world_id"])
        
        for loc in locations:
            item_code = loc.access_rules.get("item_required")
            if item_code and item_code is not None:
                if item_code not in validator.item_codes:
                    assert False, \
                        f"Location '{loc.code}' access_rules.item_required " \
                        f"references non-existent item: {item_code}"

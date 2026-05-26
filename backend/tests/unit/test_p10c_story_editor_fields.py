import pytest

from llm_rpg.storage.models import (
    WorldModel,
    LocationModel,
    NPCTemplateModel,
    EventTemplateModel,
    PromptTemplateModel,
    FactionModel,
    ChapterModel,
    ItemTemplateModel,
    QuestTemplateModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    LocationRepository,
    NPCTemplateRepository,
    EventTemplateRepository,
    PromptTemplateRepository,
    FactionRepository,
    ChapterRepository,
    ItemTemplateRepository,
    QuestTemplateRepository,
)
from llm_rpg.core.feature_flags import story_editor_enabled


class TestWorldModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        world = WorldModel(
            code=f"w-{generate_uuid()[:8]}",
            name="Editor Test World",
        )
        db_session.add(world)
        db_session.commit()
        db_session.refresh(world)

        assert world.story_package_version_id is None
        assert world.world_book_json is None
        assert world.calendar_json is None
        assert world.ruleset_json is None
        assert world.starter_location_id is None
        assert world.editor_metadata_json is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        world_repo = WorldRepository(db_session)
        loc_repo = LocationRepository(db_session)

        loc = loc_repo.create({
            "world_id": "w-editor-1",
            "code": "starter-loc",
            "name": "Starter Village",
        })

        world = world_repo.create({
            "code": f"w-{generate_uuid()[:8]}",
            "name": "Rich World",
            "world_book_json": {"lore": "ancient civilization"},
            "calendar_json": {"months": 12, "days_per_month": 30},
            "ruleset_json": {"combat": "turn_based"},
            "starter_location_id": loc.id,
            "editor_metadata_json": {"author": "admin", "tags": ["xianxia"]},
        })

        assert world.world_book_json == {"lore": "ancient civilization"}
        assert world.calendar_json == {"months": 12, "days_per_month": 30}
        assert world.ruleset_json == {"combat": "turn_based"}
        assert world.starter_location_id == loc.id
        assert world.editor_metadata_json == {"author": "admin", "tags": ["xianxia"]}

    def test_old_fields_preserved(self, db_session):
        world_repo = WorldRepository(db_session)
        world = world_repo.create({
            "code": f"w-old-{generate_uuid()[:8]}",
            "name": "Old World",
            "genre": "xianxia",
            "lore_summary": "A world of cultivation",
            "status": "active",
        })

        assert world.genre == "xianxia"
        assert world.lore_summary == "A world of cultivation"
        assert world.status == "active"


class TestLocationModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        loc = LocationModel(
            world_id="w-loc-test",
            code="loc-default",
            name="Default Location",
        )
        db_session.add(loc)
        db_session.commit()
        db_session.refresh(loc)

        assert loc.parent_location_id is None
        assert loc.location_type is None
        assert loc.environment_json is None
        assert loc.discovery_rules_json is None
        assert loc.scene_hooks_json is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        loc_repo = LocationRepository(db_session)
        parent_loc = loc_repo.create({
            "world_id": "w-loc-parent",
            "code": "parent-region",
            "name": "Parent Region",
        })

        child = loc_repo.create({
            "world_id": "w-loc-parent",
            "code": "child-village",
            "name": "Child Village",
            "parent_location_id": parent_loc.id,
            "location_type": "village",
            "environment_json": {"weather": "foggy", "lighting": "dawn"},
            "discovery_rules_json": {"requires_item": "map_scroll"},
            "scene_hooks_json": {"on_enter": "trigger_npc_greeting"},
        })

        assert child.parent_location_id == parent_loc.id
        assert child.location_type == "village"
        assert child.environment_json == {"weather": "foggy", "lighting": "dawn"}
        assert child.discovery_rules_json == {"requires_item": "map_scroll"}
        assert child.scene_hooks_json == {"on_enter": "trigger_npc_greeting"}

    def test_old_fields_preserved(self, db_session):
        loc_repo = LocationRepository(db_session)
        loc = loc_repo.create({
            "world_id": "w-loc-old",
            "code": "old-loc",
            "name": "Old Location",
            "tags": ["outdoor", "dangerous"],
            "description": "A dangerous place",
            "access_rules": {"requires_level": 5},
        })

        assert loc.tags == ["outdoor", "dangerous"]
        assert loc.description == "A dangerous place"
        assert loc.access_rules == {"requires_level": 5}


class TestNPCTemplateModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        npc = NPCTemplateModel(
            world_id="w-npc-test",
            code="npc-default",
            name="Default NPC",
        )
        db_session.add(npc)
        db_session.commit()
        db_session.refresh(npc)

        assert npc.appearance_json is None
        assert npc.body_features_json is None
        assert npc.baseline_stats_json is None
        assert npc.speech_profile_json is None
        assert npc.personality_traits_json is None
        assert npc.background_bio is None
        assert npc.decision_profile_json is None
        assert npc.initial_location_id is None
        assert npc.faction_id is None
        assert npc.portrait_asset_id is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        npc_repo = NPCTemplateRepository(db_session)
        loc_repo = LocationRepository(db_session)
        faction_repo = FactionRepository(db_session)

        loc = loc_repo.create({
            "world_id": "w-npc-loc",
            "code": "npc-start",
            "name": "NPC Start Location",
        })
        faction = faction_repo.create({
            "logical_id": "test-faction",
            "world_id": "w-npc-loc",
            "name": "Test Faction",
        })

        npc = npc_repo.create({
            "world_id": "w-npc-loc",
            "code": "rich-npc",
            "name": "Rich NPC",
            "appearance_json": {"hair": "white", "eyes": "blue"},
            "body_features_json": {"height": "tall", "build": "slender"},
            "baseline_stats_json": {"hp": 100, "mp": 50},
            "speech_profile_json": {"formality": "high", "verbosity": "low"},
            "personality_traits_json": ["cunning", "loyal", "secretive"],
            "background_bio": "An elder from the northern sect",
            "decision_profile_json": {"risk_tolerance": "high", "loyalty_weight": 0.8},
            "initial_location_id": loc.id,
            "faction_id": faction.id,
            "portrait_asset_id": "asset-portrait-rich-npc",
        })

        assert npc.appearance_json == {"hair": "white", "eyes": "blue"}
        assert npc.body_features_json == {"height": "tall", "build": "slender"}
        assert npc.baseline_stats_json == {"hp": 100, "mp": 50}
        assert npc.speech_profile_json == {"formality": "high", "verbosity": "low"}
        assert npc.personality_traits_json == ["cunning", "loyal", "secretive"]
        assert npc.background_bio == "An elder from the northern sect"
        assert npc.decision_profile_json == {"risk_tolerance": "high", "loyalty_weight": 0.8}
        assert npc.initial_location_id == loc.id
        assert npc.faction_id == faction.id
        assert npc.portrait_asset_id == "asset-portrait-rich-npc"

    def test_phase1_fields_preserved(self, db_session):
        npc_repo = NPCTemplateRepository(db_session)
        npc = npc_repo.create({
            "world_id": "w-npc-p1",
            "code": "p1-npc",
            "name": "P1 NPC",
            "is_major_npc": True,
            "memory_profile_json": {"budget": 5},
            "seed_memory_bundle_json": [{"text": "I remember"}],
        })

        assert npc.is_major_npc is True
        assert npc.memory_profile_json == {"budget": 5}
        assert npc.seed_memory_bundle_json == [{"text": "I remember"}]

    def test_old_fields_preserved(self, db_session):
        npc_repo = NPCTemplateRepository(db_session)
        npc = npc_repo.create({
            "world_id": "w-npc-old",
            "code": "old-npc",
            "name": "Old NPC",
            "role_type": "elder",
            "public_identity": "Public elder",
            "hidden_identity": "Secret master",
            "personality": "Wise and cunning",
            "speech_style": "Formal and measured",
            "appearance": "White-haired",
            "goals": ["protect the sect", "find the scroll"],
        })

        assert npc.role_type == "elder"
        assert npc.public_identity == "Public elder"
        assert npc.hidden_identity == "Secret master"
        assert npc.personality == "Wise and cunning"
        assert npc.speech_style == "Formal and measured"
        assert npc.appearance == "White-haired"
        assert npc.goals == ["protect the sect", "find the scroll"]


class TestEventTemplateModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        evt = EventTemplateModel(
            world_id="w-evt-test",
            code="evt-default",
            name="Default Event",
        )
        db_session.add(evt)
        db_session.commit()
        db_session.refresh(evt)

        assert evt.npc_memory_write_policy_json is None
        assert evt.reveal_rules_json is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        evt_repo = EventTemplateRepository(db_session)
        evt = evt_repo.create({
            "world_id": "w-evt-rich",
            "code": "evt-rich",
            "name": "Rich Event",
            "npc_memory_write_policy_json": {
                "major_npc": "always_write",
                "minor_npc": "never_write",
            },
            "reveal_rules_json": {
                "delay_turns": 3,
                "visibility": "conditional",
            },
        })

        assert evt.npc_memory_write_policy_json == {
            "major_npc": "always_write",
            "minor_npc": "never_write",
        }
        assert evt.reveal_rules_json == {
            "delay_turns": 3,
            "visibility": "conditional",
        }

    def test_old_fields_preserved(self, db_session):
        evt_repo = EventTemplateRepository(db_session)
        evt = evt_repo.create({
            "world_id": "w-evt-old",
            "code": "evt-old",
            "name": "Old Event",
            "event_type": "trigger",
            "trigger_conditions": {"location": "square"},
            "effects": [{"type": "set_state", "key": "flag"}],
        })

        assert evt.event_type == "trigger"
        assert evt.trigger_conditions == {"location": "square"}
        assert evt.effects == [{"type": "set_state", "key": "flag"}]


class TestPromptTemplateModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        pt = PromptTemplateModel(
            prompt_type="narration",
            content="Narrate the scene",
        )
        db_session.add(pt)
        db_session.commit()
        db_session.refresh(pt)

        assert pt.editor_notes is None
        assert pt.variable_schema_json is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        pt_repo = PromptTemplateRepository(db_session)
        pt = pt_repo.create({
            "prompt_type": "npc_decision",
            "content": "Decide what {{npc_name}} does next",
            "editor_notes": "This prompt is used for major NPC decisions only",
            "variable_schema_json": {
                "npc_name": {"type": "string", "required": True},
                "context": {"type": "string", "required": False},
            },
        })

        assert pt.editor_notes == "This prompt is used for major NPC decisions only"
        assert pt.variable_schema_json == {
            "npc_name": {"type": "string", "required": True},
            "context": {"type": "string", "required": False},
        }

    def test_old_fields_preserved(self, db_session):
        pt_repo = PromptTemplateRepository(db_session)
        pt = pt_repo.create({
            "prompt_type": "narration",
            "version": "2.0",
            "content": "Narrate the action",
            "enabled_flag": True,
        })

        assert pt.version == "2.0"
        assert pt.content == "Narrate the action"
        assert pt.enabled_flag is True


class TestStoryEditorFeatureFlag:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("STORY_EDITOR_ENABLED", raising=False)
        assert story_editor_enabled() is False

    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("STORY_EDITOR_ENABLED", "true")
        assert story_editor_enabled() is True

    def test_enabled_1(self, monkeypatch):
        monkeypatch.setenv("STORY_EDITOR_ENABLED", "1")
        assert story_editor_enabled() is True

    def test_enabled_yes(self, monkeypatch):
        monkeypatch.setenv("STORY_EDITOR_ENABLED", "yes")
        assert story_editor_enabled() is True

    def test_enabled_false_explicit(self, monkeypatch):
        monkeypatch.setenv("STORY_EDITOR_ENABLED", "false")
        assert story_editor_enabled() is False


class TestEditorFieldCompatibilityWithExistingRepos:
    def test_world_update_with_editor_fields(self, db_session):
        repo = WorldRepository(db_session)
        world = repo.create({
            "code": f"w-upd-{generate_uuid()[:8]}",
            "name": "Update World",
        })
        updated = repo.update(world.id, {
            "world_book_json": {"history": "ancient"},
            "ruleset_json": {"combat": "d100"},
        })
        assert updated.world_book_json == {"history": "ancient"}
        assert updated.ruleset_json == {"combat": "d100"}

    def test_location_update_with_editor_fields(self, db_session):
        repo = LocationRepository(db_session)
        loc = repo.create({
            "world_id": "w-upd-loc",
            "code": "upd-loc",
            "name": "Update Location",
        })
        updated = repo.update(loc.id, {
            "location_type": "dungeon",
            "environment_json": {"darkness": True},
        })
        assert updated.location_type == "dungeon"
        assert updated.environment_json == {"darkness": True}

    def test_npc_update_with_editor_fields(self, db_session):
        repo = NPCTemplateRepository(db_session)
        npc = repo.create({
            "world_id": "w-upd-npc",
            "code": "upd-npc",
            "name": "Update NPC",
        })
        updated = repo.update(npc.id, {
            "background_bio": "A mysterious wanderer",
            "portrait_asset_id": "asset-new-portrait",
        })
        assert updated.background_bio == "A mysterious wanderer"
        assert updated.portrait_asset_id == "asset-new-portrait"

    def test_event_update_with_editor_fields(self, db_session):
        repo = EventTemplateRepository(db_session)
        evt = repo.create({
            "world_id": "w-upd-evt",
            "code": "upd-evt",
            "name": "Update Event",
        })
        updated = repo.update(evt.id, {
            "npc_memory_write_policy_json": {"major_npc": "conditional"},
        })
        assert updated.npc_memory_write_policy_json == {"major_npc": "conditional"}

    def test_prompt_update_with_editor_fields(self, db_session):
        repo = PromptTemplateRepository(db_session)
        pt = repo.create({
            "prompt_type": "test",
            "content": "test content",
        })
        updated = repo.update(pt.id, {
            "editor_notes": "Updated notes",
            "variable_schema_json": {"x": {"type": "int"}},
        })
        assert updated.editor_notes == "Updated notes"
        assert updated.variable_schema_json == {"x": {"type": "int"}}


class TestChapterModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        chapter = ChapterModel(
            world_id="w-ch-test",
            chapter_no=1,
            name="Default Chapter",
        )
        db_session.add(chapter)
        db_session.commit()
        db_session.refresh(chapter)

        assert chapter.entry_conditions_json is None
        assert chapter.exit_conditions_json is None
        assert chapter.end_conditions_json is None
        assert chapter.timeline_json is None
        assert chapter.tags_json is None
        assert chapter.schema_json is None
        assert chapter.estimated_playtime_minutes is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": "w-ch-rich",
            "chapter_no": 2,
            "name": "Rich Chapter",
            "entry_conditions_json": {"level_min": 5, "quest_completed": "q1"},
            "exit_conditions_json": {"boss_defeated": True},
            "end_conditions_json": {"final_choice_made": True},
            "timeline_json": {"start_day": 1, "duration_days": 7},
            "tags_json": ["main", "xianxia", "training"],
            "schema_json": {"type": "linear", "branches": 0},
            "estimated_playtime_minutes": 120,
        })

        assert chapter.entry_conditions_json == {"level_min": 5, "quest_completed": "q1"}
        assert chapter.exit_conditions_json == {"boss_defeated": True}
        assert chapter.end_conditions_json == {"final_choice_made": True}
        assert chapter.timeline_json == {"start_day": 1, "duration_days": 7}
        assert chapter.tags_json == ["main", "xianxia", "training"]
        assert chapter.schema_json == {"type": "linear", "branches": 0}
        assert chapter.estimated_playtime_minutes == 120

    def test_old_fields_preserved(self, db_session):
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": "w-ch-old",
            "chapter_no": 3,
            "name": "Old Chapter",
            "summary": "A chapter about cultivation",
            "start_conditions": {"quest_complete": "intro"},
        })

        assert chapter.summary == "A chapter about cultivation"
        assert chapter.start_conditions == {"quest_complete": "intro"}

    def test_chapter_update_with_editor_fields(self, db_session):
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": "w-ch-upd",
            "chapter_no": 4,
            "name": "Update Chapter",
        })
        updated = repo.update(chapter.id, {
            "entry_conditions_json": {"level_min": 10},
            "estimated_playtime_minutes": 60,
            "tags_json": ["side"],
        })
        assert updated.entry_conditions_json == {"level_min": 10}
        assert updated.estimated_playtime_minutes == 60
        assert updated.tags_json == ["side"]


class TestItemTemplateModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        item = ItemTemplateModel(
            world_id="w-item-test",
            code="item-default",
            name="Default Item",
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        assert item.stackable_flag is None
        assert item.durability_max is None
        assert item.equip_slot is None
        assert item.stat_modifiers_json is None
        assert item.use_effects_json is None
        assert item.ownership_rules_json is None
        assert item.visibility_rules_json is None
        assert item.price_json is None
        assert item.crafting_json is None
        assert item.lore_text is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": "w-item-rich",
            "code": "item-rich",
            "name": "Rich Item",
            "stackable_flag": True,
            "durability_max": 100,
            "equip_slot": "weapon",
            "stat_modifiers_json": {"attack": 15, "speed": -2},
            "use_effects_json": {"heal": 50, "buff": "strength"},
            "ownership_rules_json": {"transferable": True, "stealable": False},
            "visibility_rules_json": {"requires_perception": 10},
            "price_json": {"buy": 500, "sell": 250},
            "crafting_json": {"materials": ["iron", "wood"], "skill_required": 3},
            "lore_text": "An ancient sword forged by the northern blacksmith.",
        })

        assert item.stackable_flag is True
        assert item.durability_max == 100
        assert item.equip_slot == "weapon"
        assert item.stat_modifiers_json == {"attack": 15, "speed": -2}
        assert item.use_effects_json == {"heal": 50, "buff": "strength"}
        assert item.ownership_rules_json == {"transferable": True, "stealable": False}
        assert item.visibility_rules_json == {"requires_perception": 10}
        assert item.price_json == {"buy": 500, "sell": 250}
        assert item.crafting_json == {"materials": ["iron", "wood"], "skill_required": 3}
        assert item.lore_text == "An ancient sword forged by the northern blacksmith."

    def test_old_fields_preserved(self, db_session):
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": "w-item-old",
            "code": "item-old",
            "name": "Old Item",
            "item_type": "weapon",
            "rarity": "legendary",
            "description": "A powerful weapon",
            "effects_json": {"damage": "+10"},
        })

        assert item.item_type == "weapon"
        assert item.rarity == "legendary"
        assert item.description == "A powerful weapon"
        assert item.effects_json == {"damage": "+10"}

    def test_item_update_with_editor_fields(self, db_session):
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": "w-item-upd",
            "code": "item-upd",
            "name": "Update Item",
        })
        updated = repo.update(item.id, {
            "stackable_flag": False,
            "equip_slot": "armor",
            "lore_text": "Updated lore.",
        })
        assert updated.stackable_flag is False
        assert updated.equip_slot == "armor"
        assert updated.lore_text == "Updated lore."


class TestQuestTemplateModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        quest = QuestTemplateModel(
            world_id="w-quest-test",
            code="quest-default",
            name="Default Quest",
        )
        db_session.add(quest)
        db_session.commit()
        db_session.refresh(quest)

        assert quest.trigger_conditions_json is None
        assert quest.availability_conditions_json is None
        assert quest.fail_conditions_json is None
        assert quest.rewards_json is None
        assert quest.branching_json is None
        assert quest.deadline_json is None
        assert quest.repeatable_flag is None
        assert quest.step_conditions_json is None

    def test_editor_fields_set_and_roundtrip(self, db_session):
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": "w-quest-rich",
            "code": "quest-rich",
            "name": "Rich Quest",
            "trigger_conditions_json": {"npc_met": "elder_wang", "location": "village_square"},
            "availability_conditions_json": {"level_min": 5, "faction": "cloud_sect"},
            "fail_conditions_json": {"timeout_days": 30, "npc_death": True},
            "rewards_json": {"xp": 500, "gold": 100, "item": "ancient_sword"},
            "branching_json": {"choice_a": {"outcome": "ally_joins"}, "choice_b": {"outcome": "fight"}},
            "deadline_json": {"in_game_days": 14, "real_time_hours": 48},
            "repeatable_flag": False,
            "step_conditions_json": {"step_1": {"objective": "talk_to_elder"}, "step_2": {"objective": "find_scroll"}},
        })

        assert quest.trigger_conditions_json == {"npc_met": "elder_wang", "location": "village_square"}
        assert quest.availability_conditions_json == {"level_min": 5, "faction": "cloud_sect"}
        assert quest.fail_conditions_json == {"timeout_days": 30, "npc_death": True}
        assert quest.rewards_json == {"xp": 500, "gold": 100, "item": "ancient_sword"}
        assert quest.branching_json == {"choice_a": {"outcome": "ally_joins"}, "choice_b": {"outcome": "fight"}}
        assert quest.deadline_json == {"in_game_days": 14, "real_time_hours": 48}
        assert quest.repeatable_flag is False
        assert quest.step_conditions_json == {"step_1": {"objective": "talk_to_elder"}, "step_2": {"objective": "find_scroll"}}

    def test_old_fields_preserved(self, db_session):
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": "w-quest-old",
            "code": "quest-old",
            "name": "Old Quest",
            "quest_type": "main",
            "summary": "Find the ancient scroll",
            "visibility": "discovered",
        })

        assert quest.quest_type == "main"
        assert quest.summary == "Find the ancient scroll"
        assert quest.visibility == "discovered"

    def test_quest_update_with_editor_fields(self, db_session):
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": "w-quest-upd",
            "code": "quest-upd",
            "name": "Update Quest",
        })
        updated = repo.update(quest.id, {
            "repeatable_flag": True,
            "rewards_json": {"xp": 1000},
            "branching_json": {"default": {"outcome": "completed"}},
        })
        assert updated.repeatable_flag is True
        assert updated.rewards_json == {"xp": 1000}
        assert updated.branching_json == {"default": {"outcome": "completed"}}
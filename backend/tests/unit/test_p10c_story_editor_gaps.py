"""P10-C Story Editor: gap closure for ChapterModel, ItemTemplateModel, QuestTemplateModel.

Tests that new nullable authoring fields persist and roundtrip correctly,
and that old fields are preserved. Also verifies admin API Pydantic models
accept and expose the new fields.
"""

import pytest
from typing import Dict, Any

from llm_rpg.storage.models import (
    WorldModel,
    ChapterModel,
    ItemTemplateModel,
    QuestTemplateModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    ChapterRepository,
    ItemTemplateRepository,
    QuestTemplateRepository,
)


def _make_world(db_session, **kw):
    repo = WorldRepository(db_session)
    code = kw.pop("code", f"w-{generate_uuid()[:8]}")
    name = kw.pop("name", "Test World")
    return repo.create({"code": code, "name": name, **kw})


# =============================================================================
# ChapterModel
# =============================================================================


class TestChapterModelEditorFields:
    def test_editor_fields_default_none(self, db_session):
        world = _make_world(db_session)
        chapter = ChapterModel(
            world_id=world.id,
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
        world = _make_world(db_session)
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": world.id,
            "chapter_no": 1,
            "name": "Rich Chapter",
            "entry_conditions_json": {"min_level": 3, "required_quest": "sword_quest"},
            "exit_conditions_json": {"boss_defeated": True},
            "end_conditions_json": {"all_quests_done": True},
            "timeline_json": [{"day": 1, "event": "arrival"}, {"day": 3, "event": "departure"}],
            "tags_json": ["main_story", "difficult"],
            "schema_json": {"locations": 5, "npcs": 3},
            "estimated_playtime_minutes": 120,
        })

        assert chapter.entry_conditions_json == {"min_level": 3, "required_quest": "sword_quest"}
        assert chapter.exit_conditions_json == {"boss_defeated": True}
        assert chapter.end_conditions_json == {"all_quests_done": True}
        assert chapter.timeline_json == [{"day": 1, "event": "arrival"}, {"day": 3, "event": "departure"}]
        assert chapter.tags_json == ["main_story", "difficult"]
        assert chapter.schema_json == {"locations": 5, "npcs": 3}
        assert chapter.estimated_playtime_minutes == 120

    def test_old_fields_preserved(self, db_session):
        world = _make_world(db_session)
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": world.id,
            "chapter_no": 1,
            "name": "Old Chapter",
            "summary": "A chapter of cultivation",
            "start_conditions": {"required_level": 5},
        })

        assert chapter.summary == "A chapter of cultivation"
        assert chapter.start_conditions == {"required_level": 5}

    def test_update_with_editor_fields(self, db_session):
        world = _make_world(db_session)
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": world.id,
            "chapter_no": 2,
            "name": "Update Chapter",
        })
        updated = repo.update(chapter.id, {
            "entry_conditions_json": {"min_level": 5},
            "tags_json": ["tag1", "tag2"],
            "estimated_playtime_minutes": 90,
        })
        assert updated.entry_conditions_json == {"min_level": 5}
        assert updated.tags_json == ["tag1", "tag2"]
        assert updated.estimated_playtime_minutes == 90

    def test_update_partial_does_not_widen(self, db_session):
        world = _make_world(db_session)
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": world.id,
            "chapter_no": 3,
            "name": "Partial Chapter",
            "entry_conditions_json": {"level": 1},
            "exit_conditions_json": {"defeat": True},
            "timeline_json": [{"tick": 0}],
        })
        updated = repo.update(chapter.id, {
            "entry_conditions_json": {"level": 2},
        })
        assert updated.entry_conditions_json == {"level": 2}
        assert updated.exit_conditions_json == {"defeat": True}
        assert updated.timeline_json == [{"tick": 0}]

    def test_chapter_fields_roundtrip_null_strings(self, db_session):
        world = _make_world(db_session)
        repo = ChapterRepository(db_session)
        chapter = repo.create({
            "world_id": world.id,
            "chapter_no": 4,
            "name": "Nullables Chapter",
            "estimated_playtime_minutes": None,
        })
        assert chapter.estimated_playtime_minutes is None


# =============================================================================
# ItemTemplateModel
# =============================================================================


class TestItemTemplateEditorFields:
    def test_editor_fields_default_none(self, db_session):
        world = _make_world(db_session)
        item = ItemTemplateModel(
            world_id=world.id,
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
        world = _make_world(db_session)
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": world.id,
            "code": "item-rich",
            "name": "Rich Item",
            "stackable_flag": True,
            "durability_max": 100,
            "equip_slot": "weapon",
            "stat_modifiers_json": {"atk": 15, "spd": 3},
            "use_effects_json": [{"type": "heal", "amount": 50}],
            "ownership_rules_json": {"bind_on_pickup": True},
            "visibility_rules_json": {"requires_level": 10},
            "price_json": {"gold": 500, "premium_currency": 25},
            "crafting_json": {"materials": [{"id": "iron_ore", "qty": 5}]},
            "lore_text": "A blade forged in dragon's fire",
        })

        assert item.stackable_flag is True
        assert item.durability_max == 100
        assert item.equip_slot == "weapon"
        assert item.stat_modifiers_json == {"atk": 15, "spd": 3}
        assert item.use_effects_json == [{"type": "heal", "amount": 50}]
        assert item.ownership_rules_json == {"bind_on_pickup": True}
        assert item.visibility_rules_json == {"requires_level": 10}
        assert item.price_json == {"gold": 500, "premium_currency": 25}
        assert item.crafting_json == {"materials": [{"id": "iron_ore", "qty": 5}]}
        assert item.lore_text == "A blade forged in dragon's fire"

    def test_old_fields_preserved(self, db_session):
        world = _make_world(db_session)
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": world.id,
            "code": "item-old",
            "name": "Old Item",
            "item_type": "weapon",
            "rarity": "legendary",
            "description": "An ancient artifact",
            "effects_json": {"damage": 42},
        })

        assert item.item_type == "weapon"
        assert item.rarity == "legendary"
        assert item.description == "An ancient artifact"
        assert item.effects_json == {"damage": 42}

    def test_update_with_editor_fields(self, db_session):
        world = _make_world(db_session)
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": world.id,
            "code": "item-upd",
            "name": "Update Item",
        })
        updated = repo.update(item.id, {
            "durability_max": 200,
            "equip_slot": "armor",
            "lore_text": "Updated lore",
        })
        assert updated.durability_max == 200
        assert updated.equip_slot == "armor"
        assert updated.lore_text == "Updated lore"

    def test_item_fields_roundtrip_bool_nullable(self, db_session):
        world = _make_world(db_session)
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": world.id,
            "code": "item-bool",
            "name": "Bool Item",
            "stackable_flag": False,
        })
        assert item.stackable_flag is False

        updated = repo.update(item.id, {"stackable_flag": True})
        assert updated.stackable_flag is True


# =============================================================================
# QuestTemplateModel
# =============================================================================


class TestQuestTemplateEditorFields:
    def test_editor_fields_default_none(self, db_session):
        world = _make_world(db_session)
        quest = QuestTemplateModel(
            world_id=world.id,
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
        world = _make_world(db_session)
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": world.id,
            "code": "quest-rich",
            "name": "Rich Quest",
            "trigger_conditions_json": {"location": "dragon_lair", "npc_present": "elder"},
            "availability_conditions_json": {"level_min": 5, "quests_completed": ["intro_quest"]},
            "fail_conditions_json": {"time_limit": 30, "npc_dead": ["guard"]},
            "rewards_json": {"xp": 500, "items": ["dragon_sword"]},
            "branching_json": {"choice_a": {"quest": "spare_dragon"}, "choice_b": {"quest": "slay_dragon"}},
            "deadline_json": {"turn_limit": 50, "real_time_days": 3},
            "repeatable_flag": False,
            "step_conditions_json": {"step_1": {"location": "tavern"}, "step_2": {"has_item": "key"}},
        })

        assert quest.trigger_conditions_json == {"location": "dragon_lair", "npc_present": "elder"}
        assert quest.availability_conditions_json == {"level_min": 5, "quests_completed": ["intro_quest"]}
        assert quest.fail_conditions_json == {"time_limit": 30, "npc_dead": ["guard"]}
        assert quest.rewards_json == {"xp": 500, "items": ["dragon_sword"]}
        assert quest.branching_json == {"choice_a": {"quest": "spare_dragon"}, "choice_b": {"quest": "slay_dragon"}}
        assert quest.deadline_json == {"turn_limit": 50, "real_time_days": 3}
        assert quest.repeatable_flag is False
        assert quest.step_conditions_json == {"step_1": {"location": "tavern"}, "step_2": {"has_item": "key"}}

    def test_old_fields_preserved(self, db_session):
        world = _make_world(db_session)
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": world.id,
            "code": "quest-old",
            "name": "Old Quest",
            "quest_type": "main_story",
            "summary": "A quest to find the scroll",
            "visibility": "hidden",
        })

        assert quest.quest_type == "main_story"
        assert quest.summary == "A quest to find the scroll"
        assert quest.visibility == "hidden"

    def test_update_with_editor_fields(self, db_session):
        world = _make_world(db_session)
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": world.id,
            "code": "quest-upd",
            "name": "Update Quest",
        })
        updated = repo.update(quest.id, {
            "rewards_json": {"xp": 1000},
            "repeatable_flag": True,
            "deadline_json": {"turn_limit": 100},
        })
        assert updated.rewards_json == {"xp": 1000}
        assert updated.repeatable_flag is True
        assert updated.deadline_json == {"turn_limit": 100}

    def test_quest_repeatable_flag_toggle(self, db_session):
        world = _make_world(db_session)
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": world.id,
            "code": "quest-rpt",
            "name": "Repeatable Quest",
            "repeatable_flag": False,
        })
        assert quest.repeatable_flag is False

        updated = repo.update(quest.id, {"repeatable_flag": True})
        assert updated.repeatable_flag is True


# =============================================================================
# Admin API Pydantic Model Validation (unit-level)
# =============================================================================


class TestAdminApiPydanticModels:
    def test_world_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import WorldUpdateRequest

        req = WorldUpdateRequest(
            name="Updated",
            world_book_json={"lore": "new"},
            calendar_json={"days": 360},
            ruleset_json={"combat": "d100"},
            starter_location_id="loc-123",
            editor_metadata_json={"author": "admin"},
            story_package_version_id="spv-abc",
        )
        assert req.world_book_json == {"lore": "new"}
        assert req.calendar_json == {"days": 360}
        assert req.ruleset_json == {"combat": "d100"}
        assert req.starter_location_id == "loc-123"
        assert req.editor_metadata_json == {"author": "admin"}
        assert req.story_package_version_id == "spv-abc"

    def test_chapter_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import ChapterUpdateRequest

        req = ChapterUpdateRequest(
            entry_conditions_json={"level": 1},
            exit_conditions_json={"boss": "dead"},
            end_conditions_json={"all_done": True},
            timeline_json=[{"day": 1}],
            tags_json=["main_story"],
            schema_json={"locations": 5},
            estimated_playtime_minutes=60,
        )
        assert req.entry_conditions_json == {"level": 1}
        assert req.exit_conditions_json == {"boss": "dead"}
        assert req.end_conditions_json == {"all_done": True}
        assert req.timeline_json == [{"day": 1}]
        assert req.tags_json == ["main_story"]
        assert req.schema_json == {"locations": 5}
        assert req.estimated_playtime_minutes == 60

    def test_location_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import LocationUpdateRequest

        req = LocationUpdateRequest(
            parent_location_id="loc-parent",
            location_type="dungeon",
            environment_json={"dark": True},
            discovery_rules_json={"needs_item": "key"},
            scene_hooks_json={"on_enter": "spawn_boss"},
        )
        assert req.parent_location_id == "loc-parent"
        assert req.location_type == "dungeon"
        assert req.environment_json == {"dark": True}
        assert req.discovery_rules_json == {"needs_item": "key"}
        assert req.scene_hooks_json == {"on_enter": "spawn_boss"}

    def test_npc_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import NPCTemplateUpdateRequest

        req = NPCTemplateUpdateRequest(
            appearance_json={"hair": "white"},
            body_features_json={"build": "tall"},
            baseline_stats_json={"hp": 100},
            speech_profile_json={"verbosity": "low"},
            personality_traits_json=["loyal", "cunning"],
            background_bio="A wandering monk",
            decision_profile_json={"risk": "high"},
            initial_location_id="loc-start",
            faction_id="fac-1",
            portrait_asset_id="asset-1",
            is_major_npc=True,
            memory_profile_json={"budget": 10},
            seed_memory_bundle_json=[{"text": "remembers"}],
        )
        assert req.appearance_json == {"hair": "white"}
        assert req.body_features_json == {"build": "tall"}
        assert req.baseline_stats_json == {"hp": 100}
        assert req.speech_profile_json == {"verbosity": "low"}
        assert req.personality_traits_json == ["loyal", "cunning"]
        assert req.background_bio == "A wandering monk"
        assert req.decision_profile_json == {"risk": "high"}
        assert req.initial_location_id == "loc-start"
        assert req.faction_id == "fac-1"
        assert req.portrait_asset_id == "asset-1"
        assert req.is_major_npc is True
        assert req.memory_profile_json == {"budget": 10}
        assert req.seed_memory_bundle_json == [{"text": "remembers"}]

    def test_item_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import ItemTemplateUpdateRequest

        req = ItemTemplateUpdateRequest(
            stackable_flag=True,
            durability_max=100,
            equip_slot="weapon",
            stat_modifiers_json={"atk": 10},
            use_effects_json={"effects": [{"type": "heal"}]},
            ownership_rules_json={"bind_on_pickup": True},
            visibility_rules_json={"min_level": 5},
            price_json={"gold": 100},
            crafting_json={"materials": []},
            lore_text="A legendary blade",
        )
        assert req.stackable_flag is True
        assert req.durability_max == 100
        assert req.equip_slot == "weapon"
        assert req.stat_modifiers_json == {"atk": 10}
        assert req.use_effects_json == {"effects": [{"type": "heal"}]}
        assert req.ownership_rules_json == {"bind_on_pickup": True}
        assert req.visibility_rules_json == {"min_level": 5}
        assert req.price_json == {"gold": 100}
        assert req.crafting_json == {"materials": []}
        assert req.lore_text == "A legendary blade"

    def test_quest_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import QuestTemplateUpdateRequest

        req = QuestTemplateUpdateRequest(
            trigger_conditions_json={"location": "cave"},
            availability_conditions_json={"level": 5},
            fail_conditions_json={"timeout": True},
            rewards_json={"xp": 500},
            branching_json={"a": {}, "b": {}},
            deadline_json={"turns": 50},
            repeatable_flag=False,
            step_conditions_json={"step_1": {"location": "tavern"}},
        )
        assert req.trigger_conditions_json == {"location": "cave"}
        assert req.availability_conditions_json == {"level": 5}
        assert req.fail_conditions_json == {"timeout": True}
        assert req.rewards_json == {"xp": 500}
        assert req.branching_json == {"a": {}, "b": {}}
        assert req.deadline_json == {"turns": 50}
        assert req.repeatable_flag is False
        assert req.step_conditions_json == {"step_1": {"location": "tavern"}}

    def test_event_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import EventTemplateUpdateRequest

        req = EventTemplateUpdateRequest(
            npc_memory_write_policy_json={"major": "always"},
            reveal_rules_json={"delay": 3},
        )
        assert req.npc_memory_write_policy_json == {"major": "always"}
        assert req.reveal_rules_json == {"delay": 3}

    def test_prompt_update_request_exposes_editor_fields(self):
        from llm_rpg.api.admin import PromptTemplateUpdateRequest

        req = PromptTemplateUpdateRequest(
            editor_notes="Important for NPC decisions",
            variable_schema_json={"npc_name": {"type": "string", "required": True}},
        )
        assert req.editor_notes == "Important for NPC decisions"
        assert req.variable_schema_json == {"npc_name": {"type": "string", "required": True}}


# =============================================================================
# Admin API Detail model read exposure
# =============================================================================


class TestAdminApiDetailModels:
    def test_world_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import WorldDetail

        w = _make_world(
            db_session,
            world_book_json={"lore": "test"},
            calendar_json={"months": 12},
            ruleset_json={"combat": "d20"},
            editor_metadata_json={"author": "test"},
        )
        detail = WorldDetail.model_validate(w)
        assert detail.world_book_json == {"lore": "test"}
        assert detail.calendar_json == {"months": 12}
        assert detail.ruleset_json == {"combat": "d20"}
        assert detail.editor_metadata_json == {"author": "test"}

    def test_chapter_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import ChapterDetail

        world = _make_world(db_session)
        repo = ChapterRepository(db_session)
        c = repo.create({
            "world_id": world.id,
            "chapter_no": 1,
            "name": "Ch1",
            "entry_conditions_json": {"level": 5},
            "estimated_playtime_minutes": 90,
        })
        detail = ChapterDetail.model_validate(c)
        assert detail.entry_conditions_json == {"level": 5}
        assert detail.estimated_playtime_minutes == 90
        assert detail.exit_conditions_json is None

    def test_location_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import LocationDetail
        from llm_rpg.storage.repositories import LocationRepository

        repo = LocationRepository(db_session)
        loc = repo.create({
            "world_id": "w-loc-detail",
            "code": "loc-d",
            "name": "Loc",
            "location_type": "village",
            "environment_json": {"weather": "sunny"},
        })
        detail = LocationDetail.model_validate(loc)
        assert detail.location_type == "village"
        assert detail.environment_json == {"weather": "sunny"}

    def test_npc_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import NPCTemplateDetail
        from llm_rpg.storage.repositories import NPCTemplateRepository

        repo = NPCTemplateRepository(db_session)
        npc = repo.create({
            "world_id": "w-npc-d",
            "code": "npc-d",
            "name": "NPC",
            "background_bio": "Bio",
            "portrait_asset_id": "asset-x",
            "personality_traits_json": ["brave"],
        })
        detail = NPCTemplateDetail.model_validate(npc)
        assert detail.background_bio == "Bio"
        assert detail.portrait_asset_id == "asset-x"
        assert detail.personality_traits_json == ["brave"]

    def test_item_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import ItemTemplateDetail

        world = _make_world(db_session)
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": world.id,
            "code": "item-d",
            "name": "Item",
            "durability_max": 200,
            "lore_text": "Lore",
            "price_json": {"gold": 999},
        })
        detail = ItemTemplateDetail.model_validate(item)
        assert detail.durability_max == 200
        assert detail.lore_text == "Lore"
        assert detail.price_json == {"gold": 999}

    def test_quest_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import QuestTemplateDetail

        world = _make_world(db_session)
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": world.id,
            "code": "quest-d",
            "name": "Quest",
            "rewards_json": {"gold": 100},
            "repeatable_flag": True,
            "deadline_json": {"turns": 100},
        })
        detail = QuestTemplateDetail.model_validate(quest)
        assert detail.rewards_json == {"gold": 100}
        assert detail.repeatable_flag is True
        assert detail.deadline_json == {"turns": 100}

    def test_event_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import EventTemplateDetail
        from llm_rpg.storage.repositories import EventTemplateRepository

        repo = EventTemplateRepository(db_session)
        evt = repo.create({
            "code": "evt-d",
            "name": "Event",
            "npc_memory_write_policy_json": {"major_npc": "conditional"},
            "reveal_rules_json": {"visibility": "hidden"},
        })
        detail = EventTemplateDetail.model_validate(evt)
        assert detail.npc_memory_write_policy_json == {"major_npc": "conditional"}
        assert detail.reveal_rules_json == {"visibility": "hidden"}

    def test_prompt_detail_exposes_editor_fields(self, db_session):
        from llm_rpg.api.admin import PromptTemplateDetail
        from llm_rpg.storage.repositories import PromptTemplateRepository

        repo = PromptTemplateRepository(db_session)
        pt = repo.create({
            "prompt_type": "test",
            "content": "test content",
            "editor_notes": "Some notes",
            "variable_schema_json": {"x": {"type": "int"}},
        })
        detail = PromptTemplateDetail.model_validate(pt)
        assert detail.editor_notes == "Some notes"
        assert detail.variable_schema_json == {"x": {"type": "int"}}


# =============================================================================
# Module-level list-item model backward compatibility
# =============================================================================


class TestListItemBackwardCompatibility:
    def test_world_list_item_unchanged(self, db_session):
        from llm_rpg.api.admin import WorldListItem

        w = _make_world(db_session, genre="xianxia", status="active")
        item = WorldListItem.model_validate(w)
        assert item.id == w.id
        assert item.code == w.code
        assert item.name == w.name
        assert item.genre == "xianxia"
        assert item.status == "active"
        # List item should NOT expose detail-only editor fields
        assert not hasattr(item, "world_book_json") or item.world_book_json is None

    def test_npc_list_item_unchanged(self, db_session):
        from llm_rpg.api.admin import NPCTemplateListItem
        from llm_rpg.storage.repositories import NPCTemplateRepository

        repo = NPCTemplateRepository(db_session)
        npc = repo.create({
            "world_id": "w-npc-list",
            "code": "npc-l",
            "name": "List NPC",
            "role_type": "elder",
        })
        item = NPCTemplateListItem.model_validate(npc)
        assert item.name == "List NPC"
        assert item.role_type == "elder"

    def test_item_list_item_unchanged(self, db_session):
        from llm_rpg.api.admin import ItemTemplateListItem

        world = _make_world(db_session)
        repo = ItemTemplateRepository(db_session)
        item = repo.create({
            "world_id": world.id,
            "code": "item-l",
            "name": "List Item",
            "item_type": "weapon",
            "rarity": "rare",
        })
        li = ItemTemplateListItem.model_validate(item)
        assert li.name == "List Item"
        assert li.item_type == "weapon"
        assert li.rarity == "rare"

    def test_quest_list_item_unchanged(self, db_session):
        from llm_rpg.api.admin import QuestTemplateListItem

        world = _make_world(db_session)
        repo = QuestTemplateRepository(db_session)
        quest = repo.create({
            "world_id": world.id,
            "code": "quest-l",
            "name": "List Quest",
            "quest_type": "side",
            "visibility": "hidden",
        })
        li = QuestTemplateListItem.model_validate(quest)
        assert li.name == "List Quest"
        assert li.quest_type == "side"
        assert li.visibility == "hidden"

    def test_event_list_item_unchanged(self, db_session):
        from llm_rpg.api.admin import EventTemplateListItem
        from llm_rpg.storage.repositories import EventTemplateRepository

        repo = EventTemplateRepository(db_session)
        evt = repo.create({
            "code": "evt-l",
            "name": "List Event",
            "event_type": "scheduled",
        })
        li = EventTemplateListItem.model_validate(evt)
        assert li.name == "List Event"
        assert li.event_type == "scheduled"

    def test_prompt_list_item_unchanged(self, db_session):
        from llm_rpg.api.admin import PromptTemplateListItem
        from llm_rpg.storage.repositories import PromptTemplateRepository

        repo = PromptTemplateRepository(db_session)
        pt = repo.create({
            "prompt_type": "narration",
            "content": "Narrate",
            "version": "1.0",
        })
        li = PromptTemplateListItem.model_validate(pt)
        assert li.prompt_type == "narration"
        assert li.version == "1.0"
        assert li.enabled_flag is True

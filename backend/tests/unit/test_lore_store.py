"""
Unit tests for LoreStore.

Tests lore visibility scoping (public vs hidden vs rumor),
loading lore for different perspectives, and empty store behavior.
"""

import pytest

from llm_rpg.core.lore_store import LoreStore
from llm_rpg.models.lore import (
    LoreEntry,
    LoreCategory,
    LoreView,
    CharacterLore,
    LocationLore,
)
from llm_rpg.models.perspectives import (
    PlayerPerspective,
    NPCPerspective,
    WorldPerspective,
    PerspectiveType,
)


class TestLoreStoreBasicOperations:
    """Test basic add/retrieve operations."""

    def test_add_entry_stores_entry(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Test Lore",
            category=LoreCategory.HISTORY,
            canonical_content="The true content",
            public_content="The public version",
        )
        
        store.add_entry(entry)
        
        assert store.get_entry("lore_1") == entry

    def test_get_entry_returns_none_for_unknown(self):
        store = LoreStore()
        
        result = store.get_entry("unknown")
        
        assert result is None

    def test_get_entries_by_category(self):
        store = LoreStore()
        history1 = LoreEntry(
            lore_id="lore_1",
            title="History 1",
            category=LoreCategory.HISTORY,
            canonical_content="History content 1",
        )
        history2 = LoreEntry(
            lore_id="lore_2",
            title="History 2",
            category=LoreCategory.HISTORY,
            canonical_content="History content 2",
        )
        character = LoreEntry(
            lore_id="lore_3",
            title="Character",
            category=LoreCategory.CHARACTER,
            canonical_content="Character content",
        )
        
        store.add_entry(history1)
        store.add_entry(history2)
        store.add_entry(character)
        
        results = store.get_entries_by_category(LoreCategory.HISTORY)
        
        assert len(results) == 2
        assert all(r.category == LoreCategory.HISTORY for r in results)

    def test_get_entries_by_tag(self):
        store = LoreStore()
        entry1 = LoreEntry(
            lore_id="lore_1",
            title="Tagged",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            tags=["important", "ancient"],
        )
        entry2 = LoreEntry(
            lore_id="lore_2",
            title="Other",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            tags=["ancient"],
        )
        
        store.add_entry(entry1)
        store.add_entry(entry2)
        
        results = store.get_entries_by_tag("ancient")
        
        assert len(results) == 2
        
        results = store.get_entries_by_tag("important")
        
        assert len(results) == 1
        assert results[0].lore_id == "lore_1"

    def test_get_entries_by_entity_character(self):
        store = LoreStore()
        entry = CharacterLore(
            lore_id="lore_1",
            title="Character Lore",
            category=LoreCategory.CHARACTER,
            canonical_content="Content",
            character_id="char_1",
        )
        
        store.add_entry(entry)
        
        results = store.get_entries_by_entity("char_1")
        
        assert len(results) == 1
        assert results[0].lore_id == "lore_1"

    def test_get_entries_by_entity_location(self):
        store = LoreStore()
        entry = LocationLore(
            lore_id="lore_1",
            title="Location Lore",
            category=LoreCategory.LOCATION,
            canonical_content="Content",
            location_id="loc_1",
        )
        
        store.add_entry(entry)
        
        results = store.get_entries_by_entity("loc_1")
        
        assert len(results) == 1

    def test_search_entries_by_title(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Ancient Dragon Legend",
            category=LoreCategory.HISTORY,
            canonical_content="Content about dragons",
        )
        
        store.add_entry(entry)
        
        results = store.search_entries("dragon")
        
        assert len(results) == 1
        assert results[0].lore_id == "lore_1"

    def test_search_entries_by_content(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Legend",
            category=LoreCategory.HISTORY,
            canonical_content="The ancient dragon sleeps in the mountain",
        )
        
        store.add_entry(entry)
        
        results = store.search_entries("mountain")
        
        assert len(results) == 1

    def test_search_entries_by_tag(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Legend",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            tags=["mythical", "dangerous"],
        )
        
        store.add_entry(entry)
        
        results = store.search_entries("mythical")
        
        assert len(results) == 1


class TestLoreVisibilityScoping:
    """Test lore visibility scoping (public vs hidden vs rumor)."""

    def test_player_sees_public_content_without_knowledge(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Public History",
            category=LoreCategory.HISTORY,
            canonical_content="The secret truth",
            public_content="The public version",
        )
        
        store.add_entry(entry)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        view = store.get_view_for_perspective("lore_1", player)
        
        assert view is not None
        assert view.content == "The public version"
        assert view.visibility_level == "partial"

    def test_player_sees_canonical_content_for_known_facts(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Secret History",
            category=LoreCategory.HISTORY,
            canonical_content="The secret truth",
            public_content="The public version",
        )
        
        store.add_entry(entry)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
            known_facts=["lore_1"],
        )
        
        view = store.get_view_for_perspective("lore_1", player)
        
        assert view is not None
        assert view.content == "The secret truth"
        assert view.visibility_level == "full"

    def test_player_sees_rumor_content_for_known_rumors(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Rumored Event",
            category=LoreCategory.RUMOR,
            canonical_content="The true story",
            public_content="The public story",
            rumor_versions=["I heard something about this..."],
        )
        
        store.add_entry(entry)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
            known_rumors=["lore_1"],
        )
        
        view = store.get_view_for_perspective("lore_1", player)
        
        assert view is not None
        assert view.is_rumor is True
        assert view.confidence == 0.5
        assert view.visibility_level == "rumor"

    def test_player_cannot_see_hidden_lore_without_public_content(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Secret Lore",
            category=LoreCategory.HISTORY,
            canonical_content="The hidden truth",
            public_content=None,
            hidden_from_player_until=["special_condition"],
        )
        
        store.add_entry(entry)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        view = store.get_view_for_perspective("lore_1", player)
        
        assert view is None

    def test_npc_sees_canonical_content_for_known_facts(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Known Fact",
            category=LoreCategory.HISTORY,
            canonical_content="The truth",
            public_content="Public version",
        )
        
        store.add_entry(entry)
        
        npc = NPCPerspective(
            perspective_id="npc_1",
            perspective_type=PerspectiveType.NPC,
            owner_id="npc_1",
            npc_id="npc_1",
            known_facts=["lore_1"],
        )
        
        view = store.get_view_for_perspective("lore_1", npc)
        
        assert view is not None
        assert view.content == "The truth"
        assert view.visibility_level == "full"

    def test_npc_sees_rumor_for_believed_rumors(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Rumor",
            category=LoreCategory.RUMOR,
            canonical_content="Truth",
            rumor_versions=["Someone said..."],
        )
        
        store.add_entry(entry)
        
        npc = NPCPerspective(
            perspective_id="npc_1",
            perspective_type=PerspectiveType.NPC,
            owner_id="npc_1",
            npc_id="npc_1",
            believed_rumors=["lore_1"],
        )
        
        view = store.get_view_for_perspective("lore_1", npc)
        
        assert view is not None
        assert view.is_rumor is True
        assert view.visibility_level == "rumor"

    def test_npc_sees_public_content_without_knowledge(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Public Lore",
            category=LoreCategory.HISTORY,
            canonical_content="Secret truth",
            public_content="Public version",
        )
        
        store.add_entry(entry)
        
        npc = NPCPerspective(
            perspective_id="npc_1",
            perspective_type=PerspectiveType.NPC,
            owner_id="npc_1",
            npc_id="npc_1",
        )
        
        view = store.get_view_for_perspective("lore_1", npc)
        
        assert view is not None
        assert view.content == "Public version"
        assert view.visibility_level == "partial"

    def test_npc_cannot_see_lore_without_public_content(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Hidden Lore",
            category=LoreCategory.HISTORY,
            canonical_content="Hidden truth",
            public_content=None,
        )
        
        store.add_entry(entry)
        
        npc = NPCPerspective(
            perspective_id="npc_1",
            perspective_type=PerspectiveType.NPC,
            owner_id="npc_1",
            npc_id="npc_1",
        )
        
        view = store.get_view_for_perspective("lore_1", npc)
        
        assert view is None


class TestLoreViewForPerspective:
    """Test loading lore for different perspectives."""

    def test_get_views_for_perspective_filters_by_category(self):
        store = LoreStore()
        history = LoreEntry(
            lore_id="lore_1",
            title="History",
            category=LoreCategory.HISTORY,
            canonical_content="History content",
            public_content="Public history",
        )
        character = LoreEntry(
            lore_id="lore_2",
            title="Character",
            category=LoreCategory.CHARACTER,
            canonical_content="Character content",
            public_content="Public character",
        )
        
        store.add_entry(history)
        store.add_entry(character)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        views = store.get_views_for_perspective(player, category=LoreCategory.HISTORY)
        
        assert len(views) == 1
        assert views[0].lore_id == "lore_1"

    def test_get_views_for_perspective_filters_by_tags(self):
        store = LoreStore()
        entry1 = LoreEntry(
            lore_id="lore_1",
            title="Important",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            public_content="Public",
            tags=["important"],
        )
        entry2 = LoreEntry(
            lore_id="lore_2",
            title="Other",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            tags=["minor"],
        )
        
        store.add_entry(entry1)
        store.add_entry(entry2)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        views = store.get_views_for_perspective(player, tags=["important"])
        
        assert len(views) == 1
        assert views[0].lore_id == "lore_1"

    def test_get_views_for_perspective_filters_by_entity(self):
        store = LoreStore()
        entry = CharacterLore(
            lore_id="lore_1",
            title="Character Lore",
            category=LoreCategory.CHARACTER,
            canonical_content="Content",
            public_content="Public",
            character_id="char_1",
        )
        other = LoreEntry(
            lore_id="lore_2",
            title="Other",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            public_content="Public",
        )
        
        store.add_entry(entry)
        store.add_entry(other)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        views = store.get_views_for_perspective(player, entity_id="char_1")
        
        assert len(views) == 1
        assert views[0].lore_id == "lore_1"

    def test_get_views_for_perspective_returns_all_without_filters(self):
        store = LoreStore()
        entry1 = LoreEntry(
            lore_id="lore_1",
            title="Lore 1",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            public_content="Public",
        )
        entry2 = LoreEntry(
            lore_id="lore_2",
            title="Lore 2",
            category=LoreCategory.CHARACTER,
            canonical_content="Content",
            public_content="Public",
        )
        
        store.add_entry(entry1)
        store.add_entry(entry2)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        views = store.get_views_for_perspective(player)
        
        assert len(views) == 2

    def test_get_views_excludes_hidden_lore(self):
        store = LoreStore()
        public_entry = LoreEntry(
            lore_id="lore_1",
            title="Public",
            category=LoreCategory.HISTORY,
            canonical_content="Secret",
            public_content="Public",
        )
        hidden_entry = LoreEntry(
            lore_id="lore_2",
            title="Hidden",
            category=LoreCategory.HISTORY,
            canonical_content="Hidden truth",
            public_content=None,
        )
        
        store.add_entry(public_entry)
        store.add_entry(hidden_entry)
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        views = store.get_views_for_perspective(player)
        
        assert len(views) == 1
        assert views[0].lore_id == "lore_1"


class TestEmptyLoreStore:
    """Test empty lore store behavior."""

    def test_empty_store_get_entry_returns_none(self):
        store = LoreStore()
        
        result = store.get_entry("any_id")
        
        assert result is None

    def test_empty_store_get_entries_by_category_returns_empty(self):
        store = LoreStore()
        
        results = store.get_entries_by_category(LoreCategory.HISTORY)
        
        assert results == []

    def test_empty_store_get_entries_by_tag_returns_empty(self):
        store = LoreStore()
        
        results = store.get_entries_by_tag("any_tag")
        
        assert results == []

    def test_empty_store_get_entries_by_entity_returns_empty(self):
        store = LoreStore()
        
        results = store.get_entries_by_entity("any_entity")
        
        assert results == []

    def test_empty_store_search_returns_empty(self):
        store = LoreStore()
        
        results = store.search_entries("any query")
        
        assert results == []

    def test_empty_store_get_view_for_perspective_returns_none(self):
        store = LoreStore()
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        view = store.get_view_for_perspective("unknown_lore", player)
        
        assert view is None

    def test_empty_store_get_views_for_perspective_returns_empty(self):
        store = LoreStore()
        
        player = PlayerPerspective(
            perspective_id="player_1",
            perspective_type=PerspectiveType.PLAYER,
            owner_id="player_1",
        )
        
        views = store.get_views_for_perspective(player)
        
        assert views == []


class TestCheckRevealConditions:
    """Test reveal condition checking."""

    def test_check_reveal_conditions_returns_false_for_unknown(self):
        store = LoreStore()
        
        result = store.check_reveal_conditions("unknown", {})
        
        assert result is False

    def test_check_reveal_conditions_with_empty_conditions(self):
        store = LoreStore()
        entry = LoreEntry(
            lore_id="lore_1",
            title="Lore",
            category=LoreCategory.HISTORY,
            canonical_content="Content",
            hidden_from_player_until=[],
        )
        
        store.add_entry(entry)
        
        result = store.check_reveal_conditions("lore_1", {})
        
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

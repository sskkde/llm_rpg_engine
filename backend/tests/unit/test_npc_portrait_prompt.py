"""Tests for NPC portrait prompt builder."""

import pytest
from unittest.mock import MagicMock, patch

from llm_rpg.services.npc_portrait_prompt import (
    MOOD_TO_EXPRESSION,
    PortraitContext,
    build_portrait_context,
    build_portrait_prompt,
    map_mood_to_expression,
)


class TestMoodToExpressionMapping:
    """Tests for mood→expression mapping."""

    def test_suspicious_maps_to_thoughtful(self):
        assert MOOD_TO_EXPRESSION["suspicious"] == "thoughtful"
        assert map_mood_to_expression("suspicious") == "thoughtful"

    def test_friendly_maps_to_happy(self):
        assert MOOD_TO_EXPRESSION["friendly"] == "happy"
        assert map_mood_to_expression("friendly") == "happy"

    def test_warm_maps_to_happy(self):
        assert MOOD_TO_EXPRESSION["warm"] == "happy"
        assert map_mood_to_expression("warm") == "happy"

    def test_wary_maps_to_surprised(self):
        assert MOOD_TO_EXPRESSION["wary"] == "surprised"
        assert map_mood_to_expression("wary") == "surprised"

    def test_neutral_maps_to_neutral(self):
        assert MOOD_TO_EXPRESSION["neutral"] == "neutral"
        assert map_mood_to_expression("neutral") == "neutral"

    def test_cold_maps_to_angry(self):
        assert MOOD_TO_EXPRESSION["cold"] == "angry"
        assert map_mood_to_expression("cold") == "angry"

    def test_unknown_mood_returns_neutral(self):
        assert map_mood_to_expression("unknown_mood") == "neutral"
        assert map_mood_to_expression("") == "neutral"
        assert map_mood_to_expression("happy") == "neutral"


class TestPortraitContext:
    """Tests for PortraitContext model."""

    def test_default_values(self):
        context = PortraitContext()
        assert context.npc_id == ""
        assert context.npc_name == ""
        assert context.role_type == ""
        assert context.mood == "neutral"
        assert context.expression == "neutral"
        assert context.personality == ""
        assert context.appearance == ""
        assert context.location_name == ""
        assert context.location_tags == []
        assert context.trust_score == 50
        assert context.suspicion_score == 0
        assert context.recent_narration_summary == ""
        assert context.combat_state == ""
        assert context.chapter_theme == ""

    def test_custom_values(self):
        context = PortraitContext(
            npc_id="npc-123",
            npc_name="张三",
            role_type="merchant",
            mood="friendly",
            expression="happy",
            personality="开朗热情",
            appearance="身材高大",
        )
        assert context.npc_id == "npc-123"
        assert context.npc_name == "张三"
        assert context.role_type == "merchant"
        assert context.mood == "friendly"
        assert context.expression == "happy"
        assert context.personality == "开朗热情"
        assert context.appearance == "身材高大"


class TestBuildPortraitContext:
    """Tests for build_portrait_context function."""

    def test_with_available_data(self):
        db = MagicMock()
        npc_template = MagicMock()
        npc_template.name = "李四"
        npc_template.role_type = "guard"
        npc_template.personality = "严肃认真"
        npc_template.appearance = "身材魁梧"

        npc_state = MagicMock()
        npc_state.trust_score = 80
        npc_state.suspicion_score = 10

        location = MagicMock()
        location.name = "城门"
        location.tags = ["outdoor", "public"]

        session_state = MagicMock()
        session_state.current_location_id = "loc-123"

        event = MagicMock()
        event.narrative_text = "玩家走近城门。"

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_state_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo = npc_repo_cls.return_value
            npc_repo.get_by_id.return_value = npc_template

            state_repo = state_repo_cls.return_value
            state_repo.get_by_session_and_npc.return_value = npc_state

            sess_state_repo = sess_state_repo_cls.return_value
            sess_state_repo.get_by_session.return_value = session_state

            loc_repo = loc_repo_cls.return_value
            loc_repo.get_by_id.return_value = location

            event_repo = event_repo_cls.return_value
            event_repo.get_recent.return_value = [event]

            context = build_portrait_context("sess-1", "npc-1", db)

        assert context.npc_id == "npc-1"
        assert context.npc_name == "李四"
        assert context.role_type == "guard"
        assert context.personality == "严肃认真"
        assert context.appearance == "身材魁梧"
        assert context.trust_score == 80
        assert context.suspicion_score == 10
        assert context.mood == "friendly"
        assert context.expression == "happy"
        assert context.location_name == "城门"
        assert context.location_tags == ["outdoor", "public"]
        assert "玩家走近城门" in context.recent_narration_summary

    def test_with_missing_npc_template(self):
        db = MagicMock()

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_state_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo = npc_repo_cls.return_value
            npc_repo.get_by_id.return_value = None

            state_repo = state_repo_cls.return_value
            state_repo.get_by_session_and_npc.return_value = None

            sess_state_repo = sess_state_repo_cls.return_value
            sess_state_repo.get_by_session.return_value = None

            loc_repo = loc_repo_cls.return_value

            event_repo = event_repo_cls.return_value
            event_repo.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-missing", db)

        assert context.npc_id == "npc-missing"
        assert context.npc_name == ""
        assert context.role_type == ""
        assert context.personality == ""
        assert context.appearance == ""
        assert context.trust_score == 50
        assert context.suspicion_score == 0
        assert context.mood == "neutral"
        assert context.expression == "neutral"
        assert context.location_name == ""
        assert context.location_tags == []
        assert context.recent_narration_summary == ""

    def test_with_high_suspicion_derives_suspicious_mood(self):
        db = MagicMock()
        npc_state = MagicMock()
        npc_state.trust_score = 50
        npc_state.suspicion_score = 75

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_state_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo = npc_repo_cls.return_value
            npc_repo.get_by_id.return_value = None

            state_repo = state_repo_cls.return_value
            state_repo.get_by_session_and_npc.return_value = npc_state

            sess_state_repo = sess_state_repo_cls.return_value
            sess_state_repo.get_by_session.return_value = None

            loc_repo = loc_repo_cls.return_value

            event_repo = event_repo_cls.return_value
            event_repo.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-1", db)

        assert context.mood == "suspicious"
        assert context.expression == "thoughtful"

    def test_with_low_trust_derives_cold_mood(self):
        db = MagicMock()
        npc_state = MagicMock()
        npc_state.trust_score = 20
        npc_state.suspicion_score = 30

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_state_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo = npc_repo_cls.return_value
            npc_repo.get_by_id.return_value = None

            state_repo = state_repo_cls.return_value
            state_repo.get_by_session_and_npc.return_value = npc_state

            sess_state_repo = sess_state_repo_cls.return_value
            sess_state_repo.get_by_session.return_value = None

            loc_repo = loc_repo_cls.return_value

            event_repo = event_repo_cls.return_value
            event_repo.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-1", db)

        assert context.mood == "cold"
        assert context.expression == "angry"


class TestBuildPortraitPrompt:
    """Tests for build_portrait_prompt function."""

    def test_produces_prompt_with_npc_name(self):
        context = PortraitContext(
            npc_id="npc-123",
            npc_name="王五",
            role_type="merchant",
            appearance="身材矮小",
            personality="精明能干，善于经商",
            mood="friendly",
            expression="happy",
        )
        prompt = build_portrait_prompt(context)
        assert "王五" in prompt
        assert "npc-123" not in prompt
        assert "merchant" in prompt
        assert "Appearance" in prompt
        assert "Personality" in prompt

    def test_with_empty_context(self):
        context = PortraitContext()
        prompt = build_portrait_prompt(context)
        assert "portrait" in prompt.lower()
        assert prompt.endswith(".")

    def test_with_only_npc_name(self):
        context = PortraitContext(npc_name="赵六")
        prompt = build_portrait_prompt(context)
        assert "赵六" in prompt
        assert prompt.startswith("A portrait of 赵六")

    def test_with_location(self):
        context = PortraitContext(
            npc_name="孙七",
            location_name="客栈",
        )
        prompt = build_portrait_prompt(context)
        assert "孙七" in prompt
        assert "客栈" in prompt

    def test_truncates_long_personality(self):
        long_personality = "a" * 500
        context = PortraitContext(
            npc_name="NPC",
            personality=long_personality,
        )
        prompt = build_portrait_prompt(context)
        assert "Personality:" in prompt
        assert len(prompt) < 600

    def test_uses_expression_over_mood(self):
        context = PortraitContext(
            npc_name="NPC",
            mood="friendly",
            expression="happy",
        )
        prompt = build_portrait_prompt(context)
        assert "Expression: happy" in prompt

    def test_uses_mood_when_expression_neutral(self):
        context = PortraitContext(
            npc_name="NPC",
            mood="suspicious",
            expression="neutral",
        )
        prompt = build_portrait_prompt(context)
        assert "Mood: suspicious" in prompt

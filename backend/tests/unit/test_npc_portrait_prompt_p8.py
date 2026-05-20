"""P8 tests: NPC portrait context builder integration with media API.

Tests cover:
- Rich prompt with full context (NPC name, mood/expression, personality, appearance, location)
- Fallback prompt with minimal data (only NPC template, no state/location)
- Prompt when NPC template doesn't exist (defaults, no crash)
- Media API uses rich prompt when session_id provided
- Media API falls back to trivial prompt when context build raises
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.services.npc_portrait_prompt import (
    PortraitContext,
    build_portrait_context,
    build_portrait_prompt,
    map_mood_to_expression,
)
from llm_rpg.storage.database import Base, get_db
from llm_rpg.main import app
from llm_rpg.api.auth import get_current_active_user


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
def test_user(db_session):
    from llm_rpg.storage.repositories import UserRepository
    user_repo = UserRepository(db_session)
    user = user_repo.create({
        "username": "test_p8_user",
        "email": "p8_test@example.com",
        "password_hash": "hashed_password",
    })
    db_session.commit()
    return user


@pytest.fixture(scope="function")
def client(db_engine, db_session, test_user):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_current_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestRichPromptWithFullContext:
    """build_portrait_context + build_portrait_prompt with all data present."""

    def test_prompt_contains_npc_name_not_id(self):
        db = MagicMock()
        npc_template = MagicMock()
        npc_template.name = "云长老"
        npc_template.role_type = "elder"
        npc_template.personality = "深沉内敛，不露声色"
        npc_template.appearance = "白发苍苍，仙风道骨"

        npc_state = MagicMock()
        npc_state.trust_score = 85
        npc_state.suspicion_score = 5

        location = MagicMock()
        location.name = "青云峰"
        location.tags = ["mountain", "sacred"]

        session_state = MagicMock()
        session_state.current_location_id = "loc-qingyun"

        event = MagicMock()
        event.narrative_text = "云长老缓缓睁开双眼。"

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo_cls.return_value.get_by_id.return_value = npc_template
            state_repo_cls.return_value.get_by_session_and_npc.return_value = npc_state
            sess_repo_cls.return_value.get_by_session.return_value = session_state
            loc_repo_cls.return_value.get_by_id.return_value = location
            event_repo_cls.return_value.get_recent.return_value = [event]

            context = build_portrait_context("sess-1", "npc-elder-1", db)

        prompt = build_portrait_prompt(context)

        assert "云长老" in prompt
        assert "npc-elder-1" not in prompt
        assert "elder" in prompt
        assert "Appearance" in prompt
        assert "仙风道骨" in prompt
        assert "Personality" in prompt
        assert "深沉内敛" in prompt
        assert "青云峰" in prompt

    def test_prompt_contains_mood_expression(self):
        db = MagicMock()
        npc_state = MagicMock()
        npc_state.trust_score = 85
        npc_state.suspicion_score = 5

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo_cls.return_value.get_by_id.return_value = None
            state_repo_cls.return_value.get_by_session_and_npc.return_value = npc_state
            sess_repo_cls.return_value.get_by_session.return_value = None
            loc_repo_cls.return_value.get_by_id.return_value = None
            event_repo_cls.return_value.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-1", db)

        prompt = build_portrait_prompt(context)
        assert context.mood == "friendly"
        assert context.expression == "happy"
        assert "Expression: happy" in prompt

    def test_prompt_contains_location_name(self):
        context = PortraitContext(
            npc_name="铁匠",
            location_name="铁匠铺",
        )
        prompt = build_portrait_prompt(context)
        assert "铁匠铺" in prompt


class TestFallbackPromptMinimalData:
    """Only NPC template exists — no state, no location. Prompt still valid."""

    def test_prompt_with_only_template(self):
        db = MagicMock()
        npc_template = MagicMock()
        npc_template.name = "路人甲"
        npc_template.role_type = "villager"
        npc_template.personality = "普通村民"
        npc_template.appearance = "衣着朴素"

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo_cls.return_value.get_by_id.return_value = npc_template
            state_repo_cls.return_value.get_by_session_and_npc.return_value = None
            sess_repo_cls.return_value.get_by_session.return_value = None
            loc_repo_cls.return_value.get_by_id.return_value = None
            event_repo_cls.return_value.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-villager", db)

        prompt = build_portrait_prompt(context)

        assert "路人甲" in prompt
        assert "villager" in prompt
        assert "Appearance" in prompt
        assert "衣着朴素" in prompt
        assert prompt.endswith(".")

    def test_no_crash_with_empty_template_fields(self):
        db = MagicMock()
        npc_template = MagicMock()
        npc_template.name = None
        npc_template.role_type = None
        npc_template.personality = None
        npc_template.appearance = None

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo_cls.return_value.get_by_id.return_value = npc_template
            state_repo_cls.return_value.get_by_session_and_npc.return_value = None
            sess_repo_cls.return_value.get_by_session.return_value = None
            loc_repo_cls.return_value.get_by_id.return_value = None
            event_repo_cls.return_value.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-blank", db)

        prompt = build_portrait_prompt(context)
        assert "portrait" in prompt.lower()
        assert prompt.endswith(".")


class TestPromptNoMatchingNpcTemplate:
    """npc_id doesn't exist — prompt uses defaults, no crash."""

    def test_missing_template_uses_defaults(self):
        db = MagicMock()

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo_cls.return_value.get_by_id.return_value = None
            state_repo_cls.return_value.get_by_session_and_npc.return_value = None
            sess_repo_cls.return_value.get_by_session.return_value = None
            loc_repo_cls.return_value.get_by_id.return_value = None
            event_repo_cls.return_value.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-nonexistent", db)

        prompt = build_portrait_prompt(context)

        assert context.npc_id == "npc-nonexistent"
        assert context.npc_name == ""
        assert context.mood == "neutral"
        assert context.expression == "neutral"
        assert "portrait" in prompt.lower()
        assert prompt.endswith(".")

    def test_missing_template_no_state_still_derives_mood(self):
        db = MagicMock()
        npc_state = MagicMock()
        npc_state.trust_score = 20
        npc_state.suspicion_score = 30

        with patch("llm_rpg.storage.repositories.NPCTemplateRepository") as npc_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionNPCStateRepository") as state_repo_cls, \
             patch("llm_rpg.storage.repositories.SessionStateRepository") as sess_repo_cls, \
             patch("llm_rpg.storage.repositories.LocationRepository") as loc_repo_cls, \
             patch("llm_rpg.storage.repositories.EventLogRepository") as event_repo_cls:
            npc_repo_cls.return_value.get_by_id.return_value = None
            state_repo_cls.return_value.get_by_session_and_npc.return_value = npc_state
            sess_repo_cls.return_value.get_by_session.return_value = None
            loc_repo_cls.return_value.get_by_id.return_value = None
            event_repo_cls.return_value.get_recent.return_value = []

            context = build_portrait_context("sess-1", "npc-unknown", db)

        assert context.mood == "cold"
        assert context.expression == "angry"
        prompt = build_portrait_prompt(context)
        assert "Expression: angry" in prompt


class TestMediaApiUsesRichPrompt:
    """Media API portrait endpoints use build_portrait_prompt when session_id provided."""

    def test_generate_portrait_with_session_id_calls_rich_prompt(self, client):
        with patch("llm_rpg.api.media.build_portrait_context") as mock_ctx, \
             patch("llm_rpg.api.media.build_portrait_prompt") as mock_prompt:
            mock_ctx.return_value = PortraitContext(
                npc_id="npc-1",
                npc_name="测试NPC",
                role_type="merchant",
                expression="happy",
                appearance="高大",
                personality="精明",
            )
            mock_prompt.return_value = "A portrait of 测试NPC, a merchant. Appearance: 高大. Personality: 精明. Expression: happy."

            response = client.post("/media/portraits/generate", json={
                "npc_id": "npc-1",
                "style": "anime",
                "session_id": "sess-1",
            })

            assert response.status_code == 200
            mock_ctx.assert_called_once()
            mock_prompt.assert_called_once()

    def test_generate_portrait_without_session_id_uses_trivial(self, client):
        with patch("llm_rpg.api.media.build_portrait_context") as mock_ctx, \
             patch("llm_rpg.api.media.build_portrait_prompt") as mock_prompt:
            response = client.post("/media/portraits/generate", json={
                "npc_id": "npc-1",
                "style": "anime",
            })

            assert response.status_code == 200
            mock_ctx.assert_not_called()
            mock_prompt.assert_not_called()

    def test_create_portrait_job_with_session_id_calls_rich_prompt(self, client):
        with patch("llm_rpg.api.media.build_portrait_context") as mock_ctx, \
             patch("llm_rpg.api.media.build_portrait_prompt") as mock_prompt:
            mock_ctx.return_value = PortraitContext(
                npc_id="npc-2",
                npc_name="商人",
            )
            mock_prompt.return_value = "A portrait of 商人."

            response = client.post("/media/jobs/portraits", json={
                "npc_id": "npc-2",
                "style": "realistic",
                "session_id": "sess-2",
            })

            assert response.status_code == 200
            mock_ctx.assert_called_once()
            mock_prompt.assert_called_once()


class TestMediaApiFallbackOnError:
    """When build_portrait_context/prompt raises, endpoint falls back to trivial prompt."""

    def test_generate_portrait_fallback_on_context_error(self, client):
        with patch("llm_rpg.api.media.build_portrait_context", side_effect=RuntimeError("DB error")), \
             patch("llm_rpg.api.media.build_portrait_prompt") as mock_prompt:
            response = client.post("/media/portraits/generate", json={
                "npc_id": "npc-1",
                "style": "anime",
                "session_id": "sess-1",
            })

            assert response.status_code == 200
            data = response.json()
            assert "asset_id" in data
            mock_prompt.assert_not_called()

    def test_generate_portrait_fallback_on_prompt_error(self, client):
        with patch("llm_rpg.api.media.build_portrait_context") as mock_ctx, \
             patch("llm_rpg.api.media.build_portrait_prompt", side_effect=ValueError("bad prompt")):
            mock_ctx.return_value = PortraitContext(npc_id="npc-1")

            response = client.post("/media/portraits/generate", json={
                "npc_id": "npc-1",
                "style": "anime",
                "session_id": "sess-1",
            })

            assert response.status_code == 200
            data = response.json()
            assert "asset_id" in data

    def test_create_portrait_job_fallback_on_error(self, client):
        with patch("llm_rpg.api.media.build_portrait_context", side_effect=Exception("unexpected")):
            response = client.post("/media/jobs/portraits", json={
                "npc_id": "npc-1",
                "style": "anime",
                "session_id": "sess-1",
            })

            assert response.status_code == 200
            data = response.json()
            assert "job_id" in data

    def test_no_500_on_context_failure(self, client):
        with patch("llm_rpg.api.media.build_portrait_context", side_effect=Exception("catastrophic")):
            response = client.post("/media/portraits/generate", json={
                "npc_id": "npc-1",
                "session_id": "sess-1",
            })
            assert response.status_code != 500

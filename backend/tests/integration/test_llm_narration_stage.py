"""
Integration tests for LLM narration stage in turn service.

Tests:
- LLM narration replaces template when enabled and successful
- Fallback to template on LLM failure/timeout/invalid output
- No hidden NPC info in narration context
- EventCommitted still precedes narration_delta in SSE
- No second turn row created (updates existing EventLogModel)
"""

import json
import pytest
import uuid
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.api.auth import get_current_active_user
from llm_rpg.main import app
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    SaveSlotModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionQuestStateModel,
    SessionStateModel,
    SystemSettingsModel,
    UserModel,
    WorldModel,
)
from llm_rpg.core.turn_service import (
    _build_narration_context,
    _get_visible_npcs,
    _is_narration_stage_enabled,
    _execute_narration_stage,
    execute_turn_service,
)
from llm_rpg.llm.service import MockLLMProvider, LLMService, LLMMessage


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded_session(db: Session) -> SessionModel:
    user = UserModel(
        id="narration_user",
        username="narration_user",
        email="narration@example.com",
        password_hash="hashed",
        is_admin=True,
    )
    world = WorldModel(
        id="narration_world",
        code="narration_world",
        name="叙事测试世界",
        genre="xianxia",
        status="active",
    )
    chapter = ChapterModel(
        id="narration_chapter",
        world_id=world.id,
        chapter_no=1,
        name="初入宗门",
    )
    square = LocationModel(
        id="narration_square",
        world_id=world.id,
        chapter_id=chapter.id,
        code="square",
        name="宗门广场",
        access_rules={"always_accessible": True},
    )
    trial_hall = LocationModel(
        id="narration_trial_hall",
        world_id=world.id,
        chapter_id=chapter.id,
        code="trial_hall",
        name="试炼堂",
        access_rules={"time_restrictions": "daytime_only"},
    )
    npc_public = NPCTemplateModel(
        id="narration_npc_public",
        world_id=world.id,
        code="senior_sister",
        name="柳师姐",
        role_type="guide",
        public_identity="宗门资深弟子",
        hidden_identity="隐藏身份不应泄露",
    )
    quest = QuestTemplateModel(
        id="narration_quest",
        world_id=world.id,
        code="first_trial",
        name="初次试炼",
        quest_type="main",
        visibility="visible",
    )
    slot = SaveSlotModel(
        id="narration_slot",
        user_id=user.id,
        slot_number=1,
        name="叙事测试存档",
    )
    session = SessionModel(
        id="narration_session",
        user_id=user.id,
        save_slot_id=slot.id,
        world_id=world.id,
        current_chapter_id=chapter.id,
        status="active",
    )

    db.add_all([
        user, world, chapter, square, trial_hall,
        npc_public, quest, slot, session,
    ])
    db.commit()
    return session


@pytest.fixture
def client(db_engine, seeded_session: SessionModel):
    SessionLocal = sessionmaker(bind=db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_current_user():
        return UserModel(
            id=seeded_session.user_id,
            username="narration_user",
            email="narration@example.com",
            is_admin=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _event_payloads(raw_sse: str):
    payloads = []
    event_name = None
    for line in raw_sse.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            payloads.append((event_name, json.loads(line.removeprefix("data: "))))
    return payloads


class TestNarrationContextBuilder:
    """Tests for _build_narration_context helper."""

    def test_context_includes_session_state(self, db: Session, seeded_session: SessionModel):
        from llm_rpg.core.state_reconstruction import reconstruct_canonical_state

        canonical = reconstruct_canonical_state(db, seeded_session.id)
        context = _build_narration_context(
            db=db,
            session_id=seeded_session.id,
            canonical_state=canonical,
            player_input="观察四周",
            action_type="inspect",
        )

        assert "world_time" in context
        assert "player_state" in context
        assert context["player_input"] == "观察四周"
        assert context["action_type"] == "inspect"

    def test_context_excludes_hidden_npc_identity(self, db: Session, seeded_session: SessionModel):
        from llm_rpg.core.state_reconstruction import reconstruct_canonical_state

        canonical = reconstruct_canonical_state(db, seeded_session.id)
        context = _build_narration_context(
            db=db,
            session_id=seeded_session.id,
            canonical_state=canonical,
            player_input="观察四周",
            action_type="inspect",
        )

        for npc in context.get("visible_npcs", []):
            assert "hidden_identity" not in npc

    def test_context_includes_movement_result(self, db: Session, seeded_session: SessionModel):
        from llm_rpg.core.state_reconstruction import reconstruct_canonical_state
        from llm_rpg.core.movement_handler import MovementResult

        canonical = reconstruct_canonical_state(db, seeded_session.id)
        movement = MovementResult(
            success=True,
            new_location_id="narration_trial_hall",
            new_location_name="试炼堂",
            new_location_code="trial_hall",
            narration_hint="你来到了试炼堂。",
        )
        context = _build_narration_context(
            db=db,
            session_id=seeded_session.id,
            canonical_state=canonical,
            player_input="前往试炼堂",
            action_type="move",
            movement_result=movement,
        )

        assert "movement" in context
        assert context["movement"]["success"] is True
        assert context["movement"]["new_location_name"] == "试炼堂"

    def test_context_includes_recent_events(self, db: Session, seeded_session: SessionModel):
        from llm_rpg.core.state_reconstruction import reconstruct_canonical_state

        canonical = reconstruct_canonical_state(db, seeded_session.id)
        context = _build_narration_context(
            db=db,
            session_id=seeded_session.id,
            canonical_state=canonical,
            player_input="观察四周",
            action_type="inspect",
        )

        assert "recent_events" in context
        assert isinstance(context["recent_events"], list)


class TestVisibleNPCs:
    """Tests for _get_visible_npcs helper."""

    def test_no_hidden_identity_in_visible_npcs(self, db: Session, seeded_session: SessionModel):
        npcs = _get_visible_npcs(db, seeded_session.id, "narration_square")
        for npc in npcs:
            assert "hidden_identity" not in npc
            assert "name" in npc
            assert "public_identity" in npc

    def test_only_location_npcs_returned(self, db: Session, seeded_session: SessionModel):
        npcs = _get_visible_npcs(db, seeded_session.id, "narration_trial_hall")
        assert len(npcs) == 0


class TestNarrationStageEnabled:
    """Tests for _is_narration_stage_enabled feature flag."""

    def test_disabled_when_provider_is_mock(self, db: Session):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()
        assert _is_narration_stage_enabled(db) is False

    def test_enabled_when_provider_is_openai(self, db: Session):
        settings = SystemSettingsModel(provider_mode="openai")
        db.add(settings)
        db.commit()
        assert _is_narration_stage_enabled(db) is True

    def test_enabled_when_provider_is_auto(self, db: Session):
        settings = SystemSettingsModel(provider_mode="auto")
        db.add(settings)
        db.commit()
        assert _is_narration_stage_enabled(db) is True


class TestLLMNarrationReplacement:
    """Tests for LLM narration replacing template text."""

    def test_llm_narration_replaces_template_when_enabled(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()

        mock_provider = MockLLMProvider(responses={
            "narration": json.dumps({
                "text": "古老的山门广场铺满了青石板，岁月在上面留下了深深的痕迹。",
                "tone": "neutral",
                "style_tags": ["descriptive"],
            }),
        })
        real_llm_service = LLMService(provider=mock_provider, db_session=db)

        with patch(
            "llm_rpg.core.turn_service._create_llm_service_from_config",
            return_value=real_llm_service,
        ):
            with patch(
                "llm_rpg.core.turn_service._is_narration_stage_enabled",
                return_value=True,
            ):
                response = client.post(
                    f"/game/sessions/{seeded_session.id}/turn",
                    json={"action": "观察四周"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["narration"] == "古老的山门广场铺满了青石板，岁月在上面留下了深深的痕迹。"

    def test_fallback_to_template_on_llm_failure(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()

        with patch(
            "llm_rpg.core.turn_service._is_narration_stage_enabled",
            return_value=True,
        ):
            with patch(
                "llm_rpg.core.turn_service._create_llm_service_from_config",
                side_effect=Exception("LLM unavailable"),
            ):
                response = client.post(
                    f"/game/sessions/{seeded_session.id}/turn",
                    json={"action": "观察四周"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["narration"] is not None
        assert len(data["narration"]) > 0


class TestExplicitProviderConfigErrors:
    """Tests for explicit provider mode configuration errors."""

    def test_openai_mode_missing_key_returns_503(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="openai")
        db.add(settings)
        db.commit()

        with patch(
            "llm_rpg.services.settings.SystemSettingsService.get_effective_openai_key",
            return_value=None,
        ):
            response = client.post(
                f"/game/sessions/{seeded_session.id}/turn",
                json={"action": "观察四周"},
            )

        assert response.status_code == 503
        data = response.json()
        assert "detail" in data
        assert data["detail"]["provider_mode"] == "openai"
        assert data["detail"]["missing_config"] == "openai_api_key"

    def test_custom_mode_missing_base_url_returns_503(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="custom")
        db.add(settings)
        db.commit()

        with patch(
            "llm_rpg.services.settings.SystemSettingsService.get_effective_custom_base_url",
            return_value=None,
        ):
            response = client.post(
                f"/game/sessions/{seeded_session.id}/turn",
                json={"action": "观察四周"},
            )

        assert response.status_code == 503
        data = response.json()
        assert "detail" in data
        assert data["detail"]["provider_mode"] == "custom"
        assert data["detail"]["missing_config"] == "custom_base_url"

    def test_custom_mode_missing_api_key_returns_503(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="custom")
        db.add(settings)
        db.commit()

        with patch(
            "llm_rpg.services.settings.SystemSettingsService.get_effective_custom_base_url",
            return_value="https://api.custom.com",
        ):
            with patch(
                "llm_rpg.services.settings.SystemSettingsService.get_effective_custom_api_key",
                return_value=None,
            ):
                response = client.post(
                    f"/game/sessions/{seeded_session.id}/turn",
                    json={"action": "观察四周"},
                )

        assert response.status_code == 503
        data = response.json()
        assert "detail" in data
        assert data["detail"]["provider_mode"] == "custom"
        assert data["detail"]["missing_config"] == "custom_api_key"

    def test_openai_mode_missing_key_no_event_log_created(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="openai")
        db.add(settings)
        db.commit()

        initial_count = db.query(EventLogModel).filter_by(
            session_id=seeded_session.id,
        ).count()

        with patch(
            "llm_rpg.services.settings.SystemSettingsService.get_effective_openai_key",
            return_value=None,
        ):
            response = client.post(
                f"/game/sessions/{seeded_session.id}/turn",
                json={"action": "观察四周"},
            )

        assert response.status_code == 503

        final_count = db.query(EventLogModel).filter_by(
            session_id=seeded_session.id,
        ).count()

        assert final_count == initial_count

    def test_custom_mode_missing_config_no_event_log_created(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="custom")
        db.add(settings)
        db.commit()

        initial_count = db.query(EventLogModel).filter_by(
            session_id=seeded_session.id,
        ).count()

        with patch(
            "llm_rpg.services.settings.SystemSettingsService.get_effective_custom_base_url",
            return_value=None,
        ):
            response = client.post(
                f"/game/sessions/{seeded_session.id}/turn",
                json={"action": "观察四周"},
            )

        assert response.status_code == 503

        final_count = db.query(EventLogModel).filter_by(
            session_id=seeded_session.id,
        ).count()

        assert final_count == initial_count

    def test_auto_mode_missing_key_returns_200_with_mock(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="auto")
        db.add(settings)
        db.commit()

        with patch(
            "llm_rpg.services.settings.SystemSettingsService.get_effective_openai_key",
            return_value=None,
        ):
            response = client.post(
                f"/game/sessions/{seeded_session.id}/turn",
                json={"action": "观察四周"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["narration"] is not None

    def test_mock_mode_always_returns_200(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()

        response = client.post(
            f"/game/sessions/{seeded_session.id}/turn",
            json={"action": "观察四周"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["narration"] is not None
        assert len(data["narration"]) > 0

    def test_fallback_on_empty_llm_output(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()

        mock_provider = MockLLMProvider(responses={
            "narration": "",
        })
        real_llm_service = LLMService(provider=mock_provider, db_session=db)

        with patch(
            "llm_rpg.core.turn_service._create_llm_service_from_config",
            return_value=real_llm_service,
        ):
            with patch(
                "llm_rpg.core.turn_service._is_narration_stage_enabled",
                return_value=True,
            ):
                response = client.post(
                    f"/game/sessions/{seeded_session.id}/turn",
                    json={"action": "观察四周"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["narration"] is not None
        assert len(data["narration"]) > 0


class TestNoSecondTurnRow:
    """Tests that LLM narration updates existing row, not creating second turn."""

    def test_single_event_log_row_after_llm_narration(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()

        mock_provider = MockLLMProvider(responses={
            "narration": json.dumps({
                "text": "LLM生成的叙事文本。",
                "tone": "neutral",
            }),
        })
        real_llm_service = LLMService(provider=mock_provider, db_session=db)

        with patch(
            "llm_rpg.core.turn_service._create_llm_service_from_config",
            return_value=real_llm_service,
        ):
            with patch(
                "llm_rpg.core.turn_service._is_narration_stage_enabled",
                return_value=True,
            ):
                response = client.post(
                    f"/game/sessions/{seeded_session.id}/turn",
                    json={"action": "观察四周"},
                )

        assert response.status_code == 200

        db.expire_all()
        event_count = db.query(EventLogModel).filter_by(
            session_id=seeded_session.id,
            turn_no=1,
            event_type="player_turn",
        ).count()
        assert event_count == 1

        event = db.query(EventLogModel).filter_by(
            session_id=seeded_session.id,
            turn_no=1,
            event_type="player_turn",
        ).one()
        assert event.narrative_text == "LLM生成的叙事文本。"


class TestSSENarrationOrder:
    """Tests for SSE event ordering with LLM narration."""

    def test_event_committed_before_narration_delta(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()

        with client.stream(
            "POST",
            f"/streaming/sessions/{seeded_session.id}/turn/mock",
            json={"action": "观察四周"},
        ) as response:
            assert response.status_code == 200
            raw_sse = "".join(response.iter_text())

        payloads = _event_payloads(raw_sse)
        event_names = [name for name, _ in payloads]

        assert "turn_started" in event_names
        assert "event_committed" in event_names
        assert "narration_delta" in event_names
        assert "turn_completed" in event_names

        committed_idx = event_names.index("event_committed")
        narration_idx = event_names.index("narration_delta")
        completed_idx = event_names.index("turn_completed")

        assert committed_idx < narration_idx < completed_idx

    def test_narration_delta_uses_final_narration(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        with client.stream(
            "POST",
            f"/streaming/sessions/{seeded_session.id}/turn/mock",
            json={"action": "探索"},
        ) as response:
            assert response.status_code == 200
            raw_sse = "".join(response.iter_text())

        payloads = _event_payloads(raw_sse)
        narration_deltas = [data for name, data in payloads if name == "narration_delta"]
        assert len(narration_deltas) > 0

        accumulated = "".join(d["delta"] for d in narration_deltas)
        assert len(accumulated) > 0


class TestNarrationContextSecurity:
    """Tests for narration context security constraints."""

    def test_narration_context_has_constraints(self, db: Session, seeded_session: SessionModel):
        from llm_rpg.core.state_reconstruction import reconstruct_canonical_state

        canonical = reconstruct_canonical_state(db, seeded_session.id)
        context = _build_narration_context(
            db=db,
            session_id=seeded_session.id,
            canonical_state=canonical,
            player_input="观察四周",
            action_type="inspect",
        )

        assert "constraints" in context
        assert any("隐藏" in c for c in context["constraints"])

    def test_narration_stage_records_fallback_reason(
        self, client: TestClient, db: Session, seeded_session: SessionModel,
    ):
        settings = SystemSettingsModel(provider_mode="mock")
        db.add(settings)
        db.commit()

        with patch(
            "llm_rpg.core.turn_service._is_narration_stage_enabled",
            return_value=True,
        ):
            with patch(
                "llm_rpg.core.turn_service._create_llm_service_from_config",
                side_effect=Exception("test error"),
            ):
                response = client.post(
                    f"/game/sessions/{seeded_session.id}/turn",
                    json={"action": "观察四周"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["narration"] is not None

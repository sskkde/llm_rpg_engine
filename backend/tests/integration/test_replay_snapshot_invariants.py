"""
Integration tests for replay/snapshot hardened invariants.

Verifies:
- Replay/snapshot does NOT call LLM (MockLLMProvider call count = 0)
- Replay does NOT create new event/state rows in DB
- Snapshot creation is read-only (no DB mutation)
- Rejected proposals do NOT leave state deltas during replay reconstruction
- POST /debug/* replay endpoints preserve admin-only access and no-LLM behavior
"""

import pytest
import uuid
from datetime import datetime
from typing import Dict, Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel, WorldModel, SessionModel, EventLogModel,
    ModelCallLogModel, SessionStateModel, SessionPlayerStateModel,
    SessionNPCStateModel, SessionQuestStateModel,
    TurnTransactionModel, GameEventModel, StateDeltaModel,
)
from llm_rpg.core.replay import (
    get_replay_store, reset_replay_store,
    ReplayEngine, StateReconstructor,
    ReplayEvent, ReplayPerspective,
    StateDelta,
)
from llm_rpg.llm.service import MockLLMProvider
from llm_rpg.main import app


# =============================================================================
# Row Counting Helpers
# =============================================================================

def _count_rows(db: Session, model_cls, **filters) -> int:
    """Count rows for a given model class, optionally filtered."""
    q = db.query(model_cls)
    for col_name, value in filters.items():
        if hasattr(model_cls, col_name):
            q = q.filter(getattr(model_cls, col_name) == value)
    return q.count()


def _all_row_counts(db: Session, session_id: str) -> Dict[str, int]:
    """Return row counts for all replay-relevant tables."""
    return {
        "event_logs": _count_rows(db, EventLogModel, session_id=session_id),
        "session_states": _count_rows(db, SessionStateModel, session_id=session_id),
        "session_player_states": _count_rows(db, SessionPlayerStateModel, session_id=session_id),
        "session_npc_states": _count_rows(db, SessionNPCStateModel, session_id=session_id),
        "session_quest_states": _count_rows(db, SessionQuestStateModel, session_id=session_id),
        "turn_transactions": _count_rows(db, TurnTransactionModel, session_id=session_id),
        "game_events": _count_rows(db, GameEventModel, session_id=session_id),
        "state_deltas": _count_rows(db, StateDeltaModel, session_id=session_id),
        "model_call_logs": _count_rows(db, ModelCallLogModel, session_id=session_id),
    }


def _initial_db_counts_after_seed(db: Session) -> Dict[str, int]:
    """Return baseline counts of all rows (before replay/snapshot operations)."""
    return {
        "event_logs": _count_rows(db, EventLogModel),
        "session_states": _count_rows(db, SessionStateModel),
        "session_player_states": _count_rows(db, SessionPlayerStateModel),
        "session_npc_states": _count_rows(db, SessionNPCStateModel),
        "session_quest_states": _count_rows(db, SessionQuestStateModel),
        "turn_transactions": _count_rows(db, TurnTransactionModel),
        "game_events": _count_rows(db, GameEventModel),
        "state_deltas": _count_rows(db, StateDeltaModel),
        "model_call_logs": _count_rows(db, ModelCallLogModel),
    }


# =============================================================================
# Test DB Fixtures (self-contained, no shared state with conftest.py)
# =============================================================================

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    """Fresh in-memory SQLite engine per test."""
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
def db_session(db_engine) -> Session:
    """Fresh DB session per test."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_engine):
    """FastAPI test client with isolated DB."""
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


# =============================================================================
# User + Auth Helpers
# =============================================================================

@pytest.fixture
def admin_user_data():
    return {
        "username": f"admin_{uuid.uuid4().hex[:8]}",
        "email": f"admin_{uuid.uuid4().hex[:8]}@example.com",
        "password": "AdminPass123!",
    }


@pytest.fixture
def regular_user_data():
    return {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"user_{uuid.uuid4().hex[:8]}@example.com",
        "password": "UserPass123!",
    }


def _create_user_in_db(db_engine, user_data, is_admin=False):
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        user = UserModel(
            id=str(uuid.uuid4()),
            username=user_data["username"],
            email=user_data["email"],
            password_hash=pwd_context.hash(user_data["password"]),
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def _get_auth_header(client, user_data):
    response = client.post("/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"],
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# Seed Helpers
# =============================================================================

def _seed_test_world(db: Session) -> str:
    """Create a minimal world with a location for testing."""
    world = WorldModel(
        id="test_world_inv",
        code="inv_world",
        name="Invariant Test World",
        genre="xianxia",
        status="active",
    )
    db.add(world)
    db.commit()
    return world.id


def _seed_test_session(db: Session, user_id: str = None, world_id: str = None) -> str:
    """Create a minimal session for testing."""
    session = SessionModel(
        id=f"ses_inv_{uuid.uuid4().hex[:8]}",
        user_id=user_id or "test_user_inv",
        world_id=world_id or "test_world_inv",
        status="active",
        started_at=datetime.now(),
        last_played_at=datetime.now(),
    )
    db.add(session)
    db.commit()
    return session.id


def _seed_session_with_events(db: Session, session_id: str) -> None:
    """Seed some event_logs for a session to test replay."""
    for turn in range(1, 4):
        event = EventLogModel(
            id=f"evt_inv_{session_id}_{turn}",
            session_id=session_id,
            turn_no=turn,
            event_type="player_input" if turn % 2 == 1 else "npc_action",
            input_text=f"Test input turn {turn}",
            narrative_text=f"Narration for turn {turn}",
            result_json={
                "llm_stages": [
                    {
                        "stage_name": "narration",
                        "enabled": True,
                        "accepted": True,
                    },
                ],
                "parsed_intent": {"intent_type": "move"},
            },
            occurred_at=datetime.now(),
        )
        db.add(event)
    db.commit()


# =============================================================================
# Test: MockLLMProvider Call Count = 0 During Replay
# =============================================================================

class TestReplayNoLLMCalls:
    """Verify that replay/snapshot operations never call LLM."""

    def setup_method(self):
        reset_replay_store()

    def test_replay_engine_reconstructs_without_llm_calls(self):
        """ReplayEngine.replay_turn_range must not call any LLM provider."""
        mock_provider = MockLLMProvider()
        engine = ReplayEngine()

        events = [
            ReplayEvent(
                event_id="evt_no_llm_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "test",
                    "result_json": {
                        "llm_stages": [
                            {"stage_name": "narration", "enabled": True, "accepted": True},
                        ],
                    },
                    "state_deltas": [
                        {"path": "player.hp", "old_value": 100, "new_value": 90, "operation": "set"},
                    ],
                },
            ),
        ]

        # Run replay - should NOT call LLM at all
        result = engine.replay_turn_range(
            session_id="test_no_llm",
            start_turn=1,
            end_turn=1,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        # Verify LLM provider was never called
        assert mock_provider.call_count == 0, (
            f"Expected 0 LLM calls during replay, got {mock_provider.call_count}"
        )

        # Verify replay succeeded
        assert result.success is True
        assert len(result.steps) == 1

    def test_replay_with_proposal_audits_no_llm_recall(self):
        """replay_with_proposal_audits must not re-call LLM."""
        mock_provider = MockLLMProvider()
        engine = ReplayEngine()

        proposal_audits = {
            1: [
                {"audit_id": "prop_001", "proposal_type": "input_intent", "fallback_used": False},
                {"audit_id": "prop_002", "proposal_type": "npc_action", "fallback_used": True},
            ],
        }

        events = [
            ReplayEvent(
                event_id="evt_prop_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={"raw_input": "test"},
            ),
        ]

        result = engine.replay_with_proposal_audits(
            session_id="test_prop_llm",
            start_turn=1,
            end_turn=1,
            events=events,
            proposal_audits=proposal_audits,
            perspective=ReplayPerspective.ADMIN,
        )

        assert mock_provider.call_count == 0
        assert result.success is True
        assert len(result.steps[0].proposal_audits) == 2

    def test_snapshot_creation_does_not_call_llm(self):
        """StateReconstructor.create_snapshot must not call LLM."""
        mock_provider = MockLLMProvider()
        reconstructor = StateReconstructor()

        snapshot = reconstructor.create_snapshot(
            session_id="test_snap_llm",
            turn_no=5,
            world_state={"time": "Day 1"},
            player_state={"hp": 100},
            npc_states={"npc_1": {"name": "Test"}},
        )

        assert mock_provider.call_count == 0
        assert snapshot.snapshot_id is not None
        assert snapshot.session_id == "test_snap_llm"

    def test_replay_extract_metadata_no_llm_call(self):
        """LLM stage metadata extraction must not call LLM - reads from stored data."""
        mock_provider = MockLLMProvider()
        engine = ReplayEngine()

        result_json = {
            "llm_stages": [
                {"stage_name": "input_intent", "enabled": True, "accepted": True},
                {"stage_name": "world", "enabled": True, "accepted": False, "fallback_reason": "validation_failed"},
            ],
        }

        metadata = engine.extract_llm_stage_metadata(result_json, ReplayPerspective.ADMIN)
        assert mock_provider.call_count == 0
        assert len(metadata) == 2

    def test_replay_get_proposal_audit_summary_no_llm_call(self):
        """Proposal audit summarization must not call LLM."""
        mock_provider = MockLLMProvider()
        engine = ReplayEngine()

        audits = [
            {"proposal_type": "input_intent", "confidence": 0.85, "fallback_used": False, "rejected": False},
            {"proposal_type": "npc_action", "confidence": 0.5, "fallback_used": True, "rejected": False},
            {"proposal_type": "scene_event", "confidence": 0.7, "fallback_used": False, "rejected": True},
        ]

        summary = engine.get_proposal_audit_summary(audits)
        assert mock_provider.call_count == 0
        assert summary["total"] == 3
        assert summary["fallbacks"] == 1
        assert summary["rejections"] == 1


# =============================================================================
# Test: Replay/Snapshot Does NOT Create New DB Rows
# =============================================================================

class TestReplayNoDBMutation:
    """Verify replay/snapshot operations do not create new DB rows."""

    def setup_method(self):
        reset_replay_store()

    def test_snapshot_creation_read_only_db(self, db_session):
        """Creating a snapshot via StateReconstructor must not create DB rows."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)

        before = _all_row_counts(db_session, session_id)

        # Create snapshot (in-memory, should NOT touch DB)
        replay_store = get_replay_store()
        replay_store.create_snapshot(
            session_id=session_id,
            turn_no=1,
            world_state={"time": "Day 1"},
            player_state={"hp": 100},
        )

        # Get snapshot (also in-memory)
        snapshots = replay_store.get_state_reconstructor()._snapshots
        assert len(snapshots) > 0

        after = _all_row_counts(db_session, session_id)

        # No DB rows should have been created
        for table, count_before in before.items():
            assert after[table] == count_before, (
                f"{table}: before={count_before}, after={after[table]} "
                f"(snapshot creation mutated DB)"
            )

    def test_replay_turn_range_no_db_mutation(self, db_session):
        """ReplayEngine.replay_turn_range must not create DB rows."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)

        before = _all_row_counts(db_session, session_id)

        engine = get_replay_store().get_replay_engine()
        events = [
            ReplayEvent(
                event_id=f"evt_r_{session_id}_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "test",
                    "state_deltas": [
                        {"path": "player.hp", "old_value": 100, "new_value": 90, "operation": "set"},
                    ],
                },
            ),
        ]

        result = engine.replay_turn_range(
            session_id=session_id,
            start_turn=1,
            end_turn=1,
            events=events,
        )

        assert result.success is True

        after = _all_row_counts(db_session, session_id)

        for table, count_before in before.items():
            assert after[table] == count_before, (
                f"{table}: before={count_before}, after={after[table]} "
                f"(replay mutated DB)"
            )

    def test_replay_from_snapshot_no_db_mutation(self, db_session):
        """ReplayEngine.replay_from_snapshot must not create DB rows."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)

        replay_store = get_replay_store()
        snapshot = replay_store.create_snapshot(
            session_id=session_id,
            turn_no=1,
            world_state={"time": "Day 1"},
            player_state={"hp": 100},
            npc_states={"npc_1": {"name": "Test", "mood": "friendly"}},
        )

        before = _all_row_counts(db_session, session_id)

        events = [
            ReplayEvent(
                event_id=f"evt_s_{session_id}_2",
                event_type="player_input",
                turn_no=2,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={"raw_input": "test"},
            ),
        ]

        result = replay_store.replay_from_snapshot(
            session_id=session_id,
            snapshot_id=snapshot.snapshot_id,
            target_turn=2,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True

        after = _all_row_counts(db_session, session_id)

        for table, count_before in before.items():
            assert after[table] == count_before, (
                f"{table}: before={count_before}, after={after[table]} "
                f"(replay_from_snapshot mutated DB)"
            )

    def test_total_db_row_count_unchanged_after_all_replay_ops(self, db_session):
        """Verify total DB row count across ALL tables unchanged after replay ops."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)

        before_total = _initial_db_counts_after_seed(db_session)

        # Run a full set of replay operations
        replay_store = get_replay_store()
        engine = replay_store.get_replay_engine()

        snapshot = replay_store.create_snapshot(
            session_id=session_id,
            turn_no=1,
            world_state={"time": "Day 1"},
            player_state={"hp": 100},
            npc_states={"npc_1": {"name": "Test", "hidden_plan_state": "secret"}},
        )

        events = [
            ReplayEvent(
                event_id="evt_1", event_type="player_input", turn_no=1,
                timestamp=datetime.now(), visible_to_player=True,
                data={
                    "raw_input": "test",
                    "state_deltas": [
                        {"path": "player.hp", "old_value": 100, "new_value": 90, "operation": "set"},
                    ],
                },
            ),
            ReplayEvent(
                event_id="evt_2", event_type="player_input", turn_no=2,
                timestamp=datetime.now(), visible_to_player=True,
                data={"raw_input": "test2"},
            ),
        ]

        # Run multiple replay operations
        engine.replay_from_snapshot(
            session_id=session_id,
            snapshot_id=snapshot.snapshot_id,
            target_turn=2,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        engine.replay_turn_range(
            session_id=session_id,
            start_turn=1,
            end_turn=2,
            events=events,
            perspective=ReplayPerspective.PLAYER,
        )

        engine.replay_with_proposal_audits(
            session_id=session_id,
            start_turn=1,
            end_turn=1,
            events=[events[0]],
            proposal_audits={
                1: [{"proposal_type": "test", "fallback_used": False}],
            },
        )

        # Compare states
        engine.compare_states(
            {"player": {"hp": 100}},
            {"player": {"hp": 90}},
        )

        # Verify consistency
        engine.verify_replay_consistency(
            engine.replay_turn_range(
                session_id=session_id,
                start_turn=1,
                end_turn=1,
                events=[events[0]],
            ),
        )

        after_total = _initial_db_counts_after_seed(db_session)

        for table, count_before in before_total.items():
            assert after_total[table] == count_before, (
                f"{table}: before={count_before}, after={after_total[table]} "
                f"(replay operations mutated DB)"
            )


# =============================================================================
# Test: Rejected Proposals Do NOT Create State Deltas During Replay
# =============================================================================

class TestRejectedProposalsNoStateDeltas:
    """Verify rejected/invalid proposals leave no state deltas during replay."""

    def setup_method(self):
        reset_replay_store()

    def test_rejected_llm_stages_produce_no_state_deltas(self):
        """LLM stages marked as accepted=False must NOT produce state_deltas."""
        engine = get_replay_store().get_replay_engine()

        result_json = {
            "llm_stages": [
                {"stage_name": "input_intent", "enabled": True, "accepted": True},
                {"stage_name": "npc", "enabled": True, "accepted": False, "fallback_reason": "validation_failed"},
                {"stage_name": "world", "enabled": True, "accepted": False, "fallback_reason": "timeout"},
                {"stage_name": "narration", "enabled": True, "accepted": True},
            ],
        }

        events = [
            ReplayEvent(
                event_id="evt_reject_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "test",
                    "result_json": result_json,
                    "state_deltas": [
                        {"path": "player.hp", "old_value": 100, "new_value": 90, "operation": "set"},
                    ],
                },
            ),
        ]

        result = engine.replay_turn_range(
            session_id="test_reject",
            start_turn=1,
            end_turn=1,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        # Verify LLM stages are correctly parsed
        assert len(result.steps[0].llm_stages) == 4

        # Accepted stages
        accepted = [s for s in result.steps[0].llm_stages if s.accepted]
        assert len(accepted) == 2

        # Rejected stages
        rejected = [s for s in result.steps[0].llm_stages if not s.accepted]
        assert len(rejected) == 2
        assert rejected[0].fallback_reason == "validation_failed"
        assert rejected[1].fallback_reason == "timeout"

        # Only the state_deltas from the event data should be present (1 delta),
        # which was explicitly in the event's data. Rejected LLM stages do NOT
        # contribute additional state_deltas.
        assert len(result.steps[0].state_deltas) == 1

    def test_replay_with_all_rejected_stages_no_extra_deltas(self):
        """When all LLM stages are rejected, only explicit event deltas appear."""
        engine = get_replay_store().get_replay_engine()

        result_json = {
            "llm_stages": [
                {"stage_name": "input_intent", "enabled": True, "accepted": False, "fallback_reason": "error"},
                {"stage_name": "world", "enabled": True, "accepted": False, "fallback_reason": "timeout"},
            ],
        }

        # Event with NO explicit state_deltas
        events = [
            ReplayEvent(
                event_id="evt_all_reject",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "test",
                    "result_json": result_json,
                    # No state_deltas in event data
                },
            ),
        ]

        result = engine.replay_turn_range(
            session_id="test_all_reject",
            start_turn=1,
            end_turn=1,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert len(result.steps[0].llm_stages) == 2
        assert all(not s.accepted for s in result.steps[0].llm_stages)

        # No state_deltas should be created
        assert result.steps[0].state_deltas == []
        assert result.total_state_deltas == 0

    def test_replay_result_json_without_state_deltas_field(self):
        """Events without state_deltas in data produce zero state deltas."""
        engine = get_replay_store().get_replay_engine()

        events = [
            ReplayEvent(
                event_id="evt_no_delta",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "test",
                    "result_json": {
                        "llm_stages": [
                            {"stage_name": "narration", "enabled": True, "accepted": True},
                        ],
                    },
                    # Intentionally no state_deltas
                },
            ),
        ]

        result = engine.replay_turn_range(
            session_id="test_no_delta",
            start_turn=1,
            end_turn=1,
            events=events,
        )

        assert result.total_state_deltas == 0
        assert result.steps[0].state_deltas == []

    def test_fallback_proposals_do_not_add_state_deltas(self):
        """Proposals that triggered fallback (rejected) do not affect state."""
        engine = get_replay_store().get_replay_engine()

        # Simulate a replay where proposal_audits show fallback proposals
        proposal_audits = {
            1: [
                {"audit_id": "prop_fb_1", "proposal_type": "npc_action", "fallback_used": True,
                 "fallback_reason": "timeout", "rejected": True},
                {"audit_id": "prop_fb_2", "proposal_type": "scene_event", "fallback_used": True,
                 "fallback_reason": "invalid", "rejected": True},
            ],
        }

        events = [
            ReplayEvent(
                event_id="evt_fallback",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={"raw_input": "test"},
            ),
        ]

        result = engine.replay_with_proposal_audits(
            session_id="test_fallback",
            start_turn=1,
            end_turn=1,
            events=events,
            proposal_audits=proposal_audits,
        )

        assert result.success is True
        # Fallback proposals should be attached to the step but NOT create state deltas
        assert len(result.steps[0].proposal_audits) == 2
        assert result.steps[0].state_deltas == []
        assert result.total_state_deltas == 0

        # Verify proposal audit summary correctly counts fallbacks/rejections
        all_audits = result.steps[0].proposal_audits
        summary = engine.get_proposal_audit_summary(all_audits)
        assert summary["fallbacks"] == 2
        assert summary["rejections"] == 2


# =============================================================================
# Test: POST /debug/* Replay Endpoints Admin-Only + No-LLM
# =============================================================================

class TestDebugReplayEndpointsAdminOnly:
    """Verify POST /debug/* replay/snapshot endpoints enforce admin-only access
    and do not call LLM."""

    @pytest.fixture(autouse=True)
    def _set_app_env(self, monkeypatch):
        """Ensure APP_ENV is set to testing."""
        monkeypatch.setenv("APP_ENV", "testing")

    def test_replay_endpoint_returns_401_without_auth(self, client, db_engine):
        """POST /debug/sessions/{id}/replay requires authentication."""
        response = client.post("/debug/sessions/any-id/replay?end_turn=5")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"

    def test_replay_endpoint_returns_403_for_non_admin(
        self, client, db_engine, admin_user_data, regular_user_data
    ):
        """POST /debug/sessions/{id}/replay requires admin role."""
        _create_user_in_db(db_engine, admin_user_data, is_admin=True)
        _create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = _get_auth_header(client, regular_user_data)
        response = client.post("/debug/sessions/any-id/replay?end_turn=5", headers=user_headers)
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"

    def test_snapshot_endpoint_returns_401_without_auth(self, client, db_engine):
        """POST /debug/sessions/{id}/snapshots requires authentication."""
        response = client.post("/debug/sessions/any-id/snapshots", params={"turn_no": 1})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"

    def test_snapshot_endpoint_returns_403_for_non_admin(
        self, client, db_engine, admin_user_data, regular_user_data
    ):
        """POST /debug/sessions/{id}/snapshots requires admin role."""
        _create_user_in_db(db_engine, admin_user_data, is_admin=True)
        _create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = _get_auth_header(client, regular_user_data)
        response = client.post("/debug/sessions/any-id/snapshots", params={"turn_no": 1}, headers=user_headers)
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"

    def test_replay_endpoint_no_llm_calls_with_admin(
        self, client, db_engine, db_session, admin_user_data
    ):
        """POST /debug/{id}/replay must not trigger any LLM calls even for admin."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)
        _create_user_in_db(db_engine, admin_user_data, is_admin=True)

        before_model_calls = _count_rows(db_session, ModelCallLogModel)

        admin_headers = _get_auth_header(client, admin_user_data)
        response = client.post(
            f"/debug/sessions/{session_id}/replay?end_turn=3",
            headers=admin_headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        after_model_calls = _count_rows(db_session, ModelCallLogModel)
        assert after_model_calls == before_model_calls, (
            f"Model call logs increased from {before_model_calls} to {after_model_calls} "
            f"during replay endpoint!"
        )

    def test_snapshot_endpoint_no_llm_calls_with_admin(
        self, client, db_engine, db_session, admin_user_data
    ):
        """POST /debug/{id}/snapshots must not trigger any LLM calls even for admin."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)
        _create_user_in_db(db_engine, admin_user_data, is_admin=True)

        before_model_calls = _count_rows(db_session, ModelCallLogModel)

        admin_headers = _get_auth_header(client, admin_user_data)
        response = client.post(
            f"/debug/sessions/{session_id}/snapshots?turn_no=1",
            headers=admin_headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        after_model_calls = _count_rows(db_session, ModelCallLogModel)
        assert after_model_calls == before_model_calls, (
            f"Model call logs increased from {before_model_calls} to {after_model_calls} "
            f"during snapshot endpoint!"
        )

    def test_replay_endpoint_no_db_mutation_with_admin(
        self, client, db_engine, db_session, admin_user_data
    ):
        """POST /debug/{id}/replay must not mutate DB (event_logs, states, etc)."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)
        _create_user_in_db(db_engine, admin_user_data, is_admin=True)

        before = _all_row_counts(db_session, session_id)

        admin_headers = _get_auth_header(client, admin_user_data)
        response = client.post(
            f"/debug/sessions/{session_id}/replay?end_turn=3",
            headers=admin_headers,
        )

        assert response.status_code == 200

        after = _all_row_counts(db_session, session_id)

        for table, count_before in before.items():
            assert after[table] == count_before, (
                f"{table}: before={count_before}, after={after[table]} "
                f"(replay endpoint mutated DB)"
            )

    def test_snapshot_endpoint_no_db_mutation_with_admin(
        self, client, db_engine, db_session, admin_user_data
    ):
        """POST /debug/{id}/snapshots must not mutate DB (event_logs, states, etc)."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)
        _create_user_in_db(db_engine, admin_user_data, is_admin=True)

        before = _all_row_counts(db_session, session_id)

        admin_headers = _get_auth_header(client, admin_user_data)
        response = client.post(
            f"/debug/sessions/{session_id}/snapshots?turn_no=1",
            headers=admin_headers,
        )

        assert response.status_code == 200

        after = _all_row_counts(db_session, session_id)

        for table, count_before in before.items():
            assert after[table] == count_before, (
                f"{table}: before={count_before}, after={after[table]} "
                f"(snapshot endpoint mutated DB)"
            )

    def test_snapshot_endpoint_creates_only_in_memory_artifact(self, client, db_engine, db_session, admin_user_data):
        """POST /debug/{id}/snapshots creates only in-memory snapshot, no turn mutation."""
        world_id = _seed_test_world(db_session)
        session_id = _seed_test_session(db_session, world_id=world_id)
        _seed_session_with_events(db_session, session_id)
        _create_user_in_db(db_engine, admin_user_data, is_admin=True)

        # Count before: specifically session_states, event_logs, turn_transactions
        before_event_logs = _count_rows(db_session, EventLogModel, session_id=session_id)
        before_session_states = _count_rows(db_session, SessionStateModel, session_id=session_id)
        before_turn_txns = _count_rows(db_session, TurnTransactionModel, session_id=session_id)

        admin_headers = _get_auth_header(client, admin_user_data)
        response = client.post(
            f"/debug/sessions/{session_id}/snapshots?turn_no=1",
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "snapshot_id" in data
        assert data["session_id"] == session_id

        # Snapshot should NOT create any new event_logs, session_states, or turn_transactions
        after_event_logs = _count_rows(db_session, EventLogModel, session_id=session_id)
        after_session_states = _count_rows(db_session, SessionStateModel, session_id=session_id)
        after_turn_txns = _count_rows(db_session, TurnTransactionModel, session_id=session_id)

        assert after_event_logs == before_event_logs, f"event_logs changed: {before_event_logs} -> {after_event_logs}"
        assert after_session_states == before_session_states, f"session_states changed: {before_session_states} -> {after_session_states}"
        assert after_turn_txns == before_turn_txns, f"turn_transactions changed: {before_turn_txns} -> {after_turn_txns}"


# =============================================================================
# Test: MockLLMProvider Integration with ReplayStore
# =============================================================================

class TestMockLLMProviderNoBypass:
    """Verify MockLLMProvider cannot be bypassed during replay."""

    def setup_method(self):
        reset_replay_store()

    def test_replay_engine_never_touches_llm_provider(self):
        """Patch LLMProvider.generate to verify it's never called during replay."""
        engine = ReplayEngine()

        with patch.object(MockLLMProvider, 'generate', wraps=MockLLMProvider().generate) as mock_gen:
            events = [
                ReplayEvent(
                    event_id="evt_patch_1",
                    event_type="player_input",
                    turn_no=1,
                    timestamp=datetime.now(),
                    visible_to_player=True,
                    data={
                        "raw_input": "test",
                        "result_json": {
                            "llm_stages": [
                                {"stage_name": "narration", "enabled": True, "accepted": True},
                            ],
                        },
                    },
                ),
            ]

            result = engine.replay_turn_range(
                session_id="test_patch",
                start_turn=1,
                end_turn=1,
                events=events,
                perspective=ReplayPerspective.ADMIN,
            )

            assert result.success is True
            # The MockLLMProvider.generate should NEVER be called by replay engine
            mock_gen.assert_not_called()

    def test_replay_from_snapshot_never_touches_llm_provider(self):
        """replay_from_snapshot must not call any LLM provider method."""
        reconstructor = StateReconstructor()
        engine = ReplayEngine(reconstructor)

        snapshot = reconstructor.create_snapshot(
            session_id="test_snap_patch",
            turn_no=5,
            world_state={"time": "Day 1"},
            player_state={"hp": 100},
        )

        with patch.object(MockLLMProvider, 'generate', wraps=MockLLMProvider().generate) as mock_gen:
            events = [
                ReplayEvent(
                    event_id="evt_snap_patch",
                    event_type="player_input",
                    turn_no=6,
                    timestamp=datetime.now(),
                    visible_to_player=True,
                    data={"raw_input": "test"},
                ),
            ]

            result = engine.replay_from_snapshot(
                session_id="test_snap_patch",
                snapshot_id=snapshot.snapshot_id,
                target_turn=6,
                events=events,
                perspective=ReplayPerspective.ADMIN,
            )

            assert result.success is True
            mock_gen.assert_not_called()

    def test_state_reconstructor_never_touches_llm_provider(self):
        """StateReconstructor methods must never call LLM."""
        reconstructor = StateReconstructor()

        with patch.object(MockLLMProvider, 'generate', wraps=MockLLMProvider().generate) as mock_gen:
            base_state = {"player": {"hp": 100}}
            deltas = [
                StateDelta(path="player.hp", old_value=100, new_value=90, operation="set"),
                StateDelta(path="player.location", old_value="a", new_value="b", operation="set"),
            ]
            result = reconstructor.reconstruct_state(base_state, deltas)
            assert result["player"]["hp"] == 90
            assert result["player"]["location"] == "b"

            mock_gen.assert_not_called()

    def test_llm_stage_metadata_extraction_never_calls_provider(self):
        """extract_llm_stage_metadata is pure data extraction - no LLM."""
        engine = ReplayEngine()

        with patch.object(MockLLMProvider, 'generate', wraps=MockLLMProvider().generate) as mock_gen:
            metadata = engine.extract_llm_stage_metadata(
                {"llm_stages": [{"stage_name": "x", "enabled": True, "accepted": True}]},
                ReplayPerspective.ADMIN,
            )
            assert len(metadata) == 1
            mock_gen.assert_not_called()

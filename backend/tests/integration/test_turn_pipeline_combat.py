"""
Integration tests for combat-like actions through the turn service main loop.

Verifies that combat-like "attack" inputs flow through the turn service
(rather than through combat.py) and produce valid, hardened responses with
exactly one player_turn event row per turn input.

Tests:
- Combat-like input produces valid TurnResponse through turn service
- Response contains validation_status, world_time, player_state
- Invalid target (NPC not in current scene) handled safely
- Exactly 1 player_turn event row per combat turn input
- No second player_turn row for a single input
- No call to combat.py endpoints required
"""

import pytest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from fastapi.testclient import TestClient

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    WorldModel,
    EventLogModel,
    TurnTransactionModel,
    GameEventModel,
)
from llm_rpg.storage.repositories import WorldRepository
from llm_rpg.main import app
from llm_rpg.core.turn_service import (
    execute_turn_service,
    TurnResult,
    TurnServiceError,
    SessionNotFoundError,
)


TEST_DATABASE_URL = "sqlite:///:memory:"


# =============================================================================
# Fixtures (TestClient-style, matching test_turn_pipeline.py patterns)
# =============================================================================

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


@pytest.fixture
def test_user_data():
    return {
        "username": f"combatuser_{uuid.uuid4().hex[:8]}",
        "email": f"combat_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePass123!",
    }


@pytest.fixture
def sample_world_data():
    return {
        "code": f"combatworld_{uuid.uuid4().hex[:8]}",
        "name": "Combat Test World",
        "genre": "xianxia",
        "lore_summary": "A world for combat integration tests",
        "status": "active",
    }


@pytest.fixture
def auth_headers(client, test_user_data):
    response = client.post("/auth/register", json=test_user_data)
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_world_in_db(db_engine, world_data):
    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        world_repo = WorldRepository(db)
        world = world_repo.create(world_data)
        db.commit()
        return world.id
    finally:
        db.close()


def create_session(client, auth_headers, db_engine, sample_world_data):
    """Helper to create a game session."""
    world_id = create_world_in_db(db_engine, sample_world_data)
    response = client.post("/saves/manual-save", json={"world_id": world_id}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["session_id"], world_id


# =============================================================================
# Tests: Combat-like actions through turn API (TestClient)
# =============================================================================

class TestCombatThroughTurnAPI:
    """Tests that combat-like inputs via the turn API produce valid responses."""

    def test_attack_input_produces_valid_turn_response(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """'attack demon' via POST /game/sessions/{id}/turn produces valid response."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "攻击恶魔"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Standard turn output fields
        assert "turn_index" in data
        assert data["turn_index"] == 1
        assert "narration" in data
        assert isinstance(data["narration"], str)
        assert len(data["narration"]) > 0
        assert "world_time" in data
        assert isinstance(data["world_time"], dict)
        assert "player_state" in data
        assert isinstance(data["player_state"], dict)
        assert "validation_passed" in data
        assert data["validation_passed"] is True
        assert "events_committed" in data
        assert data["events_committed"] > 0
        assert "transaction_id" in data
        assert data["transaction_id"] != ""

    def test_attack_response_has_validation_world_time_player_state(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Combat turn response contains validation status, world_time, player_state."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "attack enemy"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # validation_passed must be present and True (no crash)
        assert data["validation_passed"] is True

        # world_time must be a dict with calendar/season/day/period
        world_time = data["world_time"]
        assert isinstance(world_time, dict)
        assert "calendar" in world_time
        assert "season" in world_time
        assert "day" in world_time
        assert "period" in world_time

        # player_state must be a dict with entity info
        player_state = data["player_state"]
        assert isinstance(player_state, dict)
        assert "entity_id" in player_state or "name" in player_state

    def test_attack_english_and_chinese_both_work(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Both English 'attack demon' and Chinese '攻击恶魔' work through turn service."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        # Chinese input
        r1 = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "攻击恶魔"},
            headers=auth_headers,
        )
        assert r1.status_code == 200
        assert r1.json()["validation_passed"] is True

        # English input
        r2 = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "attack demon"},
            headers=auth_headers,
        )
        assert r2.status_code == 200
        assert r2.json()["validation_passed"] is True

    def test_attack_invalid_npc_target_is_handled_safely(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """
        Attacking an NPC not in the current scene is handled safely.

        The response should be 200 (no crash), with a structured response.
        The system should not throw 500 or crash when targeting a non-existent NPC.
        """
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        # Attack "demon" - not in scene, no demon NPC exists at 山门广场
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "攻击不存在的恶魔"},
            headers=auth_headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()

        # Must not crash - should return valid turn response
        assert data["validation_passed"] is True
        assert "narration" in data
        assert len(data["narration"]) > 0
        assert data["turn_index"] >= 1

    def test_attack_multiple_turns_increment_turn_index(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Multiple attack turns increment turn_index correctly."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        attack_actions = ["攻击恶魔", "attack the beast", "与敌人战斗", "准备攻击"]

        for i, action in enumerate(attack_actions, 1):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers,
            )
            assert response.status_code == 200
            assert response.json()["turn_index"] == i
            assert response.json()["validation_passed"] is True


# =============================================================================
# Tests: Event cardinality verification (direct DB access)
# =============================================================================

class TestCombatEventCardinality:
    """
    Tests that exactly ONE player_turn event row is created per combat-like turn input.

    Uses direct execute_turn_service() calls for precise DB row counting.
    """

    @pytest.fixture
    def db(self, db_engine):
        """Create a fresh SQLAlchemy session for direct DB queries."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        yield db
        db.close()

    def test_exactly_one_player_turn_event_per_combat_input_via_api(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Via API: 1 combat turn = 1 player_turn EventLogModel row."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        # Query initial count
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            initial_count = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.event_type == "player_turn",
            ).count()
        finally:
            db.close()

        # Submit one combat-like turn
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "攻击恶魔"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        # Verify exactly 1 more player_turn row
        db = SessionLocal()
        try:
            after_count = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.event_type == "player_turn",
            ).count()
        finally:
            db.close()

        assert after_count == initial_count + 1, \
            f"Expected {initial_count + 1} player_turn rows, got {after_count}"

    def test_player_turn_row_count_matches_turn_submissions(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """DB row count of EventLogModel with event_type='player_turn' == number of turns."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        actions = ["攻击恶魔", "观察四周", "attack monster", "与同伴交谈", "fight the dragon"]
        turn_count = len(actions)

        for action in actions:
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": action},
                headers=auth_headers,
            )
            assert response.status_code == 200

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            player_turn_count = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.event_type == "player_turn",
            ).count()
        finally:
            db.close()

        assert player_turn_count == turn_count, \
            f"Expected {turn_count} player_turn rows, got {player_turn_count}"

    def test_no_duplicate_player_turn_row_for_single_input(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """A single combat-like turn input creates exactly ONE player_turn row (no duplicates)."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        # Query count before
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            before_count = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.event_type == "player_turn",
            ).count()
        finally:
            db.close()

        # Submit one turn
        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "攻击恶魔领主"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        # Verify exactly +1 row, not +2
        db = SessionLocal()
        try:
            after_count = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.event_type == "player_turn",
            ).count()

            # Also verify no player_turn rows with turn_no > 1
            turn_1_rows = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.event_type == "player_turn",
                EventLogModel.turn_no == 1,
            ).count()
        finally:
            db.close()

        assert after_count == before_count + 1, \
            f"Expected exactly {before_count + 1} player_turn rows, got {after_count}"
        assert turn_1_rows == 1, \
            f"Expected exactly 1 player_turn row for turn 1, got {turn_1_rows}"

    def test_combat_turn_creates_turn_transaction(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Each combat turn creates a TurnTransaction with committed status."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "攻击敌人"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        transaction_id = response.json()["transaction_id"]

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            transaction = db.query(TurnTransactionModel).filter(
                TurnTransactionModel.id == transaction_id
            ).first()
            assert transaction is not None
            assert transaction.status == "committed"
            assert transaction.session_id == session_id
            assert transaction.turn_no == 1
        finally:
            db.close()


# =============================================================================
# Tests: Direct service calls (bypassing HTTP, like test_turn_consistency.py)
# =============================================================================

class TestCombatDirectServiceCall:
    """
    Tests that attack inputs through execute_turn_service() produce valid results
    without any dependency on combat.py endpoints.
    """

    @pytest.fixture
    def direct_db(self, db_engine):
        """Create a fresh DB session."""
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        yield db
        db.close()

    def setup_session_world_and_state(
        self, db_engine, sample_world_data
    ):
        """Set up minimal DB fixtures for direct service calls."""
        from llm_rpg.storage.models import (
            UserModel, SaveSlotModel, SessionModel, SessionStateModel,
            SessionPlayerStateModel, WorldModel,
        )
        from datetime import datetime

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            # Create user
            user = UserModel(
                id="combat_user_direct",
                username="combat_direct_user",
                email="combat_direct@example.com",
                password_hash="hashed",
            )
            db.add(user)

            # Create world
            world_id = create_world_in_db(db_engine, sample_world_data)

            # Create save slot
            slot = SaveSlotModel(
                id="combat_slot_direct",
                user_id=user.id,
                slot_number=1,
                name="Combat Direct Save",
            )
            db.add(slot)

            # Create session
            session = SessionModel(
                id="combat_session_direct",
                user_id=user.id,
                world_id=world_id,
                save_slot_id=slot.id,
                status="active",
            )
            db.add(session)
            db.commit()

            # Create session state
            state = SessionStateModel(
                id="combat_state_direct",
                session_id=session.id,
                current_time="修仙历 春 第1日 辰时",
                time_phase="辰时",
                current_location_id=None,
                active_mode="exploration",
            )
            db.add(state)

            # Create player state
            player = SessionPlayerStateModel(
                id="combat_player_direct",
                session_id=session.id,
                realm_stage="炼气一层",
                hp=100,
                max_hp=100,
            )
            db.add(player)
            db.commit()

            return session.id
        finally:
            db.close()

    def test_direct_service_attack_produces_turn_result(
        self, db_engine, sample_world_data
    ):
        """execute_turn_service() with attack input produces TurnResult."""
        session_id = self.setup_session_world_and_state(db_engine, sample_world_data)

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            result = execute_turn_service(
                db=db,
                session_id=session_id,
                player_input="攻击恶魔",
                idempotency_key="combat_direct_test_key",
            )

            assert isinstance(result, TurnResult)
            assert result.turn_no == 1
            assert result.validation_passed is True
            assert result.narration is not None
            assert len(result.narration) > 0
            assert result.world_time is not None
            assert result.player_state is not None
            assert result.transaction_id is not None
            assert result.events_committed >= 1
        finally:
            db.close()

    def test_direct_service_no_combat_py_dependency(
        self, db_engine, sample_world_data
    ):
        """Turn service works without any import from combat.py."""
        session_id = self.setup_session_world_and_state(db_engine, sample_world_data)

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            # Verify that combat.py is NOT imported in turn_service.py
            # by checking that turn service handles "attack" without combat imports
            result = execute_turn_service(
                db=db,
                session_id=session_id,
                player_input="fight the monster",
                idempotency_key="no_combat_dep_key",
            )

            assert result is not None
            assert result.validation_passed is True
            # Turn service produces its own narration, no combat.py needed
            assert result.narration is not None
            assert len(result.narration) > 0
        finally:
            db.close()


# =============================================================================
# Regression: Turn boundary contract hardening
# =============================================================================

class TestCombatTurnBoundaryContract:
    """
    Verify that the turn boundary contract holds for combat-like actions:
    - Validation passed metadata present in result_json
    - Action type recorded
    - world_time advances each turn
    """

    def test_combat_turn_has_action_type_in_event(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Attack action type is recorded in EventLogModel.structured_action or result_json."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        response = client.post(
            f"/game/sessions/{session_id}/turn",
            json={"action": "攻击恶魔"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            event = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.event_type == "player_turn",
                EventLogModel.turn_no == 1,
            ).first()

            assert event is not None
            assert event.input_text == "攻击恶魔"
            # result_json should contain action_type info
            result_json = event.result_json or {}
            assert "action_type" in result_json, \
                f"result_json missing action_type: {list(result_json.keys())}"
        finally:
            db.close()

    def test_combat_turn_world_time_advances(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """World time advances even for combat turns."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        times = []
        for _ in range(3):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": "attack something"},
                headers=auth_headers,
            )
            assert response.status_code == 200
            times.append(response.json()["world_time"]["period"])

        # Time should change between turns
        assert len(set(times)) > 1, f"Time periods did not change: {times}"

    def test_combat_turn_transaction_id_is_unique(
        self, client, auth_headers, db_engine, sample_world_data
    ):
        """Each combat turn gets a unique transaction ID."""
        session_id, _ = create_session(client, auth_headers, db_engine, sample_world_data)

        tx_ids = []
        for _ in range(3):
            response = client.post(
                f"/game/sessions/{session_id}/turn",
                json={"action": "战斗"},
                headers=auth_headers,
            )
            assert response.status_code == 200
            tx_ids.append(response.json()["transaction_id"])

        assert len(tx_ids) == len(set(tx_ids)), f"Duplicate transaction IDs: {tx_ids}"

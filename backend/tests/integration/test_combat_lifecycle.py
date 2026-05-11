"""
P3 Combat Lifecycle Tests — beyond P2 T10 coverage.

Tests combat session lifecycle (start → turns → end),
NPC deterministic counter-action, HP/status persistence,
and edge cases (defeated combatants, idempotency).

These tests exercise behavior NOT covered by P2:
- test_combat_api.py (6 tests: start/turn basic flow)
- test_turn_pipeline_combat.py (14 tests: turn-service combat-like inputs)
"""

import hashlib
import pytest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import WorldModel
from llm_rpg.storage.repositories import WorldRepository
from llm_rpg.core.combat import (
    CombatManager,
    CombatParticipant,
    CombatStatus,
    ActorType,
)
from llm_rpg.main import app


TEST_DATABASE_URL = "sqlite:///:memory:"


# =============================================================================
# Fixtures (same pattern as test_combat_api.py)
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


@pytest.fixture
def test_world(db_session: Session):
    repo = WorldRepository(db_session)
    world_data = {
        "code": f"test_world_{uuid.uuid4().hex[:8]}",
        "name": "Test World",
        "genre": "fantasy",
        "lore_summary": "A world for testing",
        "status": "active",
    }
    return repo.create(world_data)


@pytest.fixture
def test_user(client: TestClient):
    user_data = {
        "username": f"testuser_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePass123!",
    }
    response = client.post("/auth/register", json=user_data)
    if response.status_code == 201:
        return response.json()

    login_response = client.post(
        "/auth/login",
        data={"username": user_data["username"], "password": user_data["password"]}
    )
    return login_response.json()


@pytest.fixture
def auth_headers(test_user: dict):
    return {"Authorization": f"Bearer {test_user['access_token']}"}


@pytest.fixture
def test_game_session(client: TestClient, auth_headers: dict, test_world: WorldModel):
    save_slot_response = client.post(
        "/saves",
        headers=auth_headers,
        json={"slot_number": 1, "name": "Test Save Slot"}
    )
    assert save_slot_response.status_code == 201

    save_slot = save_slot_response.json()
    manual_save_response = client.post(
        "/saves/manual-save",
        headers=auth_headers,
        json={
            "slot_id": save_slot["id"],
            "world_id": test_world.id
        }
    )
    assert manual_save_response.status_code == 201
    return manual_save_response.json()


@pytest.fixture(autouse=True)
def reset_combat_manager():
    import llm_rpg.core.combat as combat_module
    combat_module._combat_manager = None
    yield
    combat_module._combat_manager = None


# =============================================================================
# Helper
# =============================================================================

def _start_combat(client, auth_headers, session_id, participants):
    """Start a combat session via API. Returns (combat_id, response_json)."""
    response = client.post(
        "/combat/start",
        headers=auth_headers,
        json={
            "session_id": session_id,
            "participants": participants,
        }
    )
    assert response.status_code == 201, f"Combat start failed: {response.text}"
    data = response.json()
    return data["combat_id"], data


def _submit_turn(client, auth_headers, combat_id, actor_id, action_type, target_id=None):
    """Submit a turn action via API. Returns response."""
    body = {"action_type": action_type}
    if target_id:
        body["target_id"] = target_id
    return client.post(
        f"/combat/{combat_id}/turn",
        headers=auth_headers,
        params={"actor_id": actor_id},
        json=body,
    )


def _get_combat(client, auth_headers, combat_id):
    """Get combat state via API. Returns response."""
    return client.get(f"/combat/{combat_id}", headers=auth_headers)


# =============================================================================
# TestCombatLifecycle — Combat session lifecycle beyond P2
# =============================================================================

class TestCombatLifecycle:
    """Tests for the full combat lifecycle: start → turns → auto-end."""

    def test_full_combat_lifecycle_start_to_end(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        Full combat lifecycle: start, multiple rounds of attack+counter,
        verify HP progression, combat auto-ends with winner.

        Beyond P2: P2 only tests single turn submit + get state.
        This exercises the full round-by-round lifecycle to completion.
        """
        combat_id, start_data = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "goblin", "actor_type": "npc", "name": "Goblin",
                 "hp": 25, "max_hp": 25, "initiative": 5},
            ]
        )

        # Track HP across rounds
        player_hp_history = [100]
        npc_hp_history = [25]
        rounds = 0

        while True:
            state_resp = _get_combat(client, auth_headers, combat_id)
            state = state_resp.json()
            if state["status"] != "active":
                break

            rounds += 1
            resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "goblin")
            assert resp.status_code == 200, f"Turn {rounds} failed: {resp.text}"

            # Re-fetch state to get updated HP
            state_resp = _get_combat(client, auth_headers, combat_id)
            state = state_resp.json()

            # Find player and goblin HPs
            participants = {p["actor_id"]: p for p in state["participants"]}
            player_hp = participants["player"]["hp"]
            npc_hp = participants.get("goblin", {}).get("hp", 0)

            player_hp_history.append(player_hp)
            npc_hp_history.append(npc_hp)

            # Safety: prevent infinite loop
            if rounds > 20:
                pytest.fail("Combat did not end within 20 rounds")

        # Verify combat ended
        final_state = _get_combat(client, auth_headers, combat_id).json()
        assert final_state["status"] == "player_won", \
            f"Expected player_won, got {final_state['status']}"
        assert final_state["winner"] == "player"

        # Verify HP progression: NPC HP monotonically decreased
        for i in range(1, len(npc_hp_history)):
            assert npc_hp_history[i] <= npc_hp_history[i - 1], \
                f"NPC HP increased from round {i - 1} to {i}"

        # Verify final state: goblin is defeated
        p_map = {p["actor_id"]: p for p in final_state["participants"]}
        goblin_p = p_map.get("goblin")
        if goblin_p:
            assert goblin_p["hp"] == 0, f"Expected goblin HP=0, got {goblin_p['hp']}"
            assert goblin_p["is_active"] is False
        assert p_map["player"]["hp"] > 0, "Player should survive"

        # Verify multiple rounds occurred
        assert rounds >= 3, f"Expected at least 3 rounds, got {rounds}"

    def test_combat_auto_ends_when_player_defeated(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        When player HP reaches 0 from NPC counter-attack, combat auto-ends
        with PLAYER_LOST status.

        Beyond P2: P2 has no auto-end-on-defeat test.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 5, "max_hp": 100, "initiative": 10},
                {"actor_id": "boss", "actor_type": "npc", "name": "Boss",
                 "hp": 200, "max_hp": 200, "initiative": 5},
            ]
        )

        # Player attacks — NPC counter-attacks for 8 damage, player only has 5 HP
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "boss")
        assert resp.status_code == 200

        state = _get_combat(client, auth_headers, combat_id).json()
        assert state["status"] == "player_lost", \
            f"Expected player_lost, got {state['status']}"

        # Player HP should be 0
        player = next(p for p in state["participants"] if p["actor_id"] == "player")
        assert player["hp"] == 0
        assert player["is_active"] is False

    def test_combat_auto_ends_when_all_enemies_defeated(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        When all enemy NPCs reach 0 HP, combat auto-ends with PLAYER_WON status.

        Beyond P2: P2 has no auto-end-on-victory test.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "weak_enemy", "actor_type": "npc", "name": "Weak Enemy",
                 "hp": 1, "max_hp": 10, "initiative": 5},
            ]
        )

        # One hit kills the weak enemy (10 damage > 1 HP)
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "weak_enemy")
        assert resp.status_code == 200

        state = _get_combat(client, auth_headers, combat_id).json()
        assert state["status"] == "player_won", \
            f"Expected player_won, got {state['status']}"
        assert state["winner"] == "player"

    def test_combat_end_idempotency(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        Ending an already-ended combat is safe — no crash, returns existing state.

        Beyond P2: P2 has no idempotency tests for combat end.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
            ]
        )

        # First end — should succeed
        resp1 = client.post(
            f"/combat/{combat_id}/end",
            headers=auth_headers,
            json={"status": "escaped"}
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "escaped"

        # Second end — should not crash, return same state
        resp2 = client.post(
            f"/combat/{combat_id}/end",
            headers=auth_headers,
            json={"status": "player_won", "winner": "player"}
        )
        assert resp2.status_code == 200
        # Status should remain "escaped" (idempotent — does not overwrite)
        assert resp2.json()["status"] == "escaped"


# =============================================================================
# TestNPCCounterAction — NPC deterministic counter-attack behavior
# =============================================================================

class TestNPCCounterAction:
    """
    Tests that NPCs automatically counter-attack after player actions,
    with deterministic target selection and damage.
    """

    def test_npc_counter_attacks_after_player_action(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        After player attacks an NPC, the round contains both the player's
        action AND the NPC's counter-action.

        Beyond P2: P2 has no NPC action verification.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "orc", "actor_type": "npc", "name": "Orc",
                 "hp": 50, "max_hp": 50, "initiative": 5},
            ]
        )

        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "orc")
        assert resp.status_code == 200

        state = _get_combat(client, auth_headers, combat_id).json()
        current_round = state["current_round"]
        actions = current_round["actions"]

        # At least 2 actions: player attack + NPC counter-attack
        assert len(actions) >= 2, f"Expected >=2 actions, got {len(actions)}: {actions}"

        # Find player action
        player_actions = [a for a in actions if a["actor_id"] == "player"]
        assert len(player_actions) == 1, "Expected exactly 1 player action"
        assert player_actions[0]["action_type"] == "attack"
        assert player_actions[0]["target_id"] == "orc"

        # Find NPC counter-action
        npc_actions = [a for a in actions if a["actor_id"] == "orc"]
        assert len(npc_actions) == 1, "Expected exactly 1 NPC counter-action"
        assert npc_actions[0]["action_type"] == "attack"
        assert npc_actions[0]["actor_type"] == "npc"
        # NPC always targets a valid actor (player, in this case)
        assert npc_actions[0]["target_id"] is not None

    def test_npc_counter_attack_reduces_player_hp(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        NPC counter-attack actually reduces the player's HP by the
        deterministic counter-damage amount (8).

        Beyond P2: P2 never verifies HP changes from NPC actions.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "troll", "actor_type": "npc", "name": "Troll",
                 "hp": 100, "max_hp": 100, "initiative": 5},
            ]
        )

        # Check initial HP
        initial = _get_combat(client, auth_headers, combat_id).json()
        initial_player_hp = next(
            p["hp"] for p in initial["participants"] if p["actor_id"] == "player"
        )
        assert initial_player_hp == 100

        # Player attacks troll
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "troll")
        assert resp.status_code == 200

        # Check HP after action + NPC counter
        after = _get_combat(client, auth_headers, combat_id).json()
        after_player_hp = next(
            p["hp"] for p in after["participants"] if p["actor_id"] == "player"
        )
        after_troll_hp = next(
            p["hp"] for p in after["participants"] if p["actor_id"] == "troll"
        )

        # Player took NPC counter-damage (8)
        assert after_player_hp == 92, \
            f"Expected player HP=92 (100-8), got {after_player_hp}"
        # Troll took player attack damage (10)
        assert after_troll_hp == 90, \
            f"Expected troll HP=90 (100-10), got {after_troll_hp}"

    def test_npc_counter_actions_are_deterministic(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        Running the same combat scenario twice produces identical NPC actions
        (same target, same damage). Uses hashlib.md5 for deterministic hashing.

        Beyond P2: P2 has no determinism guarantees.
        """
        def run_scenario():
            import llm_rpg.core.combat as combat_module
            combat_module._combat_manager = None

            combat_id, _ = _start_combat(client, auth_headers,
                test_game_session["session_id"],
                [
                    {"actor_id": "player", "actor_type": "player", "name": "Player",
                     "hp": 100, "max_hp": 100, "initiative": 10},
                    {"actor_id": "skeleton", "actor_type": "npc", "name": "Skeleton",
                     "hp": 50, "max_hp": 50, "initiative": 5},
                ]
            )

            resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "skeleton")
            assert resp.status_code == 200

            state = _get_combat(client, auth_headers, combat_id).json()
            actions = state["current_round"]["actions"]
            npc_actions = [a for a in actions if a["actor_id"] == "skeleton"]
            return npc_actions

        # WARNING: Since combat_id is a random UUID on each start, and
        # the hash seed includes combat_id, the NPC action details will
        # differ between runs. We test determinism within a single
        # CombatManager instance by resetting it and using the SAME combat_id.

        # For true determinism, we must control the combat_id.
        # Use direct CombatManager (bypass API) to control IDs.
        import llm_rpg.core.combat as combat_module
        combat_module._combat_manager = None
        mgr = combat_module.get_combat_manager()

        fixed_combat_id = "deterministic_combat_1"
        participants = [
            CombatParticipant(actor_id="player", actor_type=ActorType.PLAYER,
                              name="Player", hp=100, max_hp=100, initiative=10),
            CombatParticipant(actor_id="skeleton", actor_type=ActorType.NPC,
                              name="Skeleton", hp=50, max_hp=50, initiative=5),
        ]

        # Run 1
        mgr.create_combat(fixed_combat_id, "session_1", participants=participants)
        from llm_rpg.core.combat import CombatActionPayload, ActionType
        action1 = mgr.commit_action(fixed_combat_id, "player", ActorType.PLAYER,
                                     ActionType.ATTACK,
                                     CombatActionPayload(target_id="skeleton"))
        # NPC counter-actions complete round 1 and auto-advance to empty round 2.
        # Find the round that actually contains the actions.
        combat1 = mgr.get_combat(fixed_combat_id)
        npc_actions_run1 = []
        for r in combat1.rounds:
            npc_actions_run1.extend(a for a in r.actions if a.actor_id == "skeleton")

        # Reset
        combat_module._combat_manager = None
        mgr2 = combat_module.get_combat_manager()

        # Run 2 — same combat_id, same participants
        mgr2.create_combat(fixed_combat_id, "session_1", participants=participants)
        action2 = mgr2.commit_action(fixed_combat_id, "player", ActorType.PLAYER,
                                      ActionType.ATTACK,
                                      CombatActionPayload(target_id="skeleton"))
        combat2 = mgr2.get_combat(fixed_combat_id)
        npc_actions_run2 = []
        for r in combat2.rounds:
            npc_actions_run2.extend(a for a in r.actions if a.actor_id == "skeleton")

        # Verify identical NPC actions
        assert len(npc_actions_run1) == 1
        assert len(npc_actions_run2) == 1

        a1 = npc_actions_run1[0]
        a2 = npc_actions_run2[0]
        assert a1.action_type == a2.action_type
        assert a1.payload.target_id == a2.payload.target_id
        assert a1.resolution["damage"] == a2.resolution["damage"]
        assert a1.resolution["target_id"] == a2.resolution["target_id"]

    def test_defeated_npc_does_not_counter_attack(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        An NPC reduced to 0 HP by the player's attack does NOT get a
        counter-attack in the same round.

        Beyond P2: P2 has no defeated-NPC counter-attack suppression test.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "weak_slime", "actor_type": "npc", "name": "Weak Slime",
                 "hp": 5, "max_hp": 5, "initiative": 5},
            ]
        )

        # Player attacks — 10 damage kills the slime
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "weak_slime")
        assert resp.status_code == 200

        state = _get_combat(client, auth_headers, combat_id).json()
        actions = state["current_round"]["actions"]

        # The slime should NOT have a counter-action (hp was <= 0 after player hit)
        slime_actions = [a for a in actions if a["actor_id"] == "weak_slime"]
        assert len(slime_actions) == 0, \
            f"Defeated slime should not counter-attack, but found: {slime_actions}"

        # Verify slime is indeed defeated
        slime = next(p for p in state["participants"] if p["actor_id"] == "weak_slime")
        assert slime["hp"] == 0
        assert slime["is_active"] is False

    def test_npc_counter_attack_targets_valid_actor(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        NPC counter-attack always targets an active, non-defeated actor
        (not itself, not a defeated participant).

        Beyond P2: P2 has no target validity checks.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "wolf", "actor_type": "npc", "name": "Wolf",
                 "hp": 50, "max_hp": 50, "initiative": 5},
            ]
        )

        # Player attacks wolf
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "wolf")
        assert resp.status_code == 200

        state = _get_combat(client, auth_headers, combat_id).json()
        actions = state["current_round"]["actions"]
        wolf_actions = [a for a in actions if a["actor_id"] == "wolf"]
        assert len(wolf_actions) == 1

        wolf_action = wolf_actions[0]
        # Wolf should NOT target itself
        assert wolf_action["target_id"] != "wolf", "NPC should not target itself"
        # Wolf should target an active, non-defeated actor
        assert wolf_action["target_id"] == "player", \
            f"Expected wolf to target player, got {wolf_action['target_id']}"


# =============================================================================
# TestHPStatusPersistence — HP/status persists across API round trips
# =============================================================================

class TestHPStatusPersistence:
    """
    Tests that HP changes from combat actions (both player and NPC)
    persist across multiple API calls and round trips.
    """

    def test_hp_persists_across_api_calls(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        Start combat → submit action → get combat state.
        HP in the GET response reflects damage from BOTH player and NPC actions.

        Beyond P2: P2 only checks that action produces a response, not
        that HP is persisted across separate API calls.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "bandit", "actor_type": "npc", "name": "Bandit",
                 "hp": 80, "max_hp": 80, "initiative": 5},
            ]
        )

        # Verify initial state
        state1 = _get_combat(client, auth_headers, combat_id).json()
        p1 = next(p for p in state1["participants"] if p["actor_id"] == "player")
        b1 = next(p for p in state1["participants"] if p["actor_id"] == "bandit")
        assert p1["hp"] == 100
        assert b1["hp"] == 80

        # Submit action
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "bandit")
        assert resp.status_code == 200

        # Fetch state again — HP should reflect both player attack (10) and NPC counter (8)
        state2 = _get_combat(client, auth_headers, combat_id).json()
        p2 = next(p for p in state2["participants"] if p["actor_id"] == "player")
        b2 = next(p for p in state2["participants"] if p["actor_id"] == "bandit")

        assert p2["hp"] == 92, f"Player HP should be 92 (100-8), got {p2['hp']}"
        assert b2["hp"] == 70, f"Bandit HP should be 70 (80-10), got {b2['hp']}"

    def test_hp_decreases_with_multiple_rounds(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        Over multiple rounds, HP decreases monotonically for both
        the player (from NPC counters) and NPCs (from player attacks).

        Beyond P2: P2 never tracks HP across multiple rounds.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "dragon", "actor_type": "npc", "name": "Dragon",
                 "hp": 100, "max_hp": 100, "initiative": 5},
            ]
        )

        player_hps = [100]
        dragon_hps = [100]

        for round_no in range(1, 6):
            resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "dragon")
            assert resp.status_code == 200, f"Turn round {round_no} failed"

            state = _get_combat(client, auth_headers, combat_id).json()
            if state["status"] != "active":
                # Combat ended early
                p_map = {p["actor_id"]: p for p in state["participants"]}
                player_hps.append(p_map["player"]["hp"])
                dragon_hps.append(p_map.get("dragon", {}).get("hp", 0))
                break

            p_map = {p["actor_id"]: p for p in state["participants"]}
            player_hps.append(p_map["player"]["hp"])
            dragon_hps.append(p_map.get("dragon", {}).get("hp", 0))

        # HP should monotonically decrease (or stay the same at 0)
        for i in range(1, len(player_hps)):
            assert player_hps[i] <= player_hps[i - 1], \
                f"Player HP increased from round {i - 1} to {i}: {player_hps}"
        for i in range(1, len(dragon_hps)):
            assert dragon_hps[i] <= dragon_hps[i - 1], \
                f"Dragon HP increased from round {i - 1} to {i}: {dragon_hps}"

        # At least some damage was dealt
        assert player_hps[-1] < player_hps[0], "Player took no damage"
        assert dragon_hps[-1] < dragon_hps[0], "Dragon took no damage"

    def test_defeated_combatant_cannot_act(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        After an NPC is defeated (HP=0), attempting to submit an action
        for that defeated combatant returns a 400 error.

        Beyond P2: P2 has no defeated-combatant action rejection test.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "weak_goblin", "actor_type": "npc", "name": "Weak Goblin",
                 "hp": 1, "max_hp": 10, "initiative": 5},
            ]
        )

        # Kill the goblin first (player attack = 10 damage)
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "weak_goblin")
        assert resp.status_code == 200

        # Now try to submit an action for the DEFEATED goblin.
        # The combat may have auto-ended (PLAYER_WON), so the error could be
        # either "defeated" (if still active) or "not active" (if auto-ended).
        resp = _submit_turn(client, auth_headers, combat_id, "weak_goblin", "attack", "player")
        assert resp.status_code == 400, \
            f"Expected 400 for defeated combatant, got {resp.status_code}"
        detail = resp.json()["detail"].lower()
        assert any(phrase in detail for phrase in ("defeated", "cannot act", "inactive", "not active")), \
            f"Error should mention defeated/inactive/not active, got: {detail}"

    def test_invalid_target_after_defeated(
        self, client: TestClient, auth_headers: dict, test_game_session: dict
    ):
        """
        Attempting to attack a target that was just defeated returns a 400 error.

        Beyond P2: P2 has no defeated-target rejection test.
        """
        combat_id, _ = _start_combat(client, auth_headers,
            test_game_session["session_id"],
            [
                {"actor_id": "player", "actor_type": "player", "name": "Player",
                 "hp": 100, "max_hp": 100, "initiative": 10},
                {"actor_id": "rat1", "actor_type": "npc", "name": "Rat 1",
                 "hp": 1, "max_hp": 5, "initiative": 5},
                {"actor_id": "rat2", "actor_type": "npc", "name": "Rat 2",
                 "hp": 50, "max_hp": 50, "initiative": 3},
            ]
        )

        # Kill rat1 first
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "rat1")
        assert resp.status_code == 200

        # Now try to attack the already-dead rat1 again
        resp = _submit_turn(client, auth_headers, combat_id, "player", "attack", "rat1")
        assert resp.status_code == 400, \
            f"Expected 400 for attacking defeated target, got {resp.status_code}"
        detail = resp.json()["detail"].lower()
        assert "defeated" in detail or "cannot attack" in detail, \
            f"Error should mention defeated target, got: {detail}"

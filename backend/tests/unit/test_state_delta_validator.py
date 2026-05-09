"""
Unit tests for StateDeltaValidator.

Tests the state delta validation contract including:
1. Path whitelist/blacklist enforcement
2. Operation validation
3. old_value verification
4. Numeric bounds checking
5. source_event_id validation
"""

from unittest.mock import MagicMock

from llm_rpg.core.validation.state_delta_validator import StateDeltaValidator
from llm_rpg.core.validation.state_delta_contract import (
    is_path_allowed,
    is_operation_allowed,
    get_numeric_bounds,
)
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    NPCState,
    LocationState,
    MentalState,
    PhysicalState,
)
from llm_rpg.models.events import WorldTime


def create_sample_state() -> CanonicalState:
    """Create a sample CanonicalState for testing."""
    return CanonicalState(
        player_state=PlayerState(
            entity_id="player",
            name="TestPlayer",
            location_id="loc_tavern",
            realm="炼气一层",
            spiritual_power=50,
        ),
        world_state=WorldState(
            entity_id="world",
            world_id="world_1",
            current_time=WorldTime(
                calendar="Test",
                season="Spring",
                day=1,
                period="Morning",
            ),
            weather="sunny",
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene",
            scene_id="scene_1",
            location_id="loc_tavern",
        ),
        location_states={
            "loc_tavern": LocationState(
                entity_id="loc_tavern",
                location_id="loc_tavern",
                name="Tavern",
            ),
        },
        npc_states={
            "npc_merchant": NPCState(
                entity_id="npc_merchant",
                npc_id="npc_merchant",
                name="Merchant",
                location_id="loc_tavern",
                mental_state=MentalState(
                    trust_toward_player=0.5,
                    suspicion_toward_player=0.1,
                ),
                physical_state=PhysicalState(
                    hp=100,
                    max_hp=100,
                ),
            ),
        },
    )


class TestStateDeltaValidatorPathValidation:
    """Test path whitelist/blacklist validation."""

    def test_allowed_path_session_state_location(self):
        """Test that session_state.current_location_id is allowed."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="session_state.current_location_id",
            operation="set",
            old_value="loc_tavern",
            new_value="loc_square",
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid
        path_checks = [c for c in result.checks if c.check_name == "path"]
        assert len(path_checks) == 1
        assert path_checks[0].passed

    def test_allowed_path_player_state_spirit_power(self):
        """Test that player_state.spirit_power is allowed."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=50,
            new_value=80,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid

    def test_allowed_path_npc_trust_score(self):
        """Test that npc_state.*.trust_score is allowed."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="npc_state.npc_merchant.trust_score",
            operation="set",
            old_value=50,
            new_value=60,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid

    def test_blocked_path_session_status(self):
        """Test that session.status is blocked."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="session.status",
            operation="set",
            old_value="active",
            new_value="completed",
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("not allowed" in e for e in result.errors)

    def test_blocked_path_npc_hidden_identity(self):
        """Test that npc_state.*.hidden_identity is blocked."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="npc_state.npc_merchant.hidden_identity",
            operation="set",
            old_value=None,
            new_value="secret_spy",
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("not allowed" in e for e in result.errors)

    def test_blocked_path_npc_true_identity(self):
        """Test that npc_state.*.true_identity is blocked."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="npc_state.npc_merchant.true_identity",
            operation="set",
            old_value=None,
            new_value="demon_lord",
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("not allowed" in e for e in result.errors)

    def test_blocked_path_npc_hidden_plan_state(self):
        """Test that npc_state.*.hidden_plan_state is blocked."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="npc_state.npc_merchant.hidden_plan_state",
            operation="set",
            old_value=None,
            new_value="destroy_world",
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid

    def test_blocked_path_player_state_id(self):
        """Test that player_state.id is blocked."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.id",
            operation="set",
            old_value="player_001",
            new_value="player_002",
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid

    def test_unknown_path_rejected(self):
        """Test that unknown paths are rejected."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="unknown_entity.some_field",
            operation="set",
            old_value=None,
            new_value="value",
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("not allowed" in e for e in result.errors)


class TestStateDeltaValidatorOldValueValidation:
    """Test old_value verification."""

    def test_old_value_mismatch_rejected(self):
        """Test that old_value mismatch is rejected for fields that exist."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=30,  # Wrong! Actual is 50
            new_value=80,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("old_value mismatch" in e.lower() for e in result.errors)

    def test_old_value_match_accepted(self):
        """Test that correct old_value is accepted."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=50,  # Correct!
            new_value=80,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid

    def test_old_value_validation_for_npc_trust(self):
        """Test old_value validation for NPC trust_score."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        # NPC trust_toward_player is 0.5, which maps to 50 in trust_score
        result = validator.validate(
            path="npc_state.npc_merchant.trust_score",
            operation="set",
            old_value=50,  # Correct (0.5 * 100)
            new_value=60,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid

    def test_old_value_mismatch_for_npc_trust(self):
        """Test old_value mismatch rejection for NPC trust_score."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        # NPC trust_toward_player is 0.5, which maps to 50
        result = validator.validate(
            path="npc_state.npc_merchant.trust_score",
            operation="set",
            old_value=30,  # Wrong! Actual is 50
            new_value=60,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("old_value mismatch" in e.lower() for e in result.errors)

    def test_old_value_bypass_for_exception_source(self):
        """Test that exception source_event_id bypasses old_value check."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=None,
            new_value=100,
            current_state=state,
            source_event_id="bootstrap",
        )
        
        assert result.is_valid

    def test_dynamic_collection_path_allows_any_old_value(self):
        """Test that dynamic collection paths allow any old_value."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="session_state.flags.visited_tavern",
            operation="set",
            old_value=None,
            new_value=True,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid


class TestStateDeltaValidatorNumericBounds:
    """Test numeric bounds validation."""

    def test_value_below_minimum_rejected(self):
        """Test that value below minimum is rejected."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=50,
            new_value=-10,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("below minimum" in e for e in result.errors)

    def test_value_above_maximum_rejected(self):
        """Test that value above maximum is rejected."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="npc_state.npc_merchant.trust_score",
            operation="set",
            old_value=50,
            new_value=150,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("above maximum" in e for e in result.errors)

    def test_value_at_minimum_accepted(self):
        """Test that value at minimum is accepted."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=50,
            new_value=0,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid

    def test_value_at_maximum_accepted(self):
        """Test that value at maximum is accepted."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="npc_state.npc_merchant.trust_score",
            operation="set",
            old_value=50,
            new_value=100,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid

    def test_negative_affinity_allowed(self):
        """Test that negative affinity is allowed (range -100 to 100)."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="npc_state.npc_merchant.affinity",
            operation="set",
            old_value=0,
            new_value=-50,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert "below minimum" not in str(result.errors)


class TestStateDeltaValidatorOperationValidation:
    """Test operation type validation."""

    def test_valid_operation_set(self):
        """Test that 'set' operation is valid."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=50,
            new_value=80,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert result.is_valid

    def test_valid_operation_increment(self):
        """Test that 'increment' operation is valid."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.experience",
            operation="increment",
            old_value=0,
            new_value=100,
            current_state=state,
            source_event_id="event_001",
        )
        
        # Should pass operation check (may fail on old_value if not set up)
        operation_checks = [c for c in result.checks if c.check_name == "operation"]
        assert len(operation_checks) == 1
        assert operation_checks[0].passed

    def test_invalid_operation_rejected(self):
        """Test that invalid operation is rejected."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="delete",
            old_value=50,
            new_value=None,
            current_state=state,
            source_event_id="event_001",
        )
        
        assert not result.is_valid
        assert any("operation" in e and "not allowed" in e for e in result.errors)


class TestStateDeltaValidatorSourceEventId:
    """Test source_event_id validation."""

    def test_missing_source_event_id_rejected(self):
        """Test that missing source_event_id is rejected."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        result = validator.validate(
            path="player_state.spirit_power",
            operation="set",
            old_value=50,
            new_value=80,
            current_state=state,
            source_event_id=None,
        )
        
        assert not result.is_valid
        assert any("source_event_id" in e for e in result.errors)

    def test_exception_source_event_id_accepted(self):
        """Test that exception source_event_id values are accepted."""
        validator = StateDeltaValidator()
        state = create_sample_state()
        
        for exception_value in ["bootstrap", "system", "migration", "admin", "debug"]:
            result = validator.validate(
                path="player_state.spirit_power",
                operation="set",
                old_value=None,
                new_value=100,
                current_state=state,
                source_event_id=exception_value,
            )
            
            assert result.is_valid, f"Exception '{exception_value}' should be accepted"


class TestStateDeltaContractHelpers:
    """Test helper functions from state_delta_contract."""

    def test_is_path_allowed_for_allowed_paths(self):
        """Test is_path_allowed returns True for allowed paths."""
        allowed_paths = [
            "session_state.current_location_id",
            "player_state.hp",
            "npc_state.npc_001.trust_score",
            "world_state.weather",
            "quest_state.quest_001.status",
        ]
        
        for path in allowed_paths:
            assert is_path_allowed(path), f"Path '{path}' should be allowed"

    def test_is_path_allowed_for_blocked_paths(self):
        """Test is_path_allowed returns False for blocked paths."""
        blocked_paths = [
            "session.status",
            "session.id",
            "npc_state.npc_001.hidden_identity",
            "npc_state.npc_001.true_identity",
            "player_state.id",
        ]
        
        for path in blocked_paths:
            assert not is_path_allowed(path), f"Path '{path}' should be blocked"

    def test_is_operation_allowed_for_valid_operations(self):
        """Test is_operation_allowed returns True for valid operations."""
        valid_operations = ["set", "increment", "decrement", "append", "remove", "merge"]
        
        for op in valid_operations:
            assert is_operation_allowed(op), f"Operation '{op}' should be allowed"

    def test_is_operation_allowed_for_invalid_operations(self):
        """Test is_operation_allowed returns False for invalid operations."""
        invalid_operations = ["delete", "create", "destroy", "hack", ""]
        
        for op in invalid_operations:
            assert not is_operation_allowed(op), f"Operation '{op}' should not be allowed"

    def test_get_numeric_bounds_for_known_paths(self):
        """Test get_numeric_bounds returns correct bounds."""
        assert get_numeric_bounds("player_state.hp") == (0, None)
        assert get_numeric_bounds("player_state.stamina") == (0, 100)
        assert get_numeric_bounds("npc_state.npc_001.trust_score") == (0, 100)
        assert get_numeric_bounds("npc_state.npc_001.affinity") == (-100, 100)

    def test_get_numeric_bounds_for_unknown_paths(self):
        """Test get_numeric_bounds returns None for unknown paths."""
        assert get_numeric_bounds("unknown.path") is None
        assert get_numeric_bounds("player_state.name") is None

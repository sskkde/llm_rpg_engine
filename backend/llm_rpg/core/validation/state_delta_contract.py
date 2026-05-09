"""State Delta Contract Constants.

This module defines the contract for valid state delta operations.
All state changes must conform to these rules to be accepted.

Contract Categories:
1. Path whitelist/blacklist - which state paths can be modified
2. Operation enum - valid operation types
3. Numeric bounds - value constraints for numeric fields
4. Source event ID exceptions - special sources that bypass validation
"""



# =============================================================================
# ALLOWED DELTA PATHS
# =============================================================================
# Paths that can be modified via state deltas.
# Format: "entity_type.field_name" or "entity_type.entity_id.field_name"
# Wildcard patterns use * for dynamic IDs (e.g., npc_state.*.trust_score)

ALLOWED_DELTA_PATHS: list[str] = [
    # Session state paths
    "session_state.current_location_id",
    "session_state.world_time",
    "session_state.current_chapter_id",
    "session_state.flags.*",

    # Player state paths
    "player_state.hp",
    "player_state.stamina",
    "player_state.spirit_power",
    "player_state.realm",
    "player_state.experience",
    "player_state.gold",
    "player_state.inventory.*",
    "player_state.learned_techniques.*",
    "player_state.completed_quests.*",
    "player_state.reputation.*",

    # NPC state paths (per-NPC)
    "npc_state.*.trust_score",
    "npc_state.*.suspicion_score",
    "npc_state.*.current_location_id",
    "npc_state.*.affinity",
    "npc_state.*.dialogue_state",
    "npc_state.*.quest_progress.*",

    # World state paths
    "world_state.weather",
    "world_state.time_of_day",
    "world_state.global_flags.*",

    # Quest state paths
    "quest_state.*.status",
    "quest_state.*.current_step",
    "quest_state.*.objectives.*",
]

# =============================================================================
# BLOCKED DELTA PATHS
# =============================================================================
# Paths that are explicitly forbidden from modification.
# These represent system-critical or integrity-sensitive fields.

BLOCKED_DELTA_PATHS: list[str] = [
    # Session integrity fields
    "session.id",
    "session.status",
    "session.user_id",
    "session.created_at",
    "session.updated_at",

    # NPC hidden states (must not be directly modified by LLM proposals)
    # These represent high-authority fields that require rule-engine paths
    "npc_state.*.hidden_plan_state",
    "npc_state.*.secret_knowledge",
    "npc_state.*.true_identity",
    "npc_state.*.hidden_identity",  # Alias for true_identity
    "npc_state.*.memory.*",

    # Player immutable fields
    "player_state.id",
    "player_state.user_id",
    "player_state.created_at",

    # World immutable fields
    "world_state.id",
    "world_state.seed",

    # Quest status skips (must go through quest engine)
    "quest_state.*.skip",  # Quest skips not allowed via direct write

    # Audit fields (modified only by system)
    "audit_log.*",
    "game_events.*",
    "state_deltas.*",
    "validation_reports.*",
]

# =============================================================================
# ALLOWED OPERATIONS
# =============================================================================
# Valid operation types for state deltas.
# Each operation has specific semantics for how the value change is applied.

ALLOWED_OPERATIONS: list[str] = [
    "set",        # Replace old value with new value
    "increment",  # Add numeric delta to current value
    "decrement",  # Subtract numeric delta from current value
    "append",     # Add item to list/array
    "remove",     # Remove item from list/array
    "merge",      # Merge dict fields (partial update)
]

# =============================================================================
# NUMERIC BOUNDS
# =============================================================================
# Value constraints for numeric fields.
# Format: (min_value, max_value) - inclusive bounds
# Use None for unbounded (e.g., (0, None) means >= 0)

NUMERIC_BOUNDS: dict[str, tuple[int | None, int | None]] = {
    # Player attributes
    "player_state.hp": (0, None),           # HP >= 0
    "player_state.stamina": (0, 100),        # Stamina: 0-100
    "player_state.spirit_power": (0, None),  # Spirit power >= 0
    "player_state.realm": (0, 10),           # Cultivation realm: 0-10
    "player_state.experience": (0, None),    # Experience >= 0
    "player_state.gold": (0, None),          # Gold >= 0

    # NPC attributes
    "npc_state.*.trust_score": (0, 100),      # Trust: 0-100
    "npc_state.*.suspicion_score": (0, 100),  # Suspicion: 0-100
    "npc_state.*.affinity": (-100, 100),     # Affinity: -100 to 100

    # World state
    "session_state.world_time": (0, None),    # Time >= 0
}

# =============================================================================
# SOURCE EVENT ID EXCEPTIONS
# =============================================================================
# Special source_event_id values that bypass certain validation rules.
# These are used for system-initiated or bootstrap operations.

SOURCE_EVENT_ID_EXCEPTIONS: list[str] = [
    "bootstrap",   # Initial state setup
    "system",      # System-initiated changes
    "migration",   # Database migration scripts
    "admin",       # Admin override operations
    "debug",       # Debug/test operations
]

# =============================================================================
# PATH MATCHING UTILITIES
# =============================================================================

def is_path_allowed(path: str) -> bool:
    """Check if a path matches the allowed patterns and is not blocked."""
    import fnmatch

    # First check if explicitly blocked
    for blocked in BLOCKED_DELTA_PATHS:
        if fnmatch.fnmatch(path, blocked):
            return False

    # Then check if allowed
    for allowed in ALLOWED_DELTA_PATHS:
        if fnmatch.fnmatch(path, allowed):
            return True

    return False


def is_operation_allowed(operation: str) -> bool:
    """Check if an operation type is valid."""
    return operation in ALLOWED_OPERATIONS


def get_numeric_bounds(path: str) -> tuple[int | None, int | None] | None:
    """Get numeric bounds for a path, if defined."""
    import fnmatch

    for pattern, bounds in NUMERIC_BOUNDS.items():
        if fnmatch.fnmatch(path, pattern):
            return bounds

    return None


def is_source_event_id_exception(source_event_id: str | None) -> bool:
    """Check if source_event_id is an exception value."""
    if source_event_id is None:
        return False
    return source_event_id in SOURCE_EVENT_ID_EXCEPTIONS

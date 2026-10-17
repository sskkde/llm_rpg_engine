"""Stable reason codes for the phase-2 action authorization / resolution chain.

Two levels exist on purpose:

* :class:`ActionReasonCode` is the **public** reason code. It is the only reason
  vocabulary allowed into the ``action_resolution`` summary that reaches clients,
  and it is deliberately coarse: it must not disclose whether a hidden entity
  exists. There are exactly four values plus ``None`` for accepted actions.
* :class:`ActionDetailCode` is **restricted-audit** detail. It never leaves the
  server; it is written to audit/validation records so operators can tell an
  actor-mismatch from a cross-session reference.

Keeping the two apart is what lets the engine explain itself internally while the
public contract stays non-disclosing.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ActionStatus(str, Enum):
    """Outcome of one authorized/attempted action in a turn."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CLARIFICATION = "clarification"


class ActionReasonCode(str, Enum):
    """Public reason codes for a rejected action."""

    UNSUPPORTED = "unsupported"
    INVALID_PARAMS = "invalid_params"
    TARGET_UNAVAILABLE = "target_unavailable"
    CONTRACT_FAILURE = "contract_failure"


class ActionDetailCode(str, Enum):
    """Restricted-audit detail codes. Never returned to clients."""

    # Contract / parse layer
    CONTRACT_EMPTY_OUTPUT = "contract_empty_output"
    CONTRACT_NOT_JSON = "contract_not_json"
    CONTRACT_DUPLICATE_KEY = "contract_duplicate_key"
    CONTRACT_INVALID_CONSTANT = "contract_invalid_constant"
    CONTRACT_VERSION_MISMATCH = "contract_version_mismatch"
    CONTRACT_SCHEMA_VIOLATION = "contract_schema_violation"
    CONTRACT_UNAVAILABLE = "contract_unavailable"

    # Authorization layer
    ACTION_NOT_AUTHORIZED = "action_not_authorized"
    MISSING_TARGET = "missing_target"
    ACTOR_ROLE_MISMATCH = "actor_role_mismatch"
    ACTOR_NOT_BOUND = "actor_not_bound"
    ACTOR_IMPERSONATION = "actor_impersonation"
    ENTITY_NOT_FOUND = "entity_not_found"
    ENTITY_WRONG_WORLD = "entity_wrong_world"
    ENTITY_WRONG_SESSION = "entity_wrong_session"
    ENTITY_NOT_PRESENT = "entity_not_present"
    ENTITY_NOT_ALIVE = "entity_not_alive"
    ENTITY_NOT_VISIBLE = "entity_not_visible"
    LOCATION_NOT_DISCOVERED = "location_not_discovered"
    EVENT_REFERENCE_UNKNOWN = "event_reference_unknown"
    EVENT_REFERENCE_FOREIGN = "event_reference_foreign"
    RECOMMENDED_ACTION_UNKNOWN = "recommended_action_unknown"
    MEMORY_ID_NOT_AVAILABLE = "memory_id_not_available"

    # Resolution layer
    DOMAIN_RULE_BLOCKED = "domain_rule_blocked"
    NO_HANDLER = "no_handler"
    UNSUPPORTED_ACTION = "unsupported_action"

    # Phase-3 time simulation: a perceivable world interrupt cut the player's
    # continuous action short. Internal only -- it maps onto the existing public
    # ``target_unavailable`` vocabulary so the v1 public enum is unchanged.
    ACTION_INTERRUPTED = "action_interrupted"


def public_reason_for_detail(detail: Optional[ActionDetailCode]) -> Optional[ActionReasonCode]:
    """Map restricted detail onto the coarse public reason vocabulary.

    Unknown/absent detail maps to ``None`` so a caller that has no detail never
    accidentally invents a public reason.
    """
    if detail is None:
        return None

    if detail in _CONTRACT_DETAILS:
        return ActionReasonCode.CONTRACT_FAILURE
    if detail in _UNSUPPORTED_DETAILS:
        return ActionReasonCode.UNSUPPORTED
    if detail in _TARGET_DETAILS:
        return ActionReasonCode.TARGET_UNAVAILABLE
    return ActionReasonCode.INVALID_PARAMS


_CONTRACT_DETAILS = frozenset(
    {
        ActionDetailCode.CONTRACT_EMPTY_OUTPUT,
        ActionDetailCode.CONTRACT_NOT_JSON,
        ActionDetailCode.CONTRACT_DUPLICATE_KEY,
        ActionDetailCode.CONTRACT_INVALID_CONSTANT,
        ActionDetailCode.CONTRACT_VERSION_MISMATCH,
        ActionDetailCode.CONTRACT_SCHEMA_VIOLATION,
        ActionDetailCode.CONTRACT_UNAVAILABLE,
    }
)

_UNSUPPORTED_DETAILS = frozenset(
    {
        ActionDetailCode.ACTION_NOT_AUTHORIZED,
        ActionDetailCode.NO_HANDLER,
        ActionDetailCode.UNSUPPORTED_ACTION,
    }
)

#: Details that must be reported as "target unavailable". They are exactly the
#: reasons that could otherwise let a caller probe for a hidden entity, so they
#: collapse into one non-disclosing public code.
_TARGET_DETAILS = frozenset(
    {
        ActionDetailCode.ENTITY_NOT_FOUND,
        ActionDetailCode.ENTITY_WRONG_WORLD,
        ActionDetailCode.ENTITY_WRONG_SESSION,
        ActionDetailCode.ENTITY_NOT_PRESENT,
        ActionDetailCode.ENTITY_NOT_ALIVE,
        ActionDetailCode.ENTITY_NOT_VISIBLE,
        ActionDetailCode.LOCATION_NOT_DISCOVERED,
        ActionDetailCode.EVENT_REFERENCE_UNKNOWN,
        ActionDetailCode.EVENT_REFERENCE_FOREIGN,
        ActionDetailCode.RECOMMENDED_ACTION_UNKNOWN,
        ActionDetailCode.MEMORY_ID_NOT_AVAILABLE,
        ActionDetailCode.ACTION_INTERRUPTED,
    }
)


__all__ = [
    "ActionStatus",
    "ActionReasonCode",
    "ActionDetailCode",
    "public_reason_for_detail",
]

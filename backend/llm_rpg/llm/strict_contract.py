"""Strict production parsing for the contract_version=2 wire schema.

The strict production mode deliberately does **not** reuse the lenient repair
handler. It allows exactly two normalizations:

1. strip leading/trailing whitespace from the whole response, and
2. strip one code fence that wraps the *entire* response.

Everything else must already be a single complete JSON document. Duplicate
object keys, ``NaN``/``Infinity`` constants, trailing content, unknown fields
(including nested ones), out-of-range values and wrong contract versions are all
rejections, never repairs. A proposal that cannot be parsed reliably is reported
with a stable reason code and the caller falls back safely.

Lenient repair remains available to non-production/auxiliary callers; production
never switches back to it.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Optional, Type

from pydantic import BaseModel, ValidationError

from ..models.action_contract import PRODUCTION_CONTRACT_VERSION, production_contract_model

#: A fence that wraps the entire response, e.g. ```json\n{...}\n```
_WHOLE_RESPONSE_FENCE = re.compile(
    r"\A\s*```[A-Za-z0-9_+-]*[ \t]*\r?\n(?P<body>.*?)\r?\n?[ \t]*```\s*\Z",
    re.DOTALL,
)


class ContractReasonCode(str, Enum):
    """Stable reason codes for a rejected production contract."""

    EMPTY_OUTPUT = "contract_empty_output"
    NOT_JSON = "contract_not_json"
    DUPLICATE_KEY = "contract_duplicate_key"
    INVALID_CONSTANT = "contract_invalid_constant"
    VERSION_MISMATCH = "contract_version_mismatch"
    SCHEMA_VIOLATION = "contract_schema_violation"


class ContractViolation(Exception):
    """A production output did not satisfy the strict contract.

    ``code`` is a stable :class:`ContractReasonCode` value suitable for audit and
    for the public ``action_resolution`` summary (mapped to
    ``contract_failure``). ``detail`` is restricted-audit detail.
    """

    def __init__(self, code: ContractReasonCode, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}" if detail else code.value)


class _DuplicateKey(ValueError):
    def __init__(self, key: str):
        self.key = key
        super().__init__(key)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise _DuplicateKey(key)
        seen.add(key)
    return dict(pairs)


def _reject_constant(name: str) -> Any:
    raise ContractViolation(
        ContractReasonCode.INVALID_CONSTANT,
        f"non-finite JSON constant is not allowed: {name}",
    )


def strip_single_code_fence(raw: str) -> str:
    """Return the response with one whole-response code fence removed.

    A fence that does not wrap the entire response is left untouched: the
    subsequent JSON parse then fails, which is the intended rejection.
    """
    match = _WHOLE_RESPONSE_FENCE.match(raw)
    if match is None:
        return raw
    return match.group("body")


def parse_strict_json(raw: Optional[str]) -> Any:
    """Parse a production response into JSON with the strict rules above.

    Raises:
        ContractViolation: for empty output, non-JSON text, duplicate keys,
            non-finite constants or trailing content.
    """
    if raw is None or not raw.strip():
        raise ContractViolation(ContractReasonCode.EMPTY_OUTPUT, "empty model output")

    text = strip_single_code_fence(raw.strip())

    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ContractViolation:
        raise
    except _DuplicateKey as exc:
        raise ContractViolation(
            ContractReasonCode.DUPLICATE_KEY, f"duplicate object key: {exc.key}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ContractViolation(
            ContractReasonCode.NOT_JSON, f"invalid JSON: {exc.msg} at {exc.pos}"
        ) from exc
    except ValueError as exc:
        raise ContractViolation(ContractReasonCode.NOT_JSON, str(exc)) from exc


def _validate_contract_version(payload: Any) -> None:
    """Reject a payload whose declared contract version is not the production one.

    A missing version is also a mismatch: the model must state the version it
    believes it is answering with, so an old template's output is explicitly
    recorded as contract-incompatible instead of being silently reinterpreted.
    """
    if not isinstance(payload, dict):
        raise ContractViolation(
            ContractReasonCode.SCHEMA_VIOLATION,
            f"top-level value must be a JSON object, got {type(payload).__name__}",
        )
    version = payload.get("contract_version")
    if version != PRODUCTION_CONTRACT_VERSION:
        raise ContractViolation(
            ContractReasonCode.VERSION_MISMATCH,
            f"expected contract_version={PRODUCTION_CONTRACT_VERSION}, got {version!r}",
        )


def validate_production_contract(
    proposal_type: str,
    raw: Optional[str],
    model_cls: Optional[Type[BaseModel]] = None,
) -> BaseModel:
    """Parse and validate a production response end to end.

    Args:
        proposal_type: Production proposal key (``input_intent``, ``npc_action``,
            ``world_tick``, ``scene_event``, ``narration``).
        raw: The raw model output.
        model_cls: Optional explicit DTO; defaults to the registered one for
            ``proposal_type``.

    Returns:
        The validated contract model instance.

    Raises:
        ContractViolation: on any rejection, with a stable reason code.
        KeyError: when ``proposal_type`` has no production contract.
    """
    if model_cls is None:
        model_cls = production_contract_model(proposal_type)

    payload = parse_strict_json(raw)
    _validate_contract_version(payload)

    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors()
        detail = "; ".join(
            f"{'/'.join(str(part) for part in err.get('loc', ()))}: {err.get('msg')}"
            for err in errors[:5]
        )
        raise ContractViolation(ContractReasonCode.SCHEMA_VIOLATION, detail) from exc


__all__ = [
    "ContractReasonCode",
    "ContractViolation",
    "strip_single_code_fence",
    "parse_strict_json",
    "validate_production_contract",
]

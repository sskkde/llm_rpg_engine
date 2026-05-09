"""Narration leak validation for player-visible narration."""

import json
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from ...models.common import ValidationResult
from ...models.states import CanonicalState
from ...storage.models import GameEventModel, NPCTemplateModel, NPCSecretModel, SessionNPCStateModel
from .context import ValidationContext
from .result import make_check


@dataclass(frozen=True)
class ForbiddenNarrationFact:
    """Text that must not appear in player-visible narration."""

    content: str
    source: str


class NarrationLeakValidator:
    """Validator for narration content to prevent information leaks."""

    def validate_narration(
        self,
        text: str,
        forbidden_info: List[str],
        state: Optional[CanonicalState] = None,
        context: Optional[ValidationContext] = None,
        db: Optional[Any] = None,
        session_id: Optional[str] = None,
        npc_ids: Optional[List[str]] = None,
    ) -> ValidationResult:
        """Validate narration for information leaks.

        Args:
            text: Narration text to validate
            forbidden_info: List of forbidden information patterns
            state: Current canonical state (optional)
            context: Optional validation context
            db: Optional DB session for DB-backed forbidden fact queries
            session_id: Optional game session ID for DB-backed checks
            npc_ids: Optional NPC template IDs to constrain NPC-secret checks

        Returns:
            ValidationResult indicating if narration is safe
        """
        if context is not None and state is None:
            state = context.canonical_state
        if context is not None:
            db = db or context.db
            session_id = session_id or context.session_id

        checks = []
        errors = []
        forbidden_facts = [
            ForbiddenNarrationFact(content=info, source="explicit_forbidden_info")
            for info in forbidden_info
            if self._is_checkable_text(info)
        ]
        forbidden_facts.extend(self._load_db_forbidden_facts(db, session_id, state, npc_ids))

        for fact in self._deduplicate_facts(forbidden_facts):
            if fact.content.lower() in text.lower():
                checks.append(make_check(
                    "narration_leak_check",
                    passed=False,
                    reason=f"Narration contains forbidden information from {fact.source}",
                    severity="error",
                ))
                errors.append(f"Narration contains forbidden information from {fact.source}: {fact.content}")
            else:
                checks.append(make_check(
                    "narration_leak_check",
                    passed=True,
                ))

        if not forbidden_facts:
            checks.append(make_check("narration_leak_check", passed=True))

        return ValidationResult(
            is_valid=len(errors) == 0,
            checks=checks,
            errors=errors,
        )

    def _load_db_forbidden_facts(
        self,
        db: Optional[Any],
        session_id: Optional[str],
        state: Optional[CanonicalState],
        npc_ids: Optional[List[str]],
    ) -> List[ForbiddenNarrationFact]:
        if db is None or not session_id:
            return []

        relevant_npc_ids = self._resolve_relevant_npc_ids(db, session_id, state, npc_ids)
        facts: List[ForbiddenNarrationFact] = []

        secret_query = db.query(NPCSecretModel).filter(
            NPCSecretModel.session_id == session_id,
            NPCSecretModel.status != "revealed",
        )
        if relevant_npc_ids:
            secret_query = secret_query.filter(NPCSecretModel.npc_id.in_(relevant_npc_ids))
        for secret in secret_query.all():
            if self._is_checkable_text(secret.content):
                facts.append(ForbiddenNarrationFact(secret.content, f"npc_secret:{secret.npc_id}"))

        hidden_identity_query = db.query(NPCTemplateModel).join(
            SessionNPCStateModel,
            SessionNPCStateModel.npc_template_id == NPCTemplateModel.id,
        ).filter(SessionNPCStateModel.session_id == session_id)
        if relevant_npc_ids:
            hidden_identity_query = hidden_identity_query.filter(NPCTemplateModel.id.in_(relevant_npc_ids))
        for npc in hidden_identity_query.all():
            if self._is_checkable_text(npc.hidden_identity):
                facts.append(ForbiddenNarrationFact(npc.hidden_identity, f"hidden_identity:{npc.id}"))

        event_query = db.query(GameEventModel).filter(
            GameEventModel.session_id == session_id,
            GameEventModel.private_payload_json.isnot(None),
        )
        for event in event_query.all():
            for private_text in self._extract_private_payload_text(event.private_payload_json):
                facts.append(ForbiddenNarrationFact(private_text, f"private_payload:{event.id}"))

        return facts

    def _resolve_relevant_npc_ids(
        self,
        db: Any,
        session_id: str,
        state: Optional[CanonicalState],
        npc_ids: Optional[List[str]],
    ) -> List[str]:
        resolved = {npc_id for npc_id in (npc_ids or []) if npc_id}
        if resolved:
            return sorted(resolved)

        if state is not None and getattr(state, "npc_states", None):
            current_location_id = getattr(state.player_state, "location_id", None) if state.player_state else None
            for npc_id, npc_state in state.npc_states.items():
                if not current_location_id or getattr(npc_state, "location_id", None) == current_location_id:
                    resolved.add(getattr(npc_state, "npc_id", None) or npc_id)

        rows = db.query(SessionNPCStateModel.npc_template_id).filter(
            SessionNPCStateModel.session_id == session_id,
        ).all()
        for row in rows:
            if row[0]:
                resolved.add(row[0])

        return sorted(resolved)

    def _extract_private_payload_text(self, payload: Any) -> Iterable[str]:
        if isinstance(payload, str):
            if self._is_checkable_text(payload):
                yield payload
            return
        if isinstance(payload, dict):
            for value in payload.values():
                yield from self._extract_private_payload_text(value)
            return
        if isinstance(payload, list):
            for item in payload:
                yield from self._extract_private_payload_text(item)
            return
        if payload is not None:
            serialized = json.dumps(payload, ensure_ascii=False)
            if self._is_checkable_text(serialized):
                yield serialized

    def _deduplicate_facts(self, facts: List[ForbiddenNarrationFact]) -> List[ForbiddenNarrationFact]:
        seen = set()
        deduplicated: List[ForbiddenNarrationFact] = []
        for fact in facts:
            key = fact.content.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(fact)
        return deduplicated

    def _is_checkable_text(self, value: Optional[str]) -> bool:
        return isinstance(value, str) and len(value.strip()) >= 2


__all__ = ["NarrationLeakValidator"]

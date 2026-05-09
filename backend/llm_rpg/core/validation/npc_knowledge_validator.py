"""NPC knowledge validation for perspective-safe NPC actions."""

from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from ...models.common import ValidationCheck, ValidationResult
from ...models.states import CanonicalState
from ...storage.models import (
    NPCBeliefModel,
    NPCPrivateMemoryModel,
    NPCSecretModel,
    NPCTemplateModel,
    SessionNPCStateModel,
)
from .context import ValidationContext
from .result import failed_result, make_check


@dataclass(frozen=True)
class ProtectedNPCFact:
    """A DB-backed fact that an NPC may not reference unless it has access."""

    content: str
    source: str
    owner_npc_id: str
    fact_type: str


class NPCKnowledgeValidator:
    """Validator for NPC knowledge consistency.

    The validator performs conservative DB-backed checks against exact text that
    appears in protected fact tables. It intentionally does not attempt semantic
    or vector leak detection.
    """

    def validate_knowledge(
        self,
        npc_id: str,
        knowledge: str,
        state: CanonicalState,
        context: ValidationContext | None = None,
        db: Session | None = None,
        session_id: str | None = None,
    ) -> ValidationResult:
        """Validate NPC knowledge consistency.

        Args:
            npc_id: ID of the NPC
            knowledge: Knowledge content to validate
            state: Current canonical state
            context: Optional validation context
            db: Optional DB session for DB-backed perspective checks
            session_id: Optional session ID for DB-backed perspective checks

        Returns:
            ValidationResult indicating if knowledge is valid
        """
        if context is not None:
            state = context.canonical_state
            db = db or cast(Session, context.db)
            session_id = session_id or context.session_id

        npc_state = state.npc_states.get(npc_id)
        if npc_state is None:
            return failed_result(
                "npc_existence",
                f"NPC {npc_id} not found",
            )

        protected_facts = self._load_protected_facts(db, session_id)
        known_texts = self._load_npc_known_texts(db, session_id, npc_id)
        errors: list[str] = []
        checks: list[ValidationCheck] = []

        for fact in self._deduplicate_facts(protected_facts):
            if not self._text_contains(knowledge, fact.content):
                continue
            if self._npc_has_access(npc_id, fact, known_texts):
                checks.append(make_check(
                    "npc_knowledge_check",
                    passed=True,
                    reason=f"NPC {npc_id} has access to {fact.source}",
                    severity="info",
                ))
                continue

            reason = f"NPC {npc_id} references inaccessible {fact.source}: {fact.content}"
            checks.append(make_check(
                "npc_knowledge_check",
                passed=False,
                reason=reason,
                severity="error",
            ))
            errors.append(reason)

        if errors:
            return ValidationResult(is_valid=False, checks=checks, errors=errors, warnings=[])

        if not checks:
            checks.append(make_check("npc_knowledge_check", passed=True, severity="info"))
        return ValidationResult(
            is_valid=True,
            checks=checks,
            errors=[],
            warnings=[],
        )

    def _load_protected_facts(
        self,
        db: Session | None,
        session_id: str | None,
    ) -> list[ProtectedNPCFact]:
        if db is None or not session_id:
            return []

        facts: list[ProtectedNPCFact] = []
        secret_rows = db.query(NPCSecretModel).filter(
            NPCSecretModel.session_id == session_id,
            NPCSecretModel.status != "revealed",
        ).all()
        for secret in secret_rows:
            content = getattr(secret, "content", None)
            owner_npc_id = getattr(secret, "npc_id", "")
            if self._is_checkable_text(content):
                facts.append(ProtectedNPCFact(
                    content=cast(str, content),
                    source=f"npc_secret:{owner_npc_id}",
                    owner_npc_id=str(owner_npc_id),
                    fact_type="npc_secret",
                ))

        hidden_identity_rows = db.query(NPCTemplateModel).join(
            SessionNPCStateModel,
            SessionNPCStateModel.npc_template_id == NPCTemplateModel.id,
        ).filter(SessionNPCStateModel.session_id == session_id).all()
        for npc in hidden_identity_rows:
            content = getattr(npc, "hidden_identity", None)
            owner_npc_id = getattr(npc, "id", "")
            if self._is_checkable_text(content):
                facts.append(ProtectedNPCFact(
                    content=cast(str, content),
                    source=f"hidden_identity:{owner_npc_id}",
                    owner_npc_id=str(owner_npc_id),
                    fact_type="hidden_identity",
                ))

        return facts

    def _load_npc_known_texts(
        self,
        db: Session | None,
        session_id: str | None,
        npc_id: str,
    ) -> list[str]:
        if db is None or not session_id:
            return []

        known_texts: list[str] = []
        belief_rows = db.query(NPCBeliefModel).filter(
            NPCBeliefModel.session_id == session_id,
            NPCBeliefModel.npc_id == npc_id,
        ).all()
        for row in belief_rows:
            content = getattr(row, "content", None)
            if self._is_checkable_text(content):
                known_texts.append(cast(str, content))

        memory_rows = db.query(NPCPrivateMemoryModel).filter(
            NPCPrivateMemoryModel.session_id == session_id,
            NPCPrivateMemoryModel.npc_id == npc_id,
        ).all()
        for row in memory_rows:
            content = getattr(row, "content", None)
            if self._is_checkable_text(content):
                known_texts.append(cast(str, content))

        own_secret_rows = db.query(NPCSecretModel).filter(
            NPCSecretModel.session_id == session_id,
            NPCSecretModel.npc_id == npc_id,
        ).all()
        for row in own_secret_rows:
            content = getattr(row, "content", None)
            if self._is_checkable_text(content):
                known_texts.append(cast(str, content))

        return known_texts

    def _npc_has_access(self, npc_id: str, fact: ProtectedNPCFact, known_texts: list[str]) -> bool:
        if fact.owner_npc_id == npc_id:
            return True
        return any(self._texts_match(known_text, fact.content) for known_text in known_texts)

    def _deduplicate_facts(self, facts: list[ProtectedNPCFact]) -> list[ProtectedNPCFact]:
        seen: set[tuple[str, str]] = set()
        deduplicated: list[ProtectedNPCFact] = []
        for fact in facts:
            key = (fact.source, fact.content.casefold())
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(fact)
        return deduplicated

    def _text_contains(self, text: str, fact_content: str) -> bool:
        if not self._is_checkable_text(text) or not self._is_checkable_text(fact_content):
            return False
        return fact_content.casefold() in text.casefold()

    def _texts_match(self, known_text: str, fact_content: str) -> bool:
        if not self._is_checkable_text(known_text) or not self._is_checkable_text(fact_content):
            return False
        known = known_text.casefold()
        fact = fact_content.casefold()
        return fact in known or known in fact

    def _is_checkable_text(self, value: str | None) -> bool:
        return isinstance(value, str) and len(value.strip()) >= 2


__all__ = ["NPCKnowledgeValidator"]

"""Narration leak validation for player-visible narration."""

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ...models.common import ValidationResult
from ...models.states import CanonicalState
from ...storage.models import GameEventModel, NPCTemplateModel, NPCSecretModel, SessionNPCStateModel
from .context import ValidationContext
from .result import make_check


class LeakSeverity(Enum):
    """Severity level of a narration information leak."""

    EXACT_MATCH = "EXACT_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    SUSPICIOUS = "SUSPICIOUS"


@dataclass(frozen=True)
class ForbiddenNarrationFact:
    """Text that must not appear in player-visible narration."""

    content: str
    source: str


class NarrationLeakValidator:
    """Validator for narration content to prevent information leaks."""

    FAILURE_SEVERITIES = frozenset({LeakSeverity.EXACT_MATCH, LeakSeverity.PARTIAL_MATCH})

    # Minimum ratio of significant fact words that must overlap narration
    # to trigger a PARTIAL_MATCH (failure) vs SUSPICIOUS (warning only)
    _PARTIAL_MATCH_THRESHOLD = 0.25

    # Common stop words excluded from word-level overlap analysis
    _STOP_WORDS = frozenset({
        "the", "and", "for", "are", "but", "not", "you", "all",
        "can", "had", "her", "was", "one", "our", "out", "has",
        "have", "this", "that", "with", "from", "they", "will",
        "been", "were", "some", "them", "than", "then", "into",
        "just", "what", "when", "your", "more", "also", "very",
        "which", "their", "about", "there", "would", "could",
        "other", "these", "those", "after", "over", "before",
    })

    def validate_narration(
        self,
        text: str,
        forbidden_info: List[str],
        state: Optional[CanonicalState] = None,
        context: Optional[ValidationContext] = None,
        db: Optional[Any] = None,
        session_id: Optional[str] = None,
        npc_ids: Optional[List[str]] = None,
        forbidden_patterns: Optional[List[str]] = None,
    ) -> ValidationResult:
        """Validate narration for information leaks.

        Args:
            text: Narration text to validate
            forbidden_info: List of forbidden information patterns (exact substring match)
            state: Current canonical state (optional)
            context: Optional validation context
            db: Optional DB session for DB-backed forbidden fact queries
            session_id: Optional game session ID for DB-backed checks
            npc_ids: Optional NPC template IDs to constrain NPC-secret checks
            forbidden_patterns: Optional list of regex patterns that should
                never appear in narration

        Returns:
            ValidationResult indicating if narration is safe
        """
        if context is not None and state is None:
            state = context.canonical_state
        if context is not None:
            db = db or context.db
            session_id = session_id or context.session_id

        # --- Early exit: empty narration is always safe ---
        if not text or not text.strip():
            return ValidationResult(
                is_valid=True,
                checks=[make_check("narration_leak_check", passed=True)],
                errors=[],
                warnings=[],
            )

        # --- Normalize inputs ---
        forbidden_info = self._normalize_forbidden_info(forbidden_info)

        checks: list = []
        errors: list = []
        warnings: list = []

        text_lower = text.lower()

        # --- Exact and partial matching on forbidden facts ---
        forbidden_facts = [
            ForbiddenNarrationFact(content=info, source="explicit_forbidden_info")
            for info in forbidden_info
            if self._is_checkable_text(info)
        ]
        forbidden_facts.extend(self._load_db_forbidden_facts(db, session_id, state, npc_ids))

        for fact in self._deduplicate_facts(forbidden_facts):
            severity, reason = self._check_fact_against_text(fact, text_lower)
            if severity in self.FAILURE_SEVERITIES:
                checks.append(make_check(
                    "narration_leak_check",
                    passed=False,
                    reason=reason,
                    severity=severity.value,
                ))
                errors.append(reason)
            elif severity == LeakSeverity.SUSPICIOUS:
                checks.append(make_check(
                    "narration_leak_check",
                    passed=True,
                    reason=reason,
                    severity=severity.value,
                ))
                warnings.append(reason)
            else:
                checks.append(make_check(
                    "narration_leak_check",
                    passed=True,
                ))

        # --- Forbidden regex patterns ---
        for pattern_str in (forbidden_patterns or []):
            try:
                compiled = re.compile(pattern_str, re.IGNORECASE)
                if compiled.search(text):
                    reason = f"Narration matches forbidden pattern: {pattern_str}"
                    checks.append(make_check(
                        "narration_leak_check",
                        passed=False,
                        reason=reason,
                        severity=LeakSeverity.EXACT_MATCH.value,
                    ))
                    errors.append(reason)
            except re.error:
                checks.append(make_check(
                    "narration_leak_check",
                    passed=True,
                    reason=f"Skipped invalid regex pattern: {pattern_str}",
                    severity="info",
                ))

        if not forbidden_facts and not (forbidden_patterns or []):
            checks.append(make_check("narration_leak_check", passed=True))

        return ValidationResult(
            is_valid=len(errors) == 0,
            checks=checks,
            errors=errors,
            warnings=warnings,
        )

    def validate_narration_context(
        self,
        text: str,
        forbidden_info: Optional[List[str]] = None,
        forbidden_patterns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Pre-check narration context for potential leaks before LLM call.

        Performs lightweight checks (no DB access) to identify potential issues
        that should be addressed before an expensive LLM-based narration check.

        Args:
            text: Narration text to pre-check
            forbidden_info: Optional list of forbidden information strings
            forbidden_patterns: Optional list of regex patterns

        Returns:
            Dict with keys:
                suspicious: list of (fact, matched_words) tuples for SUSPICIOUS overlap
                warnings: list of warning messages for EXACT_MATCH / PARTIAL_MATCH
                has_warnings: bool indicating if any warnings exist
        """
        result: Dict[str, Any] = {
            "suspicious": [],
            "warnings": [],
            "has_warnings": False,
        }

        if not text or not text.strip():
            return result

        text_lower = text.lower()
        text_words_short = set(text_lower.split())
        text_words = {w for w in text_words_short if len(w) >= 3 and w not in self._STOP_WORDS}

        # Check forbidden_info for word-level overlap
        for info in (forbidden_info or []):
            if not self._is_checkable_text(info):
                continue
            info_lower = info.lower()
            info_words = {w for w in info_lower.split() if len(w) >= 3 and w not in self._STOP_WORDS}
            if not info_words:
                continue

            # Exact substring match → warning
            if info_lower in text_lower:
                msg = f"EXACT_MATCH: forbidden text '{info[:50]}...' found verbatim"
                result["warnings"].append(msg)
                result["has_warnings"] = True
                continue

            # Word overlap check
            overlap = info_words & text_words
            if not overlap:
                continue

            overlap_ratio = len(overlap) / len(info_words)
            if self._has_bigram_overlap(info_lower, text_lower):
                msg = f"PARTIAL_MATCH: key phrase from '{info[:50]}...' found"
                result["warnings"].append(msg)
                result["has_warnings"] = True
            elif overlap_ratio >= self._PARTIAL_MATCH_THRESHOLD:
                msg = f"PARTIAL_MATCH: {overlap_ratio:.0%} word overlap with '{info[:50]}...'"
                result["warnings"].append(msg)
                result["has_warnings"] = True
            else:
                result["suspicious"].append({
                    "fact": info[:100],
                    "matched_words": sorted(overlap),
                    "overlap_ratio": overlap_ratio,
                })

        # Check forbidden_patterns
        for pattern_str in (forbidden_patterns or []):
            try:
                compiled = re.compile(pattern_str, re.IGNORECASE)
                if compiled.search(text):
                    msg = f"Forbidden pattern matched: {pattern_str}"
                    result["warnings"].append(msg)
                    result["has_warnings"] = True
            except re.error:
                pass

        return result

    def _check_fact_against_text(
        self,
        fact: ForbiddenNarrationFact,
        text_lower: str,
    ) -> Tuple[LeakSeverity, str]:
        """Check a single forbidden fact against narration text.

        Returns (severity, reason_string).
        """
        fact_lower = fact.content.lower()

        # Exact substring match (primary detection method)
        if fact_lower in text_lower:
            return LeakSeverity.EXACT_MATCH, (
                f"Narration contains forbidden information from {fact.source}: {fact.content}"
            )

        # Word-level overlap detection for partial/suspicious matches
        fact_words_short = set(fact_lower.split())
        text_words_short = set(text_lower.split())

        # Filter to significant words (>= 3 chars) excluding stop words
        significant_fact_words = {
            w for w in fact_words_short
            if len(w) >= 3 and w not in self._STOP_WORDS
        }
        significant_text_words = {
            w for w in text_words_short
            if len(w) >= 3 and w not in self._STOP_WORDS
        }

        if not significant_fact_words:
            return LeakSeverity.SUSPICIOUS, ""

        overlap = significant_fact_words & significant_text_words
        if not overlap:
            return LeakSeverity.SUSPICIOUS, ""

        overlap_ratio = len(overlap) / len(significant_fact_words)

        # Bigram phrase check: any 2 consecutive words from fact appear in text
        if self._has_bigram_overlap(fact_lower, text_lower):
            return LeakSeverity.PARTIAL_MATCH, (
                f"Narration contains key phrases from {fact.source}: {fact.content}"
            )

        if overlap_ratio >= self._PARTIAL_MATCH_THRESHOLD:
            return LeakSeverity.PARTIAL_MATCH, (
                f"Narration contains key phrases from {fact.source}: {fact.content}"
            )

        return LeakSeverity.SUSPICIOUS, (
            f"Suspicious word overlap with forbidden info from {fact.source}"
        )

    def _has_bigram_overlap(self, fact_text: str, narration_text: str) -> bool:
        """Check if any contiguous word pair from fact appears in narration."""
        fact_words = fact_text.split()
        if len(fact_words) < 2:
            return False
        for i in range(len(fact_words) - 1):
            bigram = f"{fact_words[i]} {fact_words[i + 1]}"
            if bigram in narration_text:
                return True
        return False

    def _normalize_forbidden_info(self, forbidden_info: List[str]) -> List[str]:
        """Filter out None and empty entries from forbidden_info list."""
        if not forbidden_info:
            return []
        return [
            info for info in forbidden_info
            if info is not None and isinstance(info, str) and info.strip()
        ]

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


__all__ = ["NarrationLeakValidator", "LeakSeverity", "ForbiddenNarrationFact"]

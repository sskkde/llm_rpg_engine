from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, func, desc
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import (
    SessionModel,
    SessionNPCStateModel,
    NPCTemplateModel,
    NPCRelationshipMemoryModel,
    UserModel,
)
from ..storage.repositories import (
    SessionRepository,
    SessionNPCStateRepository,
    NPCTemplateRepository,
    NPCRelationshipMemoryRepository,
)
from ..core.projections import (
    project_content_public_status,
    resolve_content_public_visibility,
)
from .auth import get_current_active_user

router = APIRouter(prefix="/player", tags=["player"])


class RelationshipItem(BaseModel):
    npc_id: str
    npc_name: str
    trust_score: int
    respect_score: int
    fear_score: int
    last_interaction_turn: Optional[int] = None


class RelationshipListResponse(BaseModel):
    session_id: str
    relationships: List[RelationshipItem]
    total: int


class InteractionHistoryItem(BaseModel):
    turn: int
    content: str
    impact: Optional[dict] = None


class RelationshipDetailResponse(BaseModel):
    npc_id: str
    npc_name: str
    npc_role: Optional[str] = None
    npc_public_identity: Optional[str] = None
    trust_score: int
    suspicion_score: int
    respect_score: int
    fear_score: int
    status_flags: dict
    interaction_history: List[InteractionHistoryItem] = []


class TrustSummary(BaseModel):
    npc_id: str
    npc_name: str
    trust_score: int


class RelationshipSummaryResponse(BaseModel):
    total_npcs: int
    highest_trust: Optional[TrustSummary] = None
    lowest_trust: Optional[TrustSummary] = None
    average_trust: float
    average_respect: float


_VALID_SORT_FIELDS = frozenset({"trust", "respect", "fear", "last_interaction"})


def _resolve_npc_name(npc_repo: NPCTemplateRepository, npc_template_id: str) -> str:
    template = npc_repo.get_by_id(npc_template_id)
    return template.name if template else "Unknown"


def _extract_respect_fear(status_flags) -> tuple:
    if not isinstance(status_flags, dict):
        return 50, 0
    return status_flags.get("respect_score", 50), status_flags.get("fear_score", 0)


def _get_last_interaction_turn(
    db: Session, session_id: str, npc_template_id: str
) -> Optional[int]:
    row = (
        db.query(func.max(NPCRelationshipMemoryModel.created_turn))
        .filter(
            NPCRelationshipMemoryModel.session_id == session_id,
            or_(
                and_(
                    NPCRelationshipMemoryModel.npc_id == npc_template_id,
                    NPCRelationshipMemoryModel.target_id == "player",
                ),
                and_(
                    NPCRelationshipMemoryModel.npc_id == "player",
                    NPCRelationshipMemoryModel.target_id == npc_template_id,
                ),
            ),
        )
        .scalar()
    )
    return row


@router.get(
    "/sessions/{session_id}/relationships",
    response_model=RelationshipListResponse,
)
def list_relationships(
    session_id: str,
    sort: str = Query(
        default="trust",
        description="Sort field: trust, respect, fear, or last_interaction",
    ),
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if sort not in _VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort field: '{sort}'. Valid: trust, respect, fear, last_interaction",
        )

    content_visibility = resolve_content_public_visibility(db, session)
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    if content_visibility is not None:
        npc_states = [
            row for row in npc_states
            if row.npc_template_id in content_visibility.known_npc_template_ids
        ]

    npc_repo = NPCTemplateRepository(db)

    relationships: List[RelationshipItem] = []
    for s in npc_states:
        respect, fear = _extract_respect_fear(s.status_flags)
        last_turn = _get_last_interaction_turn(db, session_id, s.npc_template_id)
        relationships.append(
            RelationshipItem(
                npc_id=s.npc_template_id,
                npc_name=_resolve_npc_name(npc_repo, s.npc_template_id),
                trust_score=s.trust_score,
                respect_score=respect,
                fear_score=fear,
                last_interaction_turn=last_turn,
            )
        )

    sort_desc = sort != "last_interaction"
    key_map = {
        "trust": lambda r: r.trust_score,
        "respect": lambda r: r.respect_score,
        "fear": lambda r: r.fear_score,
        "last_interaction": lambda r: r.last_interaction_turn
        if r.last_interaction_turn is not None
        else -1,
    }
    relationships.sort(key=key_map[sort], reverse=sort_desc)

    return RelationshipListResponse(
        session_id=session_id,
        relationships=relationships,
        total=len(relationships),
    )


@router.get(
    "/sessions/{session_id}/relationships/summary",
    response_model=RelationshipSummaryResponse,
)
def relationship_summary(
    session_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    content_visibility = resolve_content_public_visibility(db, session)
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    if content_visibility is not None:
        npc_states = [
            row for row in npc_states
            if row.npc_template_id in content_visibility.known_npc_template_ids
        ]

    if not npc_states:
        return RelationshipSummaryResponse(
            total_npcs=0,
            highest_trust=None,
            lowest_trust=None,
            average_trust=0.0,
            average_respect=0.0,
        )

    npc_repo = NPCTemplateRepository(db)

    trust_scores: List[int] = []
    respect_scores: List[int] = []
    best: Optional[TrustSummary] = None
    worst: Optional[TrustSummary] = None

    for s in npc_states:
        trust = s.trust_score
        respect, _ = _extract_respect_fear(s.status_flags)
        trust_scores.append(trust)
        respect_scores.append(respect)

        name = _resolve_npc_name(npc_repo, s.npc_template_id)
        entry = TrustSummary(npc_id=s.npc_template_id, npc_name=name, trust_score=trust)
        if best is None or trust > best.trust_score:
            best = entry
        if worst is None or trust < worst.trust_score:
            worst = entry

    avg_trust = sum(trust_scores) / len(trust_scores)
    avg_respect = sum(respect_scores) / len(respect_scores)

    return RelationshipSummaryResponse(
        total_npcs=len(npc_states),
        highest_trust=best,
        lowest_trust=worst,
        average_trust=round(avg_trust, 2),
        average_respect=round(avg_respect, 2),
    )


@router.get(
    "/sessions/{session_id}/relationships/{npc_id}",
    response_model=RelationshipDetailResponse,
)
def get_relationship_detail(
    session_id: str,
    npc_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    content_visibility = resolve_content_public_visibility(db, session)
    if (
        content_visibility is not None
        and npc_id not in content_visibility.known_npc_template_ids
    ):
        raise HTTPException(status_code=404, detail="NPC not found")

    npc_state_repo = SessionNPCStateRepository(db)
    npc_state = npc_state_repo.get_by_session_and_npc(session_id, npc_id)

    npc_repo = NPCTemplateRepository(db)
    npc_template = npc_repo.get_by_id(npc_id)

    if not npc_state and not npc_template:
        raise HTTPException(status_code=404, detail="NPC not found")

    if not npc_state:
        raise HTTPException(status_code=404, detail="No relationship data for this NPC")

    respect, fear = _extract_respect_fear(npc_state.status_flags or {})

    if content_visibility is not None:
        # Relationship-memory text/impact is not in the content_v1 public whitelist.
        history = []
        public_status_flags = project_content_public_status(npc_state.status_flags)
    else:
        raw_memories = (
            db.query(NPCRelationshipMemoryModel)
            .filter(
                NPCRelationshipMemoryModel.session_id == session_id,
                or_(
                    and_(
                        NPCRelationshipMemoryModel.npc_id == npc_id,
                        NPCRelationshipMemoryModel.target_id == "player",
                    ),
                    and_(
                        NPCRelationshipMemoryModel.npc_id == "player",
                        NPCRelationshipMemoryModel.target_id == npc_id,
                    ),
                ),
            )
            .order_by(desc(NPCRelationshipMemoryModel.created_turn))
            .limit(10)
            .all()
        )
        history = [
            InteractionHistoryItem(
                turn=m.created_turn,
                content=m.content or "",
                impact=m.impact_json if isinstance(m.impact_json, dict) else None,
            )
            for m in reversed(raw_memories)
        ]
        public_status_flags = npc_state.status_flags or {}

    return RelationshipDetailResponse(
        npc_id=npc_id,
        npc_name=npc_template.name if npc_template else "Unknown",
        npc_role=npc_template.role_type if npc_template else None,
        npc_public_identity=npc_template.public_identity if npc_template else None,
        trust_score=npc_state.trust_score,
        suspicion_score=npc_state.suspicion_score,
        respect_score=respect,
        fear_score=fear,
        status_flags=public_status_flags,
        interaction_history=history,
    )

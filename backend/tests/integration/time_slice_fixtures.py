"""Shared fixtures for the phase-3 time-simulation turn tests.

The fixture builds a real, isolated slice session: the fixed micro world is
seeded through ``scripts.seed_time_slice``, a user/session is created, and the
baseline rows are deliberately left for the turn path to initialize (that is what
makes the "first turn defers its baseline into the final commit" contract
observable).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, List, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from llm_rpg.core import time_simulation_rules as rules
from llm_rpg.core.time_simulation import (
    PHASE3_NAMESPACE,
    SimulationRunState,
    decode_run_state,
    decode_step_conditions,
    is_phase3_conditions,
)
from llm_rpg.core.time_simulation_persistence import (
    SimulationContext,
    load_simulation_context,
)
from llm_rpg.models.action_contract import (
    IdleIntentParams,
    InspectIntentParams,
    MoveIntentParams,
    PlayerIntentV2,
)
from llm_rpg.scripts.seed_time_slice import seed_time_slice
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    EventLogModel,
    GameEventModel,
    SaveSlotModel,
    ScheduledEventModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    UserModel,
)
from llm_rpg.storage.repositories import SessionNPCStateRepository


def intent_stage_result(
    kind: str,
    *,
    target_location_id: Optional[str] = None,
    target_npc_id: Optional[str] = None,
) -> Any:
    """A fixed, accepted production contract for one player intent.

    This is the plan's "固定模型输出" seam: the *contract* is what a model would
    have to emit, so the response still travels the whole production chain
    (strict contract -> authorization -> domain adjudication -> database) without
    depending on a live model.
    """
    from llm_rpg.core import turn_service

    if kind == "idle":
        intent: Any = IdleIntentParams(action_type="idle")
    elif kind == "inspect":
        intent = InspectIntentParams(action_type="inspect", target_npc_id=target_npc_id)
    elif kind == "move":
        intent = MoveIntentParams(action_type="move", target_location_id=target_location_id)
    else:  # pragma: no cover - test programming error
        raise ValueError(f"unsupported test intent kind: {kind!r}")

    contract = PlayerIntentV2(contract_version=2, intent=intent)
    return turn_service.LLMStageResult(
        stage_name="input_intent",
        enabled=True,
        timeout=15.0,
        accepted=True,
        parsed_proposal=turn_service._player_intent_projection(contract),
        contract=contract,
    )


def patch_intent_stage(monkeypatch, result: Any) -> None:
    """Install one fixed input-intent result for the whole test."""
    from llm_rpg.core import turn_service

    monkeypatch.setattr(
        turn_service, "_execute_input_intent_stage", lambda **_kwargs: result
    )
    monkeypatch.setattr(turn_service, "_validate_explicit_llm_config", lambda _db: None)


class TimeSliceSession:
    """Ids and DB helpers for one seeded slice session."""

    def __init__(self, db: Session, ids: Dict[str, Any]):
        self.db = db
        self.ids = ids
        self.session_id: str = ids["session_id"]

    @property
    def world_id(self) -> str:
        return self.ids["world_id"]

    @property
    def location_ids(self) -> Dict[str, str]:
        return self.ids["location_ids"]

    @property
    def npc_ids(self) -> Dict[str, str]:
        return self.ids["npc_ids"]

    @property
    def item_ids(self) -> Dict[str, str]:
        return self.ids["item_ids"]

    def location_id(self, code: str) -> str:
        return self.location_ids[code]

    def location_code(self, location_id: Optional[str]) -> Optional[str]:
        for code, value in self.location_ids.items():
            if value == location_id:
                return code
        return None

    # -- reads -----------------------------------------------------------------

    def context(self, plan: Optional[Any] = None) -> SimulationContext:
        return load_simulation_context(self.db, self.session_id, plan=plan)

    def session_state(self) -> Optional[SessionStateModel]:
        return (
            self.db.query(SessionStateModel)
            .filter_by(session_id=self.session_id)
            .one_or_none()
        )

    def run_state(self) -> SimulationRunState:
        row = self.session_state()
        assert row is not None, "the turn must have initialized session_states"
        state = decode_run_state((row.global_flags_json or {}).get(PHASE3_NAMESPACE))
        assert state is not None, "the turn must have initialized the phase-3 cursor"
        return state

    def player_location_code(self) -> Optional[str]:
        row = self.session_state()
        assert row is not None
        return self.location_code(row.current_location_id)

    def npc_row(self, code: str) -> SessionNPCStateModel:
        row = SessionNPCStateRepository(self.db).get_by_session_and_npc(
            self.session_id, self.npc_ids[code]
        )
        assert row is not None, f"NPC {code} has no session state row"
        return row

    def npc_location_code(self, code: str) -> Optional[str]:
        return self.location_code(self.npc_row(code).current_location_id)

    def token_rows(self) -> List[SessionInventoryItemModel]:
        return (
            self.db.query(SessionInventoryItemModel)
            .filter_by(
                session_id=self.session_id,
                item_template_id=self.item_ids[rules.TOKEN_ITEM_CODE],
            )
            .all()
        )

    def token_owner(self) -> Any:
        rows = self.token_rows()
        assert len(rows) == 1, f"expected exactly one token row, found {len(rows)}"
        return rows[0]

    def scheduled_rows(self) -> List[ScheduledEventModel]:
        return (
            self.db.query(ScheduledEventModel)
            .filter_by(session_id=self.session_id)
            .all()
        )

    def step_statuses(self) -> Dict[str, str]:
        statuses: Dict[str, str] = {}
        for row in self.scheduled_rows():
            if not is_phase3_conditions(row.trigger_conditions_json):
                continue
            statuses[decode_step_conditions(row.trigger_conditions_json).step_key] = row.status
        return statuses

    def pending_step_keys(self) -> List[str]:
        return sorted(
            key for key, status in self.step_statuses().items() if status == "pending"
        )

    def game_events(self, event_type: Optional[str] = None) -> List[GameEventModel]:
        query = self.db.query(GameEventModel).filter_by(session_id=self.session_id)
        if event_type is not None:
            query = query.filter_by(event_type=event_type)
        return query.order_by(GameEventModel.occurred_at).all()

    def turn_result(self, turn_no: int) -> Dict[str, Any]:
        row = (
            self.db.query(EventLogModel)
            .filter_by(
                session_id=self.session_id, turn_no=turn_no, event_type="player_turn"
            )
            .one()
        )
        return row.result_json


@pytest.fixture
def time_slice(tmp_path) -> Iterator[TimeSliceSession]:
    """A fresh slice world plus one session with no baseline rows yet."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'phase3-turn.sqlite'}", poolclass=NullPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    suffix = uuid.uuid4().hex

    ids = seed_time_slice(db)
    user = UserModel(
        id=f"u-{suffix}",
        username=f"u-{suffix}",
        email=f"{suffix}@test.invalid",
        password_hash="x",
        is_admin=False,
    )
    slot = SaveSlotModel(id=f"slot-{suffix}", user_id=user.id, slot_number=1, name="存档")
    session = SessionModel(
        id=f"session-{suffix}",
        user_id=user.id,
        world_id=ids["world_id"],
        save_slot_id=slot.id,
        status="active",
    )
    db.add_all([user, slot, session])
    db.commit()

    payload = {**ids, "session_id": session.id}
    try:
        yield TimeSliceSession(db, payload)
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def run_turn(
    time_slice: TimeSliceSession,
    player_input: str,
    **kwargs: Any,
) -> Any:
    """Run one production turn against the slice session."""
    from llm_rpg.core import turn_service

    return turn_service.execute_turn_service(
        time_slice.db, time_slice.session_id, player_input, use_mock=True, **kwargs
    )

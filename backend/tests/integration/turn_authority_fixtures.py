"""Shared fixtures for the phase-2 turn authority integration tests.

These helpers build a small, real session (user/world/chapter/locations/NPCs/
session state) in an in-memory SQLite database and provide a provider that returns
*raw model JSON* per stage. That is what lets the integration tests drive the real
production entry point (``execute_turn_service``) with a malicious or malformed
model response and observe the committed database state.

Prompt-routing keys are chosen to match exactly one production prompt each:

* ``玩家输入``  -> input-intent stage
* ``世界上下文`` -> world stage
* ``场景上下文`` -> scene stage
* ``NPC 上下文`` -> NPC stage
* ``可见上下文`` -> narration stage
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from llm_rpg.llm.service import LLMService, MockLLMProvider
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    SaveSlotModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionStateModel,
    UserModel,
    WorldModel,
)

STAGE_KEYS = {
    "input_intent": "玩家输入",
    "world": "世界上下文",
    "scene": "场景上下文",
    "npc": "NPC 上下文",
    "narration": "可见上下文",
}


def contract_json(payload: Dict[str, Any]) -> str:
    """Serialize a production-contract payload the way a model would emit it."""
    return json.dumps(payload)


def player_intent_json(**intent: Any) -> str:
    return contract_json({"contract_version": 2, "intent": intent})


def world_tick_json(**fields: Any) -> str:
    body = {"contract_version": 2}
    body.update(fields)
    return contract_json(body)


def scene_event_json(**fields: Any) -> str:
    body = {"contract_version": 2}
    body.update(fields)
    return contract_json(body)


def npc_action_json(**fields: Any) -> str:
    body = {"contract_version": 2}
    body.update(fields)
    return contract_json(body)


def narration_json(text: str) -> str:
    return contract_json({"contract_version": 2, "text": text, "confidence": 1.0})


class AuthoritySession:
    """Ids and rows of the seeded session used by the authority tests."""

    def __init__(self, db: Session, ids: Dict[str, Any]):
        self.db = db
        self.ids = ids

    def __getattr__(self, item: str) -> Any:
        try:
            return self.ids[item]
        except KeyError as exc:  # pragma: no cover - programming error
            raise AttributeError(item) from exc


@pytest.fixture
def authority_session(tmp_path) -> Iterator[AuthoritySession]:
    """A fresh world with a public map, a concealed place and two NPCs."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'turn-authority.sqlite'}", poolclass=NullPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    suffix = uuid.uuid4().hex

    user = UserModel(
        id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid",
        password_hash="x", is_admin=False,
    )
    world = WorldModel(
        id=f"w-{suffix}", code=f"w-{suffix}", name="测试世界", genre="xianxia", status="active",
    )
    db.add_all([user, world])
    db.flush()

    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="第一章")
    slot = SaveSlotModel(id=f"slot-{suffix}", user_id=user.id, slot_number=1, name="存档")
    session = SessionModel(
        id=f"session-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id,
        current_chapter_id=chapter.id, status="active",
    )
    db.add_all([chapter, slot, session])
    db.flush()

    square = LocationModel(
        id=f"loc-square-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="square", name="宗门广场", tags=["public", "starting_point"],
        access_rules={"always_accessible": True},
    )
    hall = LocationModel(
        id=f"loc-hall-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="trial_hall", name="试炼堂", tags=["public", "quest_hub"],
        access_rules={"always_accessible": True},
    )
    vault = LocationModel(
        id=f"loc-vault-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="secret_vault", name="秘藏", tags=["secret"],
        access_rules={"always_accessible": True},
    )
    guide = NPCTemplateModel(
        id=f"npc-guide-{suffix}", world_id=world.id, code="guide", name="向导",
        role_type="guide", is_major_npc=True, personality="温和",
    )
    rival = NPCTemplateModel(
        id=f"npc-rival-{suffix}", world_id=world.id, code="rival", name="对手",
        role_type="guard", is_major_npc=True, personality="冷峻",
    )
    quest = QuestTemplateModel(
        id=f"quest-{suffix}", world_id=world.id, code="quest_main", name="主线任务",
        quest_type="main", visibility="visible",
    )
    db.add_all([square, hall, vault, guide, rival, quest])
    db.flush()

    guide_state = SessionNPCStateModel(
        id=f"snpc-guide-{suffix}", session_id=session.id, npc_template_id=guide.id,
        current_location_id=square.id, status_flags={"status": "alive", "mood": "calm"},
    )
    rival_state = SessionNPCStateModel(
        id=f"snpc-rival-{suffix}", session_id=session.id, npc_template_id=rival.id,
        current_location_id=square.id, status_flags={"status": "alive", "mood": "tense"},
    )
    db.add_all([guide_state, rival_state])

    db.add(SessionStateModel(
        id=f"ss-{suffix}", session_id=session.id, current_location_id=square.id,
        current_time="第1日 辰时", time_phase="辰时", active_mode="exploration",
        global_flags_json={},
    ))
    db.add(SessionPlayerStateModel(
        id=f"sps-{suffix}", session_id=session.id, realm_stage="炼气一层",
        hp=100, max_hp=100, stamina=100, spirit_power=100,
    ))
    db.commit()

    try:
        yield AuthoritySession(db, {
            "world": world,
            "session": session,
            "square": square,
            "hall": hall,
            "vault": vault,
            "guide": guide,
            "rival": rival,
            "quest": quest,
            "guide_state": guide_state,
            "rival_state": rival_state,
        })
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def patch_llm_provider(monkeypatch, responses: Dict[str, str]) -> MockLLMProvider:
    """Route raw model JSON to stages by prompt substring, through the real service.

    The provider is installed where the turn service builds its LLM service, so the
    response still travels the whole production chain (prompt -> provider -> strict
    contract -> authorization -> adjudication -> database).

    This is a plain function, not a context manager: it installs the patch through
    ``monkeypatch`` and the test keeps it for its whole body. (An earlier version was
    decorated with ``@contextmanager`` and returned without ``yield``, so the body
    never ran and the tests silently exercised the default mock provider instead of
    the injected raw JSON -- the tests passed for the wrong reason.)
    """
    from llm_rpg.core import turn_service

    # Longest/most specific keys first: MockLLMProvider returns the first key whose
    # text appears in the joined prompt, so a generic key must never shadow a
    # specific one.
    ordered = {key: responses[key] for key in STAGE_KEYS.values() if key in responses}
    for key, value in responses.items():
        if key not in ordered:
            ordered[key] = value

    provider = MockLLMProvider(responses=ordered)
    service = LLMService(provider=provider, db_session=None)
    monkeypatch.setattr(
        turn_service, "_create_llm_service_from_config", lambda *a, **k: service
    )
    monkeypatch.setattr(turn_service, "_validate_explicit_llm_config", lambda _db: None)
    return provider


def enable_all_stages(monkeypatch) -> None:
    """Turn on every LLM stage so the production chain runs end to end."""
    from llm_rpg.core import turn_service

    for name in (
        "_is_input_intent_stage_enabled",
        "_is_world_stage_enabled",
        "_is_scene_stage_enabled",
        "_is_npc_stage_enabled",
        "_is_narration_stage_enabled",
        "_is_memory_stage_enabled",
    ):
        monkeypatch.setattr(turn_service, name, lambda _db: True)


def committed_result_json(db: Session, session_id: str, turn_no: int) -> Dict[str, Any]:
    """Read the committed ``player_turn`` result snapshot for a turn."""
    from llm_rpg.storage.models import EventLogModel

    row = db.query(EventLogModel).filter_by(
        session_id=session_id, turn_no=turn_no, event_type="player_turn"
    ).one()
    return row.result_json


def memory_facts(db: Session, session_id: str) -> List[Any]:
    from llm_rpg.storage.models import MemoryFactModel

    return db.query(MemoryFactModel).filter_by(session_id=session_id).all()


def npc_beliefs(db: Session, session_id: str) -> List[Any]:
    from llm_rpg.storage.models import NPCBeliefModel

    return db.query(NPCBeliefModel).filter_by(session_id=session_id).all()


def game_events(db: Session, session_id: str) -> List[Any]:
    from llm_rpg.storage.models import GameEventModel

    return db.query(GameEventModel).filter_by(session_id=session_id).all()

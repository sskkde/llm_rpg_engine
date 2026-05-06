"""
Deterministic movement handler for player location transitions.

Resolves target locations by code/name/alias, validates access_rules
against current session state, and produces validated state deltas for
player.location_id, scene.location_id, and session_states.current_location_id.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..storage.models import (
    LocationModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
)
from ..storage.repositories import (
    LocationRepository,
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
)


# ---------------------------------------------------------------------------
# Alias / name → code mapping for seed locations
# ---------------------------------------------------------------------------
LOCATION_ALIASES: Dict[str, str] = {
    # square / 宗门广场
    "square": "square",
    "宗门": "square",
    "广场": "square",
    "宗门广场": "square",
    # trial_hall / 试炼堂
    "trial_hall": "trial_hall",
    "试炼堂": "trial_hall",
    "试炼": "trial_hall",
    # forest / 山林试炼区
    "forest": "forest",
    "山林": "forest",
    "山林试炼区": "forest",
    "林": "forest",
    # library / 藏经阁外区
    "library": "library",
    "藏经阁": "library",
    "藏经阁外区": "library",
    "经阁": "library",
    # herb_garden / 药园
    "herb_garden": "herb_garden",
    "药园": "herb_garden",
    "药": "herb_garden",
    # secret_gate / 秘境入口
    "secret_gate": "secret_gate",
    "秘境": "secret_gate",
    "秘境入口": "secret_gate",
    "石门": "secret_gate",
    # core / 异变核心
    "core": "core",
    "核心": "core",
    "异变核心": "core",
    # residence / 外门居所
    "residence": "residence",
    "居所": "residence",
    "外门居所": "residence",
    # cliff / 崖边祭坛
    "cliff": "cliff",
    "祭坛": "cliff",
    "崖边": "cliff",
    "崖边祭坛": "cliff",
    # inner_library / 藏经阁内区
    "inner_library": "inner_library",
    "内区": "inner_library",
    "藏经阁内区": "inner_library",
}


@dataclass
class MovementResult:
    """Result of a movement attempt."""

    success: bool
    new_location_id: Optional[str] = None
    new_location_code: Optional[str] = None
    new_location_name: Optional[str] = None
    blocked_reason: Optional[str] = None
    narration_hint: Optional[str] = None
    previous_location_id: Optional[str] = None


class MovementError(Exception):
    """Raised when movement processing fails due to system errors."""

    def __init__(self, message: str, session_id: Optional[str] = None):
        self.session_id = session_id
        super().__init__(message)


def _resolve_location_code(raw: str) -> Optional[str]:
    """Resolve a user-provided string to a canonical location code.

    Tries exact code match first, then alias lookup (case-insensitive).
    Returns None if no match found.
    """
    raw_lower = raw.strip().lower()

    # Direct alias / code hit
    if raw_lower in LOCATION_ALIASES:
        return LOCATION_ALIASES[raw_lower]

    return None


def _check_access_rules(
    access_rules: Dict[str, Any],
    player_state: Optional[SessionPlayerStateModel],
    session_state: Optional[SessionStateModel],
    session: SessionModel,
    global_flags: Dict[str, Any],
) -> tuple[bool, Optional[str]]:
    """Deterministically evaluate access_rules against current session state.

    Returns (allowed, reason_if_blocked).
    """
    if not access_rules:
        return True, None

    # always_accessible short-circuits everything
    if access_rules.get("always_accessible"):
        return True, None

    # player_level check
    player_level = access_rules.get("player_level")
    if player_level and player_state:
        level_hierarchy = {
            "outer_disciple": 1,
            "inner_disciple": 2,
            "core_disciple": 3,
            "elder": 4,
        }
        required = level_hierarchy.get(player_level, 0)
        current_realm = player_state.realm_stage or ""
        # Map realm_stage strings to numeric levels
        current_level = 0
        if "内门" in current_realm or "inner" in current_realm.lower():
            current_level = 2
        elif "核心" in current_realm or "core" in current_realm.lower():
            current_level = 3
        elif "长老" in current_realm or "elder" in current_realm.lower():
            current_level = 4
        elif "外门" in current_realm or "outer" in current_realm.lower() or "炼气" in current_realm:
            current_level = 1

        if current_level < required:
            return False, f"需要{player_level}身份才能进入此区域"

    # time_restrictions check
    time_restriction = access_rules.get("time_restrictions")
    if time_restriction == "daytime_only":
        time_phase = session_state.time_phase if session_state else None
        if time_phase:
            daytime_phases = {"辰时", "巳时", "午时", "未时", "申时"}
            if time_phase not in daytime_phases:
                return False, "此区域仅在白天开放"

    # chapter check
    required_chapter = access_rules.get("chapter")
    if required_chapter is not None:
        current_chapter_no = None
        if session.current_chapter_id:
            # We need to look up the chapter number; for now use global_flags
            current_chapter_no = global_flags.get("current_chapter_no")
        if current_chapter_no is None:
            # Default: chapter 1 content is accessible
            current_chapter_no = 1
        if current_chapter_no < required_chapter:
            return False, f"需要到达第{required_chapter}章才能进入此区域"

    # quest_trigger check
    quest_trigger = access_rules.get("quest_trigger")
    if quest_trigger is not None:
        if not global_flags.get(f"quest_trigger_{quest_trigger}"):
            return False, "需要触发特定事件才能进入此区域"

    # item_required check
    item_required = access_rules.get("item_required")
    if item_required is not None:
        if not global_flags.get(f"has_item_{item_required}"):
            return False, f"需要持有{item_required}才能进入此区域"

    # quest_completed check
    quest_completed = access_rules.get("quest_completed")
    if quest_completed is not None:
        if not global_flags.get(f"quest_completed_{quest_completed}"):
            return False, f"需要完成相关任务才能进入此区域"

    # boss_unlocked check
    boss_unlocked = access_rules.get("boss_unlocked")
    if boss_unlocked is True:
        if not global_flags.get("boss_unlocked"):
            return False, "需要先解锁Boss才能进入此区域"

    # combat_level check
    combat_level = access_rules.get("combat_level")
    if combat_level and player_state:
        combat_hierarchy = {
            "novice": 0,
            "apprentice": 1,
            "journeyman": 2,
            "expert": 3,
        }
        required_combat = combat_hierarchy.get(combat_level, 0)
        current_combat = combat_hierarchy.get(
            global_flags.get("combat_level", "novice"), 0
        )
        if current_combat < required_combat:
            return False, f"战斗等级不足，需要{combat_level}级别"

    # quest_requirement check (None means no requirement)
    quest_requirement = access_rules.get("quest_requirement")
    if quest_requirement is not None:
        if not global_flags.get(f"quest_active_{quest_requirement}"):
            return False, "需要接取相关任务才能进入此区域"

    # inner_restricted is informational, not a hard block by itself
    # (it's combined with player_level above)

    return True, None


def handle_movement(
    db: Session,
    session_id: str,
    target_location_code: str,
) -> MovementResult:
    """Process a player movement request deterministically.

    1. Resolve target location by code, name, or alias.
    2. Check access_rules against current session state.
    3. On success: update session_states.current_location_id.
    4. On failure: do NOT mutate location state.

    Args:
        db: SQLAlchemy database session.
        session_id: The active session ID.
        target_location_code: User-provided location identifier (code, name, or alias).

    Returns:
        MovementResult with success/failure details.

    Raises:
        MovementError: If session or world data is missing/invalid.
    """
    session_repo = SessionRepository(db)
    session_state_repo = SessionStateRepository(db)
    player_state_repo = SessionPlayerStateRepository(db)
    location_repo = LocationRepository(db)

    # 1. Load session
    session = session_repo.get_by_id(session_id)
    if session is None:
        raise MovementError(
            f"Session not found: {session_id}",
            session_id=session_id,
        )

    world_id = session.world_id

    # 2. Resolve target location code
    resolved_code = _resolve_location_code(target_location_code)
    if resolved_code is None:
        return MovementResult(
            success=False,
            blocked_reason=f"未找到名为「{target_location_code}」的地点",
            narration_hint="你环顾四周，但找不到那个地方。",
        )

    # 3. Look up location in DB
    target_location = location_repo.get_by_code(world_id, resolved_code)
    if target_location is None:
        return MovementResult(
            success=False,
            blocked_reason=f"地点「{resolved_code}」在当前世界中不存在",
            narration_hint="你试图前往那个地方，但它似乎并不在这个世界中。",
        )

    # 4. Load current session state
    session_state = session_state_repo.get_by_session(session_id)
    previous_location_id = session_state.current_location_id if session_state else None

    # 5. Load player state
    player_state = player_state_repo.get_by_session(session_id)

    # 6. Get global flags
    global_flags = {}
    if session_state and session_state.global_flags_json:
        global_flags = session_state.global_flags_json

    # 7. Check access_rules
    access_rules = target_location.access_rules or {}
    allowed, block_reason = _check_access_rules(
        access_rules, player_state, session_state, session, global_flags
    )

    if not allowed:
        return MovementResult(
            success=False,
            blocked_reason=block_reason,
            narration_hint=f"你试图前往{target_location.name}，但被阻挡了。",
            previous_location_id=previous_location_id,
        )

    # 8. Success: update session_states.current_location_id
    if session_state is not None:
        session_state_repo.update(session_state.id, {
            "current_location_id": target_location.id,
        })

    return MovementResult(
        success=True,
        new_location_id=target_location.id,
        new_location_code=target_location.code,
        new_location_name=target_location.name,
        previous_location_id=previous_location_id,
        narration_hint=f"你来到了{target_location.name}。",
    )

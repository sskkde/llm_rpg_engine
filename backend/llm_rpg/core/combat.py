"""
Light Turn-Based Combat Subsystem

A deterministic combat system for the LLM RPG Engine.
Features turn-based action resolution, event logging, and narration hooks.
"""

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class CombatStatus(str, Enum):
    ACTIVE = "active"
    PLAYER_WON = "player_won"
    PLAYER_LOST = "player_lost"
    ESCAPED = "escaped"
    DRAW = "draw"


class ActionType(str, Enum):
    ATTACK = "attack"
    DEFEND = "defend"
    SKILL = "skill"
    ITEM = "item"
    FLEE = "flee"


class ActorType(str, Enum):
    PLAYER = "player"
    NPC = "npc"
    ENVIRONMENT = "environment"


class CombatParticipant(BaseModel):
    actor_id: str = Field(..., description="Unique actor identifier")
    actor_type: ActorType = Field(..., description="Type of actor")
    name: str = Field(..., description="Display name")
    hp: int = Field(default=100, description="Current HP")
    max_hp: int = Field(default=100, description="Maximum HP")
    initiative: int = Field(default=0, description="Initiative roll")
    is_active: bool = Field(default=True, description="Can still act")


class CombatActionPayload(BaseModel):
    target_id: Optional[str] = Field(None, description="Target actor ID")
    skill_id: Optional[str] = Field(None, description="Skill ID if using skill")
    item_id: Optional[str] = Field(None, description="Item ID if using item")
    description: Optional[str] = Field(None, description="Player description of action")


class CombatAction(BaseModel):
    action_id: str = Field(..., description="Unique action ID")
    actor_id: str = Field(..., description="Actor who performed action")
    actor_type: ActorType = Field(..., description="Type of actor")
    action_type: ActionType = Field(..., description="Type of action")
    payload: CombatActionPayload = Field(default_factory=CombatActionPayload)
    resolution: Optional[Dict[str, Any]] = Field(None, description="Action resolution result")
    created_at: datetime = Field(default_factory=datetime.now)


class CombatRound(BaseModel):
    round_id: str = Field(..., description="Unique round ID")
    round_no: int = Field(..., description="Round number (1-based)")
    initiative_order: List[str] = Field(default_factory=list, description="Ordered actor IDs")
    actions: List[CombatAction] = Field(default_factory=list, description="Actions this round")
    is_complete: bool = Field(default=False, description="Round is finished")
    summary: Optional[str] = Field(None, description="Round summary narration")


class CombatSession(BaseModel):
    combat_id: str = Field(..., description="Unique combat ID")
    session_id: str = Field(..., description="Game session ID")
    location_id: Optional[str] = Field(None, description="Location where combat occurs")
    status: CombatStatus = Field(default=CombatStatus.ACTIVE)
    participants: Dict[str, CombatParticipant] = Field(default_factory=dict)
    rounds: List[CombatRound] = Field(default_factory=list)
    current_round_no: int = Field(default=0, description="Current round number")
    winner: Optional[str] = Field(None, description="Winner actor ID if resolved")
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = Field(None)
    narration_context: Optional[str] = Field(None, description="Context for LLM narration")


class CombatEvent(BaseModel):
    event_type: str = Field(..., description="Event type")
    combat_id: str = Field(..., description="Combat session ID")
    round_no: Optional[int] = Field(None)
    actor_id: Optional[str] = Field(None)
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class CombatManager:
    def __init__(self):
        self._sessions: Dict[str, CombatSession] = {}
        self._events: List[CombatEvent] = []

    def create_combat(
        self,
        combat_id: str,
        session_id: str,
        location_id: Optional[str] = None,
        participants: Optional[List[CombatParticipant]] = None,
        narration_context: Optional[str] = None
    ) -> CombatSession:
        participant_dict = {p.actor_id: p for p in (participants or [])}
        initiative_order = self._calculate_initiative(participant_dict)

        round_1 = CombatRound(
            round_id=f"{combat_id}_r1",
            round_no=1,
            initiative_order=initiative_order,
            actions=[],
            is_complete=False
        )

        combat = CombatSession(
            combat_id=combat_id,
            session_id=session_id,
            location_id=location_id,
            status=CombatStatus.ACTIVE,
            participants=participant_dict,
            rounds=[round_1],
            current_round_no=1,
            narration_context=narration_context
        )

        self._sessions[combat_id] = combat

        self._log_event(CombatEvent(
            event_type="combat_started",
            combat_id=combat_id,
            details={
                "session_id": session_id,
                "location_id": location_id,
                "participant_count": len(participant_dict),
                "participant_ids": list(participant_dict.keys())
            }
        ))

        return combat

    def get_combat(self, combat_id: str) -> Optional[CombatSession]:
        return self._sessions.get(combat_id)

    def get_current_round(self, combat_id: str) -> Optional[CombatRound]:
        combat = self._sessions.get(combat_id)
        if not combat or not combat.rounds:
            return None
        return combat.rounds[-1]

    def validate_action(
        self,
        combat_id: str,
        actor_id: str,
        action_type: ActionType,
        payload: CombatActionPayload
    ) -> Tuple[bool, Optional[str]]:
        combat = self._sessions.get(combat_id)
        if not combat:
            return False, "Combat session not found"

        if combat.status != CombatStatus.ACTIVE:
            return False, f"Combat is not active (status: {combat.status})"

        participant = combat.participants.get(actor_id)
        if not participant:
            return False, f"Actor {actor_id} is not in this combat"

        if not participant.is_active:
            return False, f"Actor {actor_id} cannot act (inactive)"

        if participant.hp <= 0:
            return False, f"Actor {actor_id} is defeated"

        if action_type == ActionType.ATTACK:
            if not payload.target_id:
                return False, "Attack requires a target"
            target = combat.participants.get(payload.target_id)
            if not target:
                return False, f"Target {payload.target_id} not found"
            if target.hp <= 0:
                return False, "Cannot attack a defeated target"

        elif action_type == ActionType.SKILL:
            if not payload.skill_id:
                return False, "Skill action requires a skill_id"
            if not payload.target_id:
                return False, "Skill requires a target"

        elif action_type == ActionType.ITEM:
            if not payload.item_id:
                return False, "Item action requires an item_id"

        current_round = self.get_current_round(combat_id)
        if current_round:
            already_acted = any(a.actor_id == actor_id for a in current_round.actions)
            if already_acted:
                return False, f"Actor {actor_id} has already acted this round"

        return True, None

    def commit_action(
        self,
        combat_id: str,
        actor_id: str,
        actor_type: ActorType,
        action_type: ActionType,
        payload: CombatActionPayload
    ) -> CombatAction:
        combat = self._sessions[combat_id]
        current_round = self.get_current_round(combat_id)

        action_id = f"{combat_id}_r{current_round.round_no}_{actor_id}_{len(current_round.actions)}"
        resolution = self._resolve_action(combat, actor_id, action_type, payload)

        action = CombatAction(
            action_id=action_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action_type=action_type,
            payload=payload,
            resolution=resolution
        )

        current_round.actions.append(action)

        self._log_event(CombatEvent(
            event_type="action_committed",
            combat_id=combat_id,
            round_no=current_round.round_no,
            actor_id=actor_id,
            details={
                "action_type": action_type,
                "target_id": payload.target_id,
                "resolution": resolution
            }
        ))

        self._apply_resolution(combat, resolution)

        # Process NPC counter-actions: NPCs that haven't acted this round
        # get a deterministic counter-attack.
        if combat.status == CombatStatus.ACTIVE:
            self._process_npc_counter_actions(combat, current_round)

        self._check_round_completion(combat, current_round)
        self._check_combat_end(combat)

        return action

    def end_combat(
        self,
        combat_id: str,
        status: CombatStatus,
        winner: Optional[str] = None
    ) -> CombatSession:
        combat = self._sessions[combat_id]
        if combat.status != CombatStatus.ACTIVE:
            return combat
        combat.status = status
        combat.winner = winner
        combat.ended_at = datetime.now()

        self._log_event(CombatEvent(
            event_type="combat_ended",
            combat_id=combat_id,
            details={
                "status": status,
                "winner": winner,
                "duration_rounds": combat.current_round_no
            }
        ))

        return combat

    def get_combat_events(
        self,
        combat_id: str,
        event_type: Optional[str] = None
    ) -> List[CombatEvent]:
        events = [e for e in self._events if e.combat_id == combat_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events

    def _calculate_initiative(
        self,
        participants: Dict[str, CombatParticipant]
    ) -> List[str]:
        sorted_parts = sorted(
            participants.values(),
            key=lambda p: (-p.initiative, p.actor_id)
        )
        return [p.actor_id for p in sorted_parts]

    def _resolve_action(
        self,
        combat: CombatSession,
        actor_id: str,
        action_type: ActionType,
        payload: CombatActionPayload
    ) -> Dict[str, Any]:
        actor = combat.participants[actor_id]
        resolution = {
            "actor_id": actor_id,
            "action_type": action_type,
            "success": True,
            "effects": []
        }

        if action_type == ActionType.ATTACK and payload.target_id:
            target = combat.participants.get(payload.target_id)
            if target:
                damage = 10
                resolution["target_id"] = payload.target_id
                resolution["damage"] = damage
                resolution["effects"].append({
                    "type": "damage",
                    "target": payload.target_id,
                    "amount": damage
                })

        elif action_type == ActionType.DEFEND:
            resolution["effects"].append({
                "type": "defense_boost",
                "target": actor_id,
                "duration": 1
            })

        elif action_type == ActionType.SKILL:
            skill_damage = 15
            resolution["skill_id"] = payload.skill_id
            resolution["damage"] = skill_damage
            if payload.target_id:
                resolution["effects"].append({
                    "type": "skill_damage",
                    "target": payload.target_id,
                    "amount": skill_damage,
                    "skill": payload.skill_id
                })

        elif action_type == ActionType.ITEM:
            resolution["item_id"] = payload.item_id
            heal_amount = 20
            resolution["healing"] = heal_amount
            resolution["effects"].append({
                "type": "heal",
                "target": actor_id,
                "amount": heal_amount,
                "item": payload.item_id
            })

        elif action_type == ActionType.FLEE:
            seed = f"{combat.combat_id}_{actor_id}_{combat.current_round_no}"
            hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)
            flee_success = (hash_val % 100) < 50

            resolution["success"] = flee_success
            result = "escaped" if flee_success else "failed"
            resolution["effects"].append({
                "type": "flee",
                "actor": actor_id,
                "result": result
            })

        return resolution

    def _apply_resolution(
        self,
        combat: CombatSession,
        resolution: Dict[str, Any]
    ):
        for effect in resolution.get("effects", []):
            effect_type = effect.get("type")
            target_id = effect.get("target")

            if effect_type in ("damage", "skill_damage"):
                if target_id and target_id in combat.participants:
                    target = combat.participants[target_id]
                    damage = effect.get("amount", 0)
                    target.hp = max(0, target.hp - damage)
                    if target.hp <= 0:
                        target.is_active = False

            elif effect_type == "heal":
                if target_id and target_id in combat.participants:
                    target = combat.participants[target_id]
                    heal = effect.get("amount", 0)
                    target.hp = min(target.max_hp, target.hp + heal)

            elif effect_type == "flee" and effect.get("result") == "escaped":
                combat.status = CombatStatus.ESCAPED
                combat.winner = None
                combat.ended_at = datetime.now()

    def _check_round_completion(self, combat: CombatSession, round: CombatRound):
        active_participants = [
            pid for pid, p in combat.participants.items()
            if p.is_active and p.hp > 0
        ]

        acted_participants = [a.actor_id for a in round.actions]

        if all(pid in acted_participants for pid in active_participants):
            round.is_complete = True

            self._log_event(CombatEvent(
                event_type="round_ended",
                combat_id=combat.combat_id,
                round_no=round.round_no,
                details={
                    "action_count": len(round.actions),
                    "participants_remaining": len(active_participants)
                }
            ))

            if combat.status == CombatStatus.ACTIVE:
                next_round = CombatRound(
                    round_id=f"{combat.combat_id}_r{round.round_no + 1}",
                    round_no=round.round_no + 1,
                    initiative_order=round.initiative_order.copy(),
                    actions=[],
                    is_complete=False
                )
                combat.rounds.append(next_round)
                combat.current_round_no = next_round.round_no

                self._log_event(CombatEvent(
                    event_type="round_started",
                    combat_id=combat.combat_id,
                    round_no=next_round.round_no,
                    details={}
                ))

    NPC_COUNTER_DAMAGE = 8

    def _process_npc_counter_actions(
        self,
        combat: CombatSession,
        current_round: CombatRound
    ):
        acted_ids = {a.actor_id for a in current_round.actions}
        npc_participants = [
            p for pid, p in combat.participants.items()
            if p.actor_type == ActorType.NPC and p.is_active and p.hp > 0
        ]
        pending_npcs = [p for p in npc_participants if p.actor_id not in acted_ids]

        for npc in pending_npcs:
            seed = f"{combat.combat_id}_{current_round.round_no}_{npc.actor_id}_counter"
            hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)

            valid_targets = [
                p for pid, p in combat.participants.items()
                if p.actor_id != npc.actor_id and p.is_active and p.hp > 0
            ]

            if not valid_targets:
                continue

            target = valid_targets[hash_val % len(valid_targets)]

            action_id = f"{combat.combat_id}_r{current_round.round_no}_{npc.actor_id}_{len(current_round.actions)}"
            resolution = {
                "actor_id": npc.actor_id,
                "action_type": "attack",
                "success": True,
                "target_id": target.actor_id,
                "damage": self.NPC_COUNTER_DAMAGE,
                "effects": [
                    {
                        "type": "damage",
                        "target": target.actor_id,
                        "amount": self.NPC_COUNTER_DAMAGE
                    }
                ]
            }

            action = CombatAction(
                action_id=action_id,
                actor_id=npc.actor_id,
                actor_type=ActorType.NPC,
                action_type=ActionType.ATTACK,
                payload=CombatActionPayload(
                    target_id=target.actor_id,
                    description="NPC counter-attack"
                ),
                resolution=resolution
            )

            current_round.actions.append(action)
            self._apply_resolution(combat, resolution)

            self._log_event(CombatEvent(
                event_type="npc_counter_action",
                combat_id=combat.combat_id,
                round_no=current_round.round_no,
                actor_id=npc.actor_id,
                details={
                    "action_type": "attack",
                    "target_id": target.actor_id,
                    "damage": self.NPC_COUNTER_DAMAGE,
                    "resolution": resolution
                }
            ))

    def _check_combat_end(self, combat: CombatSession):
        if combat.status != CombatStatus.ACTIVE:
            return

        player = combat.participants.get("player")
        if player and player.hp <= 0:
            self.end_combat(combat.combat_id, CombatStatus.PLAYER_LOST)
            return

        enemies = [
            p for pid, p in combat.participants.items()
            if p.actor_type == ActorType.NPC and p.hp > 0
        ]
        if not enemies:
            self.end_combat(combat.combat_id, CombatStatus.PLAYER_WON, winner="player")

    def _log_event(self, event: CombatEvent):
        self._events.append(event)

    def get_narration_context(
        self,
        combat_id: str,
        action: Optional[CombatAction] = None
    ) -> Dict[str, Any]:
        combat = self._sessions.get(combat_id)
        if not combat:
            return {}

        current_round = self.get_current_round(combat_id)

        def get_participant_name(pid: str) -> str:
            p = combat.participants.get(pid)
            return p.name if p else "Unknown"

        context = {
            "combat_id": combat_id,
            "round_no": current_round.round_no if current_round else 0,
            "status": combat.status,
            "participants": [
                {
                    "actor_id": p.actor_id,
                    "name": p.name,
                    "actor_type": p.actor_type,
                    "hp": p.hp,
                    "max_hp": p.max_hp,
                    "is_active": p.is_active
                }
                for p in combat.participants.values()
            ],
            "recent_actions": [
                {
                    "actor_name": get_participant_name(a.actor_id),
                    "action_type": a.action_type,
                    "target_name": get_participant_name(a.payload.target_id) if a.payload.target_id else None,
                    "resolution": a.resolution
                }
                for a in (current_round.actions[-3:] if current_round else [])
            ],
            "narration_prompt": combat.narration_context
        }

        if action:
            context["current_action"] = {
                "actor_name": get_participant_name(action.actor_id),
                "action_type": action.action_type,
                "description": action.payload.description,
                "resolution": action.resolution
            }

        return context


_combat_manager: Optional[CombatManager] = None


def get_combat_manager() -> CombatManager:
    global _combat_manager
    if _combat_manager is None:
        _combat_manager = CombatManager()
    return _combat_manager

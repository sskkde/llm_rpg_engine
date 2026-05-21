"""
ConflictResolver - Resolves action conflicts using scenario-specific rules.

5 conflict resolution scenarios:
1. NPC blocks player: NPC with higher priority blocks player action
2. Multi-character item competition: Priority + dexterity determines winner
3. Target fled causing attack failure: Verify target still reachable
4. Dialog interrupted by high-priority event: Priority comparison interrupts dialog
5. Quest stage conflict: Quest template's legal transitions reject invalid jumps

Called from ActionScheduler._resolve_conflict_group(), returns ConflictResult.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..models.common import ProposedAction, CommittedAction
from ..models.states import CanonicalState, NPCState, QuestState


@dataclass
class ConflictResult:
    should_block: bool
    blocked_actions: List[str] = field(default_factory=list)
    resolved_actions: List[CommittedAction] = field(default_factory=list)
    narration: str = ""


class ConflictResolver:

    def resolve_npc_block(
        self,
        player_action: ProposedAction,
        npc_action: ProposedAction,
        state: CanonicalState,
    ) -> ConflictResult:
        """NPC with higher priority blocks player action.

        Args:
            player_action: The player's proposed action
            npc_action: The NPC's proposed action that may block
            state: Current canonical state

        Returns:
            ConflictResult with blocked player action if NPC wins
        """
        if npc_action.priority <= player_action.priority:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        blocking_npc_types = {"move", "attack", "defend", "cast_skill", "wait"}
        blockable_player_types = {"move", "take_item", "attack", "cast_skill", "trigger_object"}

        if npc_action.action_type not in blocking_npc_types:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        if player_action.action_type not in blockable_player_types:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        npc_location = self._get_actor_location(npc_action.actor_id, state)
        player_location = self._get_actor_location(player_action.actor_id, state)

        if npc_location and player_location and npc_location != player_location:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        npc_name = self._get_actor_name(npc_action.actor_id, state)
        narration = f"{npc_name}以更高优先级行动，阻挡了你的{player_action.summary}"

        return ConflictResult(
            should_block=True,
            blocked_actions=[player_action.action_id],
            resolved_actions=[],
            narration=narration,
        )

    def resolve_item_competition(
        self,
        actions: List[ProposedAction],
        state: CanonicalState,
    ) -> ConflictResult:
        """Multiple characters compete for the same item. Winner by priority + dexterity.

        Args:
            actions: List of proposed actions competing for the same item
            state: Current canonical state

        Returns:
            ConflictResult with winner resolved and losers blocked
        """
        if not actions or len(actions) == 1:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        scored = []
        for action in actions:
            dexterity = self._get_actor_dexterity(action.actor_id, state)
            score = action.priority + dexterity * 0.1
            scored.append((score, action))

        scored.sort(key=lambda x: x[0], reverse=True)

        _, winner_action = scored[0]
        loser_actions = [a for _, a in scored[1:]]
        blocked_ids = [a.action_id for a in loser_actions]

        winner_name = self._get_actor_name(winner_action.actor_id, state)
        item_name = self._describe_targets(winner_action.target_ids)
        narration = f"{winner_name}抢先获得了{item_name}"

        return ConflictResult(
            should_block=True,
            blocked_actions=blocked_ids,
            resolved_actions=[],
            narration=narration,
        )

    def resolve_target_fled(
        self,
        action: ProposedAction,
        state: CanonicalState,
    ) -> ConflictResult:
        """Verify target is still reachable at execution time.

        Args:
            action: The proposed action (typically attack)
            state: Current canonical state

        Returns:
            ConflictResult with action blocked if target fled
        """
        target_requiring_types = {"attack", "talk", "ask", "follow", "give_item", "persuade", "cast_skill"}
        if action.action_type not in target_requiring_types:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        if not action.target_ids:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        actor_location = self._get_actor_location(action.actor_id, state)
        if not actor_location:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        for target_id in action.target_ids:
            target_location = self._get_actor_location(target_id, state)
            if target_location is not None and target_location != actor_location:
                target_name = self._get_actor_name(target_id, state)
                narration = f"{target_name}已经离开，你的行动落空了"
                return ConflictResult(
                    should_block=True,
                    blocked_actions=[action.action_id],
                    resolved_actions=[],
                    narration=narration,
                )

        return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

    def resolve_dialog_interrupt(
        self,
        action: ProposedAction,
        interrupt_event: ProposedAction,
    ) -> ConflictResult:
        """High-priority event interrupts current dialog.

        Args:
            action: The current dialog action (talk, ask, persuade)
            interrupt_event: The high-priority interrupting action

        Returns:
            ConflictResult with dialog blocked if interrupted
        """
        dialog_types = {"talk", "ask", "persuade"}

        if action.action_type not in dialog_types:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        if interrupt_event.priority <= action.priority:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        combat_types = {"attack", "cast_skill", "defend"}
        if interrupt_event.action_type in combat_types:
            narration = "战斗突然爆发，你的对话被打断了！"
        else:
            narration = "突发事件打断了你的对话"

        return ConflictResult(
            should_block=True,
            blocked_actions=[action.action_id],
            resolved_actions=[],
            narration=narration,
        )

    def resolve_quest_conflict(
        self,
        action: ProposedAction,
        quest_state: QuestState,
        quest_template: Optional[Dict[str, Any]] = None,
    ) -> ConflictResult:
        """Use quest template's legal transitions to reject invalid stage jumps.

        Args:
            action: The proposed quest_progress action
            quest_state: Current quest state
            quest_template: Quest template with legal_transitions list of [from, to] pairs

        Returns:
            ConflictResult with action blocked if transition is invalid
        """
        if action.action_type != "quest_progress":
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        if quest_template is None:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        legal_transitions = quest_template.get("legal_transitions", [])
        if not legal_transitions:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        target_stage = self._extract_quest_target_stage(action)
        if target_stage is None:
            return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        current_stage = quest_state.stage

        for transition in legal_transitions:
            if (
                isinstance(transition, (list, tuple))
                and len(transition) >= 2
                and transition[0] == current_stage
                and transition[1] == target_stage
            ):
                return ConflictResult(should_block=False, blocked_actions=[], resolved_actions=[], narration="")

        narration = f"任务阶段从'{current_stage}'到'{target_stage}'的跳转不被允许"
        return ConflictResult(
            should_block=True,
            blocked_actions=[action.action_id],
            resolved_actions=[],
            narration=narration,
        )

    def _get_actor_location(self, actor_id: str, state: CanonicalState) -> Optional[str]:
        if actor_id == "player":
            return state.player_state.location_id
        npc = state.npc_states.get(actor_id)
        if npc:
            return npc.location_id
        return None

    def _get_actor_name(self, actor_id: str, state: CanonicalState) -> str:
        if actor_id == "player":
            return state.player_state.name
        npc = state.npc_states.get(actor_id)
        if npc:
            return npc.name
        return actor_id

    def _get_actor_dexterity(self, actor_id: str, state: CanonicalState) -> float:
        """Dexterity 0.0-1.0. Player=0.5, NPC=1.0-fatigue, unknown=0.3."""
        if actor_id == "player":
            return 0.5
        npc = state.npc_states.get(actor_id)
        if npc:
            return 1.0 - npc.physical_state.fatigue
        return 0.3

    def _describe_targets(self, target_ids: List[str]) -> str:
        if not target_ids:
            return "目标物品"
        return "、".join(target_ids)

    def _extract_quest_target_stage(self, action: ProposedAction) -> Optional[str]:
        for delta in action.state_delta_candidates:
            if "to_stage" in delta:
                return str(delta["to_stage"])
            if "target_stage" in delta:
                return str(delta["target_stage"])
            if "next_stage" in delta:
                return str(delta["next_stage"])
        if action.target_ids:
            return action.target_ids[0]
        return None

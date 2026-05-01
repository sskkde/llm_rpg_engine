from typing import Any, Dict, List, Optional

from ..models.common import ProposedAction, CommittedAction
from ..models.states import CanonicalState, NPCState
from ..models.events import GameEvent


class ActionScheduler:
    
    def __init__(self):
        self._scene_triggers: Dict[str, Dict[str, Any]] = {}
        self._action_queue: List[ProposedAction] = []
        self._committed_actions: List[CommittedAction] = []
    
    def register_scene_trigger(
        self,
        trigger_id: str,
        conditions: List[str],
        event_candidate: str,
        priority: float = 0.5,
    ) -> None:
        self._scene_triggers[trigger_id] = {
            "conditions": conditions,
            "event_candidate": event_candidate,
            "priority": priority,
        }
    
    def collect_scene_triggers(
        self,
        state: CanonicalState,
    ) -> List[Dict[str, Any]]:
        triggered = []
        
        for trigger_id, trigger in self._scene_triggers.items():
            if self._evaluate_conditions(trigger["conditions"], state):
                triggered.append({
                    "trigger_id": trigger_id,
                    "event_candidate": trigger["event_candidate"],
                    "priority": trigger["priority"],
                })
        
        triggered.sort(key=lambda t: t["priority"], reverse=True)
        return triggered
    
    def _evaluate_conditions(
        self,
        conditions: List[str],
        state: CanonicalState,
    ) -> bool:
        return True
    
    def collect_actors(
        self,
        state: CanonicalState,
    ) -> List[str]:
        actors = ["player"]
        
        scene_state = state.current_scene_state
        actors.extend(scene_state.active_actor_ids)
        
        return list(set(actors))
    
    def resolve_priority(
        self,
        candidates: List[ProposedAction],
    ) -> List[ProposedAction]:
        return sorted(candidates, key=lambda c: c.priority, reverse=True)
    
    def add_proposed_action(self, action: ProposedAction) -> None:
        self._action_queue.append(action)
    
    def get_action_queue(self) -> List[ProposedAction]:
        return self._action_queue.copy()
    
    def clear_action_queue(self) -> None:
        self._action_queue.clear()
    
    def resolve_conflicts(
        self,
        actions: List[ProposedAction],
        state: CanonicalState,
    ) -> List[ProposedAction]:
        resolved = []
        conflicts = self._detect_conflicts(actions)
        
        for conflict_group in conflicts:
            if len(conflict_group) == 1:
                resolved.append(conflict_group[0])
            else:
                winner = self._resolve_conflict_group(conflict_group, state)
                resolved.append(winner)
        
        return resolved
    
    def _detect_conflicts(
        self,
        actions: List[ProposedAction],
    ) -> List[List[ProposedAction]]:
        groups = []
        used = set()
        
        for i, action in enumerate(actions):
            if i in used:
                continue
            
            group = [action]
            used.add(i)
            
            for j, other in enumerate(actions):
                if j in used:
                    continue
                
                if self._actions_conflict(action, other):
                    group.append(other)
                    used.add(j)
            
            groups.append(group)
        
        return groups
    
    def _actions_conflict(
        self,
        action1: ProposedAction,
        action2: ProposedAction,
    ) -> bool:
        if action1.target_ids and action2.target_ids:
            common_targets = set(action1.target_ids) & set(action2.target_ids)
            if common_targets:
                return True
        
        return False
    
    def _resolve_conflict_group(
        self,
        actions: List[ProposedAction],
        state: CanonicalState,
    ) -> ProposedAction:
        return max(actions, key=lambda a: a.priority)
    
    def commit_action(
        self,
        action: ProposedAction,
        state_deltas: List[Dict[str, Any]],
        event_ids: List[str],
    ) -> CommittedAction:
        committed = CommittedAction(
            action_id=action.action_id,
            actor_id=action.actor_id,
            action_type=action.action_type,
            target_ids=action.target_ids,
            summary=action.summary,
            visible_to_player=action.visible_to_player,
            state_deltas=state_deltas,
            event_ids=event_ids,
        )
        self._committed_actions.append(committed)
        return committed
    
    def get_committed_actions(self) -> List[CommittedAction]:
        return self._committed_actions.copy()
    
    def clear_committed_actions(self) -> None:
        self._committed_actions.clear()
    
    def schedule_npc_actions(
        self,
        npcs: List[NPCState],
        state: CanonicalState,
    ) -> List[ProposedAction]:
        proposed_actions = []
        
        for npc in npcs:
            if npc.current_goal_ids:
                action = ProposedAction(
                    action_id=f"auto_{npc.npc_id}_{state.world_state.current_time}",
                    actor_id=npc.npc_id,
                    action_type="auto",
                    summary=f"{npc.name} 继续执行当前目标",
                    priority=0.3,
                )
                proposed_actions.append(action)
        
        return proposed_actions
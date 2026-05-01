from typing import Any, Dict, List, Optional

from ..models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    LocationState,
    NPCState,
    QuestState,
    FactionState,
    RelationshipState,
    InventoryState,
    CombatState,
    KnowledgeState,
    ScheduleState,
)
from ..models.events import StateDelta


class StateStore:
    
    def __init__(self):
        self._states: Dict[str, CanonicalState] = {}
        self._snapshots: Dict[str, Dict[str, CanonicalState]] = {}
    
    def create_state(
        self,
        game_id: str,
        player_state: PlayerState,
        world_state: WorldState,
        scene_state: CurrentSceneState,
    ) -> CanonicalState:
        state = CanonicalState(
            player_state=player_state,
            world_state=world_state,
            current_scene_state=scene_state,
        )
        self._states[game_id] = state
        return state
    
    def get_state(self, game_id: str) -> Optional[CanonicalState]:
        return self._states.get(game_id)
    
    def update_state(self, game_id: str, state: CanonicalState) -> None:
        self._states[game_id] = state
    
    def delete_state(self, game_id: str) -> None:
        if game_id in self._states:
            del self._states[game_id]
    
    def snapshot(self, game_id: str, snapshot_id: str) -> None:
        state = self._states.get(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        if game_id not in self._snapshots:
            self._snapshots[game_id] = {}
        self._snapshots[game_id][snapshot_id] = state.model_copy(deep=True)
    
    def restore_snapshot(self, game_id: str, snapshot_id: str) -> Optional[CanonicalState]:
        if game_id not in self._snapshots:
            return None
        if snapshot_id not in self._snapshots[game_id]:
            return None
        
        state = self._snapshots[game_id][snapshot_id].model_copy(deep=True)
        self._states[game_id] = state
        return state


class CanonicalStateManager:
    
    def __init__(self):
        self._store = StateStore()
    
    def initialize_game(
        self,
        game_id: str,
        player_state: PlayerState,
        world_state: WorldState,
        scene_state: CurrentSceneState,
    ) -> CanonicalState:
        return self._store.create_state(
            game_id=game_id,
            player_state=player_state,
            world_state=world_state,
            scene_state=scene_state,
        )
    
    def get_state(self, game_id: str) -> Optional[CanonicalState]:
        return self._store.get_state(game_id)
    
    def apply_delta(self, game_id: str, delta: StateDelta) -> None:
        state = self._store.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        
        parts = delta.path.split(".")
        if len(parts) < 2:
            raise ValueError(f"Invalid delta path: {delta.path}")
        
        state_type = parts[0]
        state_id = parts[1] if len(parts) > 1 else None
        field_path = parts[2:] if len(parts) > 2 else []
        
        state_map = {
            "player": state.player_state,
            "world": state.world_state,
            "scene": state.current_scene_state,
            "locations": state.location_states,
            "npcs": state.npc_states,
            "quests": state.quest_states,
            "factions": state.faction_states,
            "relationships": state.relationship_states,
            "inventories": state.inventory_states,
            "combats": state.combat_states,
            "knowledge": state.knowledge_states,
            "schedules": state.schedule_states,
        }
        
        if state_type not in state_map:
            raise ValueError(f"Unknown state type: {state_type}")
        
        target = state_map[state_type]
        
        if isinstance(target, dict):
            if state_id is None or state_id not in target:
                raise ValueError(f"State not found: {delta.path}")
            target = target[state_id]
        
        if not field_path:
            raise ValueError(f"Invalid delta path: {delta.path}")
        
        parent = target
        for field in field_path[:-1]:
            if hasattr(parent, field):
                parent = getattr(parent, field)
            elif isinstance(parent, dict) and field in parent:
                parent = parent[field]
            else:
                raise ValueError(f"Field not found: {field} in {delta.path}")
        
        final_field = field_path[-1]
        
        if delta.operation == "set":
            if hasattr(parent, final_field):
                setattr(parent, final_field, delta.new_value)
            elif isinstance(parent, dict):
                parent[final_field] = delta.new_value
            else:
                raise ValueError(f"Cannot set field: {final_field}")
        elif delta.operation == "add":
            if hasattr(parent, final_field):
                current = getattr(parent, final_field)
                if isinstance(current, list):
                    current.append(delta.new_value)
                else:
                    raise ValueError(f"Cannot add to non-list field: {final_field}")
            elif isinstance(parent, dict) and final_field in parent:
                current = parent[final_field]
                if isinstance(current, list):
                    current.append(delta.new_value)
                else:
                    raise ValueError(f"Cannot add to non-list field: {final_field}")
            else:
                raise ValueError(f"Field not found: {final_field}")
        elif delta.operation == "remove":
            if hasattr(parent, final_field):
                current = getattr(parent, final_field)
                if isinstance(current, list) and delta.old_value in current:
                    current.remove(delta.old_value)
                else:
                    raise ValueError(f"Cannot remove from field: {final_field}")
            elif isinstance(parent, dict) and final_field in parent:
                current = parent[final_field]
                if isinstance(current, list) and delta.old_value in current:
                    current.remove(delta.old_value)
                else:
                    raise ValueError(f"Cannot remove from field: {final_field}")
            else:
                raise ValueError(f"Field not found: {final_field}")
        elif delta.operation == "increment":
            if hasattr(parent, final_field):
                current = getattr(parent, final_field)
                if isinstance(current, (int, float)):
                    setattr(parent, final_field, current + delta.new_value)
                else:
                    raise ValueError(f"Cannot increment non-numeric field: {final_field}")
            elif isinstance(parent, dict) and final_field in parent:
                current = parent[final_field]
                if isinstance(current, (int, float)):
                    parent[final_field] = current + delta.new_value
                else:
                    raise ValueError(f"Cannot increment non-numeric field: {final_field}")
            else:
                raise ValueError(f"Field not found: {final_field}")
        else:
            raise ValueError(f"Unknown operation: {delta.operation}")
    
    def apply_deltas(self, game_id: str, deltas: List[StateDelta]) -> None:
        for delta in deltas:
            self.apply_delta(game_id, delta)
    
    def get_player_state(self, game_id: str) -> Optional[PlayerState]:
        state = self._store.get_state(game_id)
        return state.player_state if state else None
    
    def get_world_state(self, game_id: str) -> Optional[WorldState]:
        state = self._store.get_state(game_id)
        return state.world_state if state else None
    
    def get_npc_state(self, game_id: str, npc_id: str) -> Optional[NPCState]:
        state = self._store.get_state(game_id)
        if state is None:
            return None
        return state.npc_states.get(npc_id)
    
    def get_location_state(self, game_id: str, location_id: str) -> Optional[LocationState]:
        state = self._store.get_state(game_id)
        if state is None:
            return None
        return state.location_states.get(location_id)
    
    def get_quest_state(self, game_id: str, quest_id: str) -> Optional[QuestState]:
        state = self._store.get_state(game_id)
        if state is None:
            return None
        return state.quest_states.get(quest_id)
    
    def get_faction_state(self, game_id: str, faction_id: str) -> Optional[FactionState]:
        state = self._store.get_state(game_id)
        if state is None:
            return None
        return state.faction_states.get(faction_id)
    
    def get_relationship_state(
        self,
        game_id: str,
        source_id: str,
        target_id: str,
    ) -> Optional[RelationshipState]:
        state = self._store.get_state(game_id)
        if state is None:
            return None
        
        key = f"{source_id}:{target_id}"
        return state.relationship_states.get(key)
    
    def update_player_state(self, game_id: str, player_state: PlayerState) -> None:
        state = self._store.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        state.player_state = player_state
    
    def update_npc_state(self, game_id: str, npc_state: NPCState) -> None:
        state = self._store.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        state.npc_states[npc_state.npc_id] = npc_state
    
    def update_world_state(self, game_id: str, world_state: WorldState) -> None:
        state = self._store.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        state.world_state = world_state
    
    def update_scene_state(self, game_id: str, scene_state: CurrentSceneState) -> None:
        state = self._store.get_state(game_id)
        if state is None:
            raise ValueError(f"State not found: {game_id}")
        state.current_scene_state = scene_state
    
    def save_snapshot(self, game_id: str, snapshot_id: str) -> None:
        self._store.snapshot(game_id, snapshot_id)
    
    def load_snapshot(self, game_id: str, snapshot_id: str) -> Optional[CanonicalState]:
        return self._store.restore_snapshot(game_id, snapshot_id)
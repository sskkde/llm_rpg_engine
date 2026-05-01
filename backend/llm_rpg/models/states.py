from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .events import WorldTime


class EntityState(BaseModel):
    entity_id: str = Field(..., description="实体唯一标识符")
    entity_type: str = Field(..., description="实体类型")
    updated_at: datetime = Field(default_factory=datetime.now, description="最后更新时间")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class PhysicalState(BaseModel):
    hp: int = Field(default=100, description="当前生命值")
    max_hp: int = Field(default=100, description="最大生命值")
    injured: bool = Field(default=False, description="是否受伤")
    fatigue: float = Field(default=0.0, ge=0.0, le=1.0, description="疲劳度")


class MentalState(BaseModel):
    fear: float = Field(default=0.0, ge=0.0, le=1.0, description="恐惧度")
    trust_toward_player: float = Field(default=0.5, ge=0.0, le=1.0, description="对玩家信任度")
    suspicion_toward_player: float = Field(default=0.0, ge=0.0, le=1.0, description="对玩家怀疑度")
    mood: str = Field(default="neutral", description="当前情绪状态")


class PlayerState(EntityState):
    entity_type: str = Field(default="player", frozen=True)
    name: str = Field(default="玩家", description="玩家名称")
    location_id: str = Field(..., description="当前位置ID")
    realm: str = Field(default="炼气一层", description="修为境界")
    spiritual_power: int = Field(default=100, description="灵力值")
    inventory_ids: List[str] = Field(default_factory=list, description="持有物品ID列表")
    active_quest_ids: List[str] = Field(default_factory=list, description="活跃任务ID列表")
    known_fact_ids: List[str] = Field(default_factory=list, description="已知事实ID列表")
    flags: Dict[str, bool] = Field(default_factory=dict, description="玩家标志位")


class WorldState(EntityState):
    entity_type: str = Field(default="world", frozen=True)
    world_id: str = Field(..., description="世界ID")
    current_time: WorldTime = Field(..., description="当前世界时间")
    global_flags: Dict[str, Any] = Field(default_factory=dict, description="全局标志位")
    active_world_events: List[str] = Field(default_factory=list, description="活跃世界事件ID列表")
    weather: str = Field(default="晴", description="天气")
    moon_phase: str = Field(default="满月", description="月相")


class CurrentSceneState(EntityState):
    entity_type: str = Field(default="scene", frozen=True)
    scene_id: str = Field(..., description="场景ID")
    location_id: str = Field(..., description="场景位置ID")
    active_actor_ids: List[str] = Field(default_factory=list, description="活跃角色ID列表")
    visible_object_ids: List[str] = Field(default_factory=list, description="可见物体ID列表")
    danger_level: float = Field(default=0.0, ge=0.0, le=1.0, description="危险等级")
    scene_phase: str = Field(default="exploration", description="场景阶段")
    blocked_paths: List[str] = Field(default_factory=list, description="被阻挡的路径")
    available_actions: List[str] = Field(default_factory=list, description="可用行动列表")


class LocationState(EntityState):
    entity_type: str = Field(default="location", frozen=True)
    location_id: str = Field(..., description="位置ID")
    name: str = Field(..., description="位置名称")
    status: str = Field(default="normal", description="位置状态")
    danger_level: float = Field(default=0.0, ge=0.0, le=1.0, description="危险等级")
    population_mood: str = Field(default="neutral", description="居民情绪")
    active_events: List[str] = Field(default_factory=list, description="活跃事件ID列表")
    known_to_player: bool = Field(default=False, description="玩家是否已知")
    last_updated_world_time: Optional[WorldTime] = Field(None, description="最后更新的世界时间")


class NPCState(EntityState):
    entity_type: str = Field(default="npc", frozen=True)
    npc_id: str = Field(..., description="NPC ID")
    name: str = Field(..., description="NPC名称")
    status: str = Field(default="alive", description="NPC状态（alive, dead, missing）")
    location_id: str = Field(..., description="当前位置ID")
    mood: str = Field(default="neutral", description="当前情绪")
    current_goal_ids: List[str] = Field(default_factory=list, description="当前目标ID列表")
    current_action: Optional[str] = Field(None, description="当前行动")
    physical_state: PhysicalState = Field(default_factory=PhysicalState, description="身体状态")
    mental_state: MentalState = Field(default_factory=MentalState, description="心理状态")


class QuestState(EntityState):
    entity_type: str = Field(default="quest", frozen=True)
    quest_id: str = Field(..., description="任务ID")
    name: str = Field(..., description="任务名称")
    status: str = Field(default="active", description="任务状态（active, completed, failed）")
    stage: str = Field(..., description="当前阶段")
    known_objectives: List[str] = Field(default_factory=list, description="已知目标")
    hidden_objectives: List[str] = Field(default_factory=list, description="隐藏目标")
    required_flags: Dict[str, Any] = Field(default_factory=dict, description="所需标志位")
    next_possible_stages: List[str] = Field(default_factory=list, description="可能的下一阶段")


class FactionState(EntityState):
    entity_type: str = Field(default="faction", frozen=True)
    faction_id: str = Field(..., description="阵营ID")
    name: str = Field(..., description="阵营名称")
    relationship_to_player: str = Field(default="unknown", description="与玩家关系")
    public_attitude: str = Field(default="neutral", description="公开态度")
    hidden_attitude: str = Field(default="neutral", description="隐藏态度")
    active_plans: List[str] = Field(default_factory=list, description="活跃计划")
    known_events: List[str] = Field(default_factory=list, description="已知事件")
    secret_knowledge: List[str] = Field(default_factory=list, description="秘密知识")


class RelationshipState(EntityState):
    entity_type: str = Field(default="relationship", frozen=True)
    source_actor_id: str = Field(..., description="关系发起者ID")
    target_actor_id: str = Field(..., description="关系目标ID")
    trust: int = Field(default=50, ge=0, le=100, description="信任度")
    respect: int = Field(default=50, ge=0, le=100, description="尊重度")
    fear: int = Field(default=0, ge=0, le=100, description="恐惧度")
    affection: int = Field(default=50, ge=0, le=100, description="好感度")
    suspicion: int = Field(default=0, ge=0, le=100, description="怀疑度")
    debt: int = Field(default=0, ge=0, le=100, description="恩惠度")
    hostility: int = Field(default=0, ge=0, le=100, description="敌意度")
    last_changed_turn: int = Field(default=0, description="最后变化回合")


class InventoryItem(BaseModel):
    item_id: str = Field(..., description="物品ID")
    name: str = Field(..., description="物品名称")
    quantity: int = Field(default=1, ge=1, description="数量")
    properties: Dict[str, Any] = Field(default_factory=dict, description="物品属性")


class InventoryState(EntityState):
    entity_type: str = Field(default="inventory", frozen=True)
    owner_id: str = Field(..., description="所有者ID")
    items: List[InventoryItem] = Field(default_factory=list, description="物品列表")
    capacity: int = Field(default=20, description="容量上限")


class CombatState(EntityState):
    entity_type: str = Field(default="combat", frozen=True)
    combat_id: str = Field(..., description="战斗ID")
    participants: List[str] = Field(default_factory=list, description="参与者ID列表")
    turn_order: List[str] = Field(default_factory=list, description="行动顺序")
    current_turn: int = Field(default=0, description="当前回合")
    status: str = Field(default="active", description="战斗状态")


class KnowledgeState(EntityState):
    entity_type: str = Field(default="knowledge", frozen=True)
    owner_id: str = Field(..., description="知识所有者ID")
    known_facts: List[str] = Field(default_factory=list, description="已知事实ID列表")
    known_rumors: List[str] = Field(default_factory=list, description="已知传闻ID列表")
    discovered_secrets: List[str] = Field(default_factory=list, description="发现的秘密ID列表")


class ScheduleEntry(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    activity: str = Field(..., description="计划活动")
    location_id: str = Field(..., description="计划位置")
    start_time: WorldTime = Field(..., description="开始时间")
    end_time: WorldTime = Field(..., description="结束时间")


class ScheduleState(EntityState):
    entity_type: str = Field(default="schedule", frozen=True)
    entries: List[ScheduleEntry] = Field(default_factory=list, description="日程条目")


class CanonicalState(BaseModel):
    player_state: PlayerState
    world_state: WorldState
    current_scene_state: CurrentSceneState
    location_states: Dict[str, LocationState] = Field(default_factory=dict)
    npc_states: Dict[str, NPCState] = Field(default_factory=dict)
    quest_states: Dict[str, QuestState] = Field(default_factory=dict)
    faction_states: Dict[str, FactionState] = Field(default_factory=dict)
    relationship_states: Dict[str, RelationshipState] = Field(default_factory=dict)
    inventory_states: Dict[str, InventoryState] = Field(default_factory=dict)
    combat_states: Dict[str, CombatState] = Field(default_factory=dict)
    knowledge_states: Dict[str, KnowledgeState] = Field(default_factory=dict)
    schedule_states: Dict[str, ScheduleState] = Field(default_factory=dict)
    
    def get_state_by_path(self, path: str) -> Any:
        parts = path.split(".")
        if len(parts) < 2:
            raise ValueError(f"Invalid path: {path}")
        
        state_type = parts[0]
        state_id = parts[1] if len(parts) > 1 else None
        field_path = parts[2:] if len(parts) > 2 else []
        
        state_map = {
            "player": self.player_state,
            "world": self.world_state,
            "scene": self.current_scene_state,
            "locations": self.location_states,
            "npcs": self.npc_states,
            "quests": self.quest_states,
            "factions": self.faction_states,
            "relationships": self.relationship_states,
            "inventories": self.inventory_states,
            "combats": self.combat_states,
            "knowledge": self.knowledge_states,
            "schedules": self.schedule_states,
        }
        
        if state_type not in state_map:
            raise ValueError(f"Unknown state type: {state_type}")
        
        target = state_map[state_type]
        
        if isinstance(target, dict):
            if state_id is None or state_id not in target:
                raise ValueError(f"State not found: {path}")
            target = target[state_id]
        
        for field in field_path:
            if hasattr(target, field):
                target = getattr(target, field)
            elif isinstance(target, dict) and field in target:
                target = target[field]
            else:
                raise ValueError(f"Field not found: {field} in {path}")
        
        return target
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class EventType(str, Enum):
    PLAYER_INPUT = "player_input"
    WORLD_TICK = "world_tick"
    SCENE_EVENT = "scene_event"
    NPC_DECISION = "npc_decision"
    NPC_ACTION = "npc_action"
    STATE_DELTA = "state_delta"
    MEMORY_WRITE = "memory_write"
    NARRATION = "narration"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


class GameEvent(BaseModel):
    event_id: str = Field(..., description="事件唯一标识符")
    event_type: EventType = Field(..., description="事件类型")
    turn_index: int = Field(..., description="所在回合索引")
    timestamp: datetime = Field(default_factory=datetime.now, description="事件发生时间")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class ParsedIntent(BaseModel):
    intent_type: str = Field(..., description="意图类型（如：move, talk, inspect, attack）")
    target: Optional[str] = Field(None, description="目标对象")
    risk_level: str = Field(default="low", description="风险等级（low, medium, high）")
    raw_tokens: List[str] = Field(default_factory=list, description="原始分词结果")


class PlayerInputEvent(GameEvent):
    event_type: EventType = Field(default=EventType.PLAYER_INPUT, frozen=True)
    actor_id: str = Field(default="player", description="行动者ID")
    raw_input: str = Field(..., description="玩家原始输入")
    parsed_intent: Optional[ParsedIntent] = Field(None, description="解析后的意图")


class WorldTime(BaseModel):
    calendar: str = Field(..., description="历法名称")
    season: str = Field(..., description="季节")
    day: int = Field(..., description="日")
    period: str = Field(..., description="时段（如：辰时、酉时）")
    
    def __str__(self) -> str:
        return f"{self.calendar} {self.season} 第{self.day}日 {self.period}"


class WorldTickEvent(GameEvent):
    event_type: EventType = Field(default=EventType.WORLD_TICK, frozen=True)
    time_before: WorldTime = Field(..., description="推进前时间")
    time_after: WorldTime = Field(..., description="推进后时间")
    affected_regions: List[str] = Field(default_factory=list, description="受影响区域ID列表")
    summary: str = Field(..., description="时间推进摘要")


class SceneEvent(GameEvent):
    event_type: EventType = Field(default=EventType.SCENE_EVENT, frozen=True)
    scene_id: str = Field(..., description="场景ID")
    trigger: str = Field(..., description="触发条件描述")
    summary: str = Field(..., description="事件摘要")
    visible_to_player: bool = Field(default=True, description="玩家是否可见")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要度（0-1）")
    affected_entities: List[str] = Field(default_factory=list, description="受影响实体ID列表")


class NPCDecisionEvent(GameEvent):
    event_type: EventType = Field(default=EventType.NPC_DECISION, frozen=True)
    npc_id: str = Field(..., description="NPC ID")
    perspective_id: str = Field(..., description="使用的视角ID")
    available_knowledge: List[str] = Field(default_factory=list, description="NPC可获得的知识")
    decision: str = Field(..., description="决策结果")
    reason_summary: str = Field(..., description="决策原因摘要")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="决策置信度")
    considered_alternatives: List[str] = Field(default_factory=list, description="考虑过的备选方案")


class NPCActionEvent(GameEvent):
    event_type: EventType = Field(default=EventType.NPC_ACTION, frozen=True)
    npc_id: str = Field(..., description="NPC ID")
    action_type: str = Field(..., description="行动类型（如：intervene, attack, talk）")
    target: Optional[str] = Field(None, description="目标实体ID")
    summary: str = Field(..., description="行动摘要")
    visible_to_player: bool = Field(default=True, description="玩家是否可见")
    state_delta_ids: List[str] = Field(default_factory=list, description="关联的状态变化ID列表")


class StateDelta(BaseModel):
    path: str = Field(..., description="状态路径（如：npc_states.npc_lingyue.mood）")
    old_value: Any = Field(..., description="旧值")
    new_value: Any = Field(..., description="新值")
    operation: str = Field(default="set", description="操作类型（set, add, remove, increment）")


class StateDeltaEvent(GameEvent):
    event_type: EventType = Field(default=EventType.STATE_DELTA, frozen=True)
    deltas: List[StateDelta] = Field(..., description="状态变化列表")
    validated: bool = Field(default=False, description="是否已通过验证")
    validator_ids: List[str] = Field(default_factory=list, description="通过的验证器ID列表")


class MemoryTarget(BaseModel):
    owner_type: str = Field(..., description="所有者类型（npc, world, faction）")
    owner_id: str = Field(..., description="所有者ID")
    memory_id: str = Field(..., description="记忆ID")
    memory_type: str = Field(default="episodic", description="记忆类型")


class MemoryWriteEvent(GameEvent):
    event_type: EventType = Field(default=EventType.MEMORY_WRITE, frozen=True)
    memory_targets: List[MemoryTarget] = Field(..., description="记忆写入目标列表")


class NarrationEvent(GameEvent):
    event_type: EventType = Field(default=EventType.NARRATION, frozen=True)
    visible_context_id: str = Field(..., description="使用的可见上下文ID")
    text: str = Field(..., description="生成的叙事文本")
    hidden_info_leaked: bool = Field(default=False, description="是否泄露了隐藏信息")
    style_tags: List[str] = Field(default_factory=list, description="文风标签")
    tone: Optional[str] = Field(None, description="语调")


class TurnTransaction(BaseModel):
    transaction_id: str = Field(..., description="事务唯一标识符")
    session_id: str = Field(..., description="会话ID")
    game_id: str = Field(..., description="游戏存档ID")
    turn_index: int = Field(..., description="回合索引")
    world_time_before: WorldTime = Field(..., description="回合开始前世界时间")
    world_time_after: Optional[WorldTime] = Field(None, description="回合结束后世界时间")
    player_input: str = Field(..., description="玩家原始输入")
    event_ids: List[str] = Field(default_factory=list, description="包含的事件ID列表")
    status: TransactionStatus = Field(default=TransactionStatus.PENDING, description="事务状态")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    committed_at: Optional[datetime] = Field(None, description="提交时间")
    
    def add_event(self, event_id: str) -> None:
        if event_id not in self.event_ids:
            self.event_ids.append(event_id)
    
    def commit(self) -> None:
        self.status = TransactionStatus.COMMITTED
        self.committed_at = datetime.now()
    
    def rollback(self) -> None:
        self.status = TransactionStatus.ROLLED_BACK


AnyGameEvent = Union[
    PlayerInputEvent,
    WorldTickEvent,
    SceneEvent,
    NPCDecisionEvent,
    NPCActionEvent,
    StateDeltaEvent,
    MemoryWriteEvent,
    NarrationEvent,
]
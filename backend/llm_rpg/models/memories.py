from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"
    GOAL = "goal"
    TRAUMA = "trauma"
    RUMOR = "rumor"
    SECRET = "secret"


class MemorySourceType(str, Enum):
    DIRECT_OBSERVATION = "direct_observation"
    TOLD_BY_OTHER = "told_by_other"
    INFERENCE = "inference"
    RUMOR = "rumor"
    SYSTEM = "system"


class Memory(BaseModel):
    memory_id: str = Field(..., description="记忆唯一标识符")
    owner_type: str = Field(..., description="所有者类型（npc, world, faction）")
    owner_id: str = Field(..., description="所有者ID")
    memory_type: MemoryType = Field(..., description="记忆类型")
    content: str = Field(..., description="记忆内容")
    source_event_ids: List[str] = Field(default_factory=list, description="来源事件ID列表")
    entities: List[str] = Field(default_factory=list, description="相关实体ID列表")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要度")
    emotional_weight: float = Field(default=0.0, ge=-1.0, le=1.0, description="情感权重")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    current_strength: float = Field(default=1.0, ge=0.0, le=1.0, description="当前强度")
    decay_rate: float = Field(default=0.01, ge=0.0, description="衰减率")
    recall_count: int = Field(default=0, description="回忆次数")
    created_turn: int = Field(..., description="创建回合")
    last_accessed_turn: int = Field(..., description="最后访问回合")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class NPCProfile(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    name: str = Field(..., description="NPC名称")
    role: str = Field(default="", description="角色定位")
    true_identity: Optional[str] = Field(None, description="真实身份")
    personality: List[str] = Field(default_factory=list, description="性格特征列表")
    speech_style: Dict[str, Any] = Field(default_factory=dict, description="说话风格")
    core_goals: List[str] = Field(default_factory=list, description="核心目标")


class Belief(BaseModel):
    belief_id: str = Field(..., description="信念ID")
    content: str = Field(..., description="信念内容")
    belief_type: str = Field(default="fact", description="信念类型（fact, suspicion, inference, rumor）")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    truth_status: str = Field(default="unknown", description="真实状态（true, false, partially_true, unknown）")
    source: MemorySourceType = Field(default=MemorySourceType.DIRECT_OBSERVATION, description="来源类型")
    source_event_ids: List[str] = Field(default_factory=list, description="来源事件ID列表")
    last_updated_turn: int = Field(..., description="最后更新回合")


class NPCBeliefState(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    beliefs: List[Belief] = Field(default_factory=list, description="信念列表")


class NPCPrivateMemory(BaseModel):
    memory_id: str = Field(..., description="记忆ID")
    owner_id: str = Field(..., description="NPC ID")
    memory_type: MemoryType = Field(default=MemoryType.EPISODIC, description="记忆类型")
    content: str = Field(..., description="记忆内容")
    source_event_ids: List[str] = Field(default_factory=list, description="来源事件ID列表")
    emotional_weight: float = Field(default=0.0, ge=-1.0, le=1.0, description="情感权重")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要度")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    created_turn: int = Field(..., description="创建回合")
    last_accessed_turn: int = Field(..., description="最后访问回合")
    recall_count: int = Field(default=0, description="回忆次数")
    current_strength: float = Field(default=1.0, ge=0.0, le=1.0, description="当前强度")


class RelationshipMemoryEntry(BaseModel):
    content: str = Field(..., description="记忆内容")
    impact: Dict[str, int] = Field(default_factory=dict, description="影响（trust, respect, fear等）")
    source_event_ids: List[str] = Field(default_factory=list, description="来源事件ID列表")
    current_strength: float = Field(default=1.0, ge=0.0, le=1.0, description="当前强度")


class NPCRelationshipMemory(BaseModel):
    owner_id: str = Field(..., description="NPC ID")
    target_id: str = Field(..., description="目标ID")
    relationship_memory: List[RelationshipMemoryEntry] = Field(default_factory=list, description="关系记忆列表")


class PerceivedEvent(BaseModel):
    turn: int = Field(..., description="回合")
    summary: str = Field(..., description="事件摘要")
    perception_type: str = Field(default="direct_observation", description="感知类型")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要度")


class NPCRecentContext(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    recent_perceived_events: List[PerceivedEvent] = Field(default_factory=list, description="最近感知事件")


class Secret(BaseModel):
    secret_id: str = Field(..., description="秘密ID")
    content: str = Field(..., description="秘密内容")
    willingness_to_reveal: float = Field(default=0.1, ge=0.0, le=1.0, description="愿意透露的程度")
    reveal_conditions: List[str] = Field(default_factory=list, description="透露条件")
    known_by: List[str] = Field(default_factory=list, description="已知者ID列表")


class NPCSecrets(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    secrets: List[Secret] = Field(default_factory=list, description="秘密列表")


class NPCKnowledgeState(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    known_facts: List[str] = Field(default_factory=list, description="已知事实ID列表")
    known_rumors: List[str] = Field(default_factory=list, description="已知传闻ID列表")
    known_secrets: List[str] = Field(default_factory=list, description="已知秘密ID列表")
    forbidden_knowledge: List[str] = Field(default_factory=list, description="禁止知识ID列表")


class NPCGoal(BaseModel):
    goal_id: str = Field(..., description="目标ID")
    description: str = Field(..., description="目标描述")
    priority: float = Field(default=0.5, ge=0.0, le=1.0, description="优先级")
    status: str = Field(default="active", description="状态")
    related_entities: List[str] = Field(default_factory=list, description="相关实体ID列表")


class NPCGoals(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    goals: List[NPCGoal] = Field(default_factory=list, description="目标列表")


class ForgetCurve(BaseModel):
    base_importance: float = Field(default=0.5, description="基础重要度")
    emotional_weight: float = Field(default=0.0, description="情感权重")
    relationship_impact: float = Field(default=0.0, description="关系影响")
    plot_relevance: float = Field(default=0.0, description="剧情相关度")
    recall_reinforcement: float = Field(default=0.0, description="回忆强化")
    time_decay: float = Field(default=0.0, description="时间衰减")


class NPCMemoryScope(BaseModel):
    npc_id: str = Field(..., description="NPC ID")
    profile: NPCProfile
    belief_state: NPCBeliefState
    private_memories: List[NPCPrivateMemory] = Field(default_factory=list, description="私有记忆列表")
    relationship_memories: List[NPCRelationshipMemory] = Field(default_factory=list, description="关系记忆列表")
    recent_context: NPCRecentContext
    secrets: NPCSecrets
    knowledge_state: NPCKnowledgeState
    goals: NPCGoals
    forget_curve: ForgetCurve = Field(default_factory=ForgetCurve, description="遗忘曲线参数")
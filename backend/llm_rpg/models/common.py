from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EntityReference(BaseModel):
    entity_id: str = Field(..., description="实体ID")
    entity_type: str = Field(..., description="实体类型")
    display_name: Optional[str] = Field(None, description="显示名称")


class TimeRange(BaseModel):
    start_turn: int = Field(..., description="开始回合")
    end_turn: int = Field(..., description="结束回合")


class ActionResult(BaseModel):
    success: bool = Field(..., description="是否成功")
    action_id: str = Field(..., description="行动ID")
    actor_id: str = Field(..., description="行动者ID")
    target_ids: List[str] = Field(default_factory=list, description="目标ID列表")
    effects: List[Dict[str, Any]] = Field(default_factory=list, description="效果列表")
    narrative: Optional[str] = Field(None, description="叙事文本")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class ProposedAction(BaseModel):
    action_id: str = Field(..., description="行动ID")
    actor_id: str = Field(..., description="行动者ID")
    action_type: str = Field(..., description="行动类型")
    target_ids: List[str] = Field(default_factory=list, description="目标ID列表")
    summary: str = Field(..., description="行动摘要")
    intention: str = Field(default="", description="意图")
    visible_to_player: bool = Field(default=True, description="玩家是否可见")
    hidden_motivation: Optional[str] = Field(None, description="隐藏动机")
    state_delta_candidates: List[Dict[str, Any]] = Field(default_factory=list, description="状态变化候选")
    priority: float = Field(default=0.5, ge=0.0, le=1.0, description="优先级")


class CommittedAction(BaseModel):
    action_id: str = Field(..., description="行动ID")
    actor_id: str = Field(..., description="行动者ID")
    action_type: str = Field(..., description="行动类型")
    target_ids: List[str] = Field(default_factory=list, description="目标ID列表")
    summary: str = Field(..., description="行动摘要")
    visible_to_player: bool = Field(default=True, description="玩家是否可见")
    state_deltas: List[Dict[str, Any]] = Field(default_factory=list, description="实际状态变化")
    event_ids: List[str] = Field(default_factory=list, description="生成的事件ID列表")


class ValidationCheck(BaseModel):
    check_name: str = Field(..., description="检查名称")
    passed: bool = Field(..., description="是否通过")
    reason: str = Field(default="", description="原因")
    severity: str = Field(default="error", description="严重程度")


class ValidationResult(BaseModel):
    is_valid: bool = Field(..., description="是否有效")
    checks: List[ValidationCheck] = Field(default_factory=list, description="检查结果列表")
    errors: List[str] = Field(default_factory=list, description="错误列表")
    warnings: List[str] = Field(default_factory=list, description="警告列表")


class ContextPack(BaseModel):
    context_id: str = Field(..., description="上下文ID")
    context_type: str = Field(..., description="上下文类型")
    owner_id: Optional[str] = Field(None, description="所有者ID")
    content: Dict[str, Any] = Field(default_factory=dict, description="上下文内容")
    included_memory_ids: List[str] = Field(default_factory=list, description="包含的记忆ID列表")
    excluded_memory_ids: List[str] = Field(default_factory=list, description="排除的记忆ID列表")
    exclusion_reasons: Dict[str, str] = Field(default_factory=dict, description="排除原因")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class MemoryQuery(BaseModel):
    query_text: str = Field(default="", description="查询文本")
    owner_id: Optional[str] = Field(None, description="所有者ID")
    owner_type: Optional[str] = Field(None, description="所有者类型")
    entity_ids: List[str] = Field(default_factory=list, description="相关实体ID列表")
    time_range: Optional[TimeRange] = Field(None, description="时间范围")
    importance_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="重要度阈值")
    memory_types: List[str] = Field(default_factory=list, description="记忆类型过滤")
    limit: int = Field(default=10, ge=1, description="返回数量限制")


class RetrievalResult(BaseModel):
    memory_id: str = Field(..., description="记忆ID")
    content: str = Field(..., description="内容")
    score: float = Field(..., description="综合得分")
    source: str = Field(default="", description="来源")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .events import WorldTime


class SummaryType(str, Enum):
    WORLD_CHRONICLE = "world_chronicle"
    SCENE_SUMMARY = "scene_summary"
    SESSION_SUMMARY = "session_summary"
    NPC_SUBJECTIVE = "npc_subjective"
    FACTION_SUMMARY = "faction_summary"
    PLAYER_JOURNEY = "player_journey"


class Summary(BaseModel):
    summary_id: str = Field(..., description="摘要唯一标识符")
    summary_type: SummaryType = Field(..., description="摘要类型")
    owner_type: Optional[str] = Field(None, description="所有者类型")
    owner_id: Optional[str] = Field(None, description="所有者ID")
    session_id: Optional[str] = Field(None, description="会话ID")
    scene_id: Optional[str] = Field(None, description="场景ID")
    start_turn: int = Field(..., description="开始回合")
    end_turn: int = Field(..., description="结束回合")
    time_range: Optional[Dict[str, Any]] = Field(None, description="时间范围")
    content: str = Field(..., description="摘要内容")
    key_event_ids: List[str] = Field(default_factory=list, description="关键事件ID列表")
    entities: List[str] = Field(default_factory=list, description="涉及实体ID列表")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要度")
    perspective: Optional[str] = Field(None, description="视角")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class WorldChronicle(Summary):
    summary_type: SummaryType = Field(default=SummaryType.WORLD_CHRONICLE, frozen=True)
    location_ids: List[str] = Field(default_factory=list, description="涉及位置ID列表")
    objective_facts: List[str] = Field(default_factory=list, description="客观事实列表")


class SceneSummary(Summary):
    summary_type: SummaryType = Field(default=SummaryType.SCENE_SUMMARY, frozen=True)
    scene_id: str = Field(..., description="场景ID")
    open_threads: List[str] = Field(default_factory=list, description="开放线索")
    scene_phase: str = Field(default="exploration", description="场景阶段")


class SessionSummary(Summary):
    summary_type: SummaryType = Field(default=SummaryType.SESSION_SUMMARY, frozen=True)
    session_id: str = Field(..., description="会话ID")
    player_actions: List[str] = Field(default_factory=list, description="玩家行动列表")
    major_events: List[str] = Field(default_factory=list, description="重大事件")


class EmotionalImpression(BaseModel):
    trust: float = Field(default=0.5, ge=0.0, le=1.0, description="信任度")
    suspicion: float = Field(default=0.0, ge=0.0, le=1.0, description="怀疑度")
    anxiety: float = Field(default=0.0, ge=0.0, le=1.0, description="焦虑度")
    affection: float = Field(default=0.5, ge=0.0, le=1.0, description="好感度")


class NPCSubjectiveSummary(Summary):
    summary_type: SummaryType = Field(default=SummaryType.NPC_SUBJECTIVE, frozen=True)
    npc_id: str = Field(..., description="NPC ID")
    subjective_summary: str = Field(..., description="主观摘要")
    emotional_impression: EmotionalImpression = Field(default_factory=EmotionalImpression, description="情感印象")
    memory_strength: float = Field(default=1.0, ge=0.0, le=1.0, description="记忆强度")
    distortion_level: float = Field(default=0.0, ge=0.0, le=1.0, description="扭曲程度")


class FactionSummary(Summary):
    summary_type: SummaryType = Field(default=SummaryType.FACTION_SUMMARY, frozen=True)
    faction_id: str = Field(..., description="阵营ID")
    known_events: List[str] = Field(default_factory=list, description="已知事件")
    strategic_concerns: List[str] = Field(default_factory=list, description="战略关注点")


class PlayerJourneySummary(Summary):
    summary_type: SummaryType = Field(default=SummaryType.PLAYER_JOURNEY, frozen=True)
    player_id: str = Field(..., description="玩家ID")
    chapter: str = Field(default="", description="章节名称")
    known_clues: List[str] = Field(default_factory=list, description="已知线索")
    unresolved_questions: List[str] = Field(default_factory=list, description="未解问题")
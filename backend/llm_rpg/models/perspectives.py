from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PerspectiveType(str, Enum):
    WORLD = "world"
    PLAYER = "player"
    NPC = "npc"
    FACTION = "faction"
    NARRATOR = "narrator"


class VisibilityLevel(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    RUMOR = "rumor"
    HIDDEN = "hidden"


class Perspective(BaseModel):
    perspective_id: str = Field(..., description="视角唯一标识符")
    perspective_type: PerspectiveType = Field(..., description="视角类型")
    owner_id: str = Field(..., description="视角所有者ID")
    description: str = Field(default="", description="视角描述")


class WorldPerspective(Perspective):
    perspective_type: PerspectiveType = Field(default=PerspectiveType.WORLD, frozen=True)
    visible_state_paths: List[str] = Field(default_factory=list, description="可见状态路径")
    hidden_state_paths: List[str] = Field(default_factory=list, description="隐藏状态路径")


class PlayerPerspective(Perspective):
    perspective_type: PerspectiveType = Field(default=PerspectiveType.PLAYER, frozen=True)
    known_facts: List[str] = Field(default_factory=list, description="已知事实ID列表")
    known_rumors: List[str] = Field(default_factory=list, description="已知传闻ID列表")
    visible_scene_ids: List[str] = Field(default_factory=list, description="可见场景ID列表")
    discovered_locations: List[str] = Field(default_factory=list, description="已发现位置ID列表")


class NPCPerspective(Perspective):
    perspective_type: PerspectiveType = Field(default=PerspectiveType.NPC, frozen=True)
    npc_id: str = Field(..., description="NPC ID")
    known_facts: List[str] = Field(default_factory=list, description="已知事实ID列表")
    believed_rumors: List[str] = Field(default_factory=list, description="相信的传闻ID列表")
    private_knowledge: List[str] = Field(default_factory=list, description="私有知识ID列表")
    secrets: List[str] = Field(default_factory=list, description="秘密ID列表")
    forbidden_knowledge: List[str] = Field(default_factory=list, description="禁止知识ID列表")


class FactionPerspective(Perspective):
    perspective_type: PerspectiveType = Field(default=PerspectiveType.FACTION, frozen=True)
    faction_id: str = Field(..., description="阵营ID")
    collective_knowledge: List[str] = Field(default_factory=list, description="集体知识ID列表")
    strategic_concerns: List[str] = Field(default_factory=list, description="战略关注点")
    active_plans: List[str] = Field(default_factory=list, description="活跃计划")


class NarratorPerspective(Perspective):
    perspective_type: PerspectiveType = Field(default=PerspectiveType.NARRATOR, frozen=True)
    base_perspective_id: str = Field(..., description="基础视角ID（通常是玩家视角）")
    style_requirements: Dict[str, Any] = Field(default_factory=dict, description="文风要求")
    tone: str = Field(default="neutral", description="语调")
    pacing: str = Field(default="normal", description="节奏")
    forbidden_info: List[str] = Field(default_factory=list, description="禁止泄露的信息")
    allowed_hints: List[str] = Field(default_factory=list, description="允许的暗示")


class VisibilityResult(BaseModel):
    is_visible: bool = Field(..., description="是否可见")
    visibility_level: VisibilityLevel = Field(..., description="可见性级别")
    content: Optional[Any] = Field(None, description="可见内容（可能经过过滤）")
    reason: str = Field(default="", description="可见性判断原因")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")


class FilteredContent(BaseModel):
    original_content: Any = Field(..., description="原始内容")
    filtered_content: Any = Field(..., description="过滤后内容")
    perspective_id: str = Field(..., description="使用的视角ID")
    filters_applied: List[str] = Field(default_factory=list, description="应用的过滤器")
    was_modified: bool = Field(default=False, description="是否被修改")
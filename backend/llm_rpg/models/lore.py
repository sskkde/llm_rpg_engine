from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LoreCategory(str, Enum):
    WORLD = "world"
    CULTIVATION_SYSTEM = "cultivation_system"
    LOCATION = "location"
    CHARACTER = "character"
    FACTION = "faction"
    ITEM = "item"
    MONSTER = "monster"
    HISTORY = "history"
    MAIN_PLOT = "main_plot"
    RULE = "rule"
    RUMOR = "rumor"


class LoreEntry(BaseModel):
    lore_id: str = Field(..., description="设定唯一标识符")
    title: str = Field(..., description="设定标题")
    category: LoreCategory = Field(..., description="设定类别")
    canonical_content: str = Field(..., description="权威内容（真实版本）")
    public_content: Optional[str] = Field(None, description="公开内容（公众版本）")
    rumor_versions: List[str] = Field(default_factory=list, description="传闻版本列表")
    known_by: List[str] = Field(default_factory=list, description="已知者ID列表")
    partial_known_by: List[str] = Field(default_factory=list, description="部分已知者ID列表")
    hidden_from_player_until: List[str] = Field(default_factory=list, description="玩家解锁条件")
    reveal_conditions: List[str] = Field(default_factory=list, description="揭示条件")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class WorldLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.WORLD, frozen=True)


class CultivationSystemLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.CULTIVATION_SYSTEM, frozen=True)
    realm_levels: List[str] = Field(default_factory=list, description="境界等级列表")
    breakthrough_conditions: Dict[str, Any] = Field(default_factory=dict, description="突破条件")


class LocationLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.LOCATION, frozen=True)
    location_id: str = Field(..., description="关联位置ID")
    historical_events: List[str] = Field(default_factory=list, description="历史事件")
    hidden_features: List[str] = Field(default_factory=list, description="隐藏特征")


class CharacterLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.CHARACTER, frozen=True)
    character_id: Optional[str] = Field(None, description="关联角色ID")
    true_identity: Optional[str] = Field(None, description="真实身份")
    background_story: str = Field(default="", description="背景故事")
    secrets: List[str] = Field(default_factory=list, description="秘密列表")


class FactionLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.FACTION, frozen=True)
    faction_id: str = Field(..., description="关联阵营ID")
    hierarchy: Dict[str, Any] = Field(default_factory=dict, description="组织架构")
    goals: List[str] = Field(default_factory=list, description="阵营目标")
    enemies: List[str] = Field(default_factory=list, description="敌对阵营")


class ItemLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.ITEM, frozen=True)
    item_id: Optional[str] = Field(None, description="关联物品ID")
    properties: Dict[str, Any] = Field(default_factory=dict, description="物品属性")
    history: str = Field(default="", description="物品历史")


class MonsterLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.MONSTER, frozen=True)
    monster_id: Optional[str] = Field(None, description="关联怪物ID")
    abilities: List[str] = Field(default_factory=list, description="能力列表")
    weaknesses: List[str] = Field(default_factory=list, description="弱点列表")
    habitat: str = Field(default="", description="栖息地")


class HistoryLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.HISTORY, frozen=True)
    time_period: str = Field(default="", description="时间时期")
    involved_entities: List[str] = Field(default_factory=list, description="涉及实体")
    consequences: List[str] = Field(default_factory=list, description="历史后果")


class MainPlotLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.MAIN_PLOT, frozen=True)
    plot_stage: str = Field(default="", description="剧情阶段")
    trigger_conditions: List[str] = Field(default_factory=list, description="触发条件")
    resolution_conditions: List[str] = Field(default_factory=list, description="解决条件")


class RuleLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.RULE, frozen=True)
    rule_type: str = Field(default="", description="规则类型")
    constraints: List[str] = Field(default_factory=list, description="约束条件")


class RumorLore(LoreEntry):
    category: LoreCategory = Field(default=LoreCategory.RUMOR, frozen=True)
    source: str = Field(default="", description="传闻来源")
    truth_status: str = Field(default="unknown", description="真实状态")
    spread_rate: float = Field(default=0.5, ge=0.0, le=1.0, description="传播率")


class LoreView(BaseModel):
    lore_id: str = Field(..., description="设定ID")
    title: str = Field(..., description="标题")
    category: LoreCategory = Field(..., description="类别")
    content: str = Field(..., description="可见内容（经过视角过滤）")
    visibility_level: str = Field(default="full", description="可见性级别")
    perspective_id: str = Field(..., description="视角ID")
    is_rumor: bool = Field(default=False, description="是否为传闻")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
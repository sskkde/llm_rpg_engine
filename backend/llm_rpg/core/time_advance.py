"""
Time Advance Proposal Module

Defines the TimeAdvanceProposal model and deterministic mappings
for converting player action intents into time advancement proposals.

Key concepts:
- INTENT_TO_TIME_CATEGORY: Maps ActionType values to time categories
- DETERMINISTIC_DEFAULTS: Default elapsed minutes per time category
- TimeAdvanceProposal: Structured proposal for time advancement
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TimeAdvanceProposal(BaseModel):
    """提议的时间推进量。

    Attributes:
        elapsed_minutes: 提议经过的分钟数
        reason: 时间推进原因
        confidence: 置信度 (0-1)
        time_category: 时间类别 (inspect/short_dialogue/...)
        display_hint: 时辰显示提示
        source: 来源 (deterministic/reused_llm/explicit_llm)
    """

    elapsed_minutes: int = Field(..., ge=0, description="提议经过的分钟数")
    reason: str = Field("", description="时间推进原因")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="置信度")
    time_category: str = Field(..., description="时间类别")
    display_hint: Optional[str] = Field(None, description="时辰显示提示")
    source: str = Field("deterministic", description="来源(deterministic/reused_llm/explicit_llm)")


# Intent type → time category mapping (covers all 16 ActionType values)
INTENT_TO_TIME_CATEGORY: dict[str, str] = {
    "move": "nearby_movement",
    "inspect": "inspect",
    "talk": "short_dialogue",
    "ask": "short_dialogue",
    "attack": "combat",
    "defend": "combat",
    "cast_skill": "combat",
    "use_item": "inspect",
    "take_item": "inspect",
    "give_item": "short_dialogue",
    "persuade": "long_dialogue",
    "hide": "inspect",
    "follow": "nearby_movement",
    "wait": "wait",
    "trigger_object": "inspect",
    "quest_progress": "short_dialogue",
}


# Deterministic default elapsed minutes per time category
DETERMINISTIC_DEFAULTS: dict[str, int] = {
    "inspect": 3,
    "short_dialogue": 8,
    "long_dialogue": 25,
    "nearby_movement": 15,
    "far_movement": 90,
    "combat": 5,
    "rest": 120,
    "wait": 60,
    "unknown": 10,
}

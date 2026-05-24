"""
Turn progress event model and emission helper.

This module provides the TurnProgressEvent dataclass and emit_stage helper
for streaming turn execution progress to the frontend via SSE.

Wave 1 of P10a Immersion Provider Routing.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


# =============================================================================
# Stage Name Type
# =============================================================================

TurnStageName = Literal[
    "input_intent",
    "action_resolving",
    "world_stage",
    "scene_stage",
    "npc_stage",
    "validation",
    "committing",
    "narration",
]
"""
Stage names for turn execution progress.

These 8 stages provide fine-grained progress tracking:
- input_intent: Parsing player intent from input
- action_resolving: Resolving and validating player action
- world_stage: World state evolution
- scene_stage: Scene/location changes
- npc_stage: NPC decision making
- validation: Rule validation checks
- committing: State persistence
- narration: Narrative text generation
"""


# =============================================================================
# Stage Labels (Chinese)
# =============================================================================

STAGE_LABELS: dict[str, str] = {
    "input_intent": "解析玩家意图……",
    "action_resolving": "执行玩家行动……",
    "world_stage": "世界演进中……",
    "scene_stage": "场景变化中……",
    "npc_stage": "NPC 思考中……",
    "validation": "规则校验中……",
    "committing": "提交状态变更……",
    "narration": "生成叙事文本……",
}
"""Human-readable Chinese labels for each stage."""


# =============================================================================
# Turn Progress Event
# =============================================================================

@dataclass
class TurnProgressEvent:
    """
    Progress event for a turn execution stage.
    
    This event is emitted to the frontend via SSE to provide real-time
    feedback on turn execution progress.
    
    Fields:
        stage: Stage identifier (e.g., "world_stage", "narration")
        phase: Execution phase ("started" or "completed")
        label: Human-readable Chinese label for the stage
        actor_id: Optional actor ID (for NPC stages)
        actor_name: Optional actor name (for NPC stages)
        progress: Estimated progress 0-100 (optional)
        duration_ms: Duration in milliseconds (set on completion)
        metadata: Additional stage-specific metadata
    """
    stage: str
    phase: str
    label: str
    actor_id: str | None = None
    actor_name: str | None = None
    progress: int | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Emit Stage Helper
# =============================================================================

def emit_stage(stage: str, phase: str, **kwargs: Any) -> TurnProgressEvent:
    """
    Create a TurnProgressEvent for a stage.
    
    This helper creates a progress event with the stage's label looked up
    from STAGE_LABELS. Additional fields can be passed via kwargs.
    
    Args:
        stage: Stage identifier (should be one of TurnStageName values)
        phase: Execution phase ("started" or "completed")
        **kwargs: Optional fields to pass through:
            - actor_id: Actor ID for NPC stages
            - actor_name: Actor name for NPC stages
            - progress: Estimated progress 0-100
            - metadata: Additional metadata dict
    
    Returns:
        TurnProgressEvent with label populated from STAGE_LABELS
    
    Example:
        >>> event = emit_stage("world_stage", "started")
        >>> print(event.stage, event.label)
        world_stage 世界演进中……
        
        >>> event = emit_stage("npc_stage", "started", actor_id="npc_001", actor_name="李长老")
        >>> print(event.actor_name)
        李长老
    """
    label = STAGE_LABELS.get(stage, "")
    
    return TurnProgressEvent(
        stage=stage,
        phase=phase,
        label=label,
        actor_id=kwargs.get("actor_id"),
        actor_name=kwargs.get("actor_name"),
        progress=kwargs.get("progress"),
        duration_ms=None,  # Set later when stage completes
        metadata=kwargs.get("metadata", {}),
    )

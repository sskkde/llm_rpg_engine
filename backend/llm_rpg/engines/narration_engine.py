from typing import Any, Dict, List, Optional

from ..models.states import CanonicalState
from ..models.perspectives import PlayerPerspective, NarratorPerspective
from ..models.common import ContextPack

from ..core.canonical_state import CanonicalStateManager
from ..core.perspective import PerspectiveService
from ..core.context_builder import ContextBuilder
from ..core.validator import Validator


class NarrationEngine:
    
    def __init__(
        self,
        state_manager: CanonicalStateManager,
        perspective_service: PerspectiveService,
        context_builder: ContextBuilder,
        validator: Validator,
    ):
        self._state_manager = state_manager
        self._perspective = perspective_service
        self._context_builder = context_builder
        self._validator = validator
    
    def generate_narration(
        self,
        game_id: str,
        turn_index: int,
        player_perspective: PlayerPerspective,
        narrator_perspective: NarratorPerspective,
        scene_tone: str = "neutral",
        writing_style: str = "default",
    ) -> str:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return "世界陷入了沉默..."
        
        context = self._context_builder.build_narration_context(
            game_id=game_id,
            turn_id=str(turn_index),
            state=state,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
            scene_tone=scene_tone,
            writing_style=writing_style,
        )
        
        narration = self._generate_text(context)
        
        validation = self._validator.validate_narration(
            text=narration,
            forbidden_info=narrator_perspective.forbidden_info,
        )
        
        if not validation.is_valid:
            narration = self._sanitize_narration(narration, narrator_perspective.forbidden_info)
        
        return narration
    
    def _generate_text(self, context: ContextPack) -> str:
        player_visible = context.content.get("player_visible_context", {})
        scene = player_visible.get("visible_scene", {})
        player_state = player_visible.get("player_state", {})
        
        location_name = scene.get("location_id", "未知之地")
        player_name = player_state.get("name", "你")
        
        scene_phase = scene.get("scene_phase", "exploration")
        danger_level = scene.get("danger_level", 0.0)
        
        if danger_level > 0.7:
            return f"{player_name} 站在 {location_name}，空气中弥漫着危险的气息。"
        elif danger_level > 0.3:
            return f"{player_name} 在 {location_name} 中前行，四周似乎隐藏着什么。"
        else:
            return f"{player_name} 站在 {location_name}，一切看起来都很平静。"
    
    def _sanitize_narration(self, narration: str, forbidden_info: List[str]) -> str:
        sanitized = narration
        for info in forbidden_info:
            if info in sanitized:
                sanitized = sanitized.replace(info, "...")
        return sanitized
    
    def describe_location(
        self,
        game_id: str,
        location_id: str,
        player_perspective: PlayerPerspective,
    ) -> str:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return "你看不清周围的一切。"
        
        location_state = state.location_states.get(location_id)
        if location_state is None:
            return "你来到了一个未知的地方。"
        
        if location_state.danger_level > 0.7:
            return f"{location_state.name}：这里充满了危险的气息。"
        elif location_state.danger_level > 0.3:
            return f"{location_state.name}：这里似乎有些不对劲。"
        else:
            return f"{location_state.name}：这里看起来很平静。"
    
    def describe_npc_interaction(
        self,
        game_id: str,
        npc_id: str,
        player_perspective: PlayerPerspective,
    ) -> str:
        state = self._state_manager.get_state(game_id)
        if state is None:
            return "你看不清对方。"
        
        npc_state = state.npc_states.get(npc_id)
        if npc_state is None:
            return "你找不到这个人。"
        
        if npc_state.mood == "hostile":
            return f"{npc_state.name} 敌意地看着你。"
        elif npc_state.mood == "anxious":
            return f"{npc_state.name} 显得有些焦虑。"
        elif npc_state.mood == "friendly":
            return f"{npc_state.name} 友善地看着你。"
        else:
            return f"{npc_state.name} 平静地看着你。"
    
    def describe_scene_event(
        self,
        event_summary: str,
        scene_tone: str = "neutral",
    ) -> str:
        if scene_tone == "tense":
            return f"气氛突然紧张起来。{event_summary}"
        elif scene_tone == "mysterious":
            return f"空气中弥漫着神秘的气息。{event_summary}"
        else:
            return event_summary
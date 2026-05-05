"""
NarrationEngine - Generates narrative text using ProposalPipeline.

Key constraints:
- Narration consumes committed/player-visible facts only
- Forbidden info from NarratorPerspective must be excluded/redacted
- LLM outputs are proposals only; never mutate CanonicalState directly
- Every LLM-driven point has deterministic fallback via _generate_text
"""

import asyncio
from typing import Any, Dict, List, Optional

from ..models.states import CanonicalState
from ..models.perspectives import PlayerPerspective, NarratorPerspective
from ..models.proposals import NarrationProposal, ProposalType
from ..models.common import ContextPack

from ..core.canonical_state import CanonicalStateManager
from ..core.perspective import PerspectiveService
from ..core.context_builder import ContextBuilder
from ..core.validator import Validator

from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig
from ..llm.service import LLMService, MockLLMProvider


class NarrationEngine:
    """
    Engine for generating narrative text based on committed state.
    
    Uses ProposalPipeline for LLM-driven narration generation.
    Falls back to deterministic _generate_text when LLM fails.
    
    CRITICAL: Narration cannot invent uncommitted facts.
    Must only describe what has been committed to canonical state.
    """
    
    def __init__(
        self,
        state_manager: CanonicalStateManager,
        perspective_service: PerspectiveService,
        context_builder: ContextBuilder,
        validator: Validator,
        proposal_pipeline: Optional[ProposalPipeline] = None,
        llm_service: Optional[LLMService] = None,
    ):
        self._state_manager = state_manager
        self._perspective = perspective_service
        self._context_builder = context_builder
        self._validator = validator
        self._proposal_pipeline = proposal_pipeline
        self._llm_service = llm_service
    
    def _ensure_pipeline(self) -> ProposalPipeline:
        """Ensure proposal pipeline is available."""
        if self._proposal_pipeline is None:
            if self._llm_service is None:
                self._llm_service = LLMService(provider=MockLLMProvider())
            self._proposal_pipeline = ProposalPipeline(
                llm_service=self._llm_service,
                config=ProposalConfig(
                    timeout_seconds=30.0,
                    max_tokens=500,
                    temperature=0.8,
                ),
            )
        return self._proposal_pipeline
    
    async def generate_narration_async(
        self,
        game_id: str,
        turn_index: int,
        player_perspective: PlayerPerspective,
        narrator_perspective: NarratorPerspective,
        scene_tone: str = "neutral",
        writing_style: str = "default",
        session_id: Optional[str] = None,
    ) -> NarrationProposal:
        """
        Generate narration using ProposalPipeline.
        
        Context is built only from committed state and build_narration_context.
        Forbidden info from NarratorPerspective is excluded/redacted.
        
        Returns NarrationProposal (LLM-driven or fallback).
        """
        state = self._state_manager.get_state(game_id)
        if state is None:
            return self._create_fallback_proposal(
                reason="State not found",
                visible_context_id=None,
            )
        
        context = self._context_builder.build_narration_context(
            game_id=game_id,
            turn_id=str(turn_index),
            state=state,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
            scene_tone=scene_tone,
            writing_style=writing_style,
        )
        
        visible_context = self._build_visible_context_for_llm(
            context=context,
            forbidden_info=narrator_perspective.forbidden_info,
        )
        
        pipeline = self._ensure_pipeline()
        
        try:
            proposal = await pipeline.generate_narration(
                visible_context=visible_context,
                prompt_template_id="narration_v1",
                session_id=session_id,
                turn_no=turn_index,
            )
            
            if not proposal.is_fallback:
                proposal = self._validate_and_sanitize_proposal(
                    proposal=proposal,
                    forbidden_info=narrator_perspective.forbidden_info,
                    visible_context_id=context.context_id,
                )
            
            return proposal
            
        except Exception as e:
            return self._create_fallback_proposal(
                reason=str(e),
                visible_context_id=context.context_id,
                context=context,
            )
    
    def generate_narration(
        self,
        game_id: str,
        turn_index: int,
        player_perspective: PlayerPerspective,
        narrator_perspective: NarratorPerspective,
        scene_tone: str = "neutral",
        writing_style: str = "default",
    ) -> str:
        """
        Generate narration text (synchronous wrapper).
        
        Uses async generation internally, falls back to deterministic
        _generate_text if async fails or returns fallback.
        """
        try:
            proposal = asyncio.run(
                self.generate_narration_async(
                    game_id=game_id,
                    turn_index=turn_index,
                    player_perspective=player_perspective,
                    narrator_perspective=narrator_perspective,
                    scene_tone=scene_tone,
                    writing_style=writing_style,
                )
            )
            
            return proposal.text
            
        except Exception:
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
            
            return self._generate_text(context)
    
    def _build_visible_context_for_llm(
        self,
        context: ContextPack,
        forbidden_info: List[str],
    ) -> Dict[str, Any]:
        """
        Build visible context for LLM, excluding forbidden info.
        
        CRITICAL: Only pass player-visible facts to LLM.
        Forbidden info must be excluded to prevent leaks.
        """
        content = context.content
        player_visible = content.get("player_visible_context", {})
        visible_context = {
            "player_state": player_visible.get("player_state", {}),
            "visible_scene": player_visible.get("visible_scene", {}),
            "visible_npc_states": player_visible.get("visible_npc_states", {}),
            "known_facts": player_visible.get("known_facts", []),
            "known_rumors": player_visible.get("known_rumors", []),
            "scene_tone": content.get("scene_tone", "neutral"),
            "writing_style": content.get("writing_style", "default"),
            "narrator_tone": content.get("narrator_tone", "neutral"),
            "narrator_pacing": content.get("narrator_pacing", "normal"),
            "allowed_hints": content.get("allowed_hints", []),
        }
        
        visible_events = player_visible.get("visible_events", [])
        visible_context["visible_events"] = visible_events
        
        lore_context = content.get("lore_context", [])
        visible_context["lore_context"] = lore_context
        
        visible_context["constraints"] = [
            "只能描述玩家可见的场景和事件",
            "不能泄露隐藏的秘密或未揭示的信息",
            "不能添加未发生的事件或未提交的状态变化",
            "叙事必须基于已提交的事实",
        ]
        
        return visible_context
    
    def _validate_and_sanitize_proposal(
        self,
        proposal: NarrationProposal,
        forbidden_info: List[str],
        visible_context_id: Optional[str],
    ) -> NarrationProposal:
        """
        Validate proposal against forbidden info and sanitize if needed.
        
        Checks narration text for forbidden info leaks.
        If detected, sanitizes text and marks proposal.
        """
        text = proposal.text
        forbidden_detected = []
        
        for info in forbidden_info:
            if info and info in text:
                forbidden_detected.append(info)
        
        if forbidden_detected:
            sanitized_text = self._sanitize_narration(text, forbidden_info)
            
            proposal.text = sanitized_text
            proposal.forbidden_info_detected = forbidden_detected
            proposal.hidden_info_check_passed = False
            proposal.visible_context_id = visible_context_id
            
            proposal.audit.validation_warnings.append(
                f"Forbidden info detected and sanitized: {len(forbidden_detected)} items"
            )
        else:
            proposal.hidden_info_check_passed = True
            proposal.visible_context_id = visible_context_id
        
        return proposal
    
    def _create_fallback_proposal(
        self,
        reason: str,
        visible_context_id: Optional[str],
        context: Optional[ContextPack] = None,
    ) -> NarrationProposal:
        """
        Create fallback NarrationProposal using deterministic generation.
        
        Used when LLM fails or state is unavailable.
        """
        from ..models.proposals import (
            ProposalAuditMetadata,
            ProposalType,
            ProposalSource,
            RepairStatus,
            ValidationStatus,
        )
        
        if context:
            text = self._generate_text(context)
        else:
            text = "世界陷入了沉默..."
        
        return NarrationProposal(
            text=text,
            tone="neutral",
            style_tags=[],
            visible_context_id=visible_context_id,
            committed_facts_used=[],
            hidden_info_check_passed=True,
            forbidden_info_detected=[],
            mentioned_entities=[],
            visibility="player_visible",
            confidence=0.0,
            recommended_actions=[],
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.NARRATION,
                source_engine=ProposalSource.NARRATION_ENGINE,
                fallback_used=True,
                fallback_reason=reason,
                validation_status=ValidationStatus.PASSED,
            ),
            is_fallback=True,
        )
    
    def _generate_text(self, context: ContextPack) -> str:
        """
        Deterministic fallback narration generation.
        
        Used when LLM fails. Generates simple template-based narration
        from player-visible context only.
        """
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
        """
        Sanitize narration by replacing forbidden info with placeholders.
        """
        sanitized = narration
        for info in forbidden_info:
            if info and info in sanitized:
                sanitized = sanitized.replace(info, "...")
        return sanitized
    
    def describe_location(
        self,
        game_id: str,
        location_id: str,
        player_perspective: PlayerPerspective,
    ) -> str:
        """Describe a location from player perspective."""
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
        """Describe NPC interaction from player perspective."""
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
        """Describe a scene event with appropriate tone."""
        if scene_tone == "tense":
            return f"气氛突然紧张起来。{event_summary}"
        elif scene_tone == "mysterious":
            return f"空气中弥漫着神秘的气息。{event_summary}"
        else:
            return event_summary
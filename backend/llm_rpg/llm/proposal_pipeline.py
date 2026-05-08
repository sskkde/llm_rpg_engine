"""
Unified Proposal Pipeline for LLM-Driven RPG Engine.

This module provides a single entry point for generating all types of proposals.
It integrates LLMService, OutputParser, RepairHandler, and audit logging.

Key features:
- Unified pipeline for all proposal types
- Automatic JSON parsing and repair
- Schema validation
- Comprehensive audit logging
- Deterministic fallback on failure
- Timeout and token budget handling
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

from ..models.proposals import (
    AnyProposal,
    InputIntentProposal,
    WorldTickProposal,
    SceneEventProposal,
    NPCActionProposal,
    NarrationProposal,
    ProposalType,
    ProposalSource,
    ProposalAuditMetadata,
    RepairStatus,
    ValidationStatus,
    create_fallback_input_intent,
    create_fallback_world_tick,
    create_fallback_scene_event,
    create_fallback_npc_action,
    create_fallback_narration,
)
from .service import LLMService, LLMMessage, LLMResponse
from .parsers import OutputParser
from .repair import RetryRepairHandler, RepairAuditRecord, RepairStatus as RepairHandlerStatus

T = TypeVar("T", bound=BaseModel)


class ProposalPipelineError(Exception):
    """Base exception for proposal pipeline errors."""
    pass


class ProposalTimeoutError(ProposalPipelineError):
    """Raised when LLM call exceeds timeout."""
    pass


class ProposalTokenBudgetError(ProposalPipelineError):
    """Raised when LLM call exceeds token budget."""
    pass


class ProposalParseError(ProposalPipelineError):
    """Raised when output cannot be parsed or repaired."""
    pass


class ProposalConfig:
    """Configuration for proposal pipeline."""
    
    def __init__(
        self,
        timeout_seconds: float = 30.0,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        max_repair_attempts: int = 3,
        enable_audit_logging: bool = True,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_repair_attempts = max_repair_attempts
        self.enable_audit_logging = enable_audit_logging


DEFAULT_CONFIG = ProposalConfig()


class ProposalPipeline:
    """
    Unified pipeline for generating LLM proposals.
    
    This class provides a single entry point for all proposal types:
    - InputIntentProposal
    - WorldTickProposal
    - SceneEventProposal
    - NPCActionProposal
    - NarrationProposal
    
    Each proposal goes through:
    1. LLM call with appropriate prompt
    2. JSON parsing via OutputParser
    3. Repair via RetryRepairHandler if malformed
    4. Schema validation against Pydantic model
    5. Audit metadata recording
    6. Fallback generation on failure
    """
    
    def __init__(
        self,
        llm_service: LLMService,
        repair_handler: Optional[RetryRepairHandler] = None,
        config: Optional[ProposalConfig] = None,
    ):
        self._llm_service = llm_service
        self._repair_handler = repair_handler or RetryRepairHandler(
            max_repair_attempts=DEFAULT_CONFIG.max_repair_attempts
        )
        self._config = config or DEFAULT_CONFIG
        self._parser = OutputParser()
    
    async def generate_proposal(
        self,
        proposal_type: ProposalType,
        prompt_messages: List[LLMMessage],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
        context: Optional[Dict[str, Any]] = None,
        fallback_context: Optional[Dict[str, Any]] = None,
    ) -> AnyProposal:
        """
        Generate a proposal of the specified type.
        
        Args:
            proposal_type: Type of proposal to generate
            prompt_messages: Messages for LLM call
            prompt_template_id: ID of prompt template used
            session_id: Game session ID for audit
            turn_no: Turn number for audit
            context: Additional context for proposal construction
            fallback_context: Context for fallback generation (e.g., npc_id, scene_id)
            
        Returns:
            Parsed proposal or fallback proposal
        """
        start_time = time.time()
        
        try:
            response = await asyncio.wait_for(
                self._llm_service.generate(
                    messages=prompt_messages,
                    template_id=prompt_template_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                ),
                timeout=self._config.timeout_seconds,
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            proposal = self._process_response(
                response=response,
                proposal_type=proposal_type,
                prompt_template_id=prompt_template_id,
                latency_ms=latency_ms,
                context=context,
            )
            
            return proposal
            
        except asyncio.TimeoutError:
            latency_ms = int((time.time() - start_time) * 1000)
            return self._create_fallback(
                proposal_type=proposal_type,
                reason="Timeout exceeded",
                latency_ms=latency_ms,
                fallback_context=fallback_context,
            )
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return self._create_fallback(
                proposal_type=proposal_type,
                reason=str(e),
                latency_ms=latency_ms,
                fallback_context=fallback_context,
            )
    
    def _process_response(
        self,
        response: LLMResponse,
        proposal_type: ProposalType,
        prompt_template_id: Optional[str],
        latency_ms: int,
        context: Optional[Dict[str, Any]],
    ) -> AnyProposal:
        """Process LLM response and create proposal."""
        raw_output = response.content
        raw_output_preview = raw_output[:200] if raw_output else ""
        
        repair_status = RepairStatus.NONE
        repair_attempts = 0
        repair_strategies_tried: List[str] = []
        
        parsed_data: Optional[Dict[str, Any]] = None
        
        parsed_data = self._parser.parse_json(raw_output)
        
        if parsed_data is None:
            parsed_data, repair_record = self._repair_handler.repair(raw_output)
            
            if parsed_data is not None:
                repair_status = RepairStatus.SUCCESS
                repair_attempts = len(repair_record.attempts)
                repair_strategies_tried = [
                    a.strategy.value for a in repair_record.attempts
                ]
            elif repair_record.fallback_used:
                repair_status = RepairStatus.FALLBACK
                repair_attempts = len(repair_record.attempts)
                repair_strategies_tried = [
                    a.strategy.value for a in repair_record.attempts
                ]
            else:
                repair_status = RepairStatus.FAILED
                repair_attempts = len(repair_record.attempts)
                repair_strategies_tried = [
                    a.strategy.value for a in repair_record.attempts
                ]
        
        if parsed_data is None:
            return self._create_fallback(
                proposal_type=proposal_type,
                reason="Failed to parse or repair LLM output",
                latency_ms=latency_ms,
                context=context,
                raw_output_preview=raw_output_preview,
                repair_status=repair_status,
                repair_attempts=repair_attempts,
                repair_strategies_tried=repair_strategies_tried,
            )
        
        proposal = self._construct_proposal(
            proposal_type=proposal_type,
            data=parsed_data,
            prompt_template_id=prompt_template_id,
            latency_ms=latency_ms,
            model_name=response.model,
            input_tokens=response.usage.get("prompt_tokens", 0),
            output_tokens=response.usage.get("completion_tokens", 0),
            raw_output_preview=raw_output_preview,
            repair_status=repair_status,
            repair_attempts=repair_attempts,
            repair_strategies_tried=repair_strategies_tried,
            context=context,
        )
        
        return proposal
    
    def _construct_proposal(
        self,
        proposal_type: ProposalType,
        data: Dict[str, Any],
        prompt_template_id: Optional[str],
        latency_ms: int,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        raw_output_preview: str,
        repair_status: RepairStatus,
        repair_attempts: int,
        repair_strategies_tried: List[str],
        context: Optional[Dict[str, Any]],
    ) -> AnyProposal:
        """Construct proposal from parsed data."""
        source_engine = self._get_source_engine(proposal_type)
        
        audit = ProposalAuditMetadata(
            proposal_type=proposal_type,
            source_engine=source_engine,
            latency_ms=latency_ms,
            prompt_template_id=prompt_template_id,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_output_preview=raw_output_preview,
            repair_status=repair_status,
            repair_attempts=repair_attempts,
            repair_strategies_tried=repair_strategies_tried,
            validation_status=ValidationStatus.PENDING,
        )
        
        context = context or {}
        
        try:
            if proposal_type == ProposalType.INPUT_INTENT:
                return InputIntentProposal(
                    intent_type=data["intent_type"],
                    target=data.get("target"),
                    target_type=data.get("target_type"),
                    parameters=data.get("parameters", {}),
                    risk_level=data.get("risk_level", "low"),
                    raw_tokens=data.get("raw_tokens", []),
                    confidence=data.get("confidence", 0.5),
                    mentioned_entities=data.get("mentioned_entities", []),
                    audit=audit,
                    is_fallback=False,
                )
                
            elif proposal_type == ProposalType.WORLD_TICK:
                return WorldTickProposal(
                    time_delta_turns=data.get("time_delta_turns", 1),
                    time_description=data.get("time_description", ""),
                    candidate_events=data.get("candidate_events", []),
                    state_deltas=data.get("state_deltas", []),
                    affected_entities=data.get("affected_entities", []),
                    visibility=data.get("visibility", "mixed"),
                    confidence=data.get("confidence", 0.5),
                    audit=audit,
                    is_fallback=False,
                )
                
            elif proposal_type == ProposalType.SCENE_EVENT:
                scene_id = context.get("scene_id", data.get("scene_id", "unknown"))
                return SceneEventProposal(
                    scene_id=scene_id,
                    scene_name=data.get("scene_name"),
                    candidate_events=data.get("candidate_events", []),
                    state_deltas=data.get("state_deltas", []),
                    affected_entities=data.get("affected_entities", []),
                    suggested_transition=data.get("suggested_transition"),
                    transition_reason=data.get("transition_reason"),
                    visibility=data.get("visibility", "player_visible"),
                    confidence=data.get("confidence", 0.5),
                    audit=audit,
                    is_fallback=False,
                )
                
            elif proposal_type == ProposalType.NPC_ACTION:
                npc_id = context.get("npc_id", data.get("npc_id", "unknown"))
                return NPCActionProposal(
                    npc_id=npc_id,
                    npc_name=data.get("npc_name"),
                    action_type=data.get("action_type", "idle"),
                    target=data.get("target"),
                    summary=data.get("summary", ""),
                    visible_motivation=data.get("visible_motivation", ""),
                    hidden_motivation=data.get("hidden_motivation"),
                    state_deltas=data.get("state_deltas", []),
                    affected_entities=data.get("affected_entities", []),
                    visibility=data.get("visibility", "player_visible"),
                    confidence=data.get("confidence", 0.5),
                    alternatives=data.get("alternatives", []),
                    audit=audit,
                    is_fallback=False,
                )
                
            elif proposal_type == ProposalType.NARRATION:
                return NarrationProposal(
                    text=data.get("text", data.get("content", "")),
                    tone=data.get("tone", "neutral"),
                    style_tags=data.get("style_tags", []),
                    visible_context_id=data.get("visible_context_id"),
                    committed_facts_used=data.get("committed_facts_used", []),
                    hidden_info_check_passed=data.get("hidden_info_check_passed", True),
                    forbidden_info_detected=data.get("forbidden_info_detected", []),
                    mentioned_entities=data.get("mentioned_entities", []),
                    confidence=data.get("confidence", 0.5),
                    recommended_actions=data.get("recommended_actions", []),
                    audit=audit,
                    is_fallback=False,
                )
                
        except ValidationError as e:
            validation_errors_list = [str(err) for err in e.errors()]
            audit.validation_status = ValidationStatus.FAILED
            audit.validation_errors = validation_errors_list
            
            return self._create_fallback(
                proposal_type=proposal_type,
                reason=f"Schema validation failed: {e}",
                latency_ms=latency_ms,
                context=context,
                raw_output_preview=raw_output_preview,
                repair_status=repair_status,
                repair_attempts=repair_attempts,
                repair_strategies_tried=repair_strategies_tried,
                validation_status=ValidationStatus.FAILED,
                validation_errors=validation_errors_list,
            )
        
        raise ProposalPipelineError(f"Unknown proposal type: {proposal_type}")
    
    def _create_fallback(
        self,
        proposal_type: ProposalType,
        reason: str,
        latency_ms: int,
        context: Optional[Dict[str, Any]] = None,
        fallback_context: Optional[Dict[str, Any]] = None,
        raw_output_preview: str = "",
        repair_status: RepairStatus = RepairStatus.NONE,
        repair_attempts: int = 0,
        repair_strategies_tried: Optional[List[str]] = None,
        validation_status: Optional[ValidationStatus] = None,
        validation_errors: Optional[List[str]] = None,
    ) -> AnyProposal:
        """Create fallback proposal when LLM fails."""
        fallback_context = fallback_context or context or {}
        
        if proposal_type == ProposalType.INPUT_INTENT:
            raw_input = fallback_context.get("raw_input", "")
            proposal = create_fallback_input_intent(raw_input, reason)
            
        elif proposal_type == ProposalType.WORLD_TICK:
            proposal = create_fallback_world_tick(reason)
            
        elif proposal_type == ProposalType.SCENE_EVENT:
            scene_id = fallback_context.get("scene_id", "unknown")
            proposal = create_fallback_scene_event(scene_id, reason)
            
        elif proposal_type == ProposalType.NPC_ACTION:
            npc_id = fallback_context.get("npc_id", "unknown")
            proposal = create_fallback_npc_action(npc_id, reason)
            
        elif proposal_type == ProposalType.NARRATION:
            proposal = create_fallback_narration(reason)
            
        else:
            raise ProposalPipelineError(f"Unknown proposal type: {proposal_type}")
        
        proposal.audit.latency_ms = latency_ms
        proposal.audit.raw_output_preview = raw_output_preview
        proposal.audit.repair_status = repair_status
        proposal.audit.repair_attempts = repair_attempts
        proposal.audit.repair_strategies_tried = repair_strategies_tried or []
        
        if validation_status is not None:
            proposal.audit.validation_status = validation_status
        if validation_errors is not None:
            proposal.audit.validation_errors = validation_errors
        
        return proposal
    
    def _get_source_engine(self, proposal_type: ProposalType) -> ProposalSource:
        """Map proposal type to source engine."""
        mapping = {
            ProposalType.INPUT_INTENT: ProposalSource.INPUT_ENGINE,
            ProposalType.WORLD_TICK: ProposalSource.WORLD_ENGINE,
            ProposalType.SCENE_EVENT: ProposalSource.SCENE_ENGINE,
            ProposalType.NPC_ACTION: ProposalSource.NPC_ENGINE,
            ProposalType.NARRATION: ProposalSource.NARRATION_ENGINE,
        }
        return mapping[proposal_type]
    
    async def generate_input_intent(
        self,
        raw_input: str,
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
        context: Optional[Dict[str, Any]] = None,
    ) -> InputIntentProposal:
        """Generate InputIntentProposal from player input."""
        messages = [
            LLMMessage(
                role="system",
                content="你是一个文字RPG游戏的意图解析器。请将玩家的自然语言输入解析为结构化的意图。"
            ),
            LLMMessage(
                role="user",
                content=f"""玩家输入: {raw_input}

请严格按照以下JSON格式输出意图解析结果，不要添加任何额外字段：
{{
  "intent_type": "move|talk|attack|inspect|interact|idle|unknown",
  "target": "目标名称或地点名称（如果是移动/交互动作）",
  "target_type": "npc|location|item",
  "parameters": {{}},
  "risk_level": "low|medium|high",
  "confidence": 0.0到1.0之间的数值
}}

示例：
玩家输入: "前往试炼堂"
输出: {{"intent_type": "move", "target": "试炼堂", "target_type": "location", "parameters": {{}}, "risk_level": "low", "confidence": 0.9}}

玩家输入: "和师姐说话"
输出: {{"intent_type": "talk", "target": "师姐", "target_type": "npc", "parameters": {{}}, "risk_level": "low", "confidence": 0.9}}"""
            ),
        ]
        
        fallback_context = {"raw_input": raw_input}
        
        return await self.generate_proposal(
            proposal_type=ProposalType.INPUT_INTENT,
            prompt_messages=messages,
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
            context=context,
            fallback_context=fallback_context,
        )
    
    async def generate_world_tick(
        self,
        world_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> WorldTickProposal:
        """Generate WorldTickProposal for world state changes."""
        messages = [
            LLMMessage(
                role="system",
                content="你是一个文字RPG游戏的世界引擎。请根据当前世界状态生成时间推进和后台事件提案。"
            ),
            LLMMessage(
                role="user",
                content=f"""世界上下文: {world_context}

请严格按照以下JSON格式输出世界推进提案，不要添加任何额外字段：
{{
  "time_description": "时间推进描述",
  "candidate_events": [
    {{
      "event_type": "事件类型",
      "description": "事件描述",
      "effects": {{}},
      "importance": 0.0到1.0之间的数值,
      "visibility": "player_visible|hidden|gm_only"
    }}
  ],
  "state_deltas": [
    {{
      "path": "global_flags|quest_progress|location_flags|scheduled_event_hints|faction_pressure",
      "operation": "set|update|delete",
      "value": "新的值",
      "reason": "变更原因"
    }}
  ],
  "confidence": 0.0到1.0之间的数值
}}"""
            ),
        ]
        
        return await self.generate_proposal(
            proposal_type=ProposalType.WORLD_TICK,
            prompt_messages=messages,
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
            context=world_context,
        )
    
    async def generate_scene_event(
        self,
        scene_id: str,
        scene_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> SceneEventProposal:
        """Generate SceneEventProposal for scene-specific content."""
        messages = [
            LLMMessage(
                role="system",
                content="你是一个文字RPG游戏的场景引擎。请根据当前场景状态生成场景事件提案。"
            ),
            LLMMessage(
                role="user",
                content=f"""场景ID: {scene_id}
场景上下文: {scene_context}

请严格按照以下JSON格式输出场景事件提案，不要添加任何额外字段：
{{
  "scene_id": "{scene_id}",
  "scene_name": "场景名称",
  "candidate_events": [
    {{
      "event_type": "事件类型（如：exploration、dialogue、combat、discovery）",
      "description": "事件详细描述",
      "importance": 0.0到1.0之间的数值
    }}
  ],
  "recommended_actions": ["推荐行动1", "推荐行动2", "推荐行动3", "推荐行动4"],
  "confidence": 0.0到1.0之间的数值
}}"""
            ),
        ]
        
        context = {"scene_id": scene_id, **scene_context}
        
        return await self.generate_proposal(
            proposal_type=ProposalType.SCENE_EVENT,
            prompt_messages=messages,
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
            context=context,
            fallback_context={"scene_id": scene_id},
        )
    
    async def generate_npc_action(
        self,
        npc_id: str,
        npc_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> NPCActionProposal:
        """Generate NPCActionProposal for NPC decisions."""
        messages = [
            LLMMessage(
                role="system",
                content="你是一个文字RPG游戏的NPC引擎。请根据NPC的上下文和记忆生成行动提案。"
            ),
            LLMMessage(
                role="user",
                content=f"""NPC ID: {npc_id}
NPC上下文: {npc_context}

请严格按照以下JSON格式输出NPC行动提案，不要添加任何额外字段：
{{
  "npc_id": "{npc_id}",
  "action_type": "interact|observe|move|idle|dialogue|attack",
  "target": "目标对象（如果有）",
  "summary": "NPC行动的简短描述（一句话）",
  "visible_motivation": "玩家可见的动机说明",
  "visibility": "player_visible|hidden|gm_only",
  "confidence": 0.0到1.0之间的数值
}}"""
            ),
        ]
        
        context = {"npc_id": npc_id, **npc_context}
        
        return await self.generate_proposal(
            proposal_type=ProposalType.NPC_ACTION,
            prompt_messages=messages,
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
            context=context,
            fallback_context={"npc_id": npc_id},
        )
    
    async def generate_narration(
        self,
        visible_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> NarrationProposal:
        """Generate NarrationProposal from committed facts."""
        messages = [
            LLMMessage(
                role="system",
                content="你是一个文字RPG游戏的叙事引擎。请根据已提交的事实生成叙事文本。注意：只能描述玩家可见的信息，不能泄露隐藏的秘密。"
            ),
            LLMMessage(
                role="user",
                content=f"""可见上下文: {visible_context}

请严格按照以下JSON格式输出叙事提案，不要添加任何额外字段：
{{
  "text": "叙事文本内容（一段生动的中文描述，100-300字）",
  "confidence": 0.0到1.0之间的数值
}}"""
            ),
        ]
        
        return await self.generate_proposal(
            proposal_type=ProposalType.NARRATION,
            prompt_messages=messages,
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
            context=visible_context,
        )


def create_proposal_pipeline(
    llm_service: Optional[LLMService] = None,
    config: Optional[ProposalConfig] = None,
) -> ProposalPipeline:
    """Create a proposal pipeline with optional configuration."""
    from .service import get_llm_service, MockLLMProvider
    
    if llm_service is None:
        llm_service = get_llm_service(provider=MockLLMProvider())
    
    return ProposalPipeline(llm_service=llm_service, config=config)
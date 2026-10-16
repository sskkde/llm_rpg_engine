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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union

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
from .service import LLMService, LLMMessage, LLMResponse, StreamingNotSupportedError
from .parsers import OutputParser
from .repair import RetryRepairHandler, RepairAuditRecord, RepairStatus as RepairHandlerStatus
from .strict_contract import ContractReasonCode, ContractViolation, validate_production_contract

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


@dataclass
class ProductionContractOutcome:
    """Result of one strict production-contract call.

    Exactly one of ``contract`` / ``reason_code`` is meaningful:

    * ``contract`` is the validated ``contract_version=2`` DTO, or ``None`` when
      the output was rejected.
    * ``reason_code`` is a stable :class:`ContractReasonCode` value, or
      ``contract_unavailable`` when no model output was obtained at all
      (timeout/provider error). ``detail`` is restricted-audit detail.

    Nothing here is an authorization credential: a parsed contract still has to
    pass entity/reference authorization and domain adjudication.
    """

    contract: Optional[BaseModel] = None
    reason_code: Optional[str] = None
    detail: str = ""
    latency_ms: int = 0
    model_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    raw_output_preview: str = ""

    @property
    def accepted(self) -> bool:
        """Whether a contract model was produced and validated."""
        return self.contract is not None

    @property
    def contract_incompatible(self) -> bool:
        """Whether the failure was a contract violation rather than no output."""
        return self.contract is None and self.reason_code not in (
            None,
            ContractReasonCode.EMPTY_OUTPUT.value,
            "contract_unavailable",
        )


#: Reason code used when no model output could be obtained at all.
CONTRACT_UNAVAILABLE = "contract_unavailable"


_STRICT_RULES = """严格遵守以下输出契约（contract_version=2）：
- 只输出一个完整 JSON 对象，不要输出解释、前后缀文字或多个对象。
- 必须包含 "contract_version": 2。
- 不得输出契约未列出的任何字段（顶层或嵌套都不允许）。
- 不得输出 state_deltas、effects、success、damage、reward、hp、relationship、time、actor、
  session、turn、source、audit、permission、role 等执行或权限字段。
- 布尔值用 true/false，空值用 null，字符串用双引号，禁止注释与尾随逗号。"""


def build_player_intent_prompt_v2(
    raw_input: str,
    context: Dict[str, Any],
) -> List[LLMMessage]:
    """Build the production player-intent prompt.

    The prompt lists exactly the stable IDs the model may reference and states
    the closed action set. It is the human-readable twin of
    ``PRODUCTION_ACTION_PERMISSIONS`` / ``PlayerIntentV2``.
    """
    available_locations = context.get("available_locations") or []
    visible_npcs = context.get("visible_npcs") or []
    location_lines = "\n".join(
        f'- id="{loc.get("id")}" code="{loc.get("code")}" name="{loc.get("name")}"'
        for loc in available_locations
    ) or "- （无可选地点）"
    npc_lines = "\n".join(
        f'- id="{npc.get("npc_id")}" name="{npc.get("name")}"'
        for npc in visible_npcs
    ) or "- （当前场景没有可见 NPC）"

    system = (
        "你是一个文字RPG游戏的意图解析器。把玩家的自然语言输入解析为受限的结构化提案。\n"
        "你只能引用下面列出的稳定 ID，不得虚构实体；无法确定目标时把目标字段设为 null。\n"
        f"{_STRICT_RULES}"
    )
    user = f"""玩家输入: {raw_input}

当前地点 id: {context.get("current_location_id")}

可选地点（只能引用这里的 id）:
{location_lines}

当前场景可见 NPC（只能引用这里的 id）:
{npc_lines}

输出格式（intent 的具体字段按 action_type 只能取下面列出的那一种，不得混用）:
{{
  "contract_version": 2,
  "intent": {{"action_type": "move", "target_location_id": "<上面某个地点 id 或 null>"}},
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.0
}}

按 action_type 允许的 intent 形状：
- move:    {{"action_type": "move", "target_location_id": "<地点 id 或 null>"}}
- talk:    {{"action_type": "talk", "target_npc_id": "<NPC id 或 null>", "topic": "<不超过240字的话题或 null>"}}
- inspect: {{"action_type": "inspect", "target_npc_id": "<NPC id 或 null>"}}
- idle:    {{"action_type": "idle"}}
- attack/interact/action/unknown: {{"action_type": "attack", "target": "<原始目标文本或 null>"}}

语义要求：
- 玩家没有明确目的地时用 move + target_location_id=null，并把 needs_clarification 设为 true。
- talk/inspect 只能指向当前场景可见 NPC；不确定就用 null。
- 不要承诺对话结果、关系变化、任务奖励或任何数值变化。"""
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def build_npc_action_prompt_v2(
    npc_id: str,
    npc_context: Dict[str, Any],
) -> List[LLMMessage]:
    """Build the production NPC-action prompt.

    The actor is bound by the server, so the wire neither carries nor needs an
    NPC identity, and it cannot carry state deltas or memory candidates.
    """
    retrieved_memories = npc_context.get("retrieved_private_memories")
    memory_section = ""
    if retrieved_memories:
        memory_section = (
            "\n本次提供给该 NPC 的私有记忆（只能引用这些 id，没有就留空列表）:\n"
            f"{retrieved_memories}\n"
        )
    allowed_memory_ids = npc_context.get("used_memory_ids") or []

    system = (
        "你是一个文字RPG游戏的NPC引擎。请基于当前可见事实和检索到的私有记忆，生成受限的行动提案。\n"
        "你只能描述该 NPC 的一个动作；actor 身份由服务端绑定，你不需要也不能声明。\n"
        "如果没有相关记忆，不得虚构经历；只能基于 NPC 当前可见事实与下面列出的记忆做决策。\n"
        "summary/visible_motivation 是给玩家看的描述文本，不是事实声明，也不得泄露玩家不可见的信息。\n"
        f"{_STRICT_RULES}"
    )
    user = f"""NPC id: {npc_id}
NPC 上下文: {npc_context}
{memory_section}
可引用的记忆 id: {allowed_memory_ids}

输出格式（action 的具体字段按 action_type 只能取下面列出的那一种）:
{{
  "contract_version": 2,
  "action": {{"action_type": "observe"}},
  "summary": "一句话描述该 NPC 的行动",
  "visible_motivation": "玩家可见的动机说明",
  "visible_to_player": true,
  "used_memory_ids": [],
  "confidence": 0.0
}}

按 action_type 允许的 action 形状：
- observe: {{"action_type": "observe"}}
- idle:    {{"action_type": "idle"}}
- talk:    {{"action_type": "talk", "target_id": "<同场景目标 id 或 null>", "utterance": "<不超过1000字的话语或 null>"}}
- refuse:  {{"action_type": "refuse", "target_id": "<同场景目标 id 或 null>", "utterance": "<不超过1000字的话语或 null>"}}

语义要求：
- 不允许输出任何状态变化、数值、伤害、奖励、物品或关系变化。
- 话语只证明“说过这句话”，不证明这句话的内容为真。
- used_memory_ids 只能从上面“可引用的记忆 id”里选；没有可用记忆时必须是空列表。"""
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def build_world_tick_prompt_v2(world_context: Dict[str, Any]) -> List[LLMMessage]:
    """Build the production world-stage prompt (reference-only)."""
    system = (
        "你是一个文字RPG游戏的世界引擎。你只能组织引擎已经产生的结果，不能创造新的事实。\n"
        "你不得提议任何状态变化、效果或时间变化；世界时间由引擎裁决。\n"
        f"{_STRICT_RULES}"
    )
    engine_event_ids = world_context.get("engine_event_ids") or []
    user = f"""世界上下文: {world_context}

本回合可引用的引擎事件 id（referenced_event_ids 只能逐字取自这里，最多3个）:
{engine_event_ids}

输出格式:
{{
  "contract_version": 2,
  "referenced_event_ids": ["<本回合引擎事件 id，最多3个>"],
  "display_hint": "<不超过500字的展示提示或 null>",
  "confidence": 0.0
}}

语义要求：
- referenced_event_ids 只能引用上下文里已经出现过的本回合事件 id；没有就留空列表。
- 不得输出 candidate_events、state_deltas、effects、elapsed_minutes、time_category 或任何时间字段。"""
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def build_scene_event_prompt_v2(
    scene_id: str,
    scene_context: Dict[str, Any],
) -> List[LLMMessage]:
    """Build the production scene-stage prompt (reference-only)."""
    legal_actions = scene_context.get("deterministic_recommended_actions") or []
    system = (
        "你是一个文字RPG游戏的场景引擎。你只能组织引擎已经产生的结果，不能创造新的事实。\n"
        "推荐行动只能从引擎给出的合法推荐动作里挑选，不得自己编写新的行动文本。\n"
        f"{_STRICT_RULES}"
    )
    engine_event_ids = scene_context.get("engine_event_ids") or []
    user = f"""场景 id: {scene_id}
场景上下文: {scene_context}

本回合可引用的引擎事件 id（referenced_event_ids 只能逐字取自这里，最多3个）:
{engine_event_ids}

引擎给出的合法推荐动作（recommended_actions 只能逐字从这里挑选，最多4个）:
{legal_actions}

输出格式:
{{
  "contract_version": 2,
  "referenced_event_ids": ["<本回合引擎事件 id，最多3个>"],
  "recommended_actions": [],
  "display_hint": "<不超过500字的展示提示或 null>",
  "confidence": 0.0
}}

语义要求：
- 不得输出 candidate_events、state_deltas、effects、scene_name 或任何状态/时间字段。
- recommended_actions 里出现不在上面列表中的字符串时，该条会被引擎丢弃。"""
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def build_narration_prompt_v2(visible_context: Dict[str, Any]) -> List[LLMMessage]:
    """Build the production narration prompt (post-commit presentation only)."""
    system = (
        "你是一个文字RPG游戏的叙事引擎。请根据已提交的事实生成叙事文本。\n"
        "只能描述玩家可见的信息，不能泄露隐藏的秘密，也不能发明未提交的事实。\n"
        f"{_STRICT_RULES}"
    )
    user = f"""可见上下文: {visible_context}

输出格式:
{{
  "contract_version": 2,
  "text": "叙事文本内容（一段生动的中文描述，100-300字）",
  "confidence": 0.0
}}"""
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


#: Proposal type key -> production prompt builder signature marker.
PRODUCTION_PROMPT_BUILDERS = {
    "input_intent": build_player_intent_prompt_v2,
    "npc_action": build_npc_action_prompt_v2,
    "world_tick": build_world_tick_prompt_v2,
    "scene_event": build_scene_event_prompt_v2,
    "narration": build_narration_prompt_v2,
}


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
                    needs_clarification=data.get("needs_clarification", False),
                    clarification_question=data.get("clarification_question"),
                    visibility=data.get("visibility", "player_visible"),
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
                    recommended_actions=data.get("recommended_actions", []),
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
                    used_memory_ids=data.get("used_memory_ids", []),
                    new_memory_candidates=data.get("new_memory_candidates", []),
                    decision_audit=data.get("decision_audit"),
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
        except (KeyError, TypeError) as e:
            # A *required* field missing from the parsed payload raises here (the
            # construction reads it directly) rather than as a pydantic
            # ValidationError. That is still a schema failure of the model's output,
            # so it must be recorded as FAILED — otherwise an invalid response is
            # indistinguishable from a valid one in the audit trail. This path is
            # non-production/legacy only: the production chain uses
            # ``generate_production_proposal`` and never reaches lenient repair.
            validation_errors_list = [f"missing or invalid field: {e!r}"]
            audit.validation_status = ValidationStatus.FAILED
            audit.validation_errors = validation_errors_list

            return self._create_fallback(
                proposal_type=proposal_type,
                reason=f"Schema validation failed: {e!r}",
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
        memory_section = ""
        retrieved_memories = npc_context.get("retrieved_private_memories")
        if retrieved_memories:
            memory_section = f"""
NPC检索到的私有记忆:
{retrieved_memories}

"""

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是一个文字RPG游戏的NPC引擎。请根据NPC的上下文和记忆生成行动提案。\n"
                    "\n"
                    "【记忆优先规则 - 必须严格遵守】\n"
                    "1. 只能基于NPC当前可见事实和retrieved_private_memories做出决策\n"
                    "2. 如果没有相关记忆，不得虚构经历\n"
                    "3. major NPC的非idle/observe行为必须引用至少一个used_memory_ids\n"
                    "4. new_memory_candidates必须使用第一人称视角\n"
                    "5. summary和visible_motivation不得泄露玩家不可见秘密"
                ),
            ),
            LLMMessage(
                role="user",
                content=f"""NPC ID: {npc_id}
NPC上下文: {npc_context}
{memory_section}请严格按照以下JSON格式输出NPC行动提案，不要添加任何额外字段：
{{
  "npc_id": "{npc_id}",
  "action_type": "interact|observe|move|idle|dialogue|attack",
  "target": "目标对象（如果有）",
  "summary": "NPC行动的简短描述（一句话）",
  "visible_motivation": "玩家可见的动机说明",
  "visibility": "player_visible|hidden|gm_only",
  "confidence": 0.0到1.0之间的数值,
  "used_memory_ids": ["本次决策引用的记忆ID列表"],
  "new_memory_candidates": [
    {{
      "memory_text": "第一人称视角的新记忆文本",
      "knowledge_source": "记忆来源类型",
      "source_turn_no": 当前回合号,
      "salience": 0.0到1.0之间的显著度,
      "confidence": 0.0到1.0之间的置信度,
      "tags": ["标签列表"]
    }}
  ],
  "decision_audit": {{
    "reasoning_basis": "决策推理依据",
    "memory_count_used": 引用的记忆数量,
    "fallback_used": false
  }}
}}""",
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
    
    async def generate_narration_streaming(
        self,
        visible_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
        on_delta: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> NarrationProposal:
        """
        Generate NarrationProposal with streaming text chunks.
        
        Uses LLMService.stream_generate() to yield chunks as they become
        available. Accumulates all chunks into full text, then builds and
        validates a normal NarrationProposal with the same leak/empty checks.
        
        If the provider does not support streaming (StreamingNotSupportedError),
        falls back to the non-streaming generate_narration() method and emits
        a ``stream_fallback`` event via ``on_event`` if provided.
        
        Args:
            visible_context: Player-visible context dict
            prompt_template_id: Optional prompt template ID
            session_id: Game session ID for audit
            turn_no: Turn number for audit
            on_delta: Optional callback invoked for each text chunk.
                      Each chunk is a string. The callback is called
                      synchronously (not awaited) to avoid reordering.
            on_event: Optional callback invoked with dict events during streaming.
                      Emitted events: ``{"event": "stream_fallback", "data": {"message": ...}}``
        
        Returns:
            NarrationProposal (validated, with full text)
        """
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
        
        accumulated_chunks: list[str] = []
        
        try:
            async for chunk in self._llm_service.stream_generate(
                messages=messages,
                template_id=prompt_template_id,
                session_id=session_id,
                turn_no=turn_no,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
            ):
                accumulated_chunks.append(chunk)
                if on_delta:
                    on_delta(chunk)
        except StreamingNotSupportedError:
            if on_event:
                on_event({
                    "event": "stream_fallback",
                    "data": {"message": "Provider does not support streaming, using fallback generation"},
                })
            return await self.generate_narration(
                visible_context=visible_context,
                prompt_template_id=prompt_template_id,
                session_id=session_id,
                turn_no=turn_no,
            )
        
        full_text = "".join(accumulated_chunks)
        
        if not full_text.strip():
            # Empty streaming result - use fallback
            return create_fallback_narration(reason="Streaming produced empty text")
        
        proposal = NarrationProposal(
            text=full_text,
            confidence=1.0,  # Confidence is unknown for streaming
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.NARRATION,
                source_engine=ProposalSource.NARRATION_ENGINE,
                prompt_template_id=prompt_template_id,
                validation_status=ValidationStatus.PASSED,
            ),
        )
        
        return proposal

    # ------------------------------------------------------------------
    # Production strict-contract path (contract_version=2)
    # ------------------------------------------------------------------
    #
    # This is the only path the authoritative turn service uses. It shares the
    # LLM call, timeout and audit metadata with ``generate_proposal`` but never
    # reaches the lenient repair handler: a proposal that does not satisfy the
    # v2 contract is reported with a stable reason code and the caller falls
    # back deterministically.

    async def generate_production_proposal(
        self,
        proposal_type: str,
        prompt_messages: List[LLMMessage],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> ProductionContractOutcome:
        """Call the model and validate its output against the v2 contract.

        Args:
            proposal_type: Production proposal key (``input_intent``,
                ``npc_action``, ``world_tick``, ``scene_event``, ``narration``).
            prompt_messages: The production prompt messages.
            prompt_template_id: Template id, recorded for audit only.
            session_id: Game session id, recorded for audit only.
            turn_no: Turn number, recorded for audit only.

        Returns:
            A :class:`ProductionContractOutcome`. Never raises for a bad model
            output: contract violations and provider failures are reported as
            reason codes so the caller can fall back safely.
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
        except asyncio.TimeoutError:
            return ProductionContractOutcome(
                reason_code=CONTRACT_UNAVAILABLE,
                detail="Timeout exceeded",
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as exc:  # provider/transport failure: no output at all
            return ProductionContractOutcome(
                reason_code=CONTRACT_UNAVAILABLE,
                detail=f"{type(exc).__name__}: {str(exc)[:200]}",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        latency_ms = int((time.time() - start_time) * 1000)
        raw_output = response.content or ""

        try:
            contract = validate_production_contract(proposal_type, raw_output)
        except ContractViolation as violation:
            return ProductionContractOutcome(
                reason_code=violation.code.value,
                detail=violation.detail,
                latency_ms=latency_ms,
                model_name=getattr(response, "model", "") or "",
                input_tokens=response.usage.get("prompt_tokens", 0),
                output_tokens=response.usage.get("completion_tokens", 0),
                raw_output_preview=raw_output[:200],
            )

        return ProductionContractOutcome(
            contract=contract,
            latency_ms=latency_ms,
            model_name=getattr(response, "model", "") or "",
            input_tokens=response.usage.get("prompt_tokens", 0),
            output_tokens=response.usage.get("completion_tokens", 0),
            raw_output_preview=raw_output[:200],
        )

    async def generate_player_intent_production(
        self,
        raw_input: str,
        context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> ProductionContractOutcome:
        """Production player-intent proposal (``PlayerIntentV2``)."""
        return await self.generate_production_proposal(
            proposal_type="input_intent",
            prompt_messages=build_player_intent_prompt_v2(raw_input, context),
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
        )

    async def generate_npc_action_production(
        self,
        npc_id: str,
        npc_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> ProductionContractOutcome:
        """Production NPC-action proposal (``NPCActionV2``)."""
        return await self.generate_production_proposal(
            proposal_type="npc_action",
            prompt_messages=build_npc_action_prompt_v2(npc_id, npc_context),
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
        )

    async def generate_world_tick_production(
        self,
        world_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> ProductionContractOutcome:
        """Production world-stage proposal (``WorldTickV2``)."""
        return await self.generate_production_proposal(
            proposal_type="world_tick",
            prompt_messages=build_world_tick_prompt_v2(world_context),
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
        )

    async def generate_scene_event_production(
        self,
        scene_id: str,
        scene_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> ProductionContractOutcome:
        """Production scene-stage proposal (``SceneEventV2``)."""
        return await self.generate_production_proposal(
            proposal_type="scene_event",
            prompt_messages=build_scene_event_prompt_v2(scene_id, scene_context),
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
        )

    async def generate_narration_production(
        self,
        visible_context: Dict[str, Any],
        prompt_template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
    ) -> ProductionContractOutcome:
        """Production narration proposal (``NarrationV2``)."""
        return await self.generate_production_proposal(
            proposal_type="narration",
            prompt_messages=build_narration_prompt_v2(visible_context),
            prompt_template_id=prompt_template_id,
            session_id=session_id,
            turn_no=turn_no,
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
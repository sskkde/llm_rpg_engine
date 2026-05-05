"""
Centralized LLM Service with Audit Logging

This module provides:
- Unified interface for all LLM operations
- Audit logging with model_call_logs persistence
- Prompt template management
- Output parsing integration
- Support for both sync and streaming responses
"""

import hashlib
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """A single message in an LLM conversation."""
    role: str
    content: str


class LLMResponse(BaseModel):
    """Standardized LLM response."""
    content: str
    model: str
    usage: Dict[str, int] = Field(default_factory=dict)
    finish_reason: str = "stop"


class LLMCallLog(BaseModel):
    """Log entry for a model call."""
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    turn_no: int = 0
    prompt_template_id: Optional[str] = None
    input_hash: str = ""
    prompt_content: str = ""
    response_content: str = ""
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0
    error: Optional[str] = None
    created_at: str = Field(default_factory=lambda: str(uuid.uuid4()))


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> LLMResponse:
        """Generate a complete response."""
        pass
    
    @abstractmethod
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming response."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o", base_url: Optional[str] = None, temperature: Optional[float] = None, max_tokens: Optional[int] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = base_url
        self._client = None
    
    def _get_client(self):
        if self._client is None:
            try:
                import openai
                kwargs: Dict[str, Any] = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = openai.AsyncOpenAI(**kwargs)
            except ImportError:
                raise ImportError("openai package required for OpenAIProvider")
        return self._client
    
    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> LLMResponse:
        client = self._get_client()
        
        response = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            finish_reason=response.choices[0].finish_reason or "stop",
        )
    
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        client = self._get_client()
        
        stream = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class MockLLMProvider(LLMProvider):
    """Mock provider for testing - no API keys required."""
    
    def __init__(self, responses: Optional[Dict[str, str]] = None):
        self.responses = responses or {}
        self.call_count = 0
        self.model = "mock-model"
    
    def _get_response(self, messages: List[LLMMessage]) -> str:
        """Get a mock response based on message content."""
        content = " ".join(m.content for m in messages)
        content_lower = content.lower()
        
        # Check for predefined responses
        for key, response in self.responses.items():
            if key.lower() in content_lower:
                return response
        
        # Default responses based on content patterns
        if "narrate" in content_lower or "describe" in content_lower or "narration" in content_lower:
            return "古老的山门广场铺满了青石板，岁月在上面留下了深深的痕迹。远处传来钟声，回荡在山谷之间。"
        elif "npc" in content_lower or "decision" in content_lower or "action" in content_lower:
            return json.dumps({
                "action_type": "observe",
                "target": "player",
                "summary": "NPC observes the player curiously",
                "confidence": 0.8
            })
        elif "intent" in content_lower or "parse" in content_lower:
            return json.dumps({
                "intent_type": "explore",
                "target": "surroundings",
                "risk_level": "low"
            })
        elif "summary" in content_lower:
            return "The player explored the area and discovered ancient ruins."
        elif "lore" in content_lower:
            return json.dumps({
                "discovered": True,
                "lore_id": "ancient_ruins",
                "description": "These ruins date back to the First Dynasty."
            })
        else:
            return "Mock LLM response for: " + content[:50]
    
    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> LLMResponse:
        self.call_count += 1
        content = self._get_response(messages)
        
        return LLMResponse(
            content=content,
            model=self.model,
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            finish_reason="stop",
        )
    
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        self.call_count += 1
        content = self._get_response(messages)
        
        # Simulate streaming by yielding word by word
        words = content.split()
        for word in words:
            yield word + " "


class PromptTemplate:
    """Template for LLM prompts with variable substitution."""
    
    def __init__(self, template_id: str, template: str, description: str = ""):
        self.template_id = template_id
        self.template = template
        self.description = description
        self._variables = self._extract_variables()
    
    def _extract_variables(self) -> List[str]:
        """Extract variable names from template."""
        import re
        pattern = r'\{(\w+)\}'
        return list(set(re.findall(pattern, self.template)))
    
    def render(self, **kwargs) -> str:
        """Render template with variables."""
        result = self.template
        for key, value in kwargs.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result
    
    @property
    def variables(self) -> List[str]:
        return self._variables


# Standard prompt templates
NARRATION_PROMPT_TEMPLATE = PromptTemplate(
    template_id="narration_v1",
    description="Generate narrative text for the player",
    template="""你是一个文字RPG的叙事者。请根据以下信息生成一段引人入胜的叙事文本。

场景信息：
{scene_info}

玩家状态：
{player_state}

最近事件：
{recent_events}

玩家行动：{player_action}

文风要求：{style}

要求：
1. 只描述玩家可以看到的信息
2. 不要泄露隐藏的秘密
3. 保持文风一致
4. 营造适当的氛围"""
)

NPC_DECISION_PROMPT_TEMPLATE = PromptTemplate(
    template_id="npc_decision_v1",
    description="Generate NPC decision based on context",
    template="""你是NPC {npc_name}，请根据以下信息决定你的行动。

性格：{personality}
目标：{goals}
当前情绪：{mood}

已知信息：
{known_facts}

当前场景：
{scene_context}

请输出JSON格式：
{{
    "action_type": "行动类型",
    "target": "目标",
    "summary": "行动描述",
    "confidence": 0.8
}}"""
)

INTENT_PARSING_PROMPT_TEMPLATE = PromptTemplate(
    template_id="intent_parsing_v1",
    description="Parse player input into structured intent",
    template="""解析玩家输入的行动意图。

玩家输入：{player_input}

请输出JSON格式：
{{
    "intent_type": "意图类型（move/talk/attack/inspect/interact/idle）",
    "target": "目标对象",
    "risk_level": "风险等级（low/medium/high）"
}}"""
)

SUMMARY_PROMPT_TEMPLATE = PromptTemplate(
    template_id="summary_v1",
    description="Generate summary of recent events",
    template="""请为以下游戏事件生成简洁摘要。

时间范围：{time_range}
事件：
{events}

要求：
1. 客观简洁
2. 突出关键事件
3. 不超过3句话"""
)

LORE_DISCOVERY_PROMPT_TEMPLATE = PromptTemplate(
    template_id="lore_discovery_v1",
    description="Generate lore discovery based on clues",
    template="""玩家发现了新的世界观信息。

已知信息：
{known_lore}

新线索：
{new_clues}

请输出JSON格式：
{{
    "discovered": true/false,
    "lore_id": "知识ID",
    "description": "知识描述"
}}"""
)


class LLMService:
    """
    Centralized LLM service with audit logging.
    
    This service:
    - Manages LLM provider lifecycle
    - Provides prompt template management
    - Logs all calls to model_call_logs
    - Integrates with output parsers
    """
    
    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        db_session: Optional[Any] = None,
    ):
        self._provider = provider
        self._db_session = db_session
        self._templates: Dict[str, PromptTemplate] = {}
        self._call_logs: List[LLMCallLog] = []
        self._register_default_templates()
    
    def _register_default_templates(self):
        """Register default prompt templates."""
        templates = [
            NARRATION_PROMPT_TEMPLATE,
            NPC_DECISION_PROMPT_TEMPLATE,
            INTENT_PARSING_PROMPT_TEMPLATE,
            SUMMARY_PROMPT_TEMPLATE,
            LORE_DISCOVERY_PROMPT_TEMPLATE,
        ]
        for template in templates:
            self._templates[template.template_id] = template
    
    def set_provider(self, provider: LLMProvider):
        """Set the LLM provider."""
        self._provider = provider
    
    def register_template(self, template: PromptTemplate):
        """Register a custom prompt template."""
        self._templates[template.template_id] = template
    
    def get_template(self, template_id: str) -> Optional[PromptTemplate]:
        """Get a prompt template by ID."""
        return self._templates.get(template_id)
    
    def _compute_input_hash(self, prompt: str) -> str:
        """Compute hash of input for auditing."""
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]
    
    def _estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost of the API call."""
        # Simple cost estimation (can be refined with actual pricing)
        pricing = {
            "gpt-4o": {"input": 0.005, "output": 0.015},
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
            "mock-model": {"input": 0, "output": 0},
        }
        
        model_pricing = pricing.get(model, pricing["gpt-3.5-turbo"])
        input_cost = (input_tokens / 1000) * model_pricing["input"]
        output_cost = (output_tokens / 1000) * model_pricing["output"]
        
        return round(input_cost + output_cost, 6)
    
    def _persist_call_log(self, log: LLMCallLog):
        """Persist call log to database if available."""
        db_error = None
        if self._db_session is not None:
            try:
                from ..storage.models import ModelCallLogModel
                
                db_log = ModelCallLogModel(
                    id=log.log_id,
                    session_id=log.session_id,
                    turn_no=log.turn_no,
                    provider=log.provider,
                    model_name=log.model,
                    prompt_type=log.prompt_template_id,
                    input_tokens=log.input_tokens,
                    output_tokens=log.output_tokens,
                    cost_estimate=log.cost_estimate,
                    latency_ms=log.latency_ms,
                )
                self._db_session.add(db_log)
                self._db_session.commit()
            except Exception as e:
                db_error = str(e)
                try:
                    self._db_session.rollback()
                except:
                    pass
        
        self._call_logs.append(log)
        
        if db_error:
            log.error = f"DB persistence failed: {db_error}"
            if self._db_session is not None:
                print(f"Failed to persist call log: {db_error}")
    
    async def generate(
        self,
        messages: List[LLMMessage],
        template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> LLMResponse:
        """
        Generate LLM response with audit logging.
        
        Args:
            messages: List of messages for the conversation
            template_id: Optional prompt template ID for tracking
            session_id: Optional session ID for context
            turn_no: Current turn number
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            LLMResponse with content and metadata
        """
        if self._provider is None:
            raise ValueError("No LLM provider configured")
        
        # Prepare prompt for hashing
        prompt_content = "\n".join(f"{m.role}: {m.content}" for m in messages)
        input_hash = self._compute_input_hash(prompt_content)
        
        # Start timing
        start_time = time.time()
        
        try:
            # Call the provider
            response = await self._provider.generate(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Create call log
            log = LLMCallLog(
                session_id=session_id,
                turn_no=turn_no,
                prompt_template_id=template_id,
                input_hash=input_hash,
                prompt_content=prompt_content[:1000],  # Truncate for storage
                response_content=response.content[:1000],  # Truncate for storage
                model=response.model,
                provider=self._provider.__class__.__name__,
                latency_ms=latency_ms,
                input_tokens=response.usage.get("prompt_tokens", 0),
                output_tokens=response.usage.get("completion_tokens", 0),
                cost_estimate=self._estimate_cost(
                    response.model,
                    response.usage.get("prompt_tokens", 0),
                    response.usage.get("completion_tokens", 0),
                ),
            )
            
            # Persist log
            self._persist_call_log(log)
            
            return response
            
        except Exception as e:
            # Calculate latency even on error
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Create error log
            log = LLMCallLog(
                session_id=session_id,
                turn_no=turn_no,
                prompt_template_id=template_id,
                input_hash=input_hash,
                prompt_content=prompt_content[:1000],
                response_content="",
                model=getattr(self._provider, 'model', 'unknown'),
                provider=self._provider.__class__.__name__,
                latency_ms=latency_ms,
                error=str(e),
            )
            
            # Persist error log
            self._persist_call_log(log)
            
            raise
    
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        template_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_no: int = 0,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming LLM response with audit logging.
        
        Yields text chunks as they are generated.
        Audit log is created after stream completes.
        """
        if self._provider is None:
            raise ValueError("No LLM provider configured")
        
        # Prepare prompt for hashing
        prompt_content = "\n".join(f"{m.role}: {m.content}" for m in messages)
        input_hash = self._compute_input_hash(prompt_content)
        
        # Start timing
        start_time = time.time()
        model_name = getattr(self._provider, 'model', 'unknown')
        provider_name = self._provider.__class__.__name__
        
        accumulated_content = []
        
        try:
            async for chunk in self._provider.generate_stream(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            ):
                accumulated_content.append(chunk)
                yield chunk
            
            # Calculate latency after stream completes
            latency_ms = int((time.time() - start_time) * 1000)
            full_content = "".join(accumulated_content)
            
            # Estimate tokens (rough approximation)
            input_tokens = len(prompt_content) // 4
            output_tokens = len(full_content) // 4
            
            # Create call log
            log = LLMCallLog(
                session_id=session_id,
                turn_no=turn_no,
                prompt_template_id=template_id,
                input_hash=input_hash,
                prompt_content=prompt_content[:1000],
                response_content=full_content[:1000],
                model=model_name,
                provider=provider_name,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_estimate=self._estimate_cost(model_name, input_tokens, output_tokens),
            )
            
            # Persist log
            self._persist_call_log(log)
            
        except Exception as e:
            # Calculate latency even on error
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Create error log
            log = LLMCallLog(
                session_id=session_id,
                turn_no=turn_no,
                prompt_template_id=template_id,
                input_hash=input_hash,
                prompt_content=prompt_content[:1000],
                response_content="",
                model=model_name,
                provider=provider_name,
                latency_ms=latency_ms,
                error=str(e),
            )
            
            # Persist error log
            self._persist_call_log(log)
            
            raise
    
    async def generate_with_template(
        self,
        template_id: str,
        template_vars: Dict[str, Any],
        session_id: Optional[str] = None,
        turn_no: int = 0,
        system_message: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate using a registered prompt template.
        
        Args:
            template_id: ID of the registered template
            template_vars: Variables to substitute in the template
            session_id: Optional session ID
            turn_no: Current turn number
            system_message: Optional system message
            
        Returns:
            LLMResponse
        """
        template = self.get_template(template_id)
        if template is None:
            raise ValueError(f"Template not found: {template_id}")
        
        # Render the template
        prompt = template.render(**template_vars)
        
        # Build messages
        messages = []
        if system_message:
            messages.append(LLMMessage(role="system", content=system_message))
        messages.append(LLMMessage(role="user", content=prompt))
        
        return await self.generate(
            messages=messages,
            template_id=template_id,
            session_id=session_id,
            turn_no=turn_no,
            **kwargs
        )
    
    async def generate_stream_with_template(
        self,
        template_id: str,
        template_vars: Dict[str, Any],
        session_id: Optional[str] = None,
        turn_no: int = 0,
        system_message: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming response using a registered prompt template.
        
        Yields text chunks as they are generated.
        """
        template = self.get_template(template_id)
        if template is None:
            raise ValueError(f"Template not found: {template_id}")
        
        # Render the template
        prompt = template.render(**template_vars)
        
        # Build messages
        messages = []
        if system_message:
            messages.append(LLMMessage(role="system", content=system_message))
        messages.append(LLMMessage(role="user", content=prompt))
        
        async for chunk in self.generate_stream(
            messages=messages,
            template_id=template_id,
            session_id=session_id,
            turn_no=turn_no,
            **kwargs
        ):
            yield chunk
    
    def get_call_logs(
        self,
        session_id: Optional[str] = None,
        turn_no: Optional[int] = None,
    ) -> List[LLMCallLog]:
        """Get call logs, optionally filtered."""
        logs = self._call_logs
        
        if session_id:
            logs = [log for log in logs if log.session_id == session_id]
        
        if turn_no is not None:
            logs = [log for log in logs if log.turn_no == turn_no]
        
        return logs
    
    def get_total_cost(self, session_id: Optional[str] = None) -> float:
        """Get total cost of calls."""
        logs = self.get_call_logs(session_id=session_id)
        return sum(log.cost_estimate for log in logs)
    
    def clear_logs(self):
        """Clear in-memory call logs (for testing)."""
        self._call_logs.clear()


# Global service instance
_llm_service: Optional[LLMService] = None


def get_llm_service(
    provider: Optional[LLMProvider] = None,
    db_session: Optional[Any] = None,
) -> LLMService:
    """Get or create the global LLM service instance."""
    global _llm_service
    
    if _llm_service is None:
        _llm_service = LLMService(provider=provider, db_session=db_session)
    elif provider is not None:
        _llm_service.set_provider(provider)
    
    return _llm_service


def reset_llm_service():
    """Reset the global LLM service (for testing)."""
    global _llm_service
    _llm_service = None

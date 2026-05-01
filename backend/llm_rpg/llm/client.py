import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    usage: Dict[str, int] = {}
    finish_reason: str = "stop"


class LLMProvider(ABC):
    
    @abstractmethod
    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> LLMResponse:
        pass
    
    @abstractmethod
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ):
        pass


class OpenAIProvider(LLMProvider):
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self._client = None
    
    def _get_client(self):
        if self._client is None:
            import openai
            self._client = openai.AsyncOpenAI(api_key=self.api_key)
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
            content=response.choices[0].message.content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            finish_reason=response.choices[0].finish_reason,
        )
    
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ):
        client = self._get_client()
        
        stream = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class LocalLLMProvider(LLMProvider):
    
    def __init__(self, model_path: str = "models/llm"):
        self.model_path = model_path
        self._model = None
    
    def _load_model(self):
        if self._model is None:
            pass
    
    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> LLMResponse:
        self._load_model()
        
        return LLMResponse(
            content="本地LLM响应",
            model="local",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ):
        self._load_model()
        
        yield "本地"


class LLMManager:
    
    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}
        self._default_provider: Optional[str] = None
    
    def register_provider(self, name: str, provider: LLMProvider, is_default: bool = False):
        self._providers[name] = provider
        if is_default or self._default_provider is None:
            self._default_provider = name
    
    def get_provider(self, name: Optional[str] = None) -> LLMProvider:
        provider_name = name or self._default_provider
        if provider_name is None or provider_name not in self._providers:
            raise ValueError(f"LLM provider not found: {provider_name}")
        return self._providers[provider_name]
    
    async def generate(
        self,
        messages: List[LLMMessage],
        provider: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        llm = self.get_provider(provider)
        return await llm.generate(messages, **kwargs)
    
    async def generate_stream(
        self,
        messages: List[LLMMessage],
        provider: Optional[str] = None,
        **kwargs
    ):
        llm = self.get_provider(provider)
        async for chunk in llm.generate_stream(messages, **kwargs):
            yield chunk
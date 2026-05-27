import pytest

from llm_rpg.llm.service import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMService,
    MockLLMProvider,
    StreamingNotSupportedError,
)

MOCK_STREAM_TEXT = (
    "凌月站在试炼堂门口，目光如炬。\n\n"
    "她缓缓开口：\"师弟，你终于来了。\"\n\n"
    "周围的灵气开始涌动。"
)


async def _collect(gen):
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return chunks


class TestMockProviderYieldsMultipleChunks:
    @pytest.mark.asyncio
    async def test_yields_multiple_chunks(self):
        provider = MockLLMProvider()
        messages = [LLMMessage(role="user", content="narrate the scene")]
        chunks = await _collect(provider.stream_generate(messages=messages))
        assert len(chunks) >= 2
        assert "".join(chunks) == MOCK_STREAM_TEXT

    @pytest.mark.asyncio
    async def test_each_chunk_non_empty(self):
        provider = MockLLMProvider()
        messages = [LLMMessage(role="user", content="narrate")]
        chunks = await _collect(provider.stream_generate(messages=messages))
        for chunk in chunks:
            assert len(chunk) > 0


class TestStreamGenerateConcatenatedText:
    @pytest.mark.asyncio
    async def test_concatenated_text_matches_full(self):
        provider = MockLLMProvider()
        messages = [LLMMessage(role="user", content="describe")]
        chunks = await _collect(provider.stream_generate(messages=messages))
        assert "".join(chunks) == MOCK_STREAM_TEXT

    @pytest.mark.asyncio
    async def test_concatenated_text_non_empty(self):
        provider = MockLLMProvider()
        messages = [LLMMessage(role="user", content="test")]
        chunks = await _collect(provider.stream_generate(messages=messages))
        assert "".join(chunks) != ""


class TestLLMServiceDelegatesStreamGenerate:
    @pytest.mark.asyncio
    async def test_delegates_to_provider(self):
        provider = MockLLMProvider()
        service = LLMService(provider=provider)
        messages = [LLMMessage(role="user", content="narrate")]
        chunks = await _collect(service.stream_generate(messages=messages))
        assert len(chunks) >= 2
        assert "".join(chunks) == MOCK_STREAM_TEXT

    @pytest.mark.asyncio
    async def test_no_provider_raises_value_error(self):
        service = LLMService(provider=None)
        messages = [LLMMessage(role="user", content="test")]
        with pytest.raises(ValueError, match="No LLM provider"):
            await _collect(service.stream_generate(messages=messages))


class TestStreamUnsupportedSignal:
    @pytest.mark.asyncio
    async def test_base_provider_raises_not_supported(self):
        class StubProvider(LLMProvider):
            async def generate(self, messages, temperature=0.7, max_tokens=1000, **kwargs):
                return LLMResponse(content="stub", model="stub", usage={})

            async def generate_stream(self, messages, temperature=0.7, max_tokens=1000, **kwargs):
                yield "stub"

        provider = StubProvider()
        messages = [LLMMessage(role="user", content="test")]
        with pytest.raises(StreamingNotSupportedError, match="StubProvider"):
            await _collect(provider.stream_generate(messages=messages))

    @pytest.mark.asyncio
    async def test_service_propagates_not_supported(self):
        class StubProvider(LLMProvider):
            async def generate(self, messages, temperature=0.7, max_tokens=1000, **kwargs):
                return LLMResponse(content="stub", model="stub", usage={})

            async def generate_stream(self, messages, temperature=0.7, max_tokens=1000, **kwargs):
                yield "stub"

        service = LLMService(provider=StubProvider())
        messages = [LLMMessage(role="user", content="test")]
        with pytest.raises(StreamingNotSupportedError):
            await _collect(service.stream_generate(messages=messages))


class TestExistingGenerateUnchanged:
    @pytest.mark.asyncio
    async def test_generate_still_works(self):
        provider = MockLLMProvider()
        service = LLMService(provider=provider)
        messages = [LLMMessage(role="user", content="narrate the scene")]
        response = await service.generate(messages=messages)
        assert response.content != ""
        assert "古老" in response.content or "山门" in response.content

    @pytest.mark.asyncio
    async def test_generate_stream_still_works(self):
        provider = MockLLMProvider()
        service = LLMService(provider=provider)
        messages = [LLMMessage(role="user", content="narrate")]
        chunks = []
        async for chunk in service.generate_stream(messages=messages):
            chunks.append(chunk)
        assert len(chunks) >= 1
        assert "".join(chunks).strip() != ""
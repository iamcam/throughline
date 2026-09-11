# tests/unit/test_llm_client.py

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.client import OpenAICompatibleEmbeddingClient, OpenAICompatibleLLMClient


def _completion_response(content: str | None = "hello", finish_reason: str = "stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=finish_reason,
            )
        ]
    )


async def _empty_async_stream():
    return
    yield  # pragma: no cover


def _make_client(model: str) -> tuple[OpenAICompatibleLLMClient, AsyncMock]:
    """Builds a real OpenAICompatibleLLMClient with a mocked AsyncOpenAI
    underneath it, and returns (client, create_mock) so tests can inspect
    exactly what kwargs create() was called with."""
    with patch("src.llm.client.AsyncOpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        client = OpenAICompatibleLLMClient(base_url="http://fake", api_key="key", model=model)
    create_mock = AsyncMock(return_value=_completion_response())
    client._client.chat.completions.create = create_mock
    return client, create_mock


@pytest.mark.parametrize("model", ["gpt-5", "gpt-5.6-luna"])
async def test_complete_omits_temperature_for_gpt5_plus(model):
    client, create_mock = _make_client(model)
    await client.complete(messages=[{"role": "user", "content": "hi"}])
    assert "temperature" not in create_mock.call_args.kwargs


async def test_complete_includes_temperature_for_non_reasoning_model():
    client, create_mock = _make_client("gpt-4o")
    await client.complete(messages=[{"role": "user", "content": "hi"}], temperature=0.3)
    assert create_mock.call_args.kwargs["temperature"] == 0.3


async def test_complete_adds_reasoning_effort_none_with_tools_for_gpt5_plus():
    client, create_mock = _make_client("gpt-5")
    await client.complete(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
    )
    assert create_mock.call_args.kwargs["reasoning_effort"] == "none"


async def test_complete_no_reasoning_effort_without_tools_for_gpt5_plus():
    client, create_mock = _make_client("gpt-5")
    await client.complete(messages=[{"role": "user", "content": "hi"}])
    assert "reasoning_effort" not in create_mock.call_args.kwargs


async def test_complete_no_reasoning_effort_for_non_reasoning_model_with_tools():
    client, create_mock = _make_client("gpt-4o")
    await client.complete(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
    )
    assert "reasoning_effort" not in create_mock.call_args.kwargs


async def test_stream_omits_temperature_for_gpt5_plus():
    client, _ = _make_client("gpt-5")
    client._client.chat.completions.create = AsyncMock(return_value=_empty_async_stream())
    async for _ in client.stream(messages=[{"role": "user", "content": "hi"}]):
        pass
    create_mock = client._client.chat.completions.create
    assert "temperature" not in create_mock.call_args.kwargs


async def test_stream_adds_reasoning_effort_none_with_tools_for_gpt5_plus():
    client, _ = _make_client("gpt-5")
    client._client.chat.completions.create = AsyncMock(return_value=_empty_async_stream())
    async for _ in client.stream(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
    ):
        pass
    create_mock = client._client.chat.completions.create
    assert create_mock.call_args.kwargs["reasoning_effort"] == "none"


async def test_stream_includes_temperature_for_non_reasoning_model():
    client, _ = _make_client("gpt-4o")
    client._client.chat.completions.create = AsyncMock(return_value=_empty_async_stream())
    async for _ in client.stream(messages=[{"role": "user", "content": "hi"}], temperature=0.5):
        pass
    create_mock = client._client.chat.completions.create
    assert create_mock.call_args.kwargs["temperature"] == 0.5


async def test_embedding_client_passes_dimensions_through():
    with patch("src.llm.client.AsyncOpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        client = OpenAICompatibleEmbeddingClient(
            base_url="http://fake", api_key="key", model="embed-model", dimensions=768
        )
    embed_response = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2], index=0)]
    )
    create_mock = AsyncMock(return_value=embed_response)
    client._client.embeddings.create = create_mock

    result = await client.embed(["some text"])

    assert result == [[0.1, 0.2]]
    assert create_mock.call_args.kwargs["dimensions"] == 768
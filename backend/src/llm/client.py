# src/llm/client.py
from collections.abc import AsyncIterator

from openai import AsyncOpenAI
from src.llm.base import LLMResponse, StreamChunk, ToolCall, ToolCallDelta
import json
import logging

logger = logging.getLogger(__name__)

class OpenAICompatibleLLMClient:
    """
    Chat completion client for any OpenAI-compoatible endpoint.
    Works with Ollama, llama.cpp, vLLM, Together, OpenAI, and others.
    Configure with LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_NAME in .env
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict]| None = None,
        response_format: dict | None = None,
        temperature: float = 0.7
    ) -> LLMResponse:
        kwargs = dict(
            model=self._model,
            messages=messages,
            temperature=temperature,
        )
        if response_format:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        message = response.choices[0].message


        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    logger.info(f"Malformed tool call arguments json string: {tc.function.arguments}")
                    arguments = {}

                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                ))

        return LLMResponse(
            content=response.choices[0].message.content,
            tool_calls=tool_calls,
            finish_reason=response.choices[0].finish_reason
            )

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        kwargs = dict(
            model=self._model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools

        response_stream = await self._client.chat.completions.create(**kwargs)

        async for chunk in response_stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            tool_call_deltas = [
                ToolCallDelta(
                    index=tc.index,
                    id=tc.id,
                    name=tc.function.name if tc.function else None,
                    arguments_delta=tc.function.arguments if tc.function else None,
                )
                for tc in (delta.tool_calls or [])
            ]

            yield StreamChunk(
                content_delta=delta.content,
                tool_call_deltas=tool_call_deltas,
                finish_reason=choice.finish_reason,
            )

class OpenAICompatibleEmbeddingClient:
    """
    Embedding client for any OpenAI-compatible endpoint.
    Works with Ollama (nomic-embed-text), OpenAI, and others.
    Configure with EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL_NAME in .env
    """

    def __init__(self, base_url: str, api_key: str, model: str, dimensions: int):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=self._dimensions
        )
        # Response items are ordered by index, not by input order
        # Sort by index to guarantee alignment with input list
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


# src/llm/base.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    content: str


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse: ...


@runtime_checkable
class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
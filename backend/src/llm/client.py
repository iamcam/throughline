# src/llm/client.py
from openai import AsyncOpenAI
from src.llm.base import LLMResponse

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

        response = await self._client.chat.completions.create(**kwargs)
        return LLMResponse(content=response.choices[0].message.content)
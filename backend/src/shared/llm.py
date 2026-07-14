# src/shared/llm.py
from src.config import get_settings
from src.llm.client import OpenAICompatibleLLMClient, OpenAICompatibleEmbeddingClient

settings = get_settings()


def get_embedding_client() -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        base_url=settings.embedding_base_url or settings.llm_base_url,
        api_key=settings.embedding_api_key or settings.llm_api_key,
        model=settings.embedding_model_name,
    )


def get_llm_client() -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model_name,
    )
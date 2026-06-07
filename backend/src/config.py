from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import pytest

class Settings(BaseSettings):

    log_level: str | None = "WARN"
    huggingface_token: str | None

    # Database
    database_url: str
    cors_origins: str

    # LLM
    llm_base_url: str
    llm_api_key: str = "none"
    llm_model_name: str

    # Chunking
    chunk_size_tokens: int = 256
    chunk_overlap_tokens: int = 32
    chunk_min_tokens: int = 20
    topic_similarity_threshold: float = 0.75


    # Embeddings
    embedding_base_url: str = ""
    embedding_api_key: str = "none"
    embedding_model_name: str = "nomic-embed-text"
    embedding_dimensions: int = 768

    # Transcription
    diarization_model: str | None = None
    whisper_backend: str = "faster_whisper"
    whisper_model_size: str = "medium"
    transcription_backend: str = "local"

    speaker_inference_window_ms: int = 900_000

    # App
    log_level: str = "INFO"
    audio_storage_path: str = "./data/audio"
    max_concurrent_ingestions: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
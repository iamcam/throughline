# src/config.py
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pydantic import model_validator


class Settings(BaseSettings):
    # App
    log_level: str = "WARN"
    audio_storage_path: str = "./data/audio"
    max_concurrent_ingestions: int = 1  # in-process semaphore size, or streaQ concurrency when REDIS_URL is set

    huggingface_token: str | None = None

    # Database
    database_url: str
    cors_origins: str

    # Queue
    redis_url: str = ""  # empty = BackgroundTaskQueue; set = StreaqQueue
    transcription_max_workers: int = 1  # ProcessPoolExecutor size for local Whisper

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
    transcription_service_url: str = ""
    transcription_api_key: str | None = None

    whisper_backend: str = "faster_whisper"
    whisper_model: str = "medium"
    transcription_max_workers: int = 1  # ProcessPoolExecutor size for local Whisper

    diarization_model: str | None = None
    speaker_inference_window_ms: int = 900_000

    # Observability
    tracing_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"
    otel_api_key: str | None = None
    otel_project_name: str = "podcast-engine"

    # Demo auth
    demo_auth_enabled: bool = False
    demo_username: str = "demo"
    demo_password: str = "changeme"

    @model_validator(mode="after")
    def validate_demo_auth(self) -> "Settings":
        if self.demo_auth_enabled:
            if self.demo_username == "demo" or self.demo_password == "changeme":
                print("DEMO_AUTH_ENABLED=true requires DEMO_USERNAME and DEMO_PASSWORD "
                    "to be explicitly set to non-default values in .env")
                raise ValueError(
                    "DEMO_AUTH_ENABLED=true requires DEMO_USERNAME and DEMO_PASSWORD "
                    "to be explicitly set to non-default values in .env"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


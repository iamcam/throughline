# src/config.py
import sys
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pydantic import model_validator


class Settings(BaseSettings):
    # App
    testing: bool = "pytest" in sys.modules

    log_level: str = "WARN"
    audio_storage_path: str = "./data/audio"

    # Database
    database_url: str
    cors_origins: str

    # Queue
    redis_url: str = ""  # empty = BackgroundTaskQueue; set = StreaqQueue
    max_concurrent_ingestions: int = 1  # in-process semaphore size, or streaQ concurrency when REDIS_URL is set
    pipeline_max_workers: int = 1  # ProcessPoolExecutor size, shared by local Whisper and local Senko


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
    embedding_base_url: str = "" # empty - use LLM base url; OpenAI-compatible API client; "local" to run local embedding
    embedding_api_key: str = "" # empty - use LLM api key if not preseent
    embedding_model_name: str = "nomic-embed-text"
    embedding_dimensions: int = 768

    embedding_max_input_tokens: int = 8000

    # Transcription
    transcription_service_url: str = ""
    transcription_api_key: str | None = None

    transcription_min_segment_words: int = 5
    transcription_max_segment_tokens: int = 200
    transcription_pause_threshold_s: float = 1.2

    whisper_backend: str = "faster_whisper"
    whisper_model: str = "medium"
    speaker_inference_window_ms: int = 900_000
    speaker_inference_padding_ms: int = 60_000  # look-back before a speaker's first utterance, to catch how they were introduced

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


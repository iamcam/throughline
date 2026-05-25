from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    database_url: str
    cors_origins: str
    # LLM
    llm_base_url: str
    llm_api_key: str = "none"
    llm_model_name: str

    # Embeddings
    embedding_base_url: str = ""
    embedding_api_key: str = "none"
    embedding_model_name: str = "nomic-embed-text"
    embedding_dimensions: int = 768

    # App
    log_level: str = "INFO"
    audio_storage_path: str = "./data/audio"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
"""Runtime configuration.

Every Azure integration is optional. When a key is absent the platform degrades to a
local implementation (deterministic reasoner, browser speech, heuristic vision) so the
whole product is runnable on a laptop with no cloud account.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # ── core ────────────────────────────────────────────────────────────────
    shoppermind_env: str = "local"
    api_secret_key: str = "dev-only-insecure-key-change-me"
    access_token_ttl_minutes: int = 720
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://shoppermind:shoppermind@localhost:5432/shoppermind"

    # ── Azure OpenAI ────────────────────────────────────────────────────────
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2025-04-01-preview"
    azure_openai_chat_deployment: str = "gpt-5.4-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-large"

    # ── Azure AI Speech ─────────────────────────────────────────────────────
    azure_speech_key: str = ""
    azure_speech_region: str = "centralindia"
    azure_speech_voice: str = "en-IN-NeerjaNeural"

    # ── Azure AI Vision ─────────────────────────────────────────────────────
    azure_vision_endpoint: str = ""
    azure_vision_key: str = ""

    # ── Azure AI Language ───────────────────────────────────────────────────
    azure_language_endpoint: str = ""
    azure_language_key: str = ""

    # ── Azure Blob Storage ──────────────────────────────────────────────────
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "shoppermind-media"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def openai_enabled(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def speech_enabled(self) -> bool:
        return bool(self.azure_speech_key and self.azure_speech_region)

    @property
    def vision_enabled(self) -> bool:
        return bool(self.azure_vision_endpoint and self.azure_vision_key)

    @property
    def language_enabled(self) -> bool:
        return bool(self.azure_language_endpoint and self.azure_language_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

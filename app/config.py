"""
Application settings loaded from environment variables / .env file.

All settings are read once at import time so any misconfiguration
surfaces immediately on startup rather than at first request.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # LLM routing
    # ------------------------------------------------------------------
    LLM_PROVIDER: str = "groq"

    # ------------------------------------------------------------------
    # Groq
    # ------------------------------------------------------------------
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate_provider_secrets(self) -> "Settings":
        if self.LLM_PROVIDER == "groq" and not self.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is required when LLM_PROVIDER='groq'. "
                "Set it in your .env file or as an environment variable."
            )
        return self


settings = Settings()

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
    # Server Configuration
    # ------------------------------------------------------------------
    PORT: int = 8080
    GROQ_VALIDATOR_API_KEY: str | None = None  # Used for simple AuthN

    # ------------------------------------------------------------------
    # Data directories — platform-agnostic path abstraction.
    # EC2 sets DATA_DIR=/data (host-mounted EBS directory).
    # Locally, DATA_DIR is unset → defaults to "." → ./chroma_db as before.
    # LangGraph checkpoints are also stored in DATA_DIR/checkpoints.sqlite.
    # ------------------------------------------------------------------
    DATA_DIR: str = "."

    # ------------------------------------------------------------------
    # LLM routing — kept for single-provider mode backward compat,
    # but ask_llm() now uses LLM_FALLBACK_ORDER for the chain.
    # ------------------------------------------------------------------
    LLM_PROVIDER: str = "groq"

    # Ordered, comma-separated provider list tried left-to-right.
    # If a provider's API key is missing it is silently skipped.
    # Example: "groq,gemini"  or  "gemini,groq"
    LLM_FALLBACK_ORDER: str = "groq,gemini"

    # ------------------------------------------------------------------
    # Groq
    # ------------------------------------------------------------------
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ------------------------------------------------------------------
    # Google Gemini
    # ------------------------------------------------------------------
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ------------------------------------------------------------------
    # AWS (SQS Messaging + ECR)
    # ------------------------------------------------------------------
    AWS_REGION: str = "ap-south-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate_provider_secrets(self) -> "Settings":
        providers = [p.strip().lower() for p in self.LLM_FALLBACK_ORDER.split(",")]

        # At least one provider in the chain must have a key configured
        has_groq = "groq" in providers and bool(self.GROQ_API_KEY)
        has_gemini = "gemini" in providers and bool(self.GEMINI_API_KEY)

        if not has_groq and not has_gemini:
            raise ValueError(
                "No usable LLM provider found. "
                "Set GROQ_API_KEY and/or GEMINI_API_KEY in your .env file. "
                f"LLM_FALLBACK_ORDER is currently: '{self.LLM_FALLBACK_ORDER}'"
            )
        return self


settings = Settings()

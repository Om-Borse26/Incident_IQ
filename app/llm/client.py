"""
Provider-agnostic LLM client.

Design
------
ask_llm() is the single public entry point.  Internally it dispatches to a
private per-provider function based on settings.LLM_PROVIDER:

    "groq"   → _ask_groq()        ← implemented
    "openai" → _ask_openai()      ← add later
    "gemini" → _ask_gemini()      ← add later

To add a new provider:
  1. Write `def _ask_<provider>(prompt, system) -> str` below.
  2. Add an `elif settings.LLM_PROVIDER == "<provider>":` branch in ask_llm().
  3. Add the provider's API key / model fields to app/config.py.
  4. Add the SDK to requirements.txt.

That's it — the rest of the app never changes.
"""

from __future__ import annotations

from app.config import settings


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when an LLM provider call fails for any reason."""


# ---------------------------------------------------------------------------
# Per-provider implementations
# ---------------------------------------------------------------------------

def _ask_groq(prompt: str, system: str | None) -> str:
    """Call the Groq Chat Completions API with retry on 429 rate-limits."""
    try:
        from groq import Groq  # lazy import — only needed for this provider
    except ImportError as exc:
        raise LLMError(
            "The 'groq' package is not installed. "
            "Run: pip install groq"
        ) from exc

    import re
    import time

    client = Groq(api_key=settings.GROQ_API_KEY)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    max_retries = 6
    backoff = 10  # seconds to wait on first 429; doubles each retry up to 120s

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=messages,
            )
            return response.choices[0].message.content

        except Exception as exc:
            msg = str(exc)
            is_rate_limit = "429" in msg or "rate_limit_exceeded" in msg

            if not is_rate_limit or attempt == max_retries - 1:
                raise LLMError(f"Groq API error: {exc}") from exc

            # Try to parse the suggested wait time from the Groq error body
            # e.g. "Please try again in 2m11.328s"
            wait = backoff
            m = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", msg)
            if m:
                minutes = int(m.group(1) or 0)
                seconds = float(m.group(2) or 0)
                wait = max(int(minutes * 60 + seconds) + 2, wait)

            print(
                f"    [rate-limit] 429 on attempt {attempt+1}/{max_retries}. "
                f"Waiting {wait}s before retry..."
            )
            time.sleep(wait)
            backoff = min(backoff * 2, 120)


# ---------------------------------------------------------------------------
# Add future providers here
# ---------------------------------------------------------------------------

# def _ask_openai(prompt: str, system: str | None) -> str:
#     """Call the OpenAI Chat Completions API."""
#     ...

# def _ask_gemini(prompt: str, system: str | None) -> str:
#     """Call the Google Gemini API."""
#     ...


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def ask_llm(prompt: str, system: str | None = None) -> str:
    """
    Send *prompt* to the configured LLM provider and return the text reply.

    Parameters
    ----------
    prompt:
        The user message to send.
    system:
        Optional system / instruction message.

    Returns
    -------
    str
        The model's reply.

    Raises
    ------
    LLMError
        On any provider-level failure (network, auth, rate-limit, etc.).
    ValueError
        If LLM_PROVIDER is set to an unknown value.
    """
    provider = settings.LLM_PROVIDER.lower()

    if provider == "groq":
        return _ask_groq(prompt, system)
    # elif provider == "openai":
    #     return _ask_openai(prompt, system)
    # elif provider == "gemini":
    #     return _ask_gemini(prompt, system)
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}'. "
            "Supported values: 'groq'."
        )

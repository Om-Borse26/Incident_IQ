"""
Provider-agnostic LLM client — refactored to LangChain with fallback chain.

Architecture
============
ask_llm() is the single public entry point. Internally it tries each provider
in LLM_FALLBACK_ORDER (from settings) until one succeeds:

    "groq"   → _ask_groq()   uses ChatGroq      (langchain-groq)
    "gemini" → _ask_gemini() uses ChatGoogleGenerativeAI (langchain-google-genai)

Fallback chain behaviour:
  1. Try provider[0]. On rate-limit / quota / API error → log warning, move on.
  2. Try provider[1]. On error → log warning, move on.
  3. If all providers fail → raise LLMAllProvidersFailed.
  4. Caller (e.g. /incident/search) catches LLMAllProvidersFailed and returns a
     degraded-but-useful response rather than a 500.

To add a new provider:
  1. Write `def _ask_<name>(prompt, system) -> str` below.
  2. Add it to PROVIDER_REGISTRY at the bottom of this file.
  3. Add its API key / model fields to app/config.py.
  4. Add the SDK to requirements.txt.
  That's it — ask_llm() discovers it automatically via PROVIDER_REGISTRY.

Rate-limit retry (for Groq):
  The retry-with-backoff loop is inside _ask_groq. It parses the suggested
  wait time from the Groq error body and sleeps before retrying up to
  max_retries times. Only 429 / rate_limit_exceeded errors are retried;
  auth errors and other failures surface immediately.
"""

from __future__ import annotations

import logging
import re
import time

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when a single LLM provider call fails."""


class LLMAllProvidersFailed(Exception):
    """
    Raised when every provider in the fallback chain is exhausted.

    The caller (e.g. /incident/search) should catch this and return a
    degraded response that still surfaces the retrieved chunks to the user,
    rather than raising a 500.
    """


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------

def _is_retryable(exc: Exception) -> bool:
    """Return True for rate-limit / quota errors that are worth retrying."""
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "rate_limit_exceeded", "resource_exhausted", "quota"))


def _ask_groq(prompt: str, system: str | None) -> str:
    """
    Call Groq via LangChain's ChatGroq with exponential-backoff retry on 429.

    Raises LLMError on permanent failure, or after max_retries rate-limit hits.
    """
    if not settings.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY not configured — skipping Groq")

    try:
        from langchain_groq import ChatGroq
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError as exc:
        raise LLMError("langchain-groq not installed. Run: pip install langchain-groq") from exc

    llm = ChatGroq(model=settings.GROQ_MODEL, api_key=settings.GROQ_API_KEY)

    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    max_retries = 6
    backoff = 10  # initial wait on 429; doubles each retry, capped at 120s

    for attempt in range(max_retries):
        try:
            response = llm.invoke(messages)
            return response.content  # type: ignore[return-value]

        except Exception as exc:
            if not _is_retryable(exc) or attempt == max_retries - 1:
                raise LLMError(f"Groq error: {exc}") from exc

            # Parse "Please try again in 2m11.328s" from the Groq error body
            wait = backoff
            m = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", str(exc))
            if m:
                mins = int(m.group(1) or 0)
                secs = float(m.group(2) or 0)
                wait = max(int(mins * 60 + secs) + 2, wait)

            logger.warning(
                "[groq] Rate-limit on attempt %d/%d — waiting %ds before retry",
                attempt + 1, max_retries, wait,
            )
            time.sleep(wait)
            backoff = min(backoff * 2, 120)


def _ask_gemini(prompt: str, system: str | None) -> str:
    """
    Call Google Gemini via LangChain's ChatGoogleGenerativeAI.

    Raises LLMError on any failure (no retry — used as a fallback,
    so a fast failure here is preferable to a long wait).
    """
    if not settings.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY not configured — skipping Gemini")

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError as exc:
        raise LLMError(
            "langchain-google-genai not installed. "
            "Run: pip install langchain-google-genai"
        ) from exc

    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
    )

    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    try:
        response = llm.invoke(messages)
        return response.content  # type: ignore[return-value]
    except Exception as exc:
        raise LLMError(f"Gemini error: {exc}") from exc


# ---------------------------------------------------------------------------
# Provider registry — add new providers here, no other code changes needed
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: dict[str, callable] = {
    "groq": _ask_groq,
    "gemini": _ask_gemini,
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def ask_llm(prompt: str, system: str | None = None) -> str:
    """
    Send *prompt* to the configured LLM and return the text reply.

    Tries each provider in LLM_FALLBACK_ORDER (left to right) until one
    succeeds. Logs which provider served the call, and warns when a fallback
    triggers. Raises LLMAllProvidersFailed if every provider is exhausted.

    Parameters
    ----------
    prompt  : str  — The user message to send.
    system  : str  — Optional system / instruction message.

    Returns
    -------
    str  — The model's reply.

    Raises
    ------
    LLMAllProvidersFailed
        When every provider in the fallback chain fails.
    """
    order = [p.strip().lower() for p in settings.LLM_FALLBACK_ORDER.split(",")]
    errors: list[tuple[str, str]] = []

    for provider_name in order:
        fn = PROVIDER_REGISTRY.get(provider_name)
        if fn is None:
            logger.warning("Unknown provider '%s' in LLM_FALLBACK_ORDER — skipping", provider_name)
            continue

        try:
            result = fn(prompt, system)
            if errors:
                logger.info("[llm] Served by '%s' (fallback after: %s)", provider_name, [e[0] for e in errors])
            else:
                logger.debug("[llm] Served by '%s' (primary)", provider_name)
            return result

        except LLMError as exc:
            logger.warning("[llm] Provider '%s' failed: %s — trying next in chain", provider_name, exc)
            errors.append((provider_name, str(exc)))

    raise LLMAllProvidersFailed(
        f"All providers in fallback chain failed. "
        f"Order tried: {order}. "
        f"Errors: {errors}"
    )

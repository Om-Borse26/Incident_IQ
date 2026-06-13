from pydantic import BaseModel, Field
import logging
from langchain_groq import ChatGroq
from app.config import settings
from services.retrieval.search import search_incidents

logger = logging.getLogger(__name__)

class ValidationResult(BaseModel):
    is_valid: bool = Field(description="True if the document is novel and contains both symptoms and a clear fix/resolution. False if it is a duplicate, or missing key information.")
    reason: str = Field(description="A brief explanation of why the document was approved or rejected.")

def validate_postmortem(document_text: str) -> ValidationResult:
    """
    Uses the LLM to verify if a raw document contains the necessary components
    (Symptoms and Fixes) and is NOT a duplicate of existing knowledge.
    """
    # Use the dedicated Validator Groq key if available, otherwise fallback to main Groq key
    api_key = settings.GROQ_VALIDATOR_API_KEY or settings.GROQ_API_KEY
    if not api_key:
        logger.error("[validator] No Groq API key found for validation.")
        return ValidationResult(is_valid=False, reason="Server missing LLM credentials for validation.")

    llm = ChatGroq(
        model_name=settings.GROQ_MODEL,
        api_key=api_key,
        temperature=0.0
    )
    extractor = llm.with_structured_output(ValidationResult)
    
    # Pre-search for deduplication
    try:
        # Search the database for the text of the new document to find potentially similar existing ones
        existing_chunks = search_incidents(query=document_text[:1000], k=3)
        existing_context = "\n\n".join([f"Existing Document ({chunk.source}):\n{chunk.text}" for chunk in existing_chunks])
    except Exception as e:
        logger.warning(f"[validator] Failed to perform deduplication search: {e}")
        existing_context = "Could not retrieve existing documents."

    prompt = f"""You are an SRE Data Quality Gatekeeper.
A user has uploaded a document to be added to the Incident Response database.

We only accept documents that are genuinely useful for diagnosing future incidents AND are novel.
To be accepted, the uploaded document MUST contain:
1. Symptoms or Error messages (what went wrong).
2. A Fix, Resolution, or Mitigation (how it was solved).

CRITICAL DEDUPLICATION RULE:
Below are snippets of existing documents already in the database. Note that these are just PARTIAL snippets, so they might not contain the full fix.
Compare the uploaded document to these existing snippets.
- If the uploaded document appears to be describing the EXACT SAME incident as any of the snippets (e.g., same title, same core issue), REJECT it (is_valid=False).
- Only accept it if it is a genuinely different incident, or if it provides a completely different alternative fix to an existing problem.

Existing Documents in Database:
---
{existing_context}
---

Uploaded Document Text:
---
{document_text}
---
"""
    try:
        result = extractor.invoke(prompt)
        return result
    except Exception as e:
        logger.error(f"[validator] Failed to validate document: {e}")
        return ValidationResult(is_valid=False, reason=f"LLM validation failed: {e}")

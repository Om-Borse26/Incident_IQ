from pydantic import BaseModel, Field
from app.llm.client import get_chat_model
import logging

logger = logging.getLogger(__name__)

class ValidationResult(BaseModel):
    is_valid: bool = Field(description="True if the document contains both symptoms and a clear fix/resolution. False otherwise.")
    reason: str = Field(description="A brief explanation of why the document was approved or rejected.")

def validate_postmortem(document_text: str) -> ValidationResult:
    """
    Uses the LLM to verify if a raw document contains the necessary components
    (Symptoms and Fixes) to be useful for the Incident Copilot.
    """
    llm = get_chat_model()
    extractor = llm.with_structured_output(ValidationResult)
    
    prompt = f"""You are an SRE Data Quality Gatekeeper.
A user has uploaded a document to be added to the Incident Response database.

We only accept documents that are genuinely useful for diagnosing future incidents.
To be accepted, the document MUST contain:
1. Symptoms or Error messages (what went wrong).
2. A Fix, Resolution, or Mitigation (how it was solved).

Review the following document and determine if it meets these criteria.
If it is just a random file, an incomplete draft, or missing the 'Fix', reject it (is_valid=False).

Document Text:
---
{document_text}
---
"""
    try:
        result = extractor.invoke(prompt)
        return result
    except Exception as e:
        logger.error(f"[validator] Failed to validate document: {e}")
        # Default to false on LLM failure to prevent garbage data
        return ValidationResult(is_valid=False, reason=f"LLM validation failed: {e}")

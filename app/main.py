from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.llm.client import ask_llm, LLMError
from services.retrieval.search import search_incidents

app = FastAPI(title="IncidentIQ")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


class IncidentSearchRequest(BaseModel):
    query: str
    k: int = 4          # number of chunks to retrieve; caller can override


class IncidentSearchResponse(BaseModel):
    answer: str
    sources: list[str]  # incident titles + filenames so the caller can verify provenance


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "incidentiq"}


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    """Send a question to the configured LLM and return its answer."""
    try:
        answer = ask_llm(prompt=body.question)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return AskResponse(answer=answer)


@app.post("/incident/search", response_model=IncidentSearchResponse)
async def incident_search(body: IncidentSearchRequest) -> IncidentSearchResponse:
    """
    RAG endpoint — Retrieve, Augment, Generate.

    Steps (kept deliberately separate so each is visible and testable):
      R — search_incidents()  embeds the query, fetches top-k chunks from Chroma
      A — build_rag_prompt()  below assembles the grounded system prompt
      G — ask_llm()           calls the LLM with the augmented prompt
    """
    # ------------------------------------------------------------------ R
    try:
        chunks = search_incidents(query=body.query, k=body.k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval error: {exc}")

    # ------------------------------------------------------------------ A
    system_prompt = _build_rag_system_prompt(chunks)

    # ------------------------------------------------------------------ G
    try:
        answer = ask_llm(prompt=body.query, system=system_prompt)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Build the sources list: "INC-XXXX: Title  (filename.md)"
    sources = [
        f"{chunk.incident_title}  ({chunk.source})"
        for chunk in chunks
    ]
    # De-duplicate: the same incident can appear in multiple chunks
    seen: set[str] = set()
    unique_sources = [s for s in sources if not (s in seen or seen.add(s))]

    return IncidentSearchResponse(answer=answer, sources=unique_sources)


# ---------------------------------------------------------------------------
# Prompt builder — the Augmentation step
# ---------------------------------------------------------------------------

def _build_rag_system_prompt(chunks) -> str:
    """
    Build a grounded system prompt from retrieved chunks.

    HOW GROUNDING IS ENFORCED:
    1. The LLM is told its ONLY knowledge source is the context block below
       — it may not use general world knowledge or training data to fill gaps.
    2. The instruction "cite the incident source" forces the model to
       attribute claims to a specific file, making hallucinations detectable
       (a fabricated incident can't produce a real filename).
    3. The explicit "I don't know" fallback prevents the model from generating
       a plausible-sounding but invented answer when the context doesn't cover
       the question. This is the critical RAG safety net: an honest no-answer
       is far less harmful than a confident wrong answer in an incident triage
       context.
    4. Context is ordered by relevance (Chroma returns nearest-first) so the
       most pertinent chunk appears at the top of the context window.
    """
    # Format each chunk with its provenance header so the LLM can cite it
    context_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        context_blocks.append(
            f"--- Context {i} ---\n"
            f"Source file : {chunk.source}\n"
            f"Incident    : {chunk.incident_title}\n"
            f"Service     : {chunk.service}\n"
            f"Relevance   : distance={chunk.distance}\n\n"
            f"{chunk.text}"
        )

    context_text = "\n\n".join(context_blocks)

    return (
        "You are IncidentIQ, an expert SRE assistant. "
        "Your job is to help engineers diagnose and resolve production incidents.\n\n"
        "STRICT RULES — follow these without exception:\n"
        "1. Answer ONLY using the incident context provided below. "
        "Do NOT use any knowledge from your training data that is not reflected in the context.\n"
        "2. When you state a fact, cite the source file it comes from "
        "(e.g., 'According to checkout-service-db-pool-exhaustion.md ...').\n"
        "3. If the answer to the question is NOT present in the context, "
        "respond with exactly: \"I don't have enough information in the provided incident "
        "reports to answer this question.\"\n"
        "4. Do not speculate, infer, or extrapolate beyond what the context explicitly states.\n\n"
        f"INCIDENT CONTEXT:\n\n{context_text}"
    )

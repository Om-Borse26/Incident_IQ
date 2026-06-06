import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.llm.client import ask_llm, LLMError, LLMAllProvidersFailed
from services.retrieval.search import search_incidents, SearchResult
from services.retrieval.tree_search import tree_search, TreeSearchResult

logger = logging.getLogger(__name__)

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
    sources: list[str]  # incident titles + filenames for traceability
    degraded: bool = False  # True when all LLM providers failed; raw chunks returned


class AnalyzeRequest(BaseModel):
    query: str
    context: str | None = None


class AnalyzeResponse(BaseModel):
    mode: str
    confidence: float
    answer: str
    sources: list[str]
    reasoning: str
    suggested_fixes: list[str]
    diagnostic_ran: bool

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
    except LLMAllProvidersFailed as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return AskResponse(answer=answer)


@app.post("/incident/analyze", response_model=AnalyzeResponse)
async def incident_analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    """
    Agentic endpoint (Phase 3) — Uses a LangChain ReAct agent to reason about the query,
    decide which retrieval tools to use (vector vs tree), and return a structured 3-mode response.
    """
    from services.agent.incident_agent import IncidentAgent
    
    agent = IncidentAgent()
    
    # We pass the query directly to the agent. If the user provided extra context,
    # we could prepend it to the query here.
    query_text = body.query
    if body.context:
        query_text = f"{body.context}\n\nQuestion: {body.query}"
        
    try:
        result_dict = agent.run(query_text)
        return AnalyzeResponse(**result_dict)
    except Exception as exc:
        logger.exception("[incident/analyze] Agent completely failed")
        
        # Graceful degradation on total agent failure
        # Fall back to returning raw vector chunks so the engineer sees *something*
        try:
            chunks = search_incidents(query=body.query, k=3)
            sources = _format_sources(chunks, include_text=True)
            return AnalyzeResponse(
                mode="unknown",
                confidence=0.0,
                answer="Agent analysis failed. Showing raw related incidents as fallback.",
                sources=sources,
                reasoning=f"Agent exception: {exc}",
                suggested_fixes=[],
                diagnostic_ran=False
            )
        except Exception as fallback_exc:
            raise HTTPException(status_code=500, detail=f"Agent failed, and fallback failed: {fallback_exc}")


@app.post("/incident/search", response_model=IncidentSearchResponse)
async def incident_search(body: IncidentSearchRequest) -> IncidentSearchResponse:
    """
    RAG endpoint — Retrieve, Augment, Generate with graceful degradation.

    Steps (kept deliberately separate so each is visible and testable):
      R — search_incidents()        embed query, fetch top-k chunks from Chroma
      A — _build_rag_system_prompt() assemble the grounded system prompt
      G — ask_llm()                 call the LLM with the augmented prompt

    Graceful degradation:
      If ALL LLM providers are exhausted (LLMAllProvidersFailed), we do NOT
      return a 500. Instead we return the retrieved chunks directly so the
      on-call engineer still sees the relevant incident records, even without
      AI synthesis. degraded=True signals the client that the answer field is
      a fallback message, not an LLM-generated synthesis.
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

    # ------------------------------------------------------------------ G  (with graceful degradation)
    try:
        answer = ask_llm(prompt=body.query, system=system_prompt)

        # Normal path — de-duplicate sources and return
        sources = _format_sources(chunks, include_text=False)
        return IncidentSearchResponse(answer=answer, sources=sources, degraded=False)

    except LLMAllProvidersFailed:
        # Degraded path — all LLM providers are down / exhausted.
        # Return the raw retrieved chunks so the engineer is never left empty-handed.
        logger.warning(
            "[incident/search] All LLM providers failed for query '%s'. "
            "Returning degraded response with raw retrieved chunks.",
            body.query,
        )
        sources = _format_sources(chunks, include_text=True)  # include chunk text in degraded mode
        return IncidentSearchResponse(
            answer=(
                "AI synthesis unavailable (all providers exhausted). "
                "Showing the most relevant incident records directly:"
            ),
            sources=sources,
            degraded=True,
        )

    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/incident/search_vectorless", response_model=IncidentSearchResponse)
async def incident_search_vectorless(body: IncidentSearchRequest) -> IncidentSearchResponse:
    """
    RAG endpoint (Vectorless) — Uses the LLM to structurally route to correct
    sections instead of using vector embeddings.
    """
    # ------------------------------------------------------------------ R
    try:
        nodes = tree_search(query=body.query)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval error: {exc}")

    # ------------------------------------------------------------------ A
    system_prompt = _build_rag_system_prompt_vectorless(nodes)

    # ------------------------------------------------------------------ G
    try:
        answer = ask_llm(prompt=body.query, system=system_prompt)

        sources = _format_sources_vectorless(nodes, include_text=False)
        return IncidentSearchResponse(answer=answer, sources=sources, degraded=False)

    except LLMAllProvidersFailed:
        logger.warning(
            "[incident/search_vectorless] All LLM providers failed for query '%s'. "
            "Returning degraded response.",
            body.query,
        )
        sources = _format_sources_vectorless(nodes, include_text=True)
        return IncidentSearchResponse(
            answer=(
                "AI synthesis unavailable (all providers exhausted). "
                "Showing the most relevant incident records directly:"
            ),
            sources=sources,
            degraded=True,
        )

    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_sources(chunks: list[SearchResult], include_text: bool) -> list[str]:
    """
    Build the sources list, de-duplicated by incident title.

    include_text=False  →  "INC-XXXX: Title  (filename.md)"
    include_text=True   →  adds the raw chunk text below the header
                           (used in degraded mode so engineers see full context)
    """
    seen: set[str] = set()
    result: list[str] = []

    for chunk in chunks:
        header = f"{chunk.incident_title}  ({chunk.source})"
        if header in seen:
            continue
        seen.add(header)

        if include_text:
            result.append(f"{header}\n\n{chunk.text}")
        else:
            result.append(header)

    return result


def _format_sources_vectorless(nodes: list[TreeSearchResult], include_text: bool) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for node in nodes:
        header = f"{node.incident_title} - {node.section_heading}  ({node.source_file})"
        if header in seen:
            continue
        seen.add(header)

        if include_text:
            result.append(f"{header}\n\n{node.section_text}")
        else:
            result.append(header)

    return result


def _build_rag_system_prompt(chunks: list[SearchResult]) -> str:
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


def _build_rag_system_prompt_vectorless(nodes: list[TreeSearchResult]) -> str:
    context_blocks = []
    for i, node in enumerate(nodes, start=1):
        context_blocks.append(
            f"--- Context {i} ---\n"
            f"Source file : {node.source_file}\n"
            f"Incident    : {node.incident_title}\n"
            f"Section     : {node.section_heading}\n\n"
            f"{node.section_text}"
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

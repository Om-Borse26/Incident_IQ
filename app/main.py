import logging
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.llm.client import ask_llm, LLMError, LLMAllProvidersFailed
from services.retrieval.search import search_incidents, SearchResult
from services.retrieval.tree_search import tree_search, TreeSearchResult
from services.agent.incident_graph import incident_graph
from services.agent.validator import validate_postmortem
from services.retrieval.ingest import ingest_single_document

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.config import settings
    logger.info("Application startup...")
    
    # Railway: If the user attached a volume at /data, it starts completely empty.
    # We must auto-detect it, redirect DATA_DIR to it, and seed it with the build-time data.
    if os.path.exists("/data") and os.path.isdir("/data"):
        logger.info("[startup] Detected persistent volume at /data. Redirecting DATA_DIR...")
        os.environ["DATA_DIR"] = "/data"
        settings.DATA_DIR = "/data"
        
        vol_chroma = "/data/chroma_db"
        app_chroma = "./chroma_db"
        
        # If the persistent volume is empty, copy the pre-built knowledge base into it
        if not os.path.exists(vol_chroma) and os.path.exists(app_chroma):
            logger.info("[startup] Persistent volume is empty. Seeding with build-time Chroma database...")
            shutil.copytree(app_chroma, vol_chroma)
            logger.info("[startup] Database successfully seeded into volume.")
            
        vol_tree = "/data/tree_index"
        app_tree = "./tree_index"
        if not os.path.exists(vol_tree) and os.path.exists(app_tree):
            shutil.copytree(app_tree, vol_tree)

    # Future: Cloud Run migration would add GCS snapshot restore here.
    
    # Ensure raw_documents directory exists
    raw_docs_dir = os.path.join(settings.DATA_DIR, "raw_documents")
    os.makedirs(raw_docs_dir, exist_ok=True)
    
    yield
    logger.info("Application shutdown...")

app = FastAPI(title="IncidentIQ", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse
import asyncio

def get_token_or_ip(request: Request) -> str:
    # 1. Rate limit by the API Token if provided
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return auth.split(" ")[1]
    
    # 2. Fallback to real client IP from proxy (Railway)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
        
    # 3. Final fallback to direct connection IP
    if request.client:
        return request.client.host
    return "127.0.0.1"

limiter = Limiter(key_func=get_token_or_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import uuid
    error_id = str(uuid.uuid4())
    logger.error(f"Unhandled exception (ID: {error_id}): {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "request_id": error_id}
    )

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://incident-iq-weld.vercel.app", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    session_id: str | None = None
    resume_action: str | None = None


class AnalyzeResponse(BaseModel):
    mode: str
    confidence: float
    answer: str
    sources: list[str]
    reasoning: str
    suggested_fixes: list[str]
    diagnostics_available: bool
    degraded: bool
    session_id: str
    status: str
    generated_postmortem_path: str | None = None

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from cachetools import TTLCache
import hashlib

# Cache completed analyses for 1 hour to ensure fast responses for identical queries
# keyed by the hash of the lowercase query string
QUERY_CACHE = TTLCache(maxsize=100, ttl=3600)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "incidentiq"}


@app.post("/ask", response_model=AskResponse)
@limiter.limit("10/minute")
async def ask(request: Request, body: AskRequest) -> AskResponse:
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
@limiter.limit("10/minute")
async def incident_analyze(request: Request, body: AnalyzeRequest) -> AnalyzeResponse:
    """
    Agentic endpoint (Phase 5) — Uses LangGraph for explicit state and orchestration.
    """
    from services.agent.incident_graph import incident_graph
    from langgraph.types import Command
    import uuid
    
    session_id = body.session_id or str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": session_id},
        "run_name": "incident_analysis",
        "metadata": {
            "session_id": session_id
        }
    }
    
    query_text = body.query.strip().lower()
    query_hash = hashlib.md5(query_text.encode('utf-8')).hexdigest()
    
    # 1. Cache Check (Only if we are NOT resuming a paused graph)
    if not body.resume_action and query_hash in QUERY_CACHE:
        logger.info(f"[analyze] CACHE HIT for query: '{body.query}'. Returning instant response.")
        cached_res = QUERY_CACHE[query_hash]
        # Generate a new session ID for the cached response so it doesn't collide
        cached_res.session_id = session_id
        return cached_res
    
    query_text = body.query
    if body.context:
        query_text = f"{body.context}\n\nQuestion: {body.query}"
        
    try:
        async def run_graph():
            if body.resume_action:
                logger.info(f"[analyze] Resuming session {session_id} with action: {body.resume_action}")
                stream = incident_graph.astream(Command(resume={"action": body.resume_action}), config)
            else:
                initial_state = {"query": query_text, "context": body.context or ""}
                stream = incident_graph.astream(initial_state, config)
                
            run_status = "completed"
            async for event in stream:
                for node_name, node_state in event.items():
                    if node_name == "__interrupt__":
                        logger.info(f"[analyze] Graph INTERRUPTED for session {session_id}")
                        run_status = "pending_approval"
                        continue
                    logger.info(f"[analyze] Node completed: {node_name}")
            return run_status

        try:
            status = await asyncio.wait_for(run_graph(), timeout=55.0)
        except asyncio.TimeoutError:
            logger.error(f"[analyze] Timeout for session {session_id}")
            return AnalyzeResponse(
                mode="unknown",
                confidence=0.0,
                answer="The analysis took too long and timed out. Please try a simpler query or check the system later.",
                sources=[],
                reasoning="Timeout exceeded 55 seconds.",
                suggested_fixes=[],
                diagnostics_available=False,
                degraded=True,
                session_id=session_id,
                status="error"
            )
                
        # Fetch final state from memory checkpointer
        current_state = incident_graph.get_state(config).values
        
        answer = current_state.get("answer", "")
        if status == "pending_approval":
            answer = "Graph execution paused waiting for human approval. Reply with resume_action='approve' to continue."
            
        generated_path = current_state.get("generated_postmortem_path")
        
        # Auto-ingest if a postmortem was generated
        if generated_path and not generated_path.startswith("Error:"):
            try:
                from services.retrieval.ingest import ingest_single_document
                import os
                filename = os.path.basename(generated_path)
                with open(generated_path, "r", encoding="utf-8") as f:
                    content = f.read()
                ingest_single_document(content, filename)
                logger.info(f"[analyze] Successfully auto-ingested generated postmortem: {filename}")
            except Exception as e:
                logger.error(f"[analyze] Failed to auto-ingest postmortem: {e}")
                
        response = AnalyzeResponse(
            mode=current_state.get("mode", "unknown"),
            confidence=current_state.get("confidence", 0.0),
            answer=answer,
            sources=current_state.get("sources", []),
            reasoning=current_state.get("reasoning", ""),
            suggested_fixes=current_state.get("suggested_fixes", []),
            diagnostics_available=current_state.get("diagnostics_available", False),
            degraded=False,
            session_id=session_id,
            status=status,
            generated_postmortem_path=generated_path
        )
        
        # Cache successful full runs
        if status == "completed":
            QUERY_CACHE[query_hash] = response
            
        return response
    except Exception as exc:
        logger.exception("[incident/analyze] Graph completely failed")
        
        # Graceful degradation on total graph failure
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
                diagnostics_available=False,
                degraded=True,
                session_id=session_id,
                status="failed"
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

        # Build list of unique source titles for UI
        sources = _format_sources(chunks, include_text=False)

        return IncidentSearchResponse(
            answer=answer,
            sources=sources,
            degraded=False
        )

    except LLMAllProvidersFailed as exc:
        logger.warning(
            "All LLMs failed (%s). Falling back to returning raw chunks directly.", exc
        )
        sources = _format_sources(chunks, include_text=True)

        return IncidentSearchResponse(
            answer="**LLM Unreachable — Showing Raw Results:**\n\nAll AI providers are currently unavailable or rate-limited. We cannot synthesize an answer right now, but here are the raw incident records retrieved from the database:",
            sources=sources,
            degraded=True
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


@app.post("/incident/ingest")
@limiter.limit("5/minute")
async def ingest_postmortem(request: Request, file: UploadFile = File(...)):
    """
    Knowledge Ingestion Pipeline.
    Uploads a postmortem document, validates it via LLM, 
    and if valid, adds it to ChromaDB and saves the raw file for download.
    """
    # 1. Read file
    content_bytes = await file.read()
    try:
        content = content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be a valid UTF-8 text or markdown file.")
        
    # 2. LLM Validation
    validation = validate_postmortem(content)
    if not validation.is_valid:
        raise HTTPException(
            status_code=422, 
            detail=f"Document Rejected: {validation.reason}"
        )
        
    # 3. Add to Vector DB
    try:
        ingest_single_document(content, file.filename)
    except Exception as e:
        logger.error(f"Failed to ingest to Chroma: {e}")
        raise HTTPException(status_code=500, detail=f"Vector DB insertion failed: {e}")
        
    # 4. Save raw file for download
    raw_docs_dir = os.path.join(os.environ.get("DATA_DIR", "."), "raw_documents")
    file_path = os.path.join(raw_docs_dir, file.filename)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    # 5. Invalidate the semantic cache since new knowledge was added
    QUERY_CACHE.clear()
        
    return {
        "status": "success",
        "message": f"Successfully ingested {file.filename}",
        "validator_reason": validation.reason
    }


@app.get("/document/{filename}")
async def download_document(filename: str):
    """
    Download a raw postmortem document.
    """
    # Look in the raw_documents persistent volume
    raw_docs_dir = os.path.join(os.environ.get("DATA_DIR", "."), "raw_documents")
    file_path = os.path.join(raw_docs_dir, filename)
    
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename, media_type="application/octet-stream", content_disposition_type="attachment")
        
    # Fallback to the pre-seeded data if not found in raw_documents
    seeded_path = os.path.join("data", "incidents", filename)
    if os.path.exists(seeded_path):
        return FileResponse(seeded_path, filename=filename, media_type="application/octet-stream", content_disposition_type="attachment")
        
    raise HTTPException(status_code=404, detail="Document not found")


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

import logging
import os
import shutil
import threading
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.llm.client import ask_llm, LLMError, LLMAllProvidersFailed
from services.retrieval.search import search_incidents, SearchResult
from services.retrieval.tree_search import tree_search, TreeSearchResult
from services.agent.incident_graph import incident_graph
from services.agent.validator import validate_postmortem

logger = logging.getLogger(__name__)

# Shared stop event used to signal the SQS worker daemon thread to exit cleanly
_worker_stop_event = threading.Event()

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

    # EC2: /data is mounted from the host directory /home/ec2-user/data.
    # This guarantees data persists across container restarts and redeploys.
    
    # Ensure raw_documents directory exists
    raw_docs_dir = os.path.join(settings.DATA_DIR, "raw_documents")
    os.makedirs(raw_docs_dir, exist_ok=True)

    # ----------------------------------------------------------------
    # SQS Setup: Create queues (idempotent) then start the worker thread
    # ----------------------------------------------------------------
    try:
        from services.messaging.pubsub_client import pubsub_client
        pubsub_client.create_topic_and_subscription_if_not_exists()
        logger.info("[startup] SQS queues ready.")

        # Start the IngestionWorker as a daemon thread alongside FastAPI.
        # It exits cleanly when _worker_stop_event is set during shutdown.
        from services.messaging.ingestion_worker import IngestionWorker
        _worker_stop_event.clear()
        worker = IngestionWorker()
        if worker.is_ready:
            worker_thread = threading.Thread(
                target=worker.start,
                args=(_worker_stop_event,),
                daemon=True,
                name="sqs-ingestion-worker",
            )
            worker_thread.start()
            logger.info("[startup] SQS ingestion worker thread started (tid=%s).", worker_thread.ident)
        else:
            logger.warning("[startup] SQS worker not ready — using BackgroundTasks fallback for ingestion.")
    except Exception as e:
        logger.warning("[startup] SQS setup failed: %s. Ingestion will use BackgroundTasks fallback.", e)

    yield

    # Graceful shutdown: signal the worker thread to stop
    logger.info("Application shutdown — signalling SQS worker to stop...")
    _worker_stop_event.set()
    logger.info("Application shutdown complete.")

app = FastAPI(title="IncidentIQ", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
from fastapi.responses import JSONResponse
import asyncio

def get_token_or_ip(request: Request) -> str:
    # 1. Fallback to real client IP from proxy (Railway)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        key = forwarded.split(",")[0].strip()
        logger.info(f"[rate_limit] Using X-Forwarded-For as key: {key}")
        return key
        
    # 3. Final fallback to direct connection IP
    key = request.client.host if request.client else "127.0.0.1"
    logger.info(f"[rate_limit] Using fallback client host as key: {key}")
    return key

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
from app.auth import router as auth_router, verify_token, save_thread, get_user_threads
from fastapi import Depends

app.include_router(auth_router)

# Cache completed analyses for 1 hour to ensure fast responses for identical queries
# keyed by the hash of the lowercase query string
QUERY_CACHE = TTLCache(maxsize=100, ttl=3600)

@app.get("/health")
async def health_check():
    """Health check endpoint for ECS and ALB"""
    return {"status": "ok", "service": "incidentiq"}

@app.get("/incident/history")
def get_history(user_id: int = Depends(verify_token)):
    """Fetch all chat threads for the current user."""
    return get_user_threads(user_id)

@app.get("/incident/history/{thread_id}")
async def get_thread_history(thread_id: str, user_id: int = Depends(verify_token)):
    """Fetch the message history for a specific thread."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    import os
    import sqlite3
    
    # Ensure thread belongs to user
    from app.auth import get_db
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM threads WHERE thread_id = ?", (thread_id,))
    row = cursor.fetchone()
    conn.close()
    if not row or row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Thread not found or access denied")
        
    db_path = os.path.join(os.environ.get("DATA_DIR", "."), "checkpoints.sqlite")
    if not os.path.exists(db_path):
        return {"messages": []}
        
    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        config = {"configurable": {"thread_id": thread_id}}
        state = await checkpointer.aget_tuple(config)
        if not state or not state.checkpoint:
            return {"messages": []}
            
        channel_values = state.checkpoint.get("channel_values", {})
        chat_history = channel_values.get("chat_history", [])
        
        # Convert objects to dicts for JSON serialization
        messages = []
        for msg in chat_history:
            if isinstance(msg, dict):
                # Preserve all fields inside the dict (mode, reasoning, sources, etc.)
                messages.append(msg)
            else:
                role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
                messages.append({"role": role, "content": getattr(msg, "content", "")})
            
        return {"messages": messages}


@app.post("/ask", response_model=AskResponse)
@limiter.limit("10/minute")
async def ask(request: Request, response: Response, body: AskRequest) -> AskResponse:
    """Send a question to the configured LLM and return its answer."""
    try:
        import asyncio
        answer = await asyncio.to_thread(ask_llm, prompt=body.question)
    except LLMAllProvidersFailed as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return AskResponse(answer=answer)


@app.post("/incident/analyze", response_model=AnalyzeResponse)
@limiter.limit("10/minute")
async def incident_analyze(request: Request, response: Response, body: AnalyzeRequest, user_id: int = Depends(verify_token)) -> AnalyzeResponse:
    """
    Agentic endpoint (Phase 12) — Conversational RAG with multi-turn memory.

    How conversation memory works:
      - The client sends a `session_id` to continue a conversation.
      - LangGraph's MemorySaver checkpointer persists the full state
        (including chat_history) per thread_id.
      - On follow-up messages, the graph reads the existing chat_history
        from the checkpoint, detects if this is a follow-up, and either:
          a) Runs the full RAG pipeline with a rewritten query
          b) Answers directly from conversation context (no retrieval)

    The original incident_graph.py is preserved for learning purposes.
    This endpoint now uses services.agent.conversational_graph.
    """
    from services.agent.conversational_graph import conversational_workflow
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command
    import uuid

    session_id = body.session_id or str(uuid.uuid4())
    
    # Save the thread context to the user's history
    title = body.query[:120] + "..." if len(body.query) > 120 else body.query
    save_thread(user_id, session_id, title)
    
    config = {
        "configurable": {"thread_id": session_id},
        "run_name": "conversational_analysis",
        "metadata": {
            "session_id": session_id
        }
    }

    query_text = body.query.strip().lower()
    query_hash = hashlib.md5(query_text.encode('utf-8')).hexdigest()

    if not body.resume_action and not body.session_id and query_hash in QUERY_CACHE:
        logger.info(f"[analyze] CACHE HIT for query: '{body.query}'. Returning instant response.")
        cached_res = QUERY_CACHE[query_hash]
        cached_res.session_id = session_id
        return cached_res

    query_text = body.query
    if body.context:
        query_text = f"{body.context}\n\nQuestion: {body.query}"

    from fastapi.responses import StreamingResponse
    import json

    async def stream_graph_execution():
        try:
            import os
            from app.config import settings
            db_path = os.path.join(settings.DATA_DIR, "checkpoints.sqlite")
            
            async with AsyncSqliteSaver.from_conn_string(db_path) as memory:
                conversational_graph = conversational_workflow.compile(checkpointer=memory)

                if body.resume_action:
                    logger.info(f"[analyze] Resuming session {session_id} with action: {body.resume_action}")
                    yield f'data: {json.dumps({"type": "status", "message": "Resuming execution..."})}\n\n'
                    stream = conversational_graph.astream_events(Command(resume={"action": body.resume_action}), config, version="v2")
                else:
                    existing_state = None
                    try:
                        existing_state = await conversational_graph.aget_state(config)
                    except Exception:
                        pass

                    existing_history = []
                    if existing_state and existing_state.values:
                        existing_history = existing_state.values.get("chat_history", [])

                    initial_state = {
                        "query": query_text,
                        "context": body.context or "",
                        "chat_history": existing_history,
                    }
                    stream = conversational_graph.astream_events(initial_state, config, version="v2")

                run_status = "completed"
                status_map = {
                    "classify_node": "Analyzing query type...",
                    "retrieve_node": "Searching historical incidents...",
                    "diagnose_node": "Running live diagnostics...",
                    "diagnostic_extraction_node": "Extracting diagnostic context...",
                    "generate_answer_node": "Generating response...",
                    "human_approval_node": "Waiting for human approval...",
                }

                try:
                    # To add a global timeout to the stream iteration:
                    async with asyncio.timeout(55.0):
                        async for event in stream:
                            event_name = event.get("event")
                        node_name = event.get("name", "")
                        
                        if event_name == "on_chat_model_stream":
                            metadata_node = event.get("metadata", {}).get("langgraph_node", "")
                            if metadata_node in ["generate_answer_node", "chitchat_node", "conversational_response_node"]:
                                chunk = event.get("data", {}).get("chunk")
                                if chunk and chunk.content:
                                    yield f'data: {json.dumps({"type": "token", "content": chunk.content})}\n\n'
                                    
                        elif event_name == "on_chain_start":
                            if node_name in status_map:
                                msg = status_map[node_name]
                                yield f'data: {json.dumps({"type": "status", "message": msg})}\n\n'
                            if node_name == "__interrupt__":
                                logger.info(f"[analyze] Graph INTERRUPTED for session {session_id}")
                                run_status = "pending_approval"

                except asyncio.TimeoutError:
                    logger.error(f"[analyze] Timeout for session {session_id}")
                    error_payload = {
                        "mode": "unknown", "confidence": 0.0,
                        "answer": "The analysis took too long and timed out.",
                        "sources": [], "reasoning": "Timeout exceeded 55 seconds.",
                        "suggested_fixes": [], "diagnostics_available": False,
                        "degraded": True, "session_id": session_id, "status": "error"
                    }
                    yield f'data: {json.dumps({"type": "final_result", "data": error_payload})}\n\n'
                    return

                # Fetch final state from memory checkpointer
                current_state = await conversational_graph.aget_state(config)
                current_state_values = current_state.values if current_state else {}

                answer = current_state_values.get("answer", "")
                if run_status == "pending_approval":
                    answer = "Graph execution paused waiting for human approval. Reply with resume_action='approve' to continue."

                generated_path = current_state_values.get("generated_postmortem_path")
                if generated_path and not generated_path.startswith("Error:"):
                    try:
                        from services.retrieval.ingest import ingest_single_document
                        import os
                        filename = os.path.basename(generated_path)
                        with open(generated_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        await asyncio.to_thread(ingest_single_document, content, filename)
                        logger.info(f"[analyze] Successfully auto-ingested generated postmortem: {filename}")
                    except Exception as e:
                        logger.error(f"[analyze] Failed to auto-ingest postmortem: {e}")

                final_payload = {
                    "mode": current_state_values.get("mode", "unknown"),
                    "query_type": current_state_values.get("query_type", "historical"),
                    "followup_type": current_state_values.get("followup_type", "new_query"),
                    "confidence": current_state_values.get("confidence", 0.0),
                    "answer": answer,
                    "sources": current_state_values.get("sources", []),
                    "reasoning": current_state_values.get("reasoning", ""),
                    "suggested_fixes": current_state_values.get("suggested_fixes", []),
                    "diagnostics_available": current_state_values.get("diagnostics_available", False),
                    "live_logs": current_state_values.get("live_logs", ""),
                    "service_health": current_state_values.get("service_health", {}),
                    "recent_deploys": current_state_values.get("recent_deploys", []),
                    "degraded": False,
                    "session_id": session_id,
                    "status": run_status,
                    "generated_postmortem_path": generated_path
                }

                yield f'data: {json.dumps({"type": "final_result", "data": final_payload})}\n\n'
                
        except Exception as exc:
            logger.exception("[incident/analyze] Graph execution failed")
            yield f'data: {json.dumps({"type": "error", "message": str(exc)})}\n\n'

    return StreamingResponse(stream_graph_execution(), media_type="text/event-stream")



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
    import asyncio
    # ------------------------------------------------------------------ R
    try:
        chunks = await asyncio.to_thread(search_incidents, query=body.query, k=body.k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval error: {exc}")

    # ------------------------------------------------------------------ A
    system_prompt = _build_rag_system_prompt(chunks)

    # ------------------------------------------------------------------ G  (with graceful degradation)
    try:
        answer = await asyncio.to_thread(ask_llm, prompt=body.query, system=system_prompt)

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
    import asyncio
    # ------------------------------------------------------------------ R
    try:
        nodes = await asyncio.to_thread(tree_search, query=body.query)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval error: {exc}")

    # ------------------------------------------------------------------ A
    system_prompt = _build_rag_system_prompt_vectorless(nodes)

    # ------------------------------------------------------------------ G
    try:
        answer = await asyncio.to_thread(ask_llm, prompt=body.query, system=system_prompt)

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


from fastapi import BackgroundTasks

async def ingest_single_document_async(content: str, filename: str):
    import asyncio
    from services.retrieval.ingest import ingest_single_document
    try:
        await asyncio.to_thread(ingest_single_document, content, filename)
    except Exception as e:
        logger.error(f"[ingest_task] Failed to ingest {filename}: {e}")

@app.post("/incident/ingest")
@limiter.limit("5/minute")
async def ingest_postmortem(request: Request, response: Response, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Knowledge Ingestion Pipeline — Phase 12: SQS Event-Driven with BackgroundTasks fallback.

    The API returns IMMEDIATELY after:
      1. Validating the document (LLM call — fast)
      2. Saving the raw file to disk
      3. Publishing an SQS message → picked up by the IngestionWorker daemon thread
         (fallback: FastAPI BackgroundTask if SQS is unavailable)

    The heavy work (embedding, ChromaDB write, tree index rebuild) is decoupled
    from the HTTP request lifecycle, providing scalable async processing.
    The incident will be searchable in ~30 seconds.
    """
    # 1. Read file
    content_bytes = await file.read()
    try:
        content = content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be a valid UTF-8 text or markdown file.")

    # 2. LLM Validation (fast — returns accept/reject + reason)
    validation = validate_postmortem(content)
    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail=f"Document Rejected: {validation.reason}"
        )

    # 3. Save raw file to disk
    raw_docs_dir = os.path.join(os.environ.get("DATA_DIR", "."), "raw_documents")
    os.makedirs(raw_docs_dir, exist_ok=True)
    file_path = os.path.join(raw_docs_dir, file.filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    incident_id = str(uuid4())
    logger.info("[ingest] File saved to '%s' (incident_id=%s).", file_path, incident_id)

    # 4. Primary path: publish to SQS — the IngestionWorker daemon picks it up
    from services.messaging.pubsub_client import pubsub_client
    sqs_msg_id = pubsub_client.publish_incident_ingested(
        incident_id=incident_id,
        filename=file.filename,
        file_path=file_path,
    )

    if sqs_msg_id:
        logger.info("[ingest] SQS message published (MessageId=%s). Worker will process asynchronously.", sqs_msg_id)
        ingestion_method = "sqs"
    else:
        # 5. Fallback: SQS unavailable — use FastAPI BackgroundTask instead
        logger.warning("[ingest] SQS publish failed — falling back to BackgroundTask for '%s'.", file.filename)
        background_tasks.add_task(ingest_single_document_async, content, file.filename)
        ingestion_method = "background_task"

    return {
        "status": "processing",
        "incident_id": incident_id,
        "ingestion_method": ingestion_method,
        "message": (
            f"File '{file.filename}' validated and saved. "
            "Ingestion is running asynchronously. "
            "The incident will be searchable shortly."
        ),
        "validator_reason": validation.reason,
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
# Trigger Jenkins

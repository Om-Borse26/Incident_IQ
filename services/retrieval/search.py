"""
Retrieval service — Phase 1, Step 2 (Vector RAG).

Responsibility: given a natural-language query, return the k most
semantically relevant incident chunks from the ChromaDB collection.

This module is RETRIEVAL ONLY — it knows nothing about LLMs or prompt
construction. That separation is deliberate:
  R (retrieve)  -- this file
  A (augment)   -- app/main.py builds the system prompt from these results
  G (generate)  -- app/llm/client.py calls the LLM

Keeping them apart lets you unit-test retrieval independently, swap the
vector store without touching the API layer, and inspect intermediate
results during debugging.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Tell huggingface_hub to skip all network checks and load from local cache.
# The embedding model (all-MiniLM-L6-v2) is downloaded once during `ingest.py`
# and cached in ~/.cache/huggingface/. The retrieval path never needs to
# re-download it, so every HEAD request to huggingface.co is pure overhead.
# Using setdefault() means an explicit HF_HUB_OFFLINE=0 in .env can still
# override this if you ever need to force a model refresh.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# Silence chromadb 0.6.3's broken posthog telemetry.
# Background: posthog changed its capture() API signature; chromadb calls it
# with the OLD positional-arg signature, which raises TypeError on every request.
# chromadb catches that exception and prints "Failed to send telemetry event ..."
# The env-var flags (ANONYMIZED_TELEMETRY / CHROMA_ANONYMIZED_TELEMETRY) are
# checked AFTER the telemetry object is constructed, so they don't help here.
# Patching posthog.capture with a no-op lambda before chromadb is imported is
# the only reliable fix without downgrading chromadb or posthog.
import posthog as _posthog
_posthog.capture = lambda *args, **kwargs: None  # type: ignore[assignment]

import chromadb
from langchain_huggingface import HuggingFaceEmbeddings

# ---------------------------------------------------------------------------
# Configuration — must mirror ingest.py exactly
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Use persistent DATA_DIR if set, otherwise fallback to local chroma_db
_DATA_DIR_ENV = os.environ.get("DATA_DIR")
if _DATA_DIR_ENV and _DATA_DIR_ENV != ".":
    CHROMA_DIR = Path(_DATA_DIR_ENV) / "chroma_db"
else:
    CHROMA_DIR = _PROJECT_ROOT / "chroma_db"

COLLECTION_NAME = "incidents"

# WHY THE SAME MODEL AS INGESTION:
#   Embedding models map text into a high-dimensional vector space where
#   semantically similar phrases end up close together. The geometry of that
#   space — which directions mean "database error" vs "timeout" — is entirely
#   defined by the specific model weights used during training.
#
#   If you embed documents with model A and query with model B, the two sets
#   of vectors live in DIFFERENT spaces. Cosine similarity between them is
#   then meaningless: two chunks about the exact same topic will appear far
#   apart, and retrieval will return garbage results.
#
#   Rule: query embedding model == document embedding model. Always.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single retrieved chunk with its provenance."""
    text: str                   # raw chunk text (injected verbatim into the LLM prompt)
    source: str                 # filename, e.g. "checkout-service-db-pool-exhaustion.md"
    incident_title: str         # H1 heading from the source file
    service: str                # affected service name
    distance: float             # cosine distance (lower == more similar)


# ---------------------------------------------------------------------------
# Module-level singletons (loaded once on first call, reused on every request)
# ---------------------------------------------------------------------------

_embeddings: HuggingFaceEmbeddings | None = None
_collection: chromadb.Collection | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embeddings


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        # anonymized_telemetry=False silences the broken posthog integration
        # in chromadb 0.6.3 ("capture() takes 1 positional argument but 3 were given")
        from app.config import settings
        chroma_path = os.path.join(settings.DATA_DIR, "chroma_db")
        client = chromadb.PersistentClient(
            path=chroma_path,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


from langsmith import traceable

@traceable(run_name="vector_retrieval")
def search_incidents(query: str, k: int = 4) -> list[SearchResult]:
    """
    Return the k most relevant incident chunks for the given query.

    Parameters
    ----------
    query : str
        The user's natural-language question or symptom description.
    k : int, default 4
        Number of chunks to retrieve.

        HOW k IS CHOSEN:
        - Too small (k=1-2): risks missing relevant context, especially when
          a single incident spans multiple chunks and the crucial detail sits
          in chunk 2 or 3.
        - Too large (k=8+): floods the LLM prompt with loosely related context,
          increasing cost, latency, and the chance the model gets distracted
          by noise and hallucinates a blend of multiple incidents.
        - k=4 is the practical sweet spot for short incident documents:
          it covers the typical 2-3 chunks a single incident produces while
          still leaving room for a second incident if the query spans topics.
          Tune upward if your documents are longer or more fragmented.

    Returns
    -------
    list[SearchResult]
        Ordered by similarity (most relevant first). Each item includes the
        chunk text, source filename, incident title, and affected service so
        the caller can build a grounded, traceable LLM prompt.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    # 1. Embed the query — same model as ingestion (see module docstring above)
    embedder = _get_embeddings()
    query_vector = embedder.embed_query(query)

    # 2. Similarity search against the ChromaDB collection
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []
        
    raw = collection.query(
        query_embeddings=[query_vector],
        n_results=min(k, count),   # guard: can't request more than stored
        include=["documents", "metadatas", "distances"],
    )

    # 3. Flatten Chroma's nested lists into clean SearchResult objects
    results: list[SearchResult] = []
    docs = raw["documents"][0]       # list of chunk texts
    metas = raw["metadatas"][0]      # list of metadata dicts
    dists = raw["distances"][0]      # list of cosine distances

    for text, meta, dist in zip(docs, metas, dists):
        results.append(
            SearchResult(
                text=text,
                source=meta.get("source", "unknown"),
                incident_title=meta.get("incident_title", "unknown"),
                service=meta.get("service", "unknown"),
                distance=round(dist, 4),
            )
        )

    return results

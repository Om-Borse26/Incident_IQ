"""
Incident document ingestion pipeline -- Phase 1 (Vector RAG).

Pipeline:
    data/incidents/*.md
        -> load (TextLoader)
        -> chunk (RecursiveCharacterTextSplitter)
        -> embed (HuggingFace all-MiniLM-L6-v2, runs locally, no API key needed)
        -> store (ChromaDB, persisted to ./chroma_db/)

Run directly:
    python -m services.retrieval.ingest
"""

from __future__ import annotations

import re
from pathlib import Path

import chromadb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

# Resolve paths relative to the project root (two levels up from this file)
import os
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
INCIDENTS_DIR = _PROJECT_ROOT / "data" / "incidents"

# Use persistent DATA_DIR if set, otherwise fallback to local chroma_db
_DATA_DIR_ENV = os.environ.get("DATA_DIR")
if _DATA_DIR_ENV and _DATA_DIR_ENV != ".":
    CHROMA_DIR = Path(_DATA_DIR_ENV) / "chroma_db"
else:
    CHROMA_DIR = _PROJECT_ROOT / "chroma_db"

COLLECTION_NAME = "incidents"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # ~80 MB download on first run, then cached

CHUNK_SIZE = 500
# WHY OVERLAP:
#   When a document is split at a boundary, a sentence that straddles two chunks
#   is incomplete in both -- the first chunk loses its tail, the second loses its
#   head. A semantic query about that sentence then matches *neither* chunk well.
#   Overlap solves this by repeating the last CHUNK_OVERLAP characters of chunk N
#   at the start of chunk N+1. This ensures every meaningful phrase appears in
#   full in at least one chunk, so it remains retrievable.
#   50 chars (~1 short sentence) is a conservative overlap -- enough to preserve
#   boundary context without bloating the chunk count significantly.
CHUNK_OVERLAP = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_frontmatter(content: str, filename: str) -> dict[str, str]:
    """
    Pull the incident title and affected service from the markdown content.

    Expected format in each file:
        # INC-XXXX: <title>
        **Affected Service:** <service-name>
    """
    title = "unknown"
    service = "unknown"

    for line in content.splitlines():
        # Match the H1 heading: "# INC-0041: Checkout Service ..."
        if line.startswith("# ") and title == "unknown":
            title = line[2:].strip()

        # Match bold field: "**Affected Service:** checkout-service, order-service"
        if "Affected Service" in line and service == "unknown":
            # Strip markdown bold markers and grab the value after the colon
            clean = re.sub(r"\*+", "", line)
            if ":" in clean:
                service = clean.split(":", 1)[1].strip()

    return {
        "source": filename,
        "incident_title": title,
        "service": service,
    }


def _load_documents():
    """Load every .md file from INCIDENTS_DIR as a LangChain Document."""
    md_files = sorted(INCIDENTS_DIR.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(
            f"No markdown files found in {INCIDENTS_DIR}. "
            "Make sure data/incidents/ contains .md incident reports."
        )

    docs = []
    for path in md_files:
        loader = TextLoader(str(path), encoding="utf-8")
        loaded = loader.load()
        for doc in loaded:
            doc.metadata["source"] = path.name
        docs.extend(loaded)

    return docs


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def ingest_incidents() -> None:
    """
    Run the full ingestion pipeline:

    1. Load .md incident files
    2. Split into overlapping chunks
    3. Embed using a local sentence-transformer model
    4. Store in ChromaDB (on-disk, persistent)

    What gets stored in Chroma per chunk
    --------------------------------------
    Chroma stores THREE things for every chunk:

    TEXT     -- the raw chunk text (stored as-is; injected verbatim into the
                LLM prompt as retrieved context during a RAG query)

    VECTOR   -- the embedding: a list of 384 floats representing the chunk's
                meaning in semantic space. Similarity search operates purely
                on these numbers via cosine distance -- the text is never
                "read" during search.

    METADATA -- arbitrary key-value pairs attached at write time (not embedded,
                not searched by default):
                  source         -> filename (e.g. "checkout-service-db-pool-exhaustion.md")
                  incident_title -> H1 heading from the file
                  service        -> affected service name
                Used for: metadata-filtered search ("only payment-service incidents")
                and for displaying source provenance alongside query results.
    """
    print("=" * 60)
    print("IncidentIQ - Document Ingestion Pipeline")
    print("=" * 60)

    # Step 1: Load
    print(f"\n[1/4] Loading incident documents from {INCIDENTS_DIR} ...")
    docs = _load_documents()
    print(f"      Loaded {len(docs)} file(s).")

    # Step 2: Chunk
    print(f"\n[2/4] Splitting into chunks (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}) ...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        # Separators tried in order: prefer paragraph breaks -> line breaks -> words -> chars.
        # This avoids cutting mid-sentence wherever possible.
        separators=["\n\n", "\n", " ", ""],
    )

    chunks = []
    for doc in docs:
        meta = _extract_frontmatter(doc.page_content, doc.metadata["source"])
        split_docs = splitter.create_documents(
            texts=[doc.page_content],
            metadatas=[meta],
        )
        chunks.extend(split_docs)

    print(f"      Created {len(chunks)} chunk(s) from {len(docs)} document(s).")

    # Step 3: Embed
    print(f"\n[3/4] Loading embedding model '{EMBEDDING_MODEL}' (local, no API key) ...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    # Step 4: Store in ChromaDB
    # ChromaDB persists automatically to disk at CHROMA_DIR.
    # Deleting the existing collection before re-creating makes re-ingestion idempotent.
    print(f"\n[4/4] Storing in ChromaDB collection '{COLLECTION_NAME}' -> {CHROMA_DIR} ...")
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe the existing collection so re-running ingest is always a clean slate
    import chromadb
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=chromadb.Settings(anonymized_telemetry=False)
    )
    try:
        client.delete_collection(COLLECTION_NAME)
        print("      Deleted existing collection for clean re-ingestion.")
    except Exception:
        pass  # Collection does not exist yet -- that is fine

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
        client_settings=chromadb.Settings(anonymized_telemetry=False),
    )

    print("\n" + "=" * 60)
    print("[OK] Ingestion complete!")
    print(f"  Documents : {len(docs)}")
    print(f"  Chunks    : {len(chunks)}")
    print(f"  Collection: {COLLECTION_NAME}")
    print(f"  Stored at : {CHROMA_DIR}")
    print("=" * 60)


def ingest_single_document(content: str, filename: str) -> None:
    """
    Ingest a single document into ChromaDB.
    Used by the POST /incident/ingest endpoint.
    """
    from langchain.docstore.document import Document
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    
    meta = _extract_frontmatter(content, filename)
    doc = Document(page_content=content, metadata=meta)
    
    chunks = splitter.create_documents([doc.page_content], metadatas=[meta])
    
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    
    # We instantiate Chroma pointing to the same directory
    import chromadb
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
        client_settings=chromadb.Settings(anonymized_telemetry=False)
    )
    vectorstore.add_documents(chunks)
    logger.info(f"[ingest] Successfully ingested {filename} ({len(chunks)} chunks)")

# ---------------------------------------------------------------------------
# Entrypoint -- python -m services.retrieval.ingest
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ingest_incidents()

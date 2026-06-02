"""
Incident document ingestion pipeline — Phase 1 (Vector RAG).

Pipeline:
    data/incidents/*.md
        → load (TextLoader)
        → chunk (RecursiveCharacterTextSplitter)
        → embed (HuggingFace all-MiniLM-L6-v2, runs locally, no API key needed)
        → store (LanceDB, persisted to ./lancedb/)

Note on vector store choice:
    ChromaDB was originally planned here but its C++ dependency (chroma-hnswlib)
    has no pre-built wheel for Python 3.14 and requires MSVC to compile.
    LanceDB is written in Rust (via maturin) and ships binary wheels for Python 3.14.
    The LangChain integration surface is identical to Chroma.

Run directly:
    python -m services.retrieval.ingest
"""

from __future__ import annotations

import re
from pathlib import Path

import lancedb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import LanceDB
from langchain_huggingface import HuggingFaceEmbeddings

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

# Resolve paths relative to the project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
INCIDENTS_DIR = _PROJECT_ROOT / "data" / "incidents"
LANCEDB_DIR = _PROJECT_ROOT / "lancedb"

COLLECTION_NAME = "incidents"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # ~80 MB download on first run, then cached

CHUNK_SIZE = 500
# WHY OVERLAP:
#   When a document is split at a boundary, a sentence that straddles two chunks
#   is incomplete in both — the first chunk loses its tail, the second loses its
#   head. A semantic query about that sentence then matches *neither* chunk well.
#   Overlap solves this by repeating the last CHUNK_OVERLAP characters of chunk N
#   at the start of chunk N+1. This ensures every meaningful phrase appears in
#   full in at least one chunk, so it remains retrievable.
#   50 chars (~1 short sentence) is a conservative overlap — enough to preserve
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
        # Match the H1 heading: "# INC-0041: Checkout Service …"
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
    4. Store in LanceDB (on-disk, persistent)

    What gets stored in LanceDB per chunk
    --------------------------------------
    Like any vector store, LanceDB stores THREE things per chunk:

    • TEXT     — the raw chunk text (used verbatim when injecting context into the LLM)
    • VECTOR   — the embedding: 384 floats representing the chunk's meaning in
                 semantic space. All similarity search operates purely on these numbers.
    • METADATA — key-value pairs attached at write time (NOT embedded, NOT searched):
                   source          → filename  (e.g. "checkout-service-db-pool-exhaustion.md")
                   incident_title  → H1 heading from the file
                   service         → affected service name
                 Used for: metadata filtering ("only incidents about payment-service")
                 and for showing source provenance in query results.
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
        # Separators tried in order: prefer paragraph breaks → line breaks → words → chars.
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

    # Step 4: Store in LanceDB
    # LanceDB persists automatically to disk at LANCEDB_DIR.
    # mode="overwrite" on the table makes re-running ingest idempotent.
    print(f"\n[4/4] Storing in LanceDB table '{COLLECTION_NAME}' -> {LANCEDB_DIR} ...")
    LANCEDB_DIR.mkdir(parents=True, exist_ok=True)
    connection = lancedb.connect(str(LANCEDB_DIR))

    # Drop existing table so re-running ingest is always a clean slate
    if COLLECTION_NAME in connection.list_tables():
        connection.drop_table(COLLECTION_NAME)
        print("      Dropped existing table for clean re-ingestion.")

    LanceDB.from_documents(
        documents=chunks,
        embedding=embeddings,
        connection=connection,
        table_name=COLLECTION_NAME,
    )

    print("\n" + "=" * 60)
    print(f"[OK] Ingestion complete!")
    print(f"  Documents : {len(docs)}")
    print(f"  Chunks    : {len(chunks)}")
    print(f"  Table     : {COLLECTION_NAME}")
    print(f"  Stored at : {LANCEDB_DIR}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entrypoint — python -m services.retrieval.ingest
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ingest_incidents()

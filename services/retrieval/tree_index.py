"""
Universal structure-aware (vectorless) indexer for IncidentIQ.

Parses documents by their structural headings to build a logical tree of
sections, rather than arbitrary fixed-size chunks. This prevents the
"chunk boundary" failure mode where a heading is separated from its body.

SUPPORTED FORMATS:
  .md   — splits by ## headings (Markdown)
  .pdf  — detects headings by font size (PyMuPDF)
  .docx — detects headings by Word heading styles (python-docx)

Each section becomes a "node" in the tree. The tree is persisted as JSON
so the LLM can query its structure (Table of Contents) during retrieval.

This implements the same core algorithm as PageIndex (VectifyAI) but:
  - Runs 100% locally with zero cloud dependencies
  - Uses our own LLM fallback chain (Groq/Gemini) instead of OpenAI
  - Supports Word docs (which PageIndex doesn't natively support)
  - Handles any document format through a pluggable parser interface

Future Upgrade Note:
  Currently, we extract the first 150 characters of a section as its 'summary'.
  A higher-quality approach would be to have an LLM generate a concise 1-sentence
  summary for each section during ingestion. That costs tokens/time, so we use
  the naive 150-char heuristic for now.
"""

import json
import logging
import re
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class TreeNode(TypedDict):
    node_id: str
    incident_title: str
    service: str
    source_file: str
    section_heading: str
    section_summary: str
    section_text: str

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
import os
_DATA_DIR_ENV = os.environ.get("DATA_DIR")
if _DATA_DIR_ENV and _DATA_DIR_ENV != ".":
    DATA_DIR = Path(_DATA_DIR_ENV) / "incidents"
    INDEX_DIR = Path(_DATA_DIR_ENV) / "tree_index"
else:
    DATA_DIR = PROJECT_ROOT / "data" / "incidents"
    INDEX_DIR = PROJECT_ROOT / "tree_index"

INDEX_PATH = INDEX_DIR / "incidents_tree.json"

SUMMARY_LENGTH = 150  # chars

# Supported file extensions (order matters for glob)
SUPPORTED_EXTENSIONS = [".md", ".pdf", ".docx"]

# ---------------------------------------------------------------------------
# Shared Helpers
# ---------------------------------------------------------------------------

def _make_summary(body: str) -> str:
    """Extract a short summary from body text (first 150 chars, cleaned)."""
    clean = re.sub(r"[\n\*\-\#_`]+", " ", body).strip()
    clean = re.sub(r"\s+", " ", clean)
    summary = clean[:SUMMARY_LENGTH]
    if len(clean) > SUMMARY_LENGTH:
        summary += "..."
    return summary


def _build_node(
    file_path: Path,
    index: int,
    title: str,
    service: str,
    heading: str,
    body: str,
) -> TreeNode | None:
    """Create a TreeNode from parsed section data. Returns None if body is empty."""
    body = body.strip()
    if not body:
        return None
    return {
        "node_id": f"{file_path.stem}-sec{index}",
        "incident_title": title or file_path.stem,
        "service": service,
        "source_file": file_path.name,
        "section_heading": heading,
        "section_summary": _make_summary(body),
        "section_text": body,
    }


# ---------------------------------------------------------------------------
# Markdown Parser (.md)
# ---------------------------------------------------------------------------

def _parse_markdown(file_path: Path) -> list[TreeNode]:
    """Parse a Markdown file into logical section nodes by ## headings."""
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    # Extract title and service from the header block
    title = ""
    service = ""
    for line in lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("**Affected Service:**"):
            service = line.replace("**Affected Service:**", "").strip()

    # Split by ## headings
    blocks = re.split(r"\n(?=## )", text)
    nodes: list[TreeNode] = []

    for i, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue

        heading = "Introduction"
        body = block

        if block.startswith("## "):
            heading_end = block.find("\n")
            if heading_end != -1:
                heading = block[3:heading_end].strip()
                body = block[heading_end:].strip()
            else:
                heading = block[3:].strip()
                body = ""

        node = _build_node(file_path, i, title, service, heading, body)
        if node:
            nodes.append(node)

    return nodes


# ---------------------------------------------------------------------------
# PDF Parser (.pdf)
# ---------------------------------------------------------------------------

def _parse_pdf(file_path: Path) -> list[TreeNode]:
    """
    Parse a PDF file into logical section nodes by detecting headings
    via font size analysis.

    Strategy:
      1. Extract all text blocks with their font sizes from every page.
      2. Identify the dominant (most common) font size — that's body text.
      3. Any text significantly larger than body text is treated as a heading.
      4. Group body text under its nearest preceding heading.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF not installed. Run: pip install PyMuPDF")
        return []

    doc = fitz.open(str(file_path))

    # Pass 1: Collect all text spans with font sizes
    spans: list[dict] = []
    for page in doc:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:  # skip images
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        spans.append({
                            "text": text,
                            "size": round(span.get("size", 12), 1),
                            "flags": span.get("flags", 0),  # bold/italic
                        })

    if not spans:
        doc.close()
        return []

    # Pass 2: Determine body font size (most common) and heading threshold
    from collections import Counter
    size_counts = Counter(s["size"] for s in spans)
    body_size = size_counts.most_common(1)[0][0]
    # Headings are typically >= 1.5pt larger than body text
    heading_threshold = body_size + 1.5

    # Pass 3: Group into sections
    # Extract title from the largest text on the first page
    title = ""
    service = ""
    max_size = max(s["size"] for s in spans)

    sections: list[tuple[str, list[str]]] = []
    current_heading = "Introduction"
    current_body: list[str] = []

    for span in spans:
        text = span["text"]

        # Detect title (largest text, first occurrence)
        if not title and span["size"] >= max_size:
            title = text
            continue

        # Detect service metadata
        if "Affected Service:" in text:
            service = text.replace("Affected Service:", "").strip()
            continue

        # Is this a heading?
        is_heading = span["size"] >= heading_threshold or (
            span["flags"] & 2**4  # bold flag
            and span["size"] > body_size
        )

        if is_heading and text and len(text) < 200:  # headings are short
            # Save previous section
            if current_body:
                sections.append((current_heading, current_body))
            current_heading = text
            current_body = []
        else:
            current_body.append(text)

    # Don't forget the last section
    if current_body:
        sections.append((current_heading, current_body))

    doc.close()

    # Build nodes
    nodes: list[TreeNode] = []
    for i, (heading, body_lines) in enumerate(sections):
        body = "\n".join(body_lines)
        node = _build_node(file_path, i, title, service, heading, body)
        if node:
            nodes.append(node)

    return nodes


# ---------------------------------------------------------------------------
# Word (.docx) Parser
# ---------------------------------------------------------------------------

def _parse_docx(file_path: Path) -> list[TreeNode]:
    """
    Parse a Word document into logical section nodes by detecting
    heading styles (Heading 1, Heading 2, etc.).

    Strategy:
      1. Iterate all paragraphs in the document.
      2. Paragraphs with a heading style become section headings.
      3. Body paragraphs are grouped under their nearest preceding heading.
    """
    try:
        from docx import Document
    except ImportError:
        logger.error("python-docx not installed. Run: pip install python-docx")
        return []

    doc = Document(str(file_path))

    title = ""
    service = ""
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Introduction"
    current_body: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style_name = (para.style.name or "").lower()

        # Extract title from Heading 1 or Title style
        if style_name in ("title", "heading 1") and not title:
            title = text
            continue

        # Detect service metadata
        if "Affected Service:" in text:
            service = text.replace("Affected Service:", "").replace("**", "").strip()
            continue

        # Is this a heading? (Heading 2, Heading 3, etc.)
        is_heading = style_name.startswith("heading") and style_name != "heading 1"

        if is_heading:
            # Save previous section
            if current_body:
                sections.append((current_heading, current_body))
            current_heading = text
            current_body = []
        else:
            current_body.append(text)

    # Don't forget the last section
    if current_body:
        sections.append((current_heading, current_body))

    # Build nodes
    nodes: list[TreeNode] = []
    for i, (heading, body_lines) in enumerate(sections):
        body = "\n".join(body_lines)
        node = _build_node(file_path, i, title, service, heading, body)
        if node:
            nodes.append(node)

    return nodes


# ---------------------------------------------------------------------------
# Universal Router
# ---------------------------------------------------------------------------

def _parse_document(file_path: Path) -> list[TreeNode]:
    """Auto-detect file type and route to the correct parser."""
    ext = file_path.suffix.lower()
    if ext == ".md":
        return _parse_markdown(file_path)
    elif ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return _parse_docx(file_path)
    else:
        logger.warning(f"[tree_index] Unsupported file type: {ext} ({file_path.name})")
        return []


# ---------------------------------------------------------------------------
# Main Builder
# ---------------------------------------------------------------------------

def build_tree_index() -> None:
    """Read all documents from data/incidents/, parse sections, persist JSON tree."""
    if not DATA_DIR.exists():
        print(f"Error: Data directory {DATA_DIR} not found.")
        return

    all_nodes: list[TreeNode] = []
    file_counts: dict[str, int] = {}

    for ext in SUPPORTED_EXTENSIONS:
        for file_path in DATA_DIR.glob(f"*{ext}"):
            nodes = _parse_document(file_path)
            all_nodes.extend(nodes)
            file_counts[ext] = file_counts.get(ext, 0) + 1

    # Persist to disk
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(all_nodes, f, indent=2, ensure_ascii=False)

    total_files = sum(file_counts.values())
    print(f"Tree index built successfully: {INDEX_PATH}")
    print(f"  Total files  : {total_files}")
    for ext, count in sorted(file_counts.items()):
        print(f"    {ext:>6} : {count}")
    print(f"  Total nodes  : {len(all_nodes)}")


if __name__ == "__main__":
    build_tree_index()

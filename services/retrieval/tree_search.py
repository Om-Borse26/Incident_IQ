"""
Structure-aware (vectorless) search implementation.

Unlike vector search which relies on semantic distance to arbitrary text chunks,
tree search provides the LLM with a structural skeleton (Table of Contents) of
all incidents. The LLM reasons about the structure and selects the specific
logical nodes (sections) that are most likely to contain the answer.

We then return the FULL text of those selected sections. This completely
eliminates the "chunk boundary" failure mode where a heading is separated from
its accompanying body text.
"""

import json
import logging
from pathlib import Path
from pydantic import BaseModel, Field

from app.llm.client import ask_llm
from services.retrieval.tree_index import INDEX_PATH, TreeNode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types / Schemas
# ---------------------------------------------------------------------------

class TreeSearchResult(BaseModel):
    source_file: str
    incident_title: str
    section_heading: str
    section_text: str
    reasoning: str


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

_tree_index = None

def _get_tree_index() -> list[TreeNode]:
    """Load the JSON tree index into memory."""
    global _tree_index
    if _tree_index is None:
        from app.config import settings
        import os
        tree_path = os.path.join(settings.DATA_DIR, "tree_index", "incidents_tree.json")
        try:
            with open(tree_path, "r", encoding="utf-8") as f:
                _tree_index = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load tree index from {tree_path}: {e}")
            _tree_index = []
    return _tree_index


def _build_toc_prompt(nodes: list[TreeNode]) -> str:
    """
    Build a Table of Contents representing the structural skeleton of the incidents.
    We only include title, heading, and the short summary to save tokens.
    """
    # Group by incident to make it easier for the LLM to read
    incidents = {}
    for node in nodes:
        inc = node["incident_title"]
        if inc not in incidents:
            incidents[inc] = []
        incidents[inc].append(node)

    toc_lines = []
    for inc_title, inc_nodes in incidents.items():
        toc_lines.append(f"\nINCIDENT: {inc_title}")
        for n in inc_nodes:
            toc_lines.append(
                f"  - Node ID: {n['node_id']}\n"
                f"    Heading: {n['section_heading']}\n"
                f"    Summary: {n['section_summary']}"
            )
            
    return "\n".join(toc_lines)


from langsmith import traceable

@traceable(run_name="vectorless_retrieval")
def tree_search(query: str) -> list[TreeSearchResult]:
    """
    Perform a vectorless reasoning search over the document structure.
    
    1. Loads the structural index.
    2. Asks the LLM to reason over the Table of Contents and pick relevant nodes.
    3. Handles malformed JSON output gracefully.
    4. Returns the FULL text of the selected nodes.
    """
    nodes = _get_tree_index()
    if not nodes:
        return []

    toc_text = _build_toc_prompt(nodes)

    system_prompt = (
        "You are an expert retrieval routing agent. "
        "Your task is to identify which sections of the available incident reports "
        "are most likely to contain the answer to the user's query.\n\n"
        "Below is a structural skeleton (Table of Contents) of all incidents. "
        "It includes the Incident Title, Section Heading, and a brief snippet.\n\n"
        "INSTRUCTIONS:\n"
        "1. Read the user's query.\n"
        "2. Review the Table of Contents.\n"
        "3. Reason about which Node IDs (sections) are required to answer the query.\n"
        "4. Return your output EXACTLY as a valid JSON object matching this schema:\n"
        "{\n"
        '  "reasoning": "Step-by-step explanation of why these nodes were selected",\n'
        '  "selected_node_ids": ["node_id_1", "node_id_2"]\n'
        "}\n\n"
        "Do not include any text outside the JSON object. Do not wrap it in markdown code blocks.\n\n"
        f"TABLE OF CONTENTS:\n{toc_text}"
    )

    try:
        response_text = ask_llm(prompt=query, system=system_prompt)
        
        # Strip potential markdown backticks just in case the LLM ignores instructions
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
            
        clean_text = clean_text.strip()
        
        parsed = json.loads(clean_text)
        reasoning = parsed.get("reasoning", "No reasoning provided.")
        selected_ids = parsed.get("selected_node_ids", [])
        
    except json.JSONDecodeError as exc:
        logger.error(f"[tree_search] Malformed JSON from LLM: {exc}. Response was: {response_text}")
        # Degrade gracefully by returning an empty list (or we could try a fallback regex here)
        return []
    except Exception as exc:
        logger.error(f"[tree_search] LLM routing failed: {exc}")
        return []

    # Map selected IDs back to full nodes
    node_map = {n["node_id"]: n for n in nodes}
    results = []
    
    for nid in selected_ids:
        if nid in node_map:
            n = node_map[nid]
            results.append(TreeSearchResult(
                source_file=n["source_file"],
                incident_title=n["incident_title"],
                section_heading=n["section_heading"],
                section_text=n["section_text"],
                reasoning=reasoning
            ))
        else:
            logger.warning(f"[tree_search] LLM selected non-existent Node ID: {nid}")

    return results

if __name__ == "__main__":
    # A quick interactive test block for running this file directly from the terminal
    import sys
    
    query = "What caused the API gateway to return mass 502 errors?"
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        
    print(f"Searching tree for: '{query}'...\n")
    results = tree_search(query)
    
    if not results:
        print("No results found or LLM failed to select nodes.")
    else:
        for i, r in enumerate(results, 1):
            print(f"--- RESULT {i} ---")
            print(f"File:    {r.source_file}")
            print(f"Heading: {r.section_heading}")
            print(f"Reason:  {r.reasoning}")
            print(f"Text:\n{r.section_text}\n")

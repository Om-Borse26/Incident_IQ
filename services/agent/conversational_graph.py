"""
services/agent/conversational_graph.py

Phase 12: Conversational RAG — Multi-Turn Incident Analysis

This is the UPGRADED version of incident_graph.py (which is preserved for
learning purposes). The key architectural differences:

1. CONVERSATION MEMORY — The state now includes a `chat_history` list of
   (role, content) tuples. Every query and answer is appended, enabling
   the LLM to see the full conversation when answering follow-ups.

2. FOLLOW-UP DETECTION — A new `classify_followup_node` detects whether
   a message is:
     - "new_query"     → a brand-new incident question (full RAG pipeline)
     - "followup_rag"  → a follow-up that needs new retrieval (e.g., "what
                          about the payment-service?")
     - "followup_conv" → a conversational follow-up that does NOT need
                          retrieval (e.g., "explain that in simpler terms",
                          "give me an analogy", "summarize the fixes")

3. CONTEXTUAL QUERY REWRITING — For follow-up RAG queries, the classifier
   also rewrites the query to be self-contained. Example:
     Turn 1: "Why did checkout fail last week?"
     Turn 2: "What about the payment service?"
     Rewritten: "Why did the payment service fail last week?"
   This prevents the vector search from receiving an ambiguous query like
   "What about the payment service?" which has no context by itself.

4. CONVERSATIONAL RESPONSE NODE — For pure conversational follow-ups
   (no retrieval needed), a lightweight node answers using ONLY the
   existing chat history + the last RAG answer, without hitting ChromaDB.

Design principles:
  - The existing incident_graph.py is UNTOUCHED for learning purposes.
  - This module is a standalone replacement that can be swapped in.
  - All existing features (classify, diagnose, retrieve, reason, postmortem)
    are preserved identically.
  - The AnalyzeResponse model stays the same — no API contract changes.
"""

import json
import logging
import os
import asyncio
import sqlite3
from typing import TypedDict, List, Dict, Any

from pydantic import BaseModel, Field

from app.llm.client import get_chat_model

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State Schema — Extended with conversation memory
# ---------------------------------------------------------------------------

class ConversationalState(TypedDict):
    # Input
    query: str
    context: str

    # Conversation memory — list of {"role": "user"|"assistant", "content": str}
    chat_history: list

    # Follow-up classification
    is_followup: bool           # True if this is a follow-up to a previous turn
    followup_type: str          # "new_query" | "followup_rag" | "followup_conv"
    rewritten_query: str        # Self-contained version of follow-up queries
    user_mood: str              # e.g., 'stressed', 'joking', 'formal'
    dynamic_temperature: float  # LLM sampling temp based on mood

    # Classification
    query_type: str             # "live" | "historical" | "chitchat" | "unknown"

    # Retrieval results (populated by retrieve_node)
    retrieved_incidents: list
    vectorless_results: list

    # Diagnostics results (populated by diagnose_node)
    live_logs: str
    service_health: dict
    recent_deploys: list
    diagnostics_available: bool

    # Reasoning output (populated by reason_node)
    mode: str                   # "known" | "partial" | "unknown"
    confidence: float
    answer: str
    reasoning: str
    suggested_fixes: list
    sources: list

    # Control flow
    needs_postmortem: bool
    postmortem_approved: bool
    generated_postmortem_path: str
    iteration_count: int


# ---------------------------------------------------------------------------
# Pydantic models for structured LLM output
# ---------------------------------------------------------------------------

class FollowupClassification(BaseModel):
    """Classifies whether a user message is a new query or a follow-up."""
    followup_type: str = Field(
        description=(
            "'new_query' if this is a brand-new question unrelated to previous conversation, "
            "'followup_rag' if the user is asking a follow-up that requires searching for NEW incidents "
            "(e.g., 'what about the payment service?', 'any similar issues with redis?'), "
            "'followup_conv' if the user is asking for clarification, rephrasing, analogies, "
            "or further explanation of the PREVIOUS answer without needing new data "
            "(e.g., 'explain that simpler', 'give me an analogy', 'summarize the fixes', 'what do you mean by that?')"
        )
    )
    rewritten_query: str = Field(
        description=(
            "If followup_type is 'followup_rag', rewrite the user's query to be self-contained "
            "by incorporating context from the conversation history. "
            "If followup_type is 'new_query', just return the original query unchanged. "
            "If followup_type is 'followup_conv', return the original query unchanged."
        )
    )
    user_mood: str = Field(
        description="The emotional tone or mood of the user based on their query "
                    "(e.g., 'stressed', 'curious', 'joking', 'formal', 'frustrated')."
    )
    suggested_temperature: float = Field(
        description="A float between 0.1 and 0.8. Use lower values (0.1-0.3) if the user "
                    "is stressed, formal, or needs strict technical accuracy. Use higher "
                    "values (0.6-0.8) if the user is joking, curious, or asking for analogies."
    )


class QueryClassification(BaseModel):
    query_type: str = Field(
        description="'live' if the query implies an ongoing/current issue, "
                    "'historical' if it asks about past incidents, "
                    "'chitchat' if the query is a general question, greeting, or off-topic, "
                    "'unknown' otherwise"
    )


class DiagnosticExtraction(BaseModel):
    """The structured output for extracting diagnostics without generating the text answer."""
    mode: str = Field(description="The incident mode: 'known', 'unknown', or 'degraded'.")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0.")
    reasoning: str = Field(description="A brief explanation of how the root cause was determined.")
    suggested_fixes: List[str] = Field(description="A list of step-by-step instructions or fixes.")
    sources: List[str] = Field(description="A list of filenames or links cited.")
    needs_postmortem: bool = Field(description="True if this is a NEW major incident that needs documenting.")


class ServiceExtraction(BaseModel):
    service_name: str = Field(
        description="The normalized name of the service mentioned in the query. "
                    "You MUST fix typos, spelling errors, and informal names. "
                    "Always format it in lowercase with hyphens. "
                    "For example: 'notif service' -> 'notification-service', "
                    "'checkout svc' -> 'checkout-service', 'api gateway' -> 'api-gateway'."
    )


# ---------------------------------------------------------------------------
# Helper: format chat history for LLM context
# ---------------------------------------------------------------------------

def _format_history_for_prompt(chat_history: list, max_turns: int = 10) -> str:
    """
    Format the last N turns of chat history into a readable prompt block.

    We limit to max_turns to avoid blowing up the context window on very
    long conversations. The most recent turns are always included.
    """
    if not chat_history:
        return "(No previous conversation)"

    recent = chat_history[-max_turns * 2:]  # Each turn = 2 entries (user + assistant)
    lines = []
    for entry in recent:
        role = entry.get("role", "unknown").upper()
        content = entry.get("content", "")
        lines.append(f"{role}: {content}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def classify_followup_node(state: ConversationalState) -> dict:
    """
    PHASE 12 NODE: Determine if this message is a follow-up or a new query.

    This node only runs when there IS chat history. On the first message of
    a conversation, the router skips this and goes straight to classify_node.

    Three possible outcomes:
      - new_query:     Completely new topic → full RAG pipeline
      - followup_rag:  Follow-up needing new search → rewrite query + RAG
      - followup_conv: Conversational follow-up → answer from history only
    """
    logger.info("[graph] classify_followup_node executing...")
    llm = get_chat_model(temperature=0.0)  # Deterministic for structured output
    extractor = llm.with_structured_output(FollowupClassification)

    history_text = _format_history_for_prompt(state.get("chat_history", []))

    prompt = f"""You are analyzing a conversation to determine if the latest user message
is a new question or a follow-up to the previous conversation.

CONVERSATION HISTORY:
{history_text}

LATEST USER MESSAGE: {state['query']}

Classify the latest message and, if it's a followup_rag, rewrite it to be
self-contained by incorporating context from the conversation."""

    try:
        res = await extractor.ainvoke(prompt)
        return {
            "is_followup": res.followup_type != "new_query",
            "followup_type": res.followup_type,
            "rewritten_query": res.rewritten_query,
            "user_mood": res.user_mood,
            "dynamic_temperature": res.suggested_temperature,
        }
    except Exception as e:
        logger.error(f"[graph] classify_followup_node failed: {e}")
        # Default: treat as a new query so we don't break the pipeline
        return {
            "is_followup": False,
            "followup_type": "new_query",
            "rewritten_query": state["query"],
            "user_mood": "formal",
            "dynamic_temperature": 0.3,
        }


async def classify_node(state: ConversationalState) -> dict:
    """Is this a live incident or a historical/analysis query?"""
    logger.info("[graph] classify_node executing...")
    # State Schema Safety: Explicitly clear out old data on a new query turn!
    cleared_state = {
        "retrieved_incidents": [],
        "vectorless_results": [],
        "live_logs": "",
        "service_health": {},
        "recent_deploys": []
    }
    
    llm = get_chat_model(temperature=0.0)  # Deterministic
    extractor = llm.with_structured_output(QueryClassification)

    # Use the rewritten query if available (from follow-up rewriting)
    query_to_classify = state.get("rewritten_query") or state["query"]

    try:
        res = await extractor.ainvoke(f"Classify the following query:\n\n{query_to_classify}")
        cleared_state["query_type"] = res.query_type
        return cleared_state
    except Exception as e:
        logger.error(f"[graph] classify_node failed: {e}")
        cleared_state["query_type"] = "historical"
        return cleared_state


async def chitchat_node(state: ConversationalState) -> dict:
    """Handle general questions, greetings, and off-topic queries dynamically."""
    logger.info("[graph] chitchat_node executing...")
    llm = get_chat_model(temperature=state.get("dynamic_temperature", 0.6))

    history_text = _format_history_for_prompt(state.get("chat_history", []))

    prompt = f"""You are IncidentIQ, an AI reliability engineer.
The user asked a general question or greeting that does not require searching the incident database.
Answer the question helpfully and conversationally based on your general knowledge.

USER MOOD: {state.get('user_mood', 'neutral')}
INSTRUCTIONS:
- Adapt your tone to match the user's mood (e.g. joke back if they are joking, be formal if they are stressed).
- Use rich markdown formatting and emojis to make your response engaging and visually appealing.
- GUARDRAIL: You are an SRE assistant. If the user asks you to write generic code (e.g., a python script), do research, write essays, or perform tasks unrelated to system diagnostics and incident resolution, you MUST politely refuse. Example: "I'm IncidentIQ, your AI reliability engineer. I can only assist with system diagnostics, postmortems, and incident resolution. I can't write generic code for you!"

CONVERSATION HISTORY:
{history_text}

User Query: {state['query']}
"""
    try:
        res = await llm.ainvoke(prompt)
        answer = res.content
    except Exception as e:
        logger.error(f"[graph] chitchat_node LLM failed: {e}")
        answer = ("Hi! I'm IncidentIQ, your AI reliability engineer. 🤖\n\n"
                  "I'm currently having trouble connecting to my brain, "
                  "but I'm here to help with production incidents! 💡")

    # Append to chat history and truncate to last 12 messages (6 turns)
    updated_history = list(state.get("chat_history", []))
    updated_history.append({"role": "user", "content": state["query"]})
    updated_history.append({"role": "assistant", "content": answer})
    updated_history = updated_history[-12:]

    return {
        "answer": answer,
        "mode": "known",
        "confidence": 1.0,
        "reasoning": "Answered using general knowledge.",
        "suggested_fixes": [],
        "sources": [],
        "diagnostics_available": False,
        "needs_postmortem": False,
        "chat_history": updated_history,
    }


async def conversational_response_node(state: ConversationalState) -> dict:
    """
    PHASE 12 NODE: Answer a conversational follow-up using ONLY existing
    chat history — no new retrieval needed.
    """
    logger.info("[graph] conversational_response_node executing...")
    llm = get_chat_model(temperature=state.get("dynamic_temperature", 0.5))

    history_text = _format_history_for_prompt(state.get("chat_history", []))

    prompt = f"""You are IncidentIQ, an expert SRE assistant having a multi-turn conversation.
The user is asking a follow-up question about your PREVIOUS answer. You do NOT need to
search for new incidents. Answer using the conversation context below.

USER MOOD: {state.get('user_mood', 'neutral')}

CONVERSATION HISTORY:
{history_text}

USER'S FOLLOW-UP: {state['query']}

INSTRUCTIONS:
- Adapt your tone to match the user's mood.
- If they ask for simpler language, use plain English and analogies.
- If they ask for a summary, condense the key points.
- If they ask "what do you mean by X?", explain that specific concept.
- Maintain the same accuracy — don't invent new incident data.
- Use rich markdown formatting, including bold text, bullet points, and appropriate emojis (e.g. 🔴, 🟢, 💡, 📊) to make the response engaging.
"""

    try:
        res = await llm.ainvoke(prompt)
        answer = res.content
    except Exception as e:
        logger.error(f"[graph] conversational_response_node failed: {e}")
        answer = "I'm sorry, I had trouble processing your follow-up. Could you rephrase? 🤔"

    # Append to chat history and truncate
    updated_history = list(state.get("chat_history", []))
    updated_history.append({"role": "user", "content": state["query"]})
    updated_history.append({"role": "assistant", "content": answer})
    updated_history = updated_history[-12:]

    return {
        "answer": answer,
        "mode": state.get("mode", "known"),
        "confidence": state.get("confidence", 0.9),
        "reasoning": "Answered from conversation context (no new retrieval).",
        "suggested_fixes": state.get("suggested_fixes", []),
        "sources": state.get("sources", []),
        "diagnostics_available": state.get("diagnostics_available", False),
        "needs_postmortem": False,
        "chat_history": updated_history,
    }


async def diagnose_node(state: ConversationalState) -> dict:
    """Call MCP diagnostic tools against the relevant service."""
    logger.info("[graph] diagnose_node executing...")
    llm = get_chat_model(temperature=0.0)  # Deterministic extraction
    extractor = llm.with_structured_output(ServiceExtraction)

    query_to_use = state.get("rewritten_query") or state["query"]

    try:
        extracted = await extractor.ainvoke(f"Extract the service name from: {query_to_use}")
        service_name = extracted.service_name.replace(" ", "-").lower() if extracted.service_name else ""
    except Exception:
        service_name = ""

    if not service_name:
        return {
            "diagnostics_available": False,
            "live_logs": "Could not extract service name",
            "service_health": {},
            "recent_deploys": [],
        }

    # Connect to MCP
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from langchain_mcp_adapters.tools import load_mcp_tools

        import sys

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "services.diagnostics.server"],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_tools = await load_mcp_tools(session)

                tool_map = {t.name: t for t in mcp_tools}

                # Wrap MCP tool calls in 10s timeouts to prevent graph hanging
                logs = ""
                if "fetch_recent_logs" in tool_map:
                    try:
                        logs = await asyncio.wait_for(
                            tool_map["fetch_recent_logs"].ainvoke({"service_name": service_name, "minutes": 30}),
                            timeout=10.0
                        )
                    except Exception as e:
                        logger.warning(f"[diagnose_node] fetch_recent_logs failed: {e}")
                        logs = "No live logs available."

                health = {}
                if "check_service_health" in tool_map:
                    try:
                        health_str = await asyncio.wait_for(
                            tool_map["check_service_health"].ainvoke({"service_name": service_name}),
                            timeout=10.0
                        )
                        health = json.loads(health_str) if isinstance(health_str, str) else health_str
                    except Exception as e:
                        logger.warning(f"[diagnose_node] check_service_health failed: {e}")
                        health = {"error": "Telemetry stream unavailable."}

                deploys = []
                if "get_recent_deploys" in tool_map:
                    try:
                        deploys_str = await asyncio.wait_for(
                            tool_map["get_recent_deploys"].ainvoke({"service_name": service_name, "hours": 24}),
                            timeout=10.0
                        )
                        deploys = (
                            json.loads(deploys_str).get("deploys", [])
                            if isinstance(deploys_str, str)
                            else deploys_str.get("deploys", [])
                        )
                    except Exception as e:
                        logger.warning(f"[diagnose_node] get_recent_deploys failed: {e}")
                        deploys = []

        return {
            "live_logs": str(logs),
            "service_health": health,
            "recent_deploys": deploys,
            "diagnostics_available": True,
        }
    except Exception as e:
        logger.error(f"[graph] MCP Error in diagnose_node: {e}")
        return {"diagnostics_available": False, "live_logs": f"MCP Error: {e}"}


async def retrieve_node(state: ConversationalState) -> dict:
    """Call both Vector and Vectorless RAG to retrieve historical context."""
    logger.info("[graph] retrieve_node executing...")
    from services.retrieval.search import search_incidents
    from services.retrieval.tree_search import tree_search

    query_to_search = state.get("rewritten_query") or state["query"]
    logger.info("[graph] Searching with query: '%s'", query_to_search)

    import asyncio

    # 1. Vector Search
    try:
        vector_res = await asyncio.to_thread(search_incidents, query_to_search, 4)
        v_list = [
            {"title": r.incident_title, "text": r.text[:1500] + ("..." if len(r.text) > 1500 else ""), "source": r.source}
            for r in vector_res
        ]
    except Exception as e:
        logger.error(f"[retrieve_node] Vector search failed: {e}")
        v_list = [{"error": str(e)}]

    # 2. Tree Search
    try:
        tree_res = await asyncio.to_thread(tree_search, query_to_search)
        t_list = [
            {
                "title": r.incident_title,
                "section": r.section_heading,
                "text": r.section_text[:1500] + ("..." if len(r.section_text) > 1500 else ""),
                "source": r.source_file,
            }
            for r in tree_res
        ]
    except Exception as e:
        t_list = [{"error": str(e)}]

    return {"retrieved_incidents": v_list, "vectorless_results": t_list}


async def diagnostic_extraction_node(state: ConversationalState) -> dict:
    """Extract structured data (mode, confidence, fixes, etc.) without generating the final text."""
    logger.info("[graph] diagnostic_extraction_node executing...")
    llm = get_chat_model(temperature=0.0)
    extractor = llm.with_structured_output(DiagnosticExtraction)

    query_to_use = state.get("rewritten_query") or state["query"]
    
    # Token protection: truncate extremely long logs
    raw_logs = state.get('live_logs', "")
    safe_logs = raw_logs[-2000:] if raw_logs else "No logs available."

    prompt = f"""You are IncidentIQ's backend diagnostic extractor.
Analyze the available state and extract the structured fields.

State Information:
Query: {query_to_use}
Diagnostics Available: {state.get('diagnostics_available')}
Health: {json.dumps(state.get('service_health', {}), indent=2)}
Deploys: {json.dumps(state.get('recent_deploys', []), indent=2)}
Logs (last 2000 chars): {safe_logs}

Historical Context:
Vector Results: {json.dumps(state.get('retrieved_incidents', []), indent=2)}
Tree Results: {json.dumps(state.get('vectorless_results', []), indent=2)}

Determine if this represents a new major incident requiring a postmortem.
Return only the extracted mode, confidence, reasoning, suggested fixes, sources, and needs_postmortem.
"""
    try:
        res = await extractor.ainvoke(prompt)

        # Guarantee accurate sources by pulling directly from state
        actual_sources = []
        for r in state.get("retrieved_incidents", []):
            src = r.get("source")
            if src and src not in actual_sources and src != "unknown":
                actual_sources.append(src)
        for r in state.get("vectorless_results", []):
            src = r.get("source")
            if src and src not in actual_sources and src != "unknown":
                actual_sources.append(src)

        return {
            "mode": res.mode,
            "confidence": res.confidence,
            "reasoning": res.reasoning,
            "suggested_fixes": res.suggested_fixes,
            "sources": actual_sources if actual_sources else res.sources,
            "needs_postmortem": res.needs_postmortem,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    except Exception as e:
        logger.error(f"[graph] diagnostic_extraction_node failed: {e}")
        return {
            "mode": "unknown",
            "confidence": 0.0,
            "reasoning": f"Extraction error: {e}",
            "suggested_fixes": [],
            "sources": [],
            "needs_postmortem": False
        }


async def generate_answer_node(state: ConversationalState) -> dict:
    """Generate the final markdown text answer."""
    logger.info("[graph] generate_answer_node executing...")
    llm = get_chat_model(temperature=state.get("dynamic_temperature", 0.3))

    history_text = _format_history_for_prompt(state.get("chat_history", []))

    # Extract raw documents for strict context
    raw_vector_results = json.dumps(state.get('retrieved_incidents', []), indent=2)
    raw_tree_results = json.dumps(state.get('vectorless_results', []), indent=2)
    raw_logs = state.get('live_logs', "")
    safe_logs = raw_logs[-2000:] if raw_logs else "No logs available."

    prompt = f"""You are IncidentIQ, an expert SRE diagnostic agent and friendly copilot.
Generate the final markdown text answer based on the extracted diagnostics and raw historical context.

CONVERSATION HISTORY:
{history_text}

USER MOOD: {state.get('user_mood', 'neutral')}
EXTRACTED MODE: {state.get('mode')}
SUGGESTED FIXES: {json.dumps(state.get('suggested_fixes', []))}
REASONING: {state.get('reasoning')}

LIVE DIAGNOSTICS:
Health: {json.dumps(state.get('service_health', {}), indent=2)}
Deploys: {json.dumps(state.get('recent_deploys', []), indent=2)}
Logs: {safe_logs}

RAW HISTORICAL CONTEXT:
Vector Results: {raw_vector_results}
Tree Results: {raw_tree_results}

Original User Message: {state['query']}

TONE INSTRUCTIONS:
- Adapt your conversational tone and style (friendly, formal, joking) to match the USER MOOD.
- Your technical facts MUST be strictly grounded in BOTH the RAW HISTORICAL CONTEXT and LIVE DIAGNOSTICS above. 
- If the user explicitly asks for logs or live metrics, you MUST print them exactly as they appear in the LIVE DIAGNOSTICS section.
- Do not invent fixes or fluff the technical analysis. 
- When explaining root causes or suggesting fixes, pull the exact details, timestamps, or code from the raw context or live logs.
- Quote directly from the source documents when providing fixes.
- Use rich markdown formatting and emojis to format your answer nicely.
- If mode is 'unknown', say so politely, but you MUST still provide the LIVE DIAGNOSTICS and Logs if they are available.
"""
    try:
        res = await llm.ainvoke(prompt)
        answer = res.content
    except Exception as e:
        logger.error(f"[graph] generate_answer_node failed: {e}")
        error_msg = str(e).lower()
        
        fallback_msg = "⚠️ **AI Generation Failed** ⚠️\n\n"
        if "429" in error_msg or "rate limit" in error_msg or "too many requests" in error_msg:
            fallback_msg += "The system is currently experiencing high traffic and the AI models have hit their **Rate Limits**. "
        else:
            fallback_msg += "An unexpected error occurred while communicating with the AI models. "
            
        fallback_msg += "However, to ensure you can still diagnose the issue, here are the raw incident records we retrieved from the database:\n\n"
        
        retrieved = state.get("retrieved_incidents", [])
        if retrieved and len(retrieved) > 0 and "title" in retrieved[0]:
            for i, chunk in enumerate(retrieved, 1):
                fallback_msg += f"{i}. **{chunk.get('title', 'Unknown')}** (Source: `{chunk.get('source', 'Unknown')}`)\n"
                text_snippet = chunk.get("text", "")[:300].replace("\n", " ")
                fallback_msg += f"   > *{text_snippet}...*\n\n"
        else:
            fallback_msg += "*No relevant historical context was found.*"
            
        answer = fallback_msg

    # Append this turn to chat history and truncate
    updated_history = list(state.get("chat_history", []))
    updated_history.append({"role": "user", "content": state["query"]})
    updated_history.append({"role": "assistant", "content": answer})
    updated_history = updated_history[-12:]

    return {
        "answer": answer,
        "chat_history": updated_history
    }


def human_approval_node(state: ConversationalState) -> dict:
    """Interrupt the graph to ask for human approval for a postmortem."""
    logger.info("[graph] human_approval_node executing (pausing graph)...")
    from langgraph.types import interrupt

    approval = interrupt(
        {"message": "Draft postmortem ready. Do you approve?", "action_required": True}
    )

    approved = False
    if isinstance(approval, dict) and approval.get("action") == "approve":
        approved = True
    elif isinstance(approval, str) and approval.lower() == "approve":
        approved = True

    return {"postmortem_approved": approved}


async def generate_postmortem_node(state: ConversationalState) -> dict:
    """Generate a Markdown postmortem and save it to raw_documents."""
    logger.info("[graph] generate_postmortem_node executing...")
    llm = get_chat_model()

    prompt = f"""You are a Senior SRE. Write a professional incident postmortem in Markdown format.
Use the following context to generate the postmortem:
Query: {state['query']}
Symptoms/Logs: {state.get('live_logs')}
RCA / Answer: {state.get('answer')}
Suggested Fixes: {chr(10).join(state.get('suggested_fixes', []))}

The output MUST be pure markdown without code blocks backticks around the entire document.
Include sections: # Incident Postmortem, ## Symptoms, ## Root Cause, ## Resolution Steps, ## Prevention."""

    try:
        from langchain_core.messages import SystemMessage
        messages = [SystemMessage(content=prompt)]
        res = await llm.ainvoke(messages)

        import time
        from pathlib import Path

        data_dir = os.environ.get("DATA_DIR", ".")
        raw_docs_dir = Path(data_dir) / "raw_documents"
        raw_docs_dir.mkdir(parents=True, exist_ok=True)

        filename = f"INC-{int(time.time())}.md"
        file_path = raw_docs_dir / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(res.content)

        return {"generated_postmortem_path": str(file_path)}
    except Exception as e:
        logger.error(f"[graph] generate_postmortem_node failed: {e}")
        return {"generated_postmortem_path": f"Error: {e}"}


def respond_node(state: ConversationalState) -> dict:
    """Terminal node to format the final output if necessary."""
    logger.info("[graph] respond_node executing...")
    return {}


# ---------------------------------------------------------------------------
# Graph Routing
# ---------------------------------------------------------------------------

def route_entry(state: ConversationalState) -> str:
    """
    ENTRY ROUTER: Decide whether to check for follow-ups or go straight
    to classification.

    If there is chat history → the user might be asking a follow-up.
    If there is no chat history → this is the first message, go to classify.
    """
    if state.get("chat_history"):
        return "classify_followup_node"
    return "classify_node"


def route_after_followup(state: ConversationalState) -> str:
    """
    Route based on follow-up classification:
      - new_query     → classify_node (full pipeline)
      - followup_rag  → classify_node (with rewritten query, full pipeline)
      - followup_conv → conversational_response_node (no retrieval needed)
    """
    ftype = state.get("followup_type", "new_query")
    if ftype == "followup_conv":
        return "conversational_response_node"
    # Both "new_query" and "followup_rag" go through the full pipeline.
    # The difference is that "followup_rag" has a rewritten_query set.
    return "classify_node"


def route_after_classify(state: ConversationalState) -> list[str]:
    """Deterministic routing based on explicit state rather than LLM reasoning."""
    q_type = state.get("query_type")
    if q_type == "chitchat":
        return ["chitchat_node"]
    if q_type == "live":
        return ["diagnose_node", "retrieve_node"]
    return ["retrieve_node"]


def route_after_generation(state: ConversationalState) -> str:
    """Route to approval if needed, otherwise skip to respond."""
    if state.get("iteration_count", 0) > 3:
        logger.warning("[graph] Iteration limit exceeded! Forcefully terminating loop.")
        return "respond_node"
    if state.get("needs_postmortem") and not state.get("postmortem_approved"):
        return "human_approval_node"
    return "respond_node"


def route_after_approval(state: ConversationalState) -> str:
    """Route to generate postmortem if approved, otherwise end."""
    if state.get("postmortem_approved"):
        return "generate_postmortem_node"
    return "respond_node"


# ---------------------------------------------------------------------------
# Graph Compilation
# ---------------------------------------------------------------------------

def build_conversational_graph():
    """
    Build the Phase 12 Conversational RAG graph.

    Graph topology:
                        ┌─── has history ──→ classify_followup_node
        START → entry ──┤                         │
                        └─── no history ──→ classify_node ←──────────┘
                                              │                (new_query / followup_rag)
                                    ┌─────────┤
                                    │         │          (followup_conv)
                              chitchat  [diagnose + retrieve]    │
                                │         │               conversational_response_node
                                └─→ reason_node ←─────┘         │
                                      │                          │
                              [approval flow]                    │
                                      │                          │
                                respond_node ←───────────────────┘
                                      │
                                     END
    """
    from langgraph.graph import StateGraph, START, END

    workflow = StateGraph(ConversationalState)

    # Add nodes
    workflow.add_node("classify_followup_node", classify_followup_node)
    workflow.add_node("classify_node", classify_node)
    workflow.add_node("chitchat_node", chitchat_node)
    workflow.add_node("conversational_response_node", conversational_response_node)
    workflow.add_node("diagnose_node", diagnose_node)
    workflow.add_node("retrieve_node", retrieve_node)
    workflow.add_node("diagnostic_extraction_node", diagnostic_extraction_node)
    workflow.add_node("generate_answer_node", generate_answer_node)
    workflow.add_node("human_approval_node", human_approval_node)
    workflow.add_node("generate_postmortem_node", generate_postmortem_node)
    workflow.add_node("respond_node", respond_node)

    # Entry: check if we have chat history
    workflow.add_conditional_edges(START, route_entry)

    # Follow-up routing
    workflow.add_conditional_edges("classify_followup_node", route_after_followup)

    # Conversational response goes straight to respond (no RAG needed)
    workflow.add_edge("conversational_response_node", "respond_node")

    # Standard classification routing
    workflow.add_conditional_edges("classify_node", route_after_classify)
    workflow.add_edge("chitchat_node", "respond_node")

    # Retrieval + diagnosis → diagnostic extraction
    workflow.add_edge("diagnose_node", "diagnostic_extraction_node")
    workflow.add_edge("retrieve_node", "diagnostic_extraction_node")

    # Extraction → Generation
    workflow.add_edge("diagnostic_extraction_node", "generate_answer_node")

    # Generation → approval or respond
    workflow.add_conditional_edges("generate_answer_node", route_after_generation)

    # Approval flow
    workflow.add_conditional_edges("human_approval_node", route_after_approval)
    workflow.add_edge("generate_postmortem_node", "respond_node")

    # Terminal
    workflow.add_edge("respond_node", END)

    # We do NOT compile with a checkpointer here because AsyncSqliteSaver requires
    # an async context manager. We will compile it dynamically in the FastAPI endpoint.
    return workflow


# Expose the uncompiled workflow. FastAPI will compile it per-request with the checkpointer.
conversational_workflow = build_conversational_graph()

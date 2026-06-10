import os
import json
import asyncio
from langsmith import Client
from langsmith.evaluation import evaluate
from langsmith.schemas import Run, Example
from pydantic import BaseModel, Field

# Ensure project root is in path if running from subfolder
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.llm.client import get_chat_model

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# If False, only the retrieval layer is called (search_incidents + tree_search)
# This allows testing context_precision without any LLM calls.
USE_REAL_GRAPH = os.environ.get("USE_REAL_GRAPH", "True").lower() == "true"

# If False, only code-based evaluators (context_precision) are run.
# This prevents token exhaustion. LLM-as-judge evaluators are skipped.
RUN_LLM_EVALUATORS = os.environ.get("RUN_LLM_EVALUATORS", "True").lower() == "true"

DATASET_NAME = "incidentiq-rag-eval"

# ---------------------------------------------------------------------------
# Dataset Initialization
# ---------------------------------------------------------------------------
def init_dataset(client: Client):
    try:
        client.read_dataset(dataset_name=DATASET_NAME)
        print(f"Dataset '{DATASET_NAME}' already exists.")
    except Exception:
        print(f"Creating dataset '{DATASET_NAME}'...")
        dataset = client.create_dataset(dataset_name=DATASET_NAME)
        
        with open(os.path.join(os.path.dirname(__file__), "dataset.json"), "r") as f:
            data = json.load(f)
        
        for item in data:
            inputs = {"query": item["query"]}
            outputs = {"expected_source": item["expected_source"], "should_answer": item["should_answer"]}
            # Special naming for C3 to track it permanently
            name = "api_gateway_502_root_cause" if item["id"] == "C3" else item["id"]
            
            client.create_example(
                inputs=inputs,
                outputs=outputs,
                dataset_id=dataset.id,
                metadata={"note": item["note"]},
            )

# ---------------------------------------------------------------------------
# Target Function
# ---------------------------------------------------------------------------
async def run_incident_analysis(inputs: dict) -> dict:
    query = inputs["query"]
    
    if not USE_REAL_GRAPH:
        from services.retrieval.search import search_incidents
        from services.retrieval.tree_search import tree_search
        
        # Retrieval-only mode (No LLM calls)
        vector_res = search_incidents(query, k=4)
        tree_res = tree_search(query)
        
        sources = [r.source for r in vector_res] + [r.source_file for r in tree_res]
        return {
            "answer": "Retrieval-only mode, no answer generated.",
            "sources": sources
        }
    else:
        from services.agent.incident_graph import incident_graph
        from langchain_core.runnables import RunnableConfig
        import uuid
        
        session_id = str(uuid.uuid4())
        config = RunnableConfig(
            configurable={"thread_id": session_id},
            run_name="incident_analysis",
            metadata={"session_id": session_id}
        )
        
        final_state = await incident_graph.ainvoke({"query": query, "context": ""}, config)
        
        return {
            "answer": final_state.get("answer", ""),
            "sources": final_state.get("sources", [])
        }

# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------
def context_precision(run: Run, example: Example) -> dict:
    """Code-based evaluator: is the expected source in the retrieved sources?"""
    expected_source = example.outputs.get("expected_source")
    if not expected_source:
        return {"key": "context_precision", "score": None}
    
    actual_sources = run.outputs.get("sources", [])
    hit = any(expected_source in src for src in actual_sources)
    return {"key": "context_precision", "score": 1.0 if hit else 0.0}

class JudgeResult(BaseModel):
    score: int = Field(description="1 if passing, 0 if failing")
    reasoning: str

def faithfulness(run: Run, example: Example) -> dict:
    """LLM-as-judge: is the answer faithful to the retrieved sources?"""
    answer = run.outputs.get("answer", "")
    sources = run.outputs.get("sources", [])
    if not USE_REAL_GRAPH or "Retrieval-only mode" in answer:
        return {"key": "faithfulness", "score": None}
        
    llm = get_chat_model()
    extractor = llm.with_structured_output(JudgeResult)
    prompt = f"""Evaluate if the answer is faithful to the provided context (sources).
Answer: {answer}
Sources: {sources}

Return 1 if the answer is fully supported by the sources, 0 if it contains unsupported hallucination."""
    try:
        res = extractor.invoke(prompt)
        return {"key": "faithfulness", "score": res.score, "comment": res.reasoning}
    except Exception as e:
         return {"key": "faithfulness", "score": 0.0, "comment": f"Judge error: {e}"}

def answer_relevance(run: Run, example: Example) -> dict:
    """LLM-as-judge: does the answer directly address the user's query?"""
    answer = run.outputs.get("answer", "")
    query = example.inputs.get("query", "")
    if not USE_REAL_GRAPH or "Retrieval-only mode" in answer:
        return {"key": "answer_relevance", "score": None}
        
    llm = get_chat_model()
    extractor = llm.with_structured_output(JudgeResult)
    prompt = f"""Evaluate if the answer directly addresses the user's query.
Query: {query}
Answer: {answer}

Return 1 if it is relevant and helpful, 0 if it misses the point."""
    try:
        res = extractor.invoke(prompt)
        return {"key": "answer_relevance", "score": res.score, "comment": res.reasoning}
    except Exception as e:
         return {"key": "answer_relevance", "score": 0.0, "comment": f"Judge error: {e}"}

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------
def main():
    # LLM-as-judge is non-deterministic — run 3+ times, measure pass RATE not individual pass/fail (from LangSmith notes §6)
    
    client = Client()
    init_dataset(client)
    
    evaluators = [context_precision]
    if RUN_LLM_EVALUATORS:
        evaluators.extend([faithfulness, answer_relevance])
        
    experiment_prefix = "phase6-baseline"
    if not USE_REAL_GRAPH:
        experiment_prefix = "phase6-retrieval-only"
        
    print(f"Running evaluation: USE_REAL_GRAPH={USE_REAL_GRAPH}, RUN_LLM_EVALUATORS={RUN_LLM_EVALUATORS}")
    
    # We must wrap the async target function correctly for evaluate()
    def sync_target(inputs):
        return asyncio.run(run_incident_analysis(inputs))
        
    results = evaluate(
        sync_target,
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=experiment_prefix
    )
    print("Evaluation completed. Check LangSmith UI for results.")

if __name__ == "__main__":
    main()

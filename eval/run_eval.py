"""
RAG Evaluation Harness — Phase 1, Step 3.

Metrics measured per test case
================================
CONTEXT PRECISION (code-based, no LLM)
    Is the expected source file present in the top-k retrieved chunks?
    Measured on RETRIEVAL ALONE, before the LLM is called.

    WHY SEPARATE FROM ANSWER METRICS:
    Retrieval and generation are independent failure modes:
      - Good retrieval + bad generation  => faithful metric catches it
      - Bad retrieval + lucky generation => context precision catches it
      - Bad retrieval + bad generation   => both fail — tells you where to fix
    If you only measure the final answer, you can't distinguish "the LLM
    made something up" from "the right chunk was never fetched in the first
    place". Fixing them requires completely different interventions
    (chunking/embedding tuning vs. prompt engineering), so you need both
    signals independently.

FAITHFULNESS (LLM-as-judge)
    "Is every claim in the answer supported by the provided context?"
    Catches hallucinations: the LLM inventing facts not in the chunks.

ANSWER RELEVANCE (LLM-as-judge)
    "Does the answer actually address the question that was asked?"
    Catches evasion: a perfectly faithful answer that sidesteps the question.

I-DON'T-KNOW (string match, for should_answer:false cases)
    Does the answer contain the expected refusal phrase?
    This tests the grounding guard — the LLM must say "I don't have enough
    information" rather than confabulating an answer from training data.

WHY LLM-AS-JUDGE IS ITSELF IMPERFECT:
    1. Self-serving bias: if the judge and the answering model share weights
       (same LLM for both), the judge may be lenient on its own output.
       Mitigation: use a different, stronger model as the judge in production.
    2. Prompt sensitivity: a slight wording change to the judge prompt can
       flip YES/NO on borderline cases. The judge is not a ground-truth oracle.
    3. Positional bias: judges tend to favour the first option presented.
    4. No calibration: YES/NO gives no confidence score — a marginal YES
       looks identical to a clear YES.
    For this harness the judge is the same Groq model (llama-3.3-70b) used
    for answering. That is acceptable for development/iteration but should
    be upgraded to a stronger external judge for production evaluation.

Run:
    python -m eval.run_eval
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from textwrap import shorten

from app.llm.client import ask_llm
from app.main import _build_rag_system_prompt
from services.retrieval.search import search_incidents
from services.retrieval.tree_search import tree_search

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_EVAL_DIR = Path(__file__).resolve().parent
DATASET_PATH = _EVAL_DIR / "dataset.json"
RESULTS_PATH = _EVAL_DIR / "results.csv"

# Number of chunks to retrieve for every eval query (mirrors the API default)
K = 4

# The exact phrase the model is instructed to say when it can't answer
DONT_KNOW_PHRASE = "I don't have enough information in the provided incident reports"


# ---------------------------------------------------------------------------
# Judge helpers
# ---------------------------------------------------------------------------

def _judge_yes_no(question: str) -> bool:
    """
    Ask the LLM a YES/NO judge question and return True for YES, False for NO.

    The prompt is deliberately terse to reduce position-bias and force a
    binary answer. Any response that doesn't start with YES is treated as NO
    to avoid false-positive faithfulness scores.
    """
    system = (
        "You are a strict evaluator. "
        "Answer the following question with a single word: YES or NO. "
        "Do not add any explanation."
    )
    raw = ask_llm(prompt=question, system=system).strip().upper()
    return raw.startswith("YES")


def _judge_faithfulness(answer: str, context_chunks) -> bool:
    """
    Is every factual claim in ANSWER supported by CONTEXT?
    Returns True (faithful) / False (hallucination detected).
    """
    context_text = "\n\n".join(c.text for c in context_chunks)
    q = (
        f"CONTEXT:\n{context_text}\n\n"
        f"ANSWER:\n{answer}\n\n"
        "Is every factual claim in the ANSWER fully supported by the CONTEXT above? "
        "Reply YES or NO."
    )
    return _judge_yes_no(q)


def _judge_relevance(query: str, answer: str) -> bool:
    """
    Does ANSWER actually address QUESTION?
    Returns True (relevant) / False (evasive or off-topic answer).
    """
    q = (
        f"QUESTION: {query}\n\n"
        f"ANSWER: {answer}\n\n"
        "Does the ANSWER directly address the QUESTION? "
        "Reply YES or NO."
    )
    return _judge_yes_no(q)


# ---------------------------------------------------------------------------
# Per-case evaluation
# ---------------------------------------------------------------------------

def evaluate_case(case: dict, k: int = K, method: str = "vector") -> dict:
    """Run all metrics for a single test case and return a result dict."""
    query = case["query"]
    expected_source: str | None = case["expected_source"]
    should_answer: bool = case["should_answer"]

    result: dict = {
        "id": case["id"],
        "method": method,
        "query": query,
        "should_answer": should_answer,
        "expected_source": expected_source or "—",
        # metrics (filled below)
        "context_precision": None,
        "faithful": None,
        "relevant": None,
        "idk_correct": None,   # only meaningful for should_answer:false cases
        "retrieved_sources": "",
        "latency_ms": None,
        "answer_snippet": "",
    }

    # ------------------------------------------------------------------ R
    if method == "vector":
        chunks = search_incidents(query, k=k)
        retrieved_sources = [c.source for c in chunks]
        context_text_for_judge = "\n\n".join(c.text for c in chunks)
        system_prompt = _build_rag_system_prompt(chunks)
    else:
        nodes = tree_search(query)
        retrieved_sources = [n.source_file for n in nodes]
        context_text_for_judge = "\n\n".join(n.section_text for n in nodes)
        
        # Build prompt identical to vectorless endpoint
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
        system_prompt = (
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

    result["retrieved_sources"] = "; ".join(dict.fromkeys(retrieved_sources))

    # CONTEXT PRECISION — code-based, no LLM involved
    if should_answer:
        # Success: the expected source is somewhere in the retrieved set
        result["context_precision"] = int(
            expected_source in retrieved_sources
        )
    else:
        # For off-topic queries we don't have a single "correct" source.
        # We treat context precision as N/A (None) and rely on the
        # idk_correct metric to catch whether the model stayed grounded.
        result["context_precision"] = None

    # ------------------------------------------------------------------ A + G
    t0 = time.perf_counter()
    answer = ask_llm(prompt=query, system=system_prompt)
    latency_ms = round((time.perf_counter() - t0) * 1000)

    result["latency_ms"] = latency_ms
    result["answer_snippet"] = shorten(answer, width=80, placeholder="...")

    # FAITHFULNESS — LLM judge
    # (Mock chunks objects for the judge to extract .text)
    class _MockChunk:
        def __init__(self, t): self.text = t
    mock_chunks = [_MockChunk(context_text_for_judge)]
    result["faithful"] = int(_judge_faithfulness(answer, mock_chunks))

    # ANSWER RELEVANCE — LLM judge
    result["relevant"] = int(_judge_relevance(query, answer))

    # I-DON'T-KNOW check (only evaluated for should_answer:false cases)
    if not should_answer:
        result["idk_correct"] = int(DONT_KNOW_PHRASE in answer)

    return result


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _fmt(val) -> str:
    """Format a metric value for the table (1 -> PASS, 0 -> FAIL, None -> N/A)."""
    if val is None:
        return " N/A "
    return " PASS" if val else " FAIL"


def print_table(results: list[dict]) -> None:
    col_q  = 42
    col_cp =  8
    col_f  =  8
    col_r  =  8
    col_idk=  8
    col_ms =  9

    header = (
        f"{'ID':<4} {'Query':<{col_q}} {'CtxPrec':>{col_cp}} "
        f"{'Faithful':>{col_f}} {'Relevant':>{col_r}} "
        f"{'IdkOK':>{col_idk}} {'Latency':>{col_ms}}"
    )
    sep = "-" * len(header)

    print("\n" + sep)
    print(header)
    print(sep)

    for r in results:
        q_short = shorten(r["query"], width=col_q, placeholder="...")
        idk_str = _fmt(r["idk_correct"]) if not r["should_answer"] else "  -- "
        print(
            f"{r['id']:<4} {q_short:<{col_q}} "
            f"{_fmt(r['context_precision']):>{col_cp}} "
            f"{_fmt(r['faithful']):>{col_f}} "
            f"{_fmt(r['relevant']):>{col_r}} "
            f"{idk_str:>{col_idk}} "
            f"{r['latency_ms']:>{col_ms-2}}ms"
        )

    print(sep)

    # Aggregate pass rates (exclude None values)
    def pass_rate(key: str, rows) -> str:
        vals = [r[key] for r in rows if r[key] is not None]
        if not vals:
            return "N/A"
        return f"{sum(vals)}/{len(vals)} ({100*sum(vals)//len(vals)}%)"

    print(f"\nContext Precision : {pass_rate('context_precision', results)}")
    print(f"Faithfulness      : {pass_rate('faithful', results)}")
    print(f"Answer Relevance  : {pass_rate('relevant', results)}")
    idk_cases = [r for r in results if not r["should_answer"]]
    print(f"I-don't-know OK   : {pass_rate('idk_correct', idk_cases)}")
    avg_ms = round(sum(r['latency_ms'] for r in results) / len(results))
    print(f"Avg latency       : {avg_ms}ms")
    print()


def save_csv(results: list[dict], method: str) -> None:
    fields = [
        "id", "method", "query", "should_answer", "expected_source",
        "context_precision", "faithful", "relevant", "idk_correct",
        "latency_ms", "retrieved_sources", "answer_snippet",
    ]
    path = RESULTS_PATH.with_name(f"results_{method}.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"Results saved to {RESULTS_PATH}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["vector", "vectorless"], default="vector")
    parser.add_argument("--cases", help="Comma-separated list of case IDs to run (e.g. C3,C5)")
    args = parser.parse_args()

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    
    if args.cases:
        subset = [c.strip() for c in args.cases.split(",")]
        dataset = [c for c in dataset if c["id"] in subset]

    print(f"\nRunning RAG eval ({args.method} mode) on {len(dataset)} cases ...")
    print("Each case: Retrieve -> Judge faithfulness -> Judge relevance\n")

    results = []
    for i, case in enumerate(dataset, 1):
        print(f"  [{i}/{len(dataset)}] {case['id']}: {shorten(case['query'], 60, placeholder='...')}")
        try:
            result = evaluate_case(case, method=args.method)
            results.append(result)
        except Exception as exc:
            print(f"    ERROR: {exc}")
        
        # Stay safe with Gemini quotas
        time.sleep(12)

    print_table(results)
    save_csv(results, args.method)


if __name__ == "__main__":
    main()

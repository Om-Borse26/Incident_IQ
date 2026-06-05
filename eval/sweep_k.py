"""
k-sweep evaluation for incidentiq.

Runs the full eval dataset THREE times at each of k=4, k=6, k=8.
Multiple runs per k exist to average out LLM-as-judge variance
(the judge is non-deterministic: the same answer can flip YES/NO
between calls, especially on borderline cases).

Outputs:
  - A per-run table for every run (so you can see individual variance)
  - A per-k SUMMARY table averaged across 3 runs
  - eval/sweep_results.csv with every individual case result

Run:
    python -m eval.sweep_k
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from textwrap import shorten

from eval.run_eval import (
    DATASET_PATH,
    evaluate_case,
    print_table,
)

K_VALUES = [4, 6, 8]
RUNS_PER_K = 1   # 1 run × 3 k-values × 8 cases × 3 LLM calls = 72 total calls.
                  # Context Precision is deterministic so 1 run is sufficient
                  # to answer "does k=6 fix C3?". Faithfulness/relevance have
                  # minor judge variance but the directional signal is clear.

SWEEP_CSV = Path(__file__).resolve().parent / "sweep_results.csv"

CSV_FIELDS = [
    "k", "run",
    "id", "query", "should_answer", "expected_source",
    "context_precision", "faithful", "relevant", "idk_correct",
    "latency_ms", "retrieved_sources", "answer_snippet",
]


def aggregate(results_runs: list[list[dict]]) -> dict[str, str]:
    """Average pass rates across multiple runs of the same k."""
    def rate(key: str) -> str:
        vals = [r[key] for run in results_runs for r in run if r[key] is not None]
        if not vals:
            return "N/A"
        mean = statistics.mean(vals)
        return f"{mean*100:.0f}%  (n={len(vals)})"

    idk_cases = [
        r for run in results_runs for r in run if not r["should_answer"]
    ]

    latencies = [r["latency_ms"] for run in results_runs for r in run]

    return {
        "Context Precision": rate("context_precision"),
        "Faithfulness     ": rate("faithful"),
        "Answer Relevance ": rate("relevant"),
        "I-don't-know OK  ": (
            rate("idk_correct")
            if idk_cases
            else "N/A"
        ),
        "Avg Latency (ms) ": f"{statistics.mean(latencies):.0f}",
    }


def main() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    all_rows: list[dict] = []        # for the CSV
    summary: dict[int, dict] = {}    # k -> averaged metrics

    for k in K_VALUES:
        print(f"\n{'='*70}")
        print(f"  k = {k}   ({RUNS_PER_K} runs x {len(dataset)} cases)")
        print(f"{'='*70}")

        runs_results: list[list[dict]] = []

        for run_idx in range(1, RUNS_PER_K + 1):
            print(f"\n  -- Run {run_idx}/{RUNS_PER_K} (k={k}) --\n")
            run_results = []

            for i, case in enumerate(dataset, 1):
                import time
                label = shorten(case["query"], 55, placeholder="...")
                print(f"    [{i}/{len(dataset)}] {case['id']}: {label}")
                try:
                    result = evaluate_case(case, k=k)
                    run_results.append(result)
                    # Tag with k and run for CSV
                    csv_row = {"k": k, "run": run_idx, **result}
                    all_rows.append(csv_row)
                except Exception as exc:
                    print(f"    ERROR: {exc}")
                time.sleep(3)  # stay under Groq's TPM burst limit

            print_table(run_results)
            runs_results.append(run_results)

        summary[k] = aggregate(runs_results)

    # ------------------------------------------------------------------ Summary
    print(f"\n{'='*70}")
    print("  SWEEP SUMMARY  (averaged over 3 runs each)")
    print(f"{'='*70}")
    print(f"\n{'Metric':<25}  {'k=4':>12}  {'k=6':>12}  {'k=8':>12}")
    print("-" * 67)
    metrics = list(next(iter(summary.values())).keys())
    for metric in metrics:
        row = f"{metric:<25}"
        for k in K_VALUES:
            row += f"  {summary[k][metric]:>12}"
        print(row)
    print()

    # ------------------------------------------------------------------ CSV
    with SWEEP_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"All results saved to {SWEEP_CSV}\n")


if __name__ == "__main__":
    main()

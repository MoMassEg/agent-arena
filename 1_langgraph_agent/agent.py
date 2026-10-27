"""
LangGraph Code Review Agent — main agent module.

Builds a ``StateGraph`` with four processing nodes and conditional routing:

    START → input_processor
        ├──(invalid)──→ output_validator → END
        └──(valid)────→ llm_analyzer
                          ├──(critical)──→ deep_analyzer → output_validator → END
                          └──(other)─────→ output_validator → END

Usage::

    from agent import run_review

    report = run_review("def foo(): pass", language="python")
    print(report)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add local libraries if present
_lib_dir = Path.home() / "python_libs"
if _lib_dir.exists() and str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from nodes import deep_analyzer, input_processor, llm_analyzer, output_validator
from state import CodeReviewState

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _route_after_input(state: CodeReviewState) -> str:
    """Route after input_processor: skip analysis if input is invalid."""
    if not state.get("is_valid_input", False):
        return "output_validator"
    return "llm_analyzer"


def _route_after_analysis(state: CodeReviewState) -> str:
    """Route after llm_analyzer: deep-dive when severity is critical."""
    if state.get("severity") == "critical":
        return "deep_analyzer"
    return "output_validator"


def build_graph() -> StateGraph:
    """Construct and compile the LangGraph code-review pipeline."""
    graph = StateGraph(CodeReviewState)

    # -- Nodes -----------------------------------------------------------------
    graph.add_node("input_processor", input_processor)
    graph.add_node("llm_analyzer", llm_analyzer)
    graph.add_node("deep_analyzer", deep_analyzer)
    graph.add_node("output_validator", output_validator)

    # -- Edges -----------------------------------------------------------------
    graph.add_edge(START, "input_processor")

    graph.add_conditional_edges(
        "input_processor",
        _route_after_input,
        {"llm_analyzer": "llm_analyzer", "output_validator": "output_validator"},
    )

    graph.add_conditional_edges(
        "llm_analyzer",
        _route_after_analysis,
        {"deep_analyzer": "deep_analyzer", "output_validator": "output_validator"},
    )

    graph.add_edge("deep_analyzer", "output_validator")
    graph.add_edge("output_validator", END)

    return graph.compile()


# Module-level compiled graph (singleton).
_compiled_graph = build_graph()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_review(code: str, language: str = "auto") -> dict:
    """Run the code-review pipeline and return the final report.

    Args:
        code: Source code to review.
        language: Programming language hint (``'auto'`` to auto-detect).

    Returns:
        A dict containing the structured review report.
    """
    logger.info("run_review: starting review (language=%s, code_len=%d)", language, len(code))

    initial_state: dict = {
        "code": code,
        "language": language,
        "is_valid_input": False,
        "parsed_info": {},
        "review_result": {},
        "severity": "info",
        "deep_analysis": {},
        "final_report": {},
        "errors": [],
    }

    result = _compiled_graph.invoke(initial_state)
    return result.get("final_report", {})


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _pretty_print_report(name: str, report: dict) -> None:
    """Print a report with nice formatting."""
    status = report.get("status", "unknown")
    severity = report.get("severity", "?")
    symbol = {"reviewed": "✅", "error": "❌"}.get(status, "❓")

    print(f"\n{'═' * 72}")
    print(f"  {symbol}  {name}")
    print(f"{'─' * 72}")
    print(f"  Status   : {status}")
    print(f"  Severity : {severity}")

    summary = report.get("input_summary", {})
    if summary:
        print(f"  Language : {summary.get('language', '?')}")
        print(f"  Lines    : {summary.get('line_count', '?')}")

    recs = report.get("recommendations", [])
    if recs:
        print(f"  Recommendations ({len(recs)}):")
        for r in recs[:10]:
            print(f"    • {r}")
        if len(recs) > 10:
            print(f"    … and {len(recs) - 10} more")

    errs = report.get("errors")
    if errs:
        print(f"  Errors:")
        for e in errs:
            print(f"    ⚠ {e}")

    print(f"{'═' * 72}")


def main() -> None:
    """Load test inputs, run each through the agent, and save results."""
    test_inputs_path = Path(__file__).resolve().parent.parent / "shared" / "test_inputs.json"
    results_path = Path(__file__).resolve().parent / "results.json"

    if not test_inputs_path.exists():
        print(f"ERROR: test inputs not found at {test_inputs_path}")
        sys.exit(1)

    with open(test_inputs_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    print(f"\n🔍  LangGraph Code Review Agent — running {len(test_cases)} test(s)\n")

    all_results: list[dict] = []
    for tc in test_cases:
        name = tc.get("name", "Unnamed")
        code = tc.get("code", "")
        lang = tc.get("language", "auto")

        print(f"▶ Running: {name} …")
        report = run_review(code, language=lang)
        _pretty_print_report(name, report)

        all_results.append({"name": name, "report": report})

    # Save results to JSON.
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n📄 Results saved to {results_path}")


if __name__ == "__main__":
    main()

"""
Test harness for the LangGraph Code Review Agent.

Loads test inputs from ``../shared/test_inputs.json``, runs each case through
the agent, validates results against expected severity, measures wall-clock
time, and saves a detailed report to ``test_results.json``.
"""

from __future__ import annotations

import json
import logging
import sys
import time
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

from agent import run_review

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _severity_matches(actual: str, expected: str) -> bool:
    """Check whether the actual severity is compatible with the expectation.

    ``expected='error'`` matches any report whose status is ``'error'``.
    Otherwise a direct string comparison is performed.
    """
    if expected == "error":
        return True  # Handled separately via status check.
    return actual == expected


def _format_result(name: str, passed: bool, elapsed: float, details: str) -> str:
    """Return a human-readable one-liner for a test result."""
    icon = "✅ PASS" if passed else "❌ FAIL"
    return f"  {icon}  {name:<40s}  ({elapsed:.2f}s)  {details}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    test_inputs_path = Path(__file__).resolve().parent.parent / "shared" / "test_inputs.json"
    results_path = Path(__file__).resolve().parent / "test_results.json"

    if not test_inputs_path.exists():
        print(f"ERROR: test inputs not found at {test_inputs_path}")
        sys.exit(1)

    with open(test_inputs_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    total = len(test_cases)
    print(f"\n{'═' * 72}")
    print(f"  🧪  LangGraph Code Review Agent — Test Harness")
    print(f"  Running {total} test case(s)")
    print(f"{'═' * 72}\n")

    results: list[dict] = []
    pass_count = 0
    total_time = 0.0

    for idx, tc in enumerate(test_cases, start=1):
        name = tc.get("name", f"Test #{idx}")
        code = tc.get("code", "")
        lang = tc.get("language", "auto")
        expected_severity = tc.get("expected_severity", None)

        print(f"  [{idx}/{total}] Running: {name} …", end="", flush=True)

        t0 = time.perf_counter()
        try:
            report = run_review(code, language=lang)
            error_msg = None
        except Exception as exc:
            report = {"status": "error", "severity": "unknown", "error": str(exc)}
            error_msg = str(exc)
        elapsed = time.perf_counter() - t0
        total_time += elapsed

        # --- Determine pass/fail ----------------------------------------------
        actual_status = report.get("status", "unknown")
        actual_severity = report.get("severity", "unknown")

        if expected_severity == "error":
            passed = actual_status == "error"
            detail = f"status={actual_status}"
        elif expected_severity:
            passed = actual_severity == expected_severity
            detail = f"expected={expected_severity}, got={actual_severity}"
        else:
            passed = actual_status in ("reviewed", "error")
            detail = f"status={actual_status}"

        if passed:
            pass_count += 1

        # Clear the "Running" text and print the result.
        print("\r" + _format_result(name, passed, elapsed, detail))

        results.append({
            "name": name,
            "passed": passed,
            "expected_severity": expected_severity,
            "actual_severity": actual_severity,
            "actual_status": actual_status,
            "elapsed_seconds": round(elapsed, 3),
            "report": report,
            "error": error_msg,
        })

    # --- Summary --------------------------------------------------------------
    fail_count = total - pass_count
    print(f"\n{'─' * 72}")
    print(
        f"  Results: {pass_count}/{total} passed, "
        f"{fail_count} failed  |  Total time: {total_time:.2f}s"
    )
    print(f"{'═' * 72}\n")

    # Save detailed results.
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"📄 Detailed results saved to {results_path}\n")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

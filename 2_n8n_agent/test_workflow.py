#!/usr/bin/env python3
"""
test_workflow.py — Test harness for the n8n Code Review Agent workflow.

Sends each test case from test_inputs.json to the n8n webhook endpoint,
collects results, measures response times, and saves everything to test_results.json.

Requirements:
    pip install requests

Usage:
    python test_workflow.py
    python test_workflow.py --url http://localhost:5678/webhook/code-review
    python test_workflow.py --url http://localhost:5678/webhook-test/code-review  # for test mode
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package is required. Install it with:")
    print("  pip install requests")
    sys.exit(1)


# ── Configuration ────────────────────────────────────────────────────────────

DEFAULT_URL = "http://localhost:5678/webhook/code-review"
TEST_INPUTS_FILE = "test_inputs.json"
RESULTS_FILE = "test_results.json"
REQUEST_TIMEOUT = 60  # seconds — LLM calls can be slow


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_test_inputs(filepath: str) -> list[dict]:
    """Load test cases from the JSON file."""
    path = Path(filepath)
    if not path.exists():
        print(f"ERROR: Test inputs file not found: {filepath}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("test_cases", [])


def send_test_request(url: str, payload: dict, timeout: int = REQUEST_TIMEOUT) -> dict:
    """Send a single test request to the webhook and return the result."""
    start_time = time.time()
    result = {
        "status_code": None,
        "response": None,
        "response_time_seconds": 0,
        "error": None,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        result["status_code"] = response.status_code
        result["response_time_seconds"] = round(time.time() - start_time, 3)

        try:
            result["response"] = response.json()
        except json.JSONDecodeError:
            result["response"] = response.text

    except requests.exceptions.ConnectionError:
        result["error"] = (
            f"Connection refused at {url}. "
            "Is n8n running? Is the workflow active?"
        )
        result["response_time_seconds"] = round(time.time() - start_time, 3)
    except requests.exceptions.Timeout:
        result["error"] = f"Request timed out after {timeout}s."
        result["response_time_seconds"] = timeout
    except Exception as e:
        result["error"] = str(e)
        result["response_time_seconds"] = round(time.time() - start_time, 3)

    return result


def print_separator(char: str = "─", width: int = 80):
    """Print a visual separator line."""
    print(char * width)


def print_result_summary(name: str, result: dict):
    """Pretty-print a single test result."""
    status = result.get("status_code")
    time_s = result.get("response_time_seconds", 0)
    error = result.get("error")

    # Status indicator
    if error:
        indicator = "❌ ERROR"
    elif status == 200:
        indicator = "✅ PASS"
    elif status == 400:
        indicator = "⚠️  VALIDATION ERROR (expected for invalid inputs)"
    else:
        indicator = f"❓ HTTP {status}"

    print(f"\n  {indicator}")
    print(f"  Response Time: {time_s:.3f}s")

    if error:
        print(f"  Error: {error}")
        return

    response = result.get("response", {})
    if isinstance(response, dict):
        # Success response
        if response.get("status") == "success":
            review = response.get("review", {})
            print(f"  Severity: {review.get('severity', 'N/A')}")
            print(f"  Issues Found: {review.get('issueCount', 0)}")
            print(f"  Summary: {review.get('summary', 'N/A')[:100]}")
            metrics = review.get("metrics", {})
            if metrics:
                print(f"  Scores — Overall: {metrics.get('overall', 'N/A')}, "
                      f"Security: {metrics.get('security', 'N/A')}, "
                      f"Performance: {metrics.get('performance', 'N/A')}")
            if response.get("deepAnalysis"):
                deep = response["deepAnalysis"]
                exploits = deep.get("exploitScenarios", [])
                fixes = deep.get("fixSuggestions", [])
                print(f"  Deep Analysis: {len(exploits)} exploit scenarios, "
                      f"{len(fixes)} fix suggestions")

        # Error response
        elif response.get("status") == "error":
            err = response.get("error", {})
            print(f"  Error Type: {err.get('type', 'N/A')}")
            print(f"  Message: {err.get('message', 'N/A')}")
    else:
        # Raw text response
        preview = str(response)[:200]
        print(f"  Response: {preview}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test the n8n Code Review Agent workflow"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Webhook URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--inputs",
        default=TEST_INPUTS_FILE,
        help=f"Path to test inputs JSON (default: {TEST_INPUTS_FILE})",
    )
    parser.add_argument(
        "--output",
        default=RESULTS_FILE,
        help=f"Path to save results JSON (default: {RESULTS_FILE})",
    )
    parser.add_argument(
        "--only",
        type=int,
        default=None,
        help="Run only a specific test case by index (0-based)",
    )
    args = parser.parse_args()

    # Resolve paths relative to the script's directory
    script_dir = Path(__file__).parent
    inputs_path = script_dir / args.inputs if not Path(args.inputs).is_absolute() else Path(args.inputs)
    output_path = script_dir / args.output if not Path(args.output).is_absolute() else Path(args.output)

    # Load test cases
    test_cases = load_test_inputs(str(inputs_path))
    if args.only is not None:
        if 0 <= args.only < len(test_cases):
            test_cases = [test_cases[args.only]]
        else:
            print(f"ERROR: Test index {args.only} is out of range (0–{len(test_cases) - 1})")
            sys.exit(1)

    print_separator("═")
    print("  n8n Code Review Agent — Workflow Test Runner")
    print_separator("═")
    print(f"\n  Webhook URL : {args.url}")
    print(f"  Test Cases  : {len(test_cases)}")
    print(f"  Timestamp   : {datetime.now().isoformat()}")
    print()

    # Run each test
    all_results = []
    total_time = 0

    for i, test_case in enumerate(test_cases):
        name = test_case.get("name", f"Test {i}")
        description = test_case.get("description", "")
        payload = test_case.get("payload", {})

        print_separator()
        print(f"  [{i + 1}/{len(test_cases)}] {name}")
        if description:
            print(f"  {description}")

        result = send_test_request(args.url, payload)
        total_time += result.get("response_time_seconds", 0)

        print_result_summary(name, result)

        all_results.append({
            "test_name": name,
            "description": description,
            "payload": payload,
            **result,
        })

    # Summary
    print()
    print_separator("═")
    print("  SUMMARY")
    print_separator("═")

    passed = sum(1 for r in all_results if r.get("status_code") == 200)
    validation_errors = sum(1 for r in all_results if r.get("status_code") == 400)
    failures = sum(1 for r in all_results if r.get("error") is not None)
    other = len(all_results) - passed - validation_errors - failures

    print(f"\n  Total Tests      : {len(all_results)}")
    print(f"  ✅ Passed (200)   : {passed}")
    print(f"  ⚠️  Validation (400): {validation_errors}")
    print(f"  ❌ Errors          : {failures}")
    if other:
        print(f"  ❓ Other           : {other}")
    print(f"  Total Time       : {total_time:.3f}s")
    print(f"  Avg Time/Test    : {total_time / max(len(all_results), 1):.3f}s")
    print()

    # Save results
    output = {
        "metadata": {
            "webhook_url": args.url,
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(all_results),
            "total_time_seconds": round(total_time, 3),
        },
        "results": all_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"  Results saved to: {output_path}")
    print_separator("═")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Hermes Agent Code Review Runner
================================

This script demonstrates the Hermes Agent approach to the Code Review Agent.
It showcases two unique features not available in LangGraph or n8n:

  1. **Persistent Memory** — Remembers past reviews across sessions so the
     agent can track recurring issues, detect regressions, and build a
     knowledge base of project-specific patterns.
  2. **Scheduled Recurring Tasks** — Automatically reviews code on a
     configurable schedule (e.g., every weekday at 9 AM) without
     external cron or workflow orchestration.

Since Hermes Agent requires its own runtime environment (installed
separately via ``pipx install hermes-agent`` or the official installer),
this script provides two operational modes:

  **Option A** — Full Hermes integration (when ``hermes-agent`` is installed)
  **Option B** — Simulation / Standalone mode that demonstrates the same
                 CONCEPTS and architecture using raw Python + Groq API

Usage:
    python agent_runner.py                # Auto-detects mode
    python agent_runner.py --standalone   # Force standalone mode
    python agent_runner.py --hermes       # Force Hermes mode
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hermes_runner")

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
SHARED_DIR = PROJECT_DIR.parent / "shared"
TEST_INPUTS_PATH = SHARED_DIR / "test_inputs.json"
RESULTS_PATH = PROJECT_DIR / "test_results.json"
MEMORY_DIR = PROJECT_DIR / "memory_store"
MEMORY_FILE = MEMORY_DIR / "review_history.json"
CONFIG_PATH = PROJECT_DIR / "config.yaml"

# Add project root to path so skills can be imported
sys.path.insert(0, str(PROJECT_DIR))

from skills.code_review_skill import _static_code_analysis_impl as static_code_analysis

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
env_path = PROJECT_DIR.parent / "1_langgraph_agent" / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


# ===========================================================================
# Persistent Memory — Simulation Layer
# ===========================================================================

class PersistentMemory:
    """JSON-file-backed persistent memory that mirrors the Hermes Agent
    ``agent.memory`` API.

    In Hermes Agent, memory is automatically persisted and indexed.
    This class replicates the core store / recall / search interface
    so the rest of the runner code is identical regardless of mode.
    """

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = self._load()

    # ---- Core API (mirrors Hermes agent.memory) ----

    def store(self, key: str, value: Any) -> None:
        """Persist a value under *key*."""
        self._data[key] = value
        self._save()
        logger.debug("Memory stored: %s", key)

    def recall(self, key: str, default: Any = None) -> Any:
        """Retrieve a previously stored value."""
        return self._data.get(key, default)

    def append(self, key: str, item: Any) -> None:
        """Append *item* to a list stored under *key*."""
        lst = self._data.setdefault(key, [])
        lst.append(item)
        self._save()

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Simple keyword search across stored review history."""
        results = []
        history = self._data.get("review_history", [])
        query_lower = query.lower()
        for entry in history:
            text = json.dumps(entry).lower()
            if query_lower in text:
                results.append(entry)
        return results

    def list_keys(self) -> List[str]:
        """Return all stored keys."""
        return list(self._data.keys())

    def clear(self) -> None:
        """Wipe all stored data."""
        self._data = {}
        self._save()

    # ---- Persistence helpers ----

    def _load(self) -> Dict[str, Any]:
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load memory file: %s", exc)
        return {}

    def _save(self) -> None:
        with open(self.storage_path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, default=str)


# ===========================================================================
# Groq LLM Client (standalone mode)
# ===========================================================================

class GroqReviewClient:
    """Thin wrapper around the Groq REST API for LLM-powered code review.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint.
    """

    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Lazy import so the module can be loaded even without requests
        try:
            import requests as _requests
            self._requests = _requests
        except ImportError:
            self._requests = None
            logger.warning("requests library not installed — LLM calls will be skipped.")

    def review_code(
        self,
        code: str,
        language: str,
        static_findings: List[Dict[str, Any]],
        past_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Send code + static analysis results to the LLM for a full review.

        The prompt incorporates static findings so the LLM can provide
        context-aware explanations and additional insights.
        """
        if self._requests is None:
            return "[LLM review skipped — 'requests' library not installed]"

        # Build the system prompt
        system_prompt = (
            "You are an expert code reviewer. You have been given source code "
            "along with static analysis findings. Provide a comprehensive but "
            "concise review that:\n"
            "1. Explains each static finding in plain language\n"
            "2. Identifies any ADDITIONAL issues the static analysis missed\n"
            "3. Suggests specific fixes with code examples where helpful\n"
            "4. Rates overall code quality (Critical / Warning / Clean)\n\n"
            "Keep the review structured with headers and bullet points."
        )

        # Build the user prompt
        findings_text = json.dumps(static_findings, indent=2) if static_findings else "None"
        past_context = ""
        if past_reviews:
            past_context = (
                "\n\n--- Past Review Context ---\n"
                f"The agent has reviewed {len(past_reviews)} file(s) previously. "
                "Keep in mind recurring patterns.\n"
            )

        user_prompt = (
            f"## Code ({language})\n```{language}\n{code}\n```\n\n"
            f"## Static Analysis Findings\n```json\n{findings_text}\n```"
            f"{past_context}\n\n"
            "Please provide your code review."
        )

        for attempt in range(1, 4):
            try:
                response = self._requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 800,
                    },
                    timeout=60,
                )
                if response.status_code == 429:
                    logger.warning("Rate limited (429), waiting 5s before retry (attempt %d/3)...", attempt)
                    time.sleep(5)
                    continue
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                if attempt == 3:
                    logger.error("LLM review request failed after 3 attempts: %s", exc)
                    return f"[LLM review failed: {exc}]"
                time.sleep(3)
        return "[LLM review failed: max retries reached]"


# ===========================================================================
# Option A: Hermes Agent Integration
# ===========================================================================

def run_hermes_mode() -> List[Dict[str, Any]]:
    """Run the code review agent using the full Hermes Agent framework.

    This requires ``hermes-agent`` to be installed.
    """
    logger.info("=" * 60)
    logger.info("HERMES AGENT MODE — Full Integration")
    logger.info("=" * 60)

    try:
        from hermes_agent import AIAgent  # type: ignore
    except ImportError:
        logger.error(
            "hermes-agent is not installed. Run: pipx install hermes-agent\n"
            "Falling back to standalone mode."
        )
        return run_standalone_mode()

    # Initialize the Hermes agent
    agent = AIAgent(
        model=f"groq/{GROQ_MODEL}",
        api_key=GROQ_API_KEY,
        quiet_mode=True,
        skills_dir=str(PROJECT_DIR / "skills"),
    )

    # Load test inputs
    test_inputs = _load_test_inputs()
    results: List[Dict[str, Any]] = []

    # Recall past reviews from persistent memory
    past_reviews = agent.memory.recall("review_history") or []
    logger.info("Persistent memory: %d past review(s) found.", len(past_reviews))

    for test_case in test_inputs:
        name = test_case.get("name", "unknown")
        code = test_case.get("code", "")
        language = test_case.get("language", "python")

        logger.info("Reviewing: %s (%s)", name, language)

        # Step 1: Run custom static analysis skill
        static_result = static_code_analysis(code, language)

        # Step 2: Have the agent do LLM-powered review
        review_prompt = (
            f"Review this {language} code. Static analysis found "
            f"{static_result['summary']['total_issues']} issue(s):\n"
            f"```{language}\n{code}\n```\n"
            f"Static findings: {json.dumps(static_result['findings'], indent=2)}"
        )
        llm_review = agent.chat(review_prompt)

        # Step 3: Build result
        result = {
            "test_name": name,
            "language": language,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "static_analysis": static_result,
            "llm_review": llm_review,
            "expected_severity": test_case.get("expected_severity", "unknown"),
        }
        results.append(result)

        # Step 4: Store in persistent memory
        agent.memory.store("review_history", results)

    # Schedule recurring review (demonstrate the feature)
    logger.info("Scheduling recurring code review: weekdays at 9 AM")
    agent.schedule(
        "review_codebase",
        cron="0 9 * * 1-5",
        target_dir=str(PROJECT_DIR / "code_to_review"),
    )

    return results


# ===========================================================================
# Option B: Standalone Mode (Simulation)
# ===========================================================================

def run_standalone_mode() -> List[Dict[str, Any]]:
    """Run the code review agent in standalone mode.

    This mode simulates Hermes Agent features using:
    - PersistentMemory class (JSON-backed) for persistent memory
    - GroqReviewClient for direct LLM calls
    - Standard Python for scheduled task demonstration
    """
    logger.info("=" * 60)
    logger.info("STANDALONE MODE — Simulating Hermes Agent Features")
    logger.info("=" * 60)

    # Initialize components
    memory = PersistentMemory(MEMORY_FILE)
    llm_client = GroqReviewClient(GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL)

    # ---- Demonstrate persistent memory: recall past reviews ----
    past_reviews = memory.recall("review_history", default=[])
    if past_reviews:
        logger.info(
            "[Persistent Memory] Found %d past review(s) from previous sessions.",
            len(past_reviews),
        )
        logger.info(
            "  Most recent: %s at %s",
            past_reviews[-1].get("test_name", "?"),
            past_reviews[-1].get("timestamp", "?"),
        )
    else:
        logger.info("[Persistent Memory] No past reviews found — first run.")

    # Increment session counter
    session_count = memory.recall("session_count", default=0) + 1
    memory.store("session_count", session_count)
    logger.info("[Persistent Memory] Session #%d", session_count)

    # Load test inputs
    test_inputs = _load_test_inputs()
    results: List[Dict[str, Any]] = []

    print("\n" + "=" * 70)
    print("  HERMES AGENT CODE REVIEW — Standalone Mode")
    print("  Model: %s | Session: #%d" % (GROQ_MODEL, session_count))
    print("=" * 70)

    for idx, test_case in enumerate(test_inputs, start=1):
        name = test_case.get("name", "unknown")
        code = test_case.get("code", "")
        language = test_case.get("language", "python")
        expected = test_case.get("expected_severity", "unknown")

        print(f"\n{'─' * 70}")
        print(f"  Test {idx}/{len(test_inputs)}: {name}")
        print(f"  Language: {language} | Expected: {expected}")
        print(f"{'─' * 70}")

        # ── Step 1: Custom Static Analysis Skill ──
        logger.info("Running static analysis on '%s'...", name)
        static_result = static_code_analysis(code, language)
        findings = static_result["findings"]
        summary = static_result["summary"]

        print(f"\n  📊 Static Analysis: {summary['total_issues']} issue(s) found")
        print(f"     Critical: {summary['severity_counts']['critical']}"
              f"  Warning: {summary['severity_counts']['warning']}"
              f"  Info: {summary['severity_counts']['info']}")

        if findings:
            print("\n  Findings:")
            for f in findings[:8]:  # Show first 8
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(
                    f["severity"], "⚪"
                )
                print(f"    {icon} [{f['severity'].upper()}] Line {f['line']}: "
                      f"{f['message']}")
            if len(findings) > 8:
                print(f"    ... and {len(findings) - 8} more")

        # ── Step 2: LLM-Powered Review ──
        logger.info("Requesting LLM review for '%s'...", name)
        llm_review = llm_client.review_code(
            code=code,
            language=language,
            static_findings=findings,
            past_reviews=past_reviews[-3:] if past_reviews else None,
        )

        # Print a truncated preview of the LLM review
        preview_lines = llm_review.strip().split("\n")[:12]
        print(f"\n  🤖 LLM Review (preview):")
        for line in preview_lines:
            print(f"    {line}")
        if len(llm_review.strip().split("\n")) > 12:
            print(f"    ... (truncated, see test_results.json for full review)")

        # ── Step 3: Build result ──
        result = {
            "test_name": name,
            "language": language,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": session_count,
            "static_analysis": static_result,
            "llm_review": llm_review,
            "expected_severity": expected,
            "detected_severity": summary["overall_severity"],
        }
        results.append(result)

        # ── Step 4: Store in persistent memory ──
        memory.append("review_history", {
            "test_name": name,
            "language": language,
            "timestamp": result["timestamp"],
            "session": session_count,
            "severity": summary["overall_severity"],
            "issue_count": summary["total_issues"],
        })

        # Rate limiting for Groq free tier
        time.sleep(2)

    # ── Final summary ──
    print("\n" + "=" * 70)
    print("  REVIEW SUMMARY")
    print("=" * 70)

    total_issues = sum(
        r["static_analysis"]["summary"]["total_issues"] for r in results
    )
    critical_count = sum(
        r["static_analysis"]["summary"]["severity_counts"]["critical"]
        for r in results
    )
    print(f"  Files reviewed:   {len(results)}")
    print(f"  Total issues:     {total_issues}")
    print(f"  Critical issues:  {critical_count}")
    print(f"  Session:          #{session_count}")

    # Show memory stats
    all_history = memory.recall("review_history", [])
    print(f"\n  [Persistent Memory]")
    print(f"  Total reviews stored:  {len(all_history)}")
    print(f"  Total sessions:        {session_count}")
    print(f"  Memory file:           {MEMORY_FILE}")

    # Demonstrate memory search
    crit_matches = memory.search("critical")
    if crit_matches:
        print(f"  Reviews with 'critical': {len(crit_matches)}")

    print("=" * 70)

    return results


# ===========================================================================
# Helpers
# ===========================================================================

def _load_test_inputs() -> List[Dict[str, Any]]:
    """Load test inputs from the shared test_inputs.json file."""
    if not TEST_INPUTS_PATH.exists():
        logger.warning("Test inputs not found at %s — using built-in samples.", TEST_INPUTS_PATH)
        return _builtin_test_inputs()

    with open(TEST_INPUTS_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    logger.info("Loaded %d test input(s) from %s", len(data), TEST_INPUTS_PATH)
    return data


def _builtin_test_inputs() -> List[Dict[str, Any]]:
    """Fallback test inputs if shared/test_inputs.json is missing."""
    return [
        {
            "name": "Python Security Issues",
            "language": "python",
            "expected_severity": "critical",
            "code": (
                'import os\n\n'
                'DB_PASSWORD = "supersecret123"\n\n'
                'def connect(host, retries=[]):\n'
                '    unused = 42\n'
                '    try:\n'
                '        return True\n'
                '    except:\n'
                '        pass\n'
            ),
        },
        {
            "name": "JavaScript XSS",
            "language": "javascript",
            "expected_severity": "critical",
            "code": (
                'var x = document.getElementById("input").value;\n'
                'document.getElementById("out").innerHTML = x;\n'
                'eval(x);\n'
                'var q = "SELECT * FROM users WHERE id = \'" + x + "\'";\n'
            ),
        },
    ]


def _save_results(results: List[Dict[str, Any]]) -> None:
    """Save review results to test_results.json."""
    output = {
        "agent": "hermes",
        "model": GROQ_MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_reviews": len(results),
        "results": results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, default=str)
    logger.info("Results saved to %s", RESULTS_PATH)


def _detect_hermes() -> bool:
    """Check if hermes-agent is importable."""
    try:
        import hermes_agent  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hermes Agent Code Review Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python agent_runner.py              # Auto-detect mode\n"
            "  python agent_runner.py --standalone  # Force standalone\n"
            "  python agent_runner.py --hermes      # Force Hermes mode\n"
        ),
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--hermes", action="store_true",
        help="Force Hermes Agent mode (requires hermes-agent installed)",
    )
    mode_group.add_argument(
        "--standalone", action="store_true",
        help="Force standalone/simulation mode",
    )
    parser.add_argument(
        "--clear-memory", action="store_true",
        help="Clear persistent memory before running",
    )
    args = parser.parse_args()

    # Optionally clear memory
    if args.clear_memory:
        memory = PersistentMemory(MEMORY_FILE)
        memory.clear()
        logger.info("Persistent memory cleared.")

    # Decide which mode to use
    if args.hermes:
        results = run_hermes_mode()
    elif args.standalone:
        results = run_standalone_mode()
    else:
        # Auto-detect
        if _detect_hermes():
            logger.info("Hermes Agent detected — using full integration.")
            results = run_hermes_mode()
        else:
            logger.info("Hermes Agent not found — using standalone mode.")
            results = run_standalone_mode()

    # Save results
    _save_results(results)

    print(f"\n✅ Results saved to: {RESULTS_PATH}")
    print("Run again to see persistent memory in action!\n")


if __name__ == "__main__":
    main()

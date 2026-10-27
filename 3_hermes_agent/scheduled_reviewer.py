#!/usr/bin/env python3
"""
Hermes Agent — Scheduled Code Reviewer
=======================================

This script demonstrates one of Hermes Agent's **unique features**:
scheduled recurring tasks.  Unlike LangGraph (which needs an external
scheduler) or n8n (which requires a separate workflow trigger), Hermes
Agent can schedule tasks natively with:

    agent.schedule("review_codebase", cron="0 9 * * 1-5", ...)

This standalone version replicates that behaviour by:
  1. Watching a target directory for new / modified code files
  2. Running static analysis + LLM review on changed files
  3. Storing results in persistent memory
  4. Repeating on a configurable interval

Usage:
    python scheduled_reviewer.py                     # Default: every 60 s
    python scheduled_reviewer.py --interval 300      # Every 5 minutes
    python scheduled_reviewer.py --once               # Single scan, no loop
    python scheduled_reviewer.py --dir ./my_code      # Custom watch directory

The Hermes Agent equivalent would be a single line:
    agent.schedule("review_codebase", cron="*/5 * * * *",
                   target_dir="./code_to_review")
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduled_reviewer")

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from skills.code_review_skill import _static_code_analysis_impl as static_code_analysis

env_path = PROJECT_DIR.parent / "1_langgraph_agent" / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

MEMORY_DIR = PROJECT_DIR / "memory_store"
MEMORY_FILE = MEMORY_DIR / "scheduled_reviews.json"
STATE_FILE = MEMORY_DIR / "file_hashes.json"

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
}


# ===========================================================================
# Persistent State (file hash tracking)
# ===========================================================================

class FileStateTracker:
    """Tracks file content hashes to detect new or modified files.

    In Hermes Agent, this would be handled by the agent's internal
    memory and change-detection system.
    """

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._hashes: Dict[str, str] = self._load()

    def get_changed_files(self, directory: Path) -> List[Path]:
        """Return files that are new or modified since the last scan."""
        changed: List[Path] = []

        if not directory.exists():
            logger.warning("Watch directory does not exist: %s", directory)
            return changed

        for ext in SUPPORTED_EXTENSIONS:
            for file_path in directory.rglob(f"*{ext}"):
                # Skip hidden dirs and __pycache__
                parts = file_path.parts
                if any(p.startswith(".") or p == "__pycache__" for p in parts):
                    continue

                current_hash = self._hash_file(file_path)
                key = str(file_path.resolve())

                if key not in self._hashes or self._hashes[key] != current_hash:
                    changed.append(file_path)
                    self._hashes[key] = current_hash

        if changed:
            self._save()

        return changed

    def _hash_file(self, path: Path) -> str:
        """Compute SHA-256 hash of file contents."""
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""

    def _load(self) -> Dict[str, str]:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(self._hashes, fh, indent=2)


# ===========================================================================
# Review Memory
# ===========================================================================

class ReviewMemory:
    """Persistent storage for scheduled review results.

    Mirrors the Hermes Agent ``agent.memory`` API.
    """

    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = self._load()

    def store_review(self, review: Dict[str, Any]) -> None:
        """Store a single review result."""
        history = self._data.setdefault("reviews", [])
        history.append(review)
        self._data["last_scan"] = datetime.now(timezone.utc).isoformat()
        self._data["total_scans"] = self._data.get("total_scans", 0) + 1
        self._save()

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate statistics."""
        reviews = self._data.get("reviews", [])
        return {
            "total_reviews": len(reviews),
            "total_scans": self._data.get("total_scans", 0),
            "last_scan": self._data.get("last_scan", "never"),
            "total_issues": sum(
                r.get("issue_count", 0) for r in reviews
            ),
        }

    def get_recent(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return the N most recent reviews."""
        return self._data.get("reviews", [])[-n:]

    def _load(self) -> Dict[str, Any]:
        if self.memory_path.exists():
            try:
                with open(self.memory_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self) -> None:
        with open(self.memory_path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, default=str)


# ===========================================================================
# Groq LLM Client (lightweight)
# ===========================================================================

def llm_review(code: str, language: str, static_findings: list) -> str:
    """Call Groq LLM for a concise code review."""
    try:
        import requests
    except ImportError:
        return "[LLM review skipped — requests not installed]"

    findings_json = json.dumps(static_findings, indent=2) if static_findings else "None"

    try:
        resp = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a concise code reviewer. Provide a brief "
                            "review (max 200 words) covering security, bugs, "
                            "and style issues. Reference the static analysis "
                            "findings provided."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Language: {language}\n"
                            f"```{language}\n{code}\n```\n\n"
                            f"Static findings:\n```json\n{findings_json}\n```"
                        ),
                    },
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return f"[LLM review failed: {exc}]"


# ===========================================================================
# Scanner
# ===========================================================================

def scan_directory(
    watch_dir: Path,
    tracker: FileStateTracker,
    memory: ReviewMemory,
    use_llm: bool = True,
) -> int:
    """Scan a directory for changed code files and review them.

    Returns the number of files reviewed.
    """
    changed_files = tracker.get_changed_files(watch_dir)

    if not changed_files:
        logger.info("No new or modified files found.")
        return 0

    logger.info("Found %d changed file(s) to review.", len(changed_files))

    reviewed = 0
    for file_path in changed_files:
        ext = file_path.suffix.lower()
        language = EXTENSION_TO_LANGUAGE.get(ext, "python")
        relative = file_path.relative_to(watch_dir) if file_path.is_relative_to(watch_dir) else file_path

        logger.info("Reviewing: %s (%s)", relative, language)

        try:
            code = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("Cannot read %s: %s", file_path, exc)
            continue

        # Static analysis
        static_result = static_code_analysis(code, language)
        summary = static_result["summary"]

        print(f"\n  📄 {relative}")
        print(f"     Issues: {summary['total_issues']} "
              f"(Critical: {summary['severity_counts']['critical']}, "
              f"Warning: {summary['severity_counts']['warning']}, "
              f"Info: {summary['severity_counts']['info']})")
        print(f"     Severity: {summary['overall_severity'].upper()}")

        # LLM review (optional)
        llm_result = ""
        if use_llm and code.strip():
            llm_result = llm_review(code, language, static_result["findings"])
            # Brief preview
            first_lines = llm_result.strip().split("\n")[:3]
            for line in first_lines:
                print(f"     🤖 {line}")
            # Rate limit
            time.sleep(2)

        # Store in memory
        review_record = {
            "file": str(relative),
            "language": language,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "issue_count": summary["total_issues"],
            "severity": summary["overall_severity"],
            "findings_summary": {
                "critical": summary["severity_counts"]["critical"],
                "warning": summary["severity_counts"]["warning"],
                "info": summary["severity_counts"]["info"],
            },
            "llm_review_excerpt": llm_result[:500] if llm_result else "",
        }
        memory.store_review(review_record)
        reviewed += 1

    return reviewed


# ===========================================================================
# Main loop
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scheduled Code Reviewer — Hermes Agent Feature Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "This demonstrates Hermes Agent's scheduled task feature.\n"
            "In Hermes, this would be:\n"
            '  agent.schedule("review_codebase", cron="*/5 * * * *", '
            'target_dir="./code_to_review")\n'
        ),
    )
    parser.add_argument(
        "--dir", type=str,
        default=str(PROJECT_DIR / "code_to_review"),
        help="Directory to watch for code files (default: ./code_to_review)",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Scan interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single scan and exit (no loop)",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM review (static analysis only)",
    )
    args = parser.parse_args()

    watch_dir = Path(args.dir).resolve()
    watch_dir.mkdir(parents=True, exist_ok=True)

    tracker = FileStateTracker(STATE_FILE)
    memory = ReviewMemory(MEMORY_FILE)

    print("=" * 60)
    print("  HERMES AGENT — Scheduled Code Reviewer")
    print("=" * 60)
    print(f"  Watch directory:  {watch_dir}")
    print(f"  Scan interval:    {args.interval}s")
    print(f"  LLM review:       {'disabled' if args.no_llm else 'enabled'}")
    print(f"  Mode:             {'single scan' if args.once else 'recurring'}")

    # Show memory stats
    stats = memory.get_stats()
    print(f"\n  [Persistent Memory]")
    print(f"  Total past scans:   {stats['total_scans']}")
    print(f"  Total past reviews: {stats['total_reviews']}")
    print(f"  Last scan:          {stats['last_scan']}")
    print("=" * 60)

    if args.once:
        # Single scan
        reviewed = scan_directory(watch_dir, tracker, memory, use_llm=not args.no_llm)
        print(f"\n✅ Scan complete: {reviewed} file(s) reviewed.")
        _print_stats(memory)
        return

    # Recurring scan loop
    print(f"\n🔄 Starting recurring scan (Ctrl+C to stop)...")
    print(f"   Place code files in: {watch_dir}")
    print(f"   Hermes equivalent: agent.schedule('review_codebase', "
          f"cron='*/{args.interval // 60 or 1} * * * *')\n")

    scan_count = 0
    try:
        while True:
            scan_count += 1
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n{'─' * 60}")
            print(f"  Scan #{scan_count} at {timestamp}")
            print(f"{'─' * 60}")

            reviewed = scan_directory(
                watch_dir, tracker, memory, use_llm=not args.no_llm
            )

            if reviewed > 0:
                _print_stats(memory)

            logger.info(
                "Scan #%d complete (%d files reviewed). "
                "Next scan in %ds...",
                scan_count, reviewed, args.interval,
            )
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print(f"\n\n🛑 Stopped after {scan_count} scan(s).")
        _print_stats(memory)


def _print_stats(memory: ReviewMemory) -> None:
    """Print aggregate memory statistics."""
    stats = memory.get_stats()
    print(f"\n  [Memory Stats]")
    print(f"  Total scans:   {stats['total_scans']}")
    print(f"  Total reviews: {stats['total_reviews']}")
    print(f"  Total issues:  {stats['total_issues']}")

    recent = memory.get_recent(3)
    if recent:
        print(f"  Recent reviews:")
        for r in recent:
            print(f"    - {r['file']} ({r['severity']}, "
                  f"{r['issue_count']} issues) at {r['timestamp']}")


if __name__ == "__main__":
    main()

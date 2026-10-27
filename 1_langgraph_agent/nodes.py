"""
Node functions for the LangGraph Code Review Agent.

Each function represents a distinct processing step in the review pipeline:
  1. input_processor  — validates and parses the raw code input
  2. llm_analyzer     — sends the code to an LLM for review
  3. deep_analyzer    — performs deeper analysis on critical findings
  4. output_validator — compiles a structured final report

All nodes accept and return a partial ``CodeReviewState`` dict.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add local libraries if present
_lib_dir = Path.home() / "python_libs"
if _lib_dir.exists() and str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from state import CodeReviewState

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Language-detection heuristics — keyword sets keyed by language name.
_LANGUAGE_KEYWORDS: dict[str, set[str]] = {
    "python": {"def", "import", "class", "elif", "self", "print(", "lambda", "except", "raise"},
    "javascript": {"function", "const", "let", "var", "=>", "console.log", "document.", "window."},
    "typescript": {"interface", "type ", ": string", ": number", "export", "import", "const", "let"},
    "java": {"public class", "public static void", "System.out", "import java", "private", "protected"},
    "c": {"#include", "int main", "printf", "scanf", "void", "malloc", "free("},
    "cpp": {"#include", "std::", "cout", "cin", "namespace", "template", "class"},
    "rust": {"fn ", "let mut", "impl", "pub fn", "use std", "println!", "match"},
    "go": {"func ", "package ", "import (", "fmt.", "go func", "chan ", "defer"},
    "ruby": {"def ", "end", "puts", "require", "attr_accessor", "class", "module"},
}

# Generic keywords that suggest text is source code (language-agnostic).
_CODE_INDICATORS = {
    "def ", "function ", "class ", "if ", "for ", "while ", "return ",
    "import ", "#include", "var ", "let ", "const ", "{", "}", "()", "=>",
    "public", "private", "void", "int ", "str ", "print(", "console.log",
    "try", "catch", "except", "throw", "raise", "switch", "case",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_llm() -> ChatGroq:
    """Return a configured ``ChatGroq`` instance."""
    return ChatGroq(
        model=_MODEL_NAME,
        temperature=0,
        max_tokens=1024,
    )


def _detect_language(code: str) -> str:
    """Heuristically detect the programming language of *code*.

    Returns the best-matching language name or ``'unknown'``.
    """
    code_lower = code.lower()
    scores: dict[str, int] = {}
    for lang, keywords in _LANGUAGE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in code_lower)
        if score:
            scores[lang] = score
    if scores:
        return max(scores, key=scores.get)  # type: ignore[arg-type]
    return "unknown"


def _looks_like_code(text: str) -> bool:
    """Return ``True`` if *text* appears to be source code rather than prose."""
    hits = sum(1 for kw in _CODE_INDICATORS if kw in text)
    return hits >= 2


def _parse_json_from_text(text: str) -> dict[str, Any]:
    """Extract the first JSON object from *text*, tolerating markdown fences."""
    # Strip markdown code fences if present.
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip().rstrip("`")

    # Try parsing the whole thing first.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fall back: find the first { … } block.
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


# ---------------------------------------------------------------------------
# Node 1 — Input Processor
# ---------------------------------------------------------------------------


def input_processor(state: CodeReviewState) -> dict[str, Any]:
    """Validate and parse the raw code input.

    Sets ``is_valid_input`` to ``False`` (with an error) when the input is
    empty or does not look like source code.  Otherwise, populates
    ``parsed_info`` with basic metadata such as line count, whether the code
    contains functions, classes, or imports, and detects the language when
    set to ``'auto'``.
    """
    logger.info("input_processor: validating input")

    code: str = state.get("code", "")
    language: str = state.get("language", "auto")

    # --- Empty input check ---------------------------------------------------
    if not code or not code.strip():
        logger.warning("input_processor: empty code input")
        return {
            "is_valid_input": False,
            "parsed_info": {"error": "Empty code input"},
            "errors": ["Input validation failed: code is empty."],
        }

    # --- Does it look like code? ---------------------------------------------
    if not _looks_like_code(code):
        logger.warning("input_processor: input does not look like code")
        return {
            "is_valid_input": False,
            "parsed_info": {"error": "Input does not appear to be source code"},
            "errors": [
                "Input validation failed: the provided text does not appear "
                "to be source code."
            ],
        }

    # --- Language detection ----------------------------------------------------
    if language in ("auto", "", None):
        language = _detect_language(code)
        logger.info("input_processor: detected language as '%s'", language)

    # --- Parse basic metadata -------------------------------------------------
    lines = code.splitlines()
    non_empty_lines = [l for l in lines if l.strip()]

    parsed_info: dict[str, Any] = {
        "line_count": len(lines),
        "non_empty_line_count": len(non_empty_lines),
        "has_functions": bool(re.search(r"\b(def|function|func|fn)\b", code)),
        "has_classes": bool(re.search(r"\bclass\b", code)),
        "has_imports": bool(re.search(r"\b(import|require|include|use)\b", code)),
        "has_comments": bool(re.search(r"(#|//|/\*|\*\*|'''|\"\"\")", code)),
        "detected_language": language,
    }

    logger.info(
        "input_processor: valid input — %d lines, language=%s",
        parsed_info["line_count"],
        language,
    )

    return {
        "is_valid_input": True,
        "language": language,
        "parsed_info": parsed_info,
    }


# ---------------------------------------------------------------------------
# Node 2 — LLM Analyzer
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM_PROMPT = (
    "You are an expert code reviewer. Analyze the following code for:\n"
    "1) Bugs and logic errors\n"
    "2) Security vulnerabilities\n"
    "3) Style and best practice violations\n"
    "4) Performance issues\n\n"
    "Respond in JSON format with keys: "
    "bugs (list), security_issues (list), style_issues (list), "
    "performance_issues (list), overall_quality (string: excellent/good/"
    "needs_improvement/poor), summary (string)."
)


def llm_analyzer(state: CodeReviewState) -> dict[str, Any]:
    """Send the code to the Groq LLM for review and classify severity.

    The LLM is prompted to return a structured JSON object.  Severity is
    determined as:
      - ``'critical'`` — security issues found **or** bugs mentioning high
        impact
      - ``'warning'``  — style or performance issues (but no critical ones)
      - ``'info'``     — minor observations only
      - ``'clean'``    — no issues at all
    """
    logger.info("llm_analyzer: sending code to LLM")

    code = state["code"]
    language = state.get("language", "unknown")

    try:
        llm = _get_llm()
        messages = [
            SystemMessage(content=_REVIEW_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Language: {language}\n\n```{language}\n{code}\n```"
                )
            ),
        ]

        response = llm.invoke(messages)
        review = _parse_json_from_text(response.content)

        if not review:
            logger.error("llm_analyzer: failed to parse LLM response")
            return {
                "review_result": {"raw_response": response.content},
                "severity": "warning",
                "errors": ["LLM response could not be parsed as JSON."],
            }

        # --- Determine severity -----------------------------------------------
        has_security = bool(review.get("security_issues"))
        has_bugs = bool(review.get("bugs"))
        has_style = bool(review.get("style_issues"))
        has_perf = bool(review.get("performance_issues"))

        if has_security or has_bugs:
            severity = "critical"
        elif has_style or has_perf:
            severity = "warning"
        else:
            severity = "clean"

        logger.info("llm_analyzer: severity = %s", severity)

        return {
            "review_result": review,
            "severity": severity,
        }

    except Exception as exc:
        logger.exception("llm_analyzer: LLM call failed")
        return {
            "review_result": {},
            "severity": "warning",
            "errors": [f"LLM analysis failed: {exc}"],
        }


# ---------------------------------------------------------------------------
# Node 3 — Deep Analyzer (critical severity only)
# ---------------------------------------------------------------------------

_DEEP_ANALYSIS_SYSTEM_PROMPT = (
    "You are a senior security engineer and code auditor. You have already "
    "identified critical issues in the code below. Provide a deep analysis "
    "with:\n"
    "1) Detailed fix suggestions with corrected code snippets\n"
    "2) Exploit scenarios — how an attacker could exploit each vulnerability\n"
    "3) Root cause analysis — why the developer likely made this mistake\n\n"
    "Respond in JSON format with keys: "
    "fix_suggestions (list of objects with 'issue', 'fix', 'corrected_code'), "
    "exploit_scenarios (list of objects with 'vulnerability', 'scenario', 'impact'), "
    "root_cause_analysis (list of objects with 'issue', 'root_cause', 'prevention')."
)


def deep_analyzer(state: CodeReviewState) -> dict[str, Any]:
    """Perform an in-depth analysis of critical findings.

    Only invoked when ``severity == 'critical'``.  Calls the LLM with
    the original code **and** the previously identified issues so it can
    produce fix suggestions, exploit scenarios, and root-cause analysis.
    """
    logger.info("deep_analyzer: performing deep analysis on critical issues")

    code = state["code"]
    language = state.get("language", "unknown")
    review = state.get("review_result", {})

    issues_summary = json.dumps(
        {
            "bugs": review.get("bugs", []),
            "security_issues": review.get("security_issues", []),
        },
        indent=2,
    )

    try:
        llm = _get_llm()
        messages = [
            SystemMessage(content=_DEEP_ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Language: {language}\n\n"
                    f"Code:\n```{language}\n{code}\n```\n\n"
                    f"Previously identified critical issues:\n{issues_summary}"
                )
            ),
        ]

        response = llm.invoke(messages)
        deep = _parse_json_from_text(response.content)

        if not deep:
            logger.error("deep_analyzer: could not parse LLM response")
            return {
                "deep_analysis": {"raw_response": response.content},
                "errors": ["Deep analysis response could not be parsed as JSON."],
            }

        logger.info("deep_analyzer: analysis complete")
        return {"deep_analysis": deep}

    except Exception as exc:
        logger.exception("deep_analyzer: LLM call failed")
        return {
            "deep_analysis": {},
            "errors": [f"Deep analysis failed: {exc}"],
        }


# ---------------------------------------------------------------------------
# Node 4 — Output Validator
# ---------------------------------------------------------------------------


def output_validator(state: CodeReviewState) -> dict[str, Any]:
    """Compile all results into a validated, structured ``final_report``.

    The report includes status, input summary, findings, severity,
    deep analysis (when present), actionable recommendations, and a
    timestamp.
    """
    logger.info("output_validator: compiling final report")

    errors = state.get("errors", [])
    is_valid = state.get("is_valid_input", False)

    # --- Build recommendations ------------------------------------------------
    recommendations: list[str] = []
    review = state.get("review_result", {})

    if not is_valid:
        status = "error"
    else:
        status = "reviewed"
        for bug in review.get("bugs", []):
            if isinstance(bug, dict):
                recommendations.append(f"Fix bug: {bug.get('description', bug)}")
            else:
                recommendations.append(f"Fix bug: {bug}")
        for issue in review.get("security_issues", []):
            if isinstance(issue, dict):
                recommendations.append(f"Security: {issue.get('description', issue)}")
            else:
                recommendations.append(f"Security: {issue}")
        for issue in review.get("style_issues", []):
            if isinstance(issue, dict):
                recommendations.append(f"Style: {issue.get('description', issue)}")
            else:
                recommendations.append(f"Style: {issue}")
        for issue in review.get("performance_issues", []):
            if isinstance(issue, dict):
                recommendations.append(f"Performance: {issue.get('description', issue)}")
            else:
                recommendations.append(f"Performance: {issue}")

    # --- Assemble report ------------------------------------------------------
    parsed_info = state.get("parsed_info", {})
    deep_analysis = state.get("deep_analysis")

    final_report: dict[str, Any] = {
        "status": status,
        "input_summary": {
            "language": state.get("language", "unknown"),
            "line_count": parsed_info.get("line_count", 0),
            "non_empty_line_count": parsed_info.get("non_empty_line_count", 0),
            "has_functions": parsed_info.get("has_functions", False),
            "has_classes": parsed_info.get("has_classes", False),
        },
        "findings": review if review else None,
        "severity": state.get("severity", "info"),
        "deep_analysis": deep_analysis if deep_analysis else None,
        "recommendations": recommendations,
        "errors": errors if errors else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- Validate required fields ---------------------------------------------
    required = {"status", "input_summary", "findings", "severity", "recommendations", "timestamp"}
    missing = required - set(final_report.keys())
    if missing:
        logger.error("output_validator: report missing fields: %s", missing)
        final_report["validation_warning"] = f"Missing fields: {missing}"

    logger.info("output_validator: report compiled — status=%s", status)

    return {"final_report": final_report}

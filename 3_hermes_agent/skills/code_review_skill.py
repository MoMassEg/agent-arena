"""
Hermes Agent Code Review Skill — Static Code Analysis
======================================================

This module provides a custom skill for the Hermes Agent framework that
performs static code analysis WITHOUT calling an LLM. It uses Python's
`ast` module for Python code and regex patterns for JavaScript analysis.

Detected issues include:
  - Unused variables
  - Functions without docstrings
  - Bare except clauses
  - Mutable default arguments
  - Hardcoded credentials (passwords, API keys)
  - eval() usage, innerHTML (XSS), SQL injection patterns
  - var instead of let/const (JavaScript)

Two implementations are provided:
  1. Hermes decorator-based skill (Option A)
  2. Standalone function (Option B) — works without Hermes installed
"""

import ast
import re
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credential detection patterns (shared across languages)
# ---------------------------------------------------------------------------
CREDENTIAL_PATTERNS = [
    # API keys (generic patterns)
    (r"""(?:api[_-]?key|apikey)\s*[=:]\s*['"][A-Za-z0-9_\-]{16,}['"]""",
     "Hardcoded API key detected"),
    # Secret keys
    (r"""(?:secret[_-]?key|secretkey)\s*[=:]\s*['"][^'"]{8,}['"]""",
     "Hardcoded secret key detected"),
    # Passwords
    (r"""(?:password|passwd|pwd|db_password|DB_PASSWORD)\s*[=:]\s*['"][^'"]+['"]""",
     "Hardcoded password detected"),
    # AWS-style keys
    (r"""(?:AKIA|ASIA)[A-Z0-9]{16}""",
     "Potential AWS access key detected"),
    # Generic tokens (sk-, ghp_, gsk_, etc.)
    (r"""['"](?:sk-|ghp_|gsk_|glpat-|xox[boaprs]-)[A-Za-z0-9_\-]{10,}['"]""",
     "Hardcoded token/secret detected"),
    # Connection strings with embedded credentials
    (r"""(?:mongodb|postgresql|mysql|redis)://[^:]+:[^@]+@""",
     "Connection string with embedded credentials detected"),
]


# ===========================================================================
# Python Analysis (AST-based)
# ===========================================================================

class PythonAnalyzer(ast.NodeVisitor):
    """AST-based analyzer for Python code.

    Walks the abstract syntax tree to detect common code quality and
    security issues without executing the code.
    """

    def __init__(self, source: str):
        self.source = source
        self.findings: List[Dict[str, Any]] = []
        self._assigned_names: Dict[str, int] = {}  # name -> line
        self._used_names: set = set()
        self._function_depth = 0

    # ---- Bare except clauses ----
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.findings.append({
                "rule": "bare-except",
                "severity": "warning",
                "line": node.lineno,
                "message": "Bare 'except:' clause — catches all exceptions including "
                           "KeyboardInterrupt and SystemExit. Use 'except Exception:' instead.",
            })
        self.generic_visit(node)

    # ---- Functions without docstrings & mutable default args ----
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)

    def _check_function(self, node: ast.FunctionDef) -> None:
        # Missing docstring
        if not (node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, (ast.Constant, ast.Str))):
            self.findings.append({
                "rule": "missing-docstring",
                "severity": "info",
                "line": node.lineno,
                "message": f"Function '{node.name}' has no docstring.",
            })

        # Mutable default arguments (list, dict, set literals)
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.findings.append({
                    "rule": "mutable-default-argument",
                    "severity": "warning",
                    "line": default.lineno,
                    "message": f"Mutable default argument in '{node.name}()'. "
                               "Use None and assign inside the function body.",
                })

        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    # ---- Track assignments and usage for unused-variable detection ----
    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                # Skip dunder names and module-level constants (ALL_CAPS)
                if not name.startswith("_") and not name.isupper():
                    self._assigned_names[name] = node.lineno
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._used_names.add(node.id)
        self.generic_visit(node)

    # ---- Finalize: detect unused variables ----
    def finalize(self) -> None:
        for name, line in self._assigned_names.items():
            if name not in self._used_names:
                self.findings.append({
                    "rule": "unused-variable",
                    "severity": "info",
                    "line": line,
                    "message": f"Variable '{name}' is assigned but never used.",
                })


def _analyze_python(code: str) -> List[Dict[str, Any]]:
    """Run AST-based analysis on Python source code."""
    findings: List[Dict[str, Any]] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        findings.append({
            "rule": "syntax-error",
            "severity": "critical",
            "line": exc.lineno or 0,
            "message": f"Syntax error: {exc.msg}",
        })
        return findings

    analyzer = PythonAnalyzer(code)
    analyzer.visit(tree)
    analyzer.finalize()
    findings.extend(analyzer.findings)

    # Credential patterns (regex-based, applied to raw source)
    findings.extend(_scan_credentials(code))

    return findings


# ===========================================================================
# JavaScript Analysis (Regex-based)
# ===========================================================================

# JavaScript-specific patterns
JS_PATTERNS = [
    # eval() usage
    (r"""\beval\s*\(""",
     "eval-usage",
     "critical",
     "Use of eval() is a critical security risk — allows arbitrary code execution."),
    # innerHTML (XSS)
    (r"""\.innerHTML\s*=""",
     "innerhtml-xss",
     "critical",
     "Direct innerHTML assignment is an XSS risk. Use textContent or a sanitization library."),
    # SQL string concatenation
    (r"""(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s+.+["']\s*\+""",
     "sql-concatenation",
     "critical",
     "SQL query built via string concatenation — vulnerable to SQL injection."),
    # var instead of let/const
    (r"""\bvar\s+""",
     "var-usage",
     "warning",
     "Use 'let' or 'const' instead of 'var' for proper block scoping."),
    # document.write
    (r"""\bdocument\.write\s*\(""",
     "document-write",
     "warning",
     "document.write() can overwrite the entire document. Avoid in modern code."),
]


def _analyze_javascript(code: str) -> List[Dict[str, Any]]:
    """Run regex-based analysis on JavaScript source code."""
    findings: List[Dict[str, Any]] = []
    lines = code.split("\n")

    for line_num, line in enumerate(lines, start=1):
        for pattern, rule, severity, message in JS_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "rule": rule,
                    "severity": severity,
                    "line": line_num,
                    "message": message,
                })

    # Credential patterns
    findings.extend(_scan_credentials(code))

    return findings


# ===========================================================================
# Shared helpers
# ===========================================================================

def _scan_credentials(code: str) -> List[Dict[str, Any]]:
    """Scan source code for hardcoded credentials using regex patterns."""
    findings: List[Dict[str, Any]] = []
    lines = code.split("\n")

    for line_num, line in enumerate(lines, start=1):
        for pattern, message in CREDENTIAL_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "rule": "hardcoded-credential",
                    "severity": "critical",
                    "line": line_num,
                    "message": message,
                })

    return findings


def _compute_summary(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute a summary from a list of findings."""
    severity_counts = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    total = len(findings)
    if severity_counts["critical"] > 0:
        overall = "critical"
    elif severity_counts["warning"] > 0:
        overall = "warning"
    elif severity_counts["info"] > 0:
        overall = "info"
    else:
        overall = "clean"

    return {
        "total_issues": total,
        "severity_counts": severity_counts,
        "overall_severity": overall,
    }


# ===========================================================================
# Option A: Hermes Agent Skill (decorator-based API)
# ===========================================================================
try:
    from hermes_agent.skills import Skill, skill  # type: ignore

    @skill(
        name="static_code_analysis",
        description=(
            "Performs static analysis on code to find bugs, security issues, "
            "and style violations without calling an LLM. Supports Python "
            "(AST-based) and JavaScript (regex-based) analysis."
        ),
    )
    def static_code_analysis(code: str, language: str = "python") -> dict:
        """Hermes skill entry-point for static code analysis.

        Args:
            code: Source code string to analyze.
            language: Programming language — 'python' or 'javascript'.

        Returns:
            dict with 'findings', 'summary', and 'language' keys.
        """
        return _static_code_analysis_impl(code, language)

    logger.info("Hermes Agent skill decorator loaded successfully.")

except ImportError:
    logger.debug(
        "hermes_agent not installed — falling back to standalone function."
    )
    # Define fallback when hermes_agent is not installed
    def static_code_analysis(code: str, language: str = "python") -> dict:
        return _static_code_analysis_impl(code, language)



# ===========================================================================
# Option B: Standalone function (always available)
# ===========================================================================

def _static_code_analysis_impl(code: str, language: str = "python") -> Dict[str, Any]:
    """Core implementation of static code analysis.

    This function works independently of the Hermes Agent framework.

    Args:
        code: Source code string to analyze.
        language: Programming language — 'python', 'javascript', or 'auto'.

    Returns:
        Dictionary containing:
            - language (str): Detected or specified language.
            - findings (list): List of issue dicts with rule, severity, line, message.
            - summary (dict): Aggregate counts and overall severity.
    """
    if not code or not code.strip():
        return {
            "language": language,
            "findings": [],
            "summary": {
                "total_issues": 0,
                "severity_counts": {"critical": 0, "warning": 0, "info": 0},
                "overall_severity": "clean",
            },
            "note": "Empty or whitespace-only input — nothing to analyze.",
        }

    # Auto-detect language by simple heuristics
    if language == "auto":
        language = _detect_language(code)

    lang = language.lower().strip()
    if lang in ("python", "py"):
        findings = _analyze_python(code)
    elif lang in ("javascript", "js", "typescript", "ts"):
        findings = _analyze_javascript(code)
    else:
        # Fallback: run credential scan only
        findings = _scan_credentials(code)
        findings.append({
            "rule": "unsupported-language",
            "severity": "info",
            "line": 0,
            "message": f"Language '{language}' is not fully supported. "
                       "Only credential scanning was performed.",
        })

    summary = _compute_summary(findings)

    return {
        "language": language,
        "findings": findings,
        "summary": summary,
    }


def _detect_language(code: str) -> str:
    """Simple heuristic to guess the programming language."""
    python_signals = [
        r"\bdef\s+\w+\s*\(",
        r"\bimport\s+\w+",
        r"\bclass\s+\w+.*:",
        r"\bprint\s*\(",
    ]
    js_signals = [
        r"\bfunction\s+\w+\s*\(",
        r"\bconst\s+\w+",
        r"\blet\s+\w+",
        r"\bvar\s+\w+",
        r"\bdocument\.",
        r"\bconsole\.log\(",
    ]

    py_score = sum(1 for p in python_signals if re.search(p, code))
    js_score = sum(1 for p in js_signals if re.search(p, code))

    if py_score > js_score:
        return "python"
    elif js_score > py_score:
        return "javascript"
    else:
        return "python"  # default


# Public alias for standalone usage
static_code_analysis_standalone = _static_code_analysis_impl


# ===========================================================================
# CLI entry-point (for quick testing)
# ===========================================================================
if __name__ == "__main__":
    import json
    import sys

    sample_python = '''
import os

DB_PASSWORD = "supersecret123"

def process(data=[]):
    unused = 42
    try:
        return len(data)
    except:
        pass
'''

    sample_js = '''
var x = document.getElementById('input').value;
var query = "SELECT * FROM users WHERE name = '" + x + "'";
document.getElementById('out').innerHTML = x;
eval(x);
'''

    print("=" * 60)
    print("Python Analysis")
    print("=" * 60)
    result = _static_code_analysis_impl(sample_python, "python")
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 60)
    print("JavaScript Analysis")
    print("=" * 60)
    result = _static_code_analysis_impl(sample_js, "javascript")
    print(json.dumps(result, indent=2))

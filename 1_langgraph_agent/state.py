"""
State definition for the LangGraph Code Review Agent.

Defines the shared state schema (TypedDict) that flows through all nodes
in the review pipeline. Uses Annotated types with custom reducers for
fields that accumulate values across nodes.
"""

from typing import Annotated, TypedDict


def _merge_dict(existing: dict, new: dict) -> dict:
    """Reducer that merges two dicts, with new values overriding existing ones."""
    if existing is None:
        return new or {}
    if new is None:
        return existing
    merged = {**existing, **new}
    return merged


def _append_errors(existing: list[str], new: list[str]) -> list[str]:
    """Reducer that appends new error messages to the existing list."""
    if existing is None:
        existing = []
    if new is None:
        return existing
    return existing + new


class CodeReviewState(TypedDict):
    """Shared state flowing through the LangGraph code review pipeline.

    Attributes:
        code: Raw source code input to be reviewed.
        language: Programming language of the code (e.g. 'python', 'javascript').
        is_valid_input: Whether the input was validated as actual code.
        parsed_info: Metadata extracted during parsing — line count, whether
            the code contains functions, classes, imports, etc.
        review_result: Raw analysis result from the LLM, including bugs,
            security issues, style issues, performance issues, and a summary.
        severity: Overall severity classification — one of
            'critical', 'warning', 'info', or 'clean'.
        deep_analysis: Optional deeper analysis produced only when severity
            is 'critical'. Contains fix suggestions, exploit scenarios, and
            root-cause analysis.
        final_report: The structured final output compiled by the output
            validator node, ready for consumption by the caller.
        errors: Accumulated error messages from any node that encounters
            a problem during processing.
    """

    code: str
    language: str
    is_valid_input: bool
    parsed_info: Annotated[dict, _merge_dict]
    review_result: Annotated[dict, _merge_dict]
    severity: str
    deep_analysis: Annotated[dict, _merge_dict]
    final_report: Annotated[dict, _merge_dict]
    errors: Annotated[list[str], _append_errors]

# Skills package — makes the skills directory importable
"""
Hermes Agent Skills Package
============================

This package contains custom skills for the CodeReviewBot agent.
Skills are automatically discovered by the Hermes Agent runtime
when placed in the configured skills_dir.
"""

from skills.code_review_skill import (
    _static_code_analysis_impl as static_code_analysis,
)

__all__ = ["static_code_analysis"]

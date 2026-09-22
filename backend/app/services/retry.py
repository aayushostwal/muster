"""Failure classification and backoff computation (see docs/SPEC.md
"Failure handling & retry").
"""
from __future__ import annotations

import re

from app.config import settings
from app.db.models import FailureClass

# Patterns considered transient: rate/usage limits and network blips.
_TRANSIENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"usage limit",
        r"rate limit",
        r"\b429\b",
        r"ECONNRESET",
        r"timeout",
        r"getaddrinfo",
        r"network",
    )
]


def classify(exit_code: int, stderr_tail: str) -> FailureClass:
    """Classify a nonzero-exit failure as transient (retryable) or other."""
    stderr_tail = stderr_tail or ""
    for pattern in _TRANSIENT_PATTERNS:
        if pattern.search(stderr_tail):
            return FailureClass.transient
    return FailureClass.other


def compute_backoff(attempt: int) -> int:
    """Exponential backoff in seconds, capped at settings.retry_max_seconds.

    `attempt` is 0-indexed (first retry -> attempt=0).
    """
    return min(settings.retry_base_seconds * (2**attempt), settings.retry_max_seconds)

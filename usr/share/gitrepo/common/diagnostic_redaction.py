"""Redact credentials before diagnostics reach logs or user-facing buffers."""

from __future__ import annotations

import re


_REDACTIONS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:token|bearer)\s+)[^\s'\"]+"),
    re.compile(r"(?i)((?:token|password|passwd|secret)\s*[:=]\s*)[^\s'\"]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b"),
    # Fine-grained personal access tokens and App tokens.
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # Credentials embedded in a remote URL: https://user:secret@host.
    re.compile(r"(://[^/\s:@]+:)[^/\s@]+(?=@)"),
)


def redact_diagnostic(message: object) -> str:
    """Return printable diagnostic text with common secret forms removed."""
    redacted = str(message)
    for pattern in _REDACTIONS:
        redacted = pattern.sub(
            lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]", redacted
        )
    return redacted

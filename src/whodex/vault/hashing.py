"""Content hashing utilities for the vault layer."""

from __future__ import annotations

import hashlib


def content_hash(text: str) -> str:
    """Return the SHA-256 hex digest of *text* (encoded as UTF-8)."""
    return hashlib.sha256(text.encode()).hexdigest()

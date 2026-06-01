"""Identifier normalisation — pure, no IO, no ORM."""

from __future__ import annotations


def normalize_identifier(kind: str, value: str) -> str:
    """Return the canonical form of *value* for the given identifier *kind*.

    Rules:
    - ``email``: lowercase + strip surrounding whitespace.
    - ``linkedin_url``: lowercase host/path + strip trailing ``/`` characters.
    - ``phone``: strip all spaces and dashes.
    - anything else: strip surrounding whitespace only.
    """
    if kind == "email":
        return value.strip().lower()
    if kind == "linkedin_url":
        return value.strip().lower().rstrip("/")
    if kind == "phone":
        return value.replace(" ", "").replace("-", "")
    return value.strip()

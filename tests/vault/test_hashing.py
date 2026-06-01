"""Tests for content_hash helper."""

from __future__ import annotations

from whodex.vault.hashing import content_hash


def test_content_hash_is_stable() -> None:
    """Same input always produces same hash."""
    text = "Hello, world!"
    assert content_hash(text) == content_hash(text)


def test_content_hash_differs_on_different_input() -> None:
    """Different strings produce different hashes."""
    assert content_hash("abc") != content_hash("def")


def test_content_hash_returns_64_char_hex_string() -> None:
    """SHA-256 hex digest is exactly 64 characters."""
    result = content_hash("test")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_content_hash_empty_string() -> None:
    """Empty string produces a stable, non-empty hash."""
    result = content_hash("")
    assert len(result) == 64


def test_content_hash_differs_from_empty() -> None:
    """Non-empty input differs from empty."""
    assert content_hash("x") != content_hash("")

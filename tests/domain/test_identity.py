"""Unit tests for normalize_identifier — pure domain behaviour."""

from __future__ import annotations

from whodex.domain.identity import normalize_identifier


class TestEmailNormalization:
    def test_lowercases_and_strips(self) -> None:
        assert normalize_identifier("email", "  Jane@Acme.COM  ") == "jane@acme.com"

    def test_already_normalized_is_unchanged(self) -> None:
        assert normalize_identifier("email", "jane@acme.com") == "jane@acme.com"

    def test_strips_whitespace_only(self) -> None:
        assert normalize_identifier("email", "  a@b.com  ") == "a@b.com"


class TestLinkedinUrlNormalization:
    def test_lowercases_host_and_strips_trailing_slash(self) -> None:
        assert (
            normalize_identifier("linkedin_url", "https://www.linkedin.com/in/Jane/")
            == "https://www.linkedin.com/in/jane"
        )

    def test_no_trailing_slash_passes_through(self) -> None:
        assert (
            normalize_identifier("linkedin_url", "https://www.linkedin.com/in/jane")
            == "https://www.linkedin.com/in/jane"
        )

    def test_strips_multiple_trailing_slashes(self) -> None:
        assert (
            normalize_identifier("linkedin_url", "https://www.linkedin.com/in/jane//")
            == "https://www.linkedin.com/in/jane"
        )


class TestPhoneNormalization:
    def test_strips_spaces_and_dashes(self) -> None:
        assert normalize_identifier("phone", "+49 173 123-456") == "+49173123456"

    def test_no_spaces_or_dashes_unchanged(self) -> None:
        assert normalize_identifier("phone", "+49173123456") == "+49173123456"


class TestFallbackNormalization:
    def test_unknown_kind_strips_whitespace(self) -> None:
        assert normalize_identifier("canonical_name", "  Acme Corp  ") == "Acme Corp"

    def test_unknown_kind_preserves_case(self) -> None:
        assert normalize_identifier("wikilink", "Jane Doe") == "Jane Doe"

"""Tests for the linkedin_ext PUSH source connector."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.conftest import raw
from whodex.domain.enums import Capability
from whodex.domain.fields import is_valid_field
from whodex.sources.linkedin.ext import LinkedInExtSource

T0 = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def source() -> LinkedInExtSource:
    return LinkedInExtSource()


@pytest.fixture()
def representative_record():
    return raw(
        source="linkedin_ext",
        identity={"linkedin_url": "https://linkedin.com/in/jdoe"},
        payload={
            "name": "Jane Doe",
            "title": "Staff Engineer",
            "company": "Acme Corp",
            "linkedin_url": "https://linkedin.com/in/jdoe",
        },
        observed=T0,
    )


# ---------------------------------------------------------------------------
# Shared SourceContract (mirrors test_source_contract.py)
# ---------------------------------------------------------------------------


def test_id_is_stable_nonempty(source: LinkedInExtSource) -> None:
    assert isinstance(source.id, str) and source.id


def test_id_matches_trust_key(source: LinkedInExtSource) -> None:
    from whodex.domain.trust import DEFAULT_TRUST

    assert source.id in DEFAULT_TRUST
    assert DEFAULT_TRUST[source.id] == 50


def test_normalize_yields_valid_field_drafts(
    source: LinkedInExtSource, representative_record
) -> None:
    for draft in source.normalize(representative_record):
        assert is_valid_field(draft.field), f"Unknown canonical field: {draft.field!r}"


def test_normalize_is_idempotent(source: LinkedInExtSource, representative_record) -> None:
    assert source.normalize(representative_record) == source.normalize(representative_record)


def test_capability_is_push(source: LinkedInExtSource) -> None:
    assert Capability.PUSH in source.capabilities


def test_identity_keys(source: LinkedInExtSource) -> None:
    assert "linkedin_url" in source.identity_keys


# ---------------------------------------------------------------------------
# Payload mapping: behavioral tests
# ---------------------------------------------------------------------------


def test_payload_maps_to_expected_canonical_fields(source: LinkedInExtSource) -> None:
    record = raw(
        source="linkedin_ext",
        identity={"linkedin_url": "https://linkedin.com/in/jdoe"},
        payload={
            "name": "Jane",
            "title": "Staff Eng",
            "company": "Acme",
            "linkedin_url": "https://linkedin.com/in/jdoe",
        },
        observed=T0,
    )
    drafts = source.normalize(record)
    result = {(d.field, d.value) for d in drafts}
    expected = {
        ("name.full", "Jane"),
        ("job.title", "Staff Eng"),
        ("job.org", "Acme"),
        ("linkedin.url", "https://linkedin.com/in/jdoe"),
    }
    assert result == expected


def test_empty_payload_produces_no_drafts(source: LinkedInExtSource) -> None:
    record = raw(
        source="linkedin_ext",
        identity={"linkedin_url": "https://linkedin.com/in/jdoe"},
        payload={},
        observed=T0,
    )
    assert source.normalize(record) == []


def test_missing_optional_keys_skipped(source: LinkedInExtSource) -> None:
    """Only fields present in the payload should produce drafts."""
    record = raw(
        source="linkedin_ext",
        identity={"linkedin_url": "https://linkedin.com/in/jdoe"},
        payload={"name": "Bob"},
        observed=T0,
    )
    drafts = source.normalize(record)
    fields = {d.field for d in drafts}
    assert "name.full" in fields
    assert "job.title" not in fields
    assert "job.org" not in fields
    assert "linkedin.url" not in fields


def test_empty_string_values_skipped(source: LinkedInExtSource) -> None:
    record = raw(
        source="linkedin_ext",
        identity={"linkedin_url": "https://linkedin.com/in/jdoe"},
        payload={"name": "", "title": "Eng", "company": ""},
        observed=T0,
    )
    drafts = source.normalize(record)
    fields = {d.field for d in drafts}
    assert "name.full" not in fields
    assert "job.title" in fields
    assert "job.org" not in fields


def test_location_is_not_mapped(source: LinkedInExtSource) -> None:
    """location → no scalar location canonical exists; location payload key is skipped."""
    record = raw(
        source="linkedin_ext",
        identity={"linkedin_url": "https://linkedin.com/in/jdoe"},
        payload={"name": "Jane", "location": "London, UK"},
        observed=T0,
    )
    drafts = source.normalize(record)
    location_fields = [d.field for d in drafts if "location" in d.field or "lives" in d.field]
    assert location_fields == []


def test_headline_is_not_mapped(source: LinkedInExtSource) -> None:
    """headline → no fitting canonical field; skipped."""
    record = raw(
        source="linkedin_ext",
        identity={"linkedin_url": "https://linkedin.com/in/jdoe"},
        payload={"name": "Jane", "headline": "Building things at Acme"},
        observed=T0,
    )
    drafts = source.normalize(record)
    headline_fields = [d.field for d in drafts if "headline" in d.field]
    assert headline_fields == []

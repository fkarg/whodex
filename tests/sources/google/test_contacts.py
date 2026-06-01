"""Tests for GoogleContacts PULL source (P1e-2).

All HTTP calls are mocked with respx — no live network requests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from whodex.domain.clock import FixedClock
from whodex.domain.events import RawRecord
from whodex.domain.fields import is_valid_field
from whodex.sources.google.contacts import GoogleContacts

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_TOKEN = "tok"
_PEOPLE_URL = "https://people.googleapis.com/v1/people/me/connections"

_PERSON = {
    "resourceName": "people/c123",
    "names": [{"displayName": "Alice Example"}],
    "emailAddresses": [{"value": "Alice@Example.COM"}],
    "phoneNumbers": [{"value": "+49 30 1234567"}],
    "organizations": [{"title": "Staff Engineer", "name": "Acme Corp"}],
    "metadata": {
        "sources": [
            {"updateTime": "2025-11-01T09:00:00Z"},
        ]
    },
}


def _make_source() -> GoogleContacts:
    return GoogleContacts(
        httpx.Client(),
        token=lambda: _TOKEN,
        clock=FixedClock(_FIXED_NOW),
    )


# ---------------------------------------------------------------------------
# GG1: mapping and identity
# ---------------------------------------------------------------------------


@respx.mock
def test_gg1_mapping_yields_expected_fields() -> None:
    """fetch yields a RawRecord with correct identity; normalize maps all fields."""
    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"connections": [_PERSON]},
        )
    )

    source = _make_source()
    records = list(source.fetch(None))

    assert len(records) == 1
    rec = records[0]

    # Identity
    assert rec.source == "google_contacts"
    assert rec.identity["google_resource"] == "people/c123"
    assert rec.identity["email"] == "alice@example.com"

    # observed_at parsed from metadata.sources[0].updateTime
    expected_observed = datetime(2025, 11, 1, 9, 0, 0, tzinfo=UTC)
    assert rec.observed_at == expected_observed

    # Normalization
    drafts = source.normalize(rec)
    by_field = {d.field: d.value for d in drafts}

    assert by_field["name.full"] == "Alice Example"
    assert by_field["email"] == "alice@example.com"
    assert by_field["phone"] == "+49 30 1234567"
    assert by_field["job.title"] == "Staff Engineer"
    assert by_field["job.org"] == "Acme Corp"


@respx.mock
def test_gg1_authorization_header_sent() -> None:
    """Authorization: Bearer <token> header is present on every request."""
    route = respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(200, json={"connections": [_PERSON]})
    )

    list(_make_source().fetch(None))

    assert route.called
    sent_auth = route.calls[0].request.headers.get("authorization")
    assert sent_auth == f"Bearer {_TOKEN}"


@respx.mock
def test_gg1_normalize_all_drafts_are_valid_fields() -> None:
    """Every field name emitted by normalize must exist in the field registry."""
    respx.get(_PEOPLE_URL).mock(return_value=httpx.Response(200, json={"connections": [_PERSON]}))

    source = _make_source()
    for rec in source.fetch(None):
        for draft in source.normalize(rec):
            assert is_valid_field(draft.field), f"Unknown field: {draft.field!r}"


@respx.mock
def test_gg1_observed_at_falls_back_to_clock_when_no_metadata() -> None:
    """When metadata.sources has no updateTime, observed_at equals clock.now()."""
    person_no_meta = {
        "resourceName": "people/c999",
        "names": [{"displayName": "Bob"}],
        "emailAddresses": [{"value": "bob@example.com"}],
    }
    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(200, json={"connections": [person_no_meta]})
    )

    source = _make_source()
    records = list(source.fetch(None))

    assert len(records) == 1
    assert records[0].observed_at == _FIXED_NOW


@respx.mock
def test_gg1_no_email_identity_still_has_google_resource() -> None:
    """A person without emailAddresses still has google_resource identity key."""
    person_no_email = {
        "resourceName": "people/c000",
        "names": [{"displayName": "No Email"}],
    }
    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(200, json={"connections": [person_no_email]})
    )

    records = list(_make_source().fetch(None))
    assert len(records) == 1
    assert "google_resource" in records[0].identity
    assert "email" not in records[0].identity


# ---------------------------------------------------------------------------
# GG2: pagination
# ---------------------------------------------------------------------------


@respx.mock
def test_gg2_pagination_follows_next_page_token() -> None:
    """fetch follows nextPageToken and accumulates connections from all pages."""
    person_a = {**_PERSON, "resourceName": "people/page1"}
    person_b = {
        "resourceName": "people/page2",
        "names": [{"displayName": "Bob"}],
        "emailAddresses": [{"value": "bob@example.com"}],
    }

    page1_route = respx.get(_PEOPLE_URL, params__contains={"pageSize": "200"}).mock(
        side_effect=lambda req: httpx.Response(
            200,
            json={
                "connections": [person_a],
                "nextPageToken": "TOKEN_P2",
            }
            if "pageToken" not in str(req.url)
            else {
                "connections": [person_b],
            },
        )
    )

    source = _make_source()
    records = list(source.fetch(None))

    assert len(records) == 2
    resource_names = {r.identity["google_resource"] for r in records}
    assert resource_names == {"people/page1", "people/page2"}
    # The route was called twice (once per page)
    assert page1_route.call_count == 2


@respx.mock
def test_gg2_pagination_explicit_two_routes() -> None:
    """Two separate routes: first returns nextPageToken, second does not."""
    person_a = {
        "resourceName": "people/a",
        "emailAddresses": [{"value": "a@example.com"}],
    }
    person_b = {
        "resourceName": "people/b",
        "emailAddresses": [{"value": "b@example.com"}],
    }

    # Route for first page (no pageToken param)
    first_route = respx.get(_PEOPLE_URL).mock(
        side_effect=lambda req: (
            httpx.Response(
                200,
                json={"connections": [person_a], "nextPageToken": "T2"},
            )
            if "pageToken" not in req.url.params
            else httpx.Response(
                200,
                json={"connections": [person_b]},
            )
        )
    )

    source = _make_source()
    records = list(source.fetch(None))

    assert {r.identity["google_resource"] for r in records} == {"people/a", "people/b"}
    assert first_route.call_count == 2


# ---------------------------------------------------------------------------
# GG5: SourceContract
# ---------------------------------------------------------------------------


class _Canned:
    """Minimal SourceContract-compatible wrapper around GoogleContacts.normalize."""

    def __init__(self) -> None:
        self._inner = GoogleContacts(
            httpx.Client(),
            token=lambda: "tok",
            clock=FixedClock(_FIXED_NOW),
        )

    @property
    def id(self) -> str:
        return self._inner.id

    @property
    def capabilities(self):  # type: ignore[return]
        return self._inner.capabilities

    @property
    def identity_keys(self):  # type: ignore[return]
        return self._inner.identity_keys

    @property
    def provides(self):  # type: ignore[return]
        return self._inner.provides

    def _make_record(self) -> RawRecord:
        return RawRecord(
            source="google_contacts",
            identity={"google_resource": "people/c1", "email": "alice@example.com"},
            payload=_PERSON,
            observed_at=_FIXED_NOW,
        )

    @respx.mock
    def fetch(self, since):  # type: ignore[override]
        respx.get(_PEOPLE_URL).mock(
            return_value=httpx.Response(200, json={"connections": [_PERSON]})
        )
        return list(self._inner.fetch(since))

    def normalize(self, record: RawRecord):  # type: ignore[return]
        return self._inner.normalize(record)


@pytest.fixture
def source() -> _Canned:
    return _Canned()


def test_gg5_normalize_yields_valid_field_drafts(source: _Canned) -> None:
    """SourceContract: all field names emitted by normalize are in the registry."""
    rec = source._make_record()
    for draft in source.normalize(rec):
        assert is_valid_field(draft.field)


def test_gg5_normalize_is_idempotent(source: _Canned) -> None:
    """SourceContract: normalize(r) == normalize(r)."""
    rec = source._make_record()
    assert source.normalize(rec) == source.normalize(rec)


def test_gg5_id_is_stable_nonempty(source: _Canned) -> None:
    """SourceContract: id is a non-empty string."""
    assert isinstance(source.id, str) and source.id


@respx.mock
def test_gg5_fetch_returns_raw_records() -> None:
    """SourceContract: fetch(None) yields RawRecord objects."""
    respx.get(_PEOPLE_URL).mock(return_value=httpx.Response(200, json={"connections": [_PERSON]}))
    source = _make_source()
    records = list(source.fetch(None))
    assert all(isinstance(r, RawRecord) for r in records)

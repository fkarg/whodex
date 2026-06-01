"""Tests for GoogleContacts incremental sync via nextSyncToken (P1e-3).

GG3: first fetch → full list, persists nextSyncToken; second fetch uses syncToken.
GG4: expired sync token → retry full sync, no exception, store updated.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from whodex.domain.clock import FixedClock
from whodex.sources.google.contacts import GoogleContacts
from whodex.store.memory import InMemorySyncTokenStore

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_TOKEN = "bearer_tok"
_PEOPLE_URL = "https://people.googleapis.com/v1/people/me/connections"

_PERSON_A = {
    "resourceName": "people/a1",
    "names": [{"displayName": "Alice"}],
    "emailAddresses": [{"value": "alice@example.com"}],
    "metadata": {"sources": [{"updateTime": "2025-12-01T10:00:00Z"}]},
}

_PERSON_B = {
    "resourceName": "people/b2",
    "names": [{"displayName": "Bob"}],
    "emailAddresses": [{"value": "bob@example.com"}],
    "metadata": {"sources": [{"updateTime": "2025-12-02T10:00:00Z"}]},
}

_PERSON_C = {
    "resourceName": "people/c3",
    "names": [{"displayName": "Charlie"}],
    "emailAddresses": [{"value": "charlie@example.com"}],
    "metadata": {"sources": [{"updateTime": "2026-01-10T08:00:00Z"}]},
}


def _make_source(store: InMemorySyncTokenStore) -> GoogleContacts:
    return GoogleContacts(
        httpx.Client(),
        token=lambda: _TOKEN,
        clock=FixedClock(_FIXED_NOW),
        sync_token_store=store,
    )


# ---------------------------------------------------------------------------
# GG3: incremental sync — two fetches
# ---------------------------------------------------------------------------


@respx.mock
def test_gg3_first_fetch_is_full_and_persists_sync_token() -> None:
    """First fetch (empty store) → full list, persists nextSyncToken='T1'."""
    store = InMemorySyncTokenStore()
    source = _make_source(store)

    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "connections": [_PERSON_A, _PERSON_B],
                "nextSyncToken": "T1",
            },
        )
    )

    records = list(source.fetch(None))

    assert len(records) == 2
    resource_names = {r.identity["google_resource"] for r in records}
    assert resource_names == {"people/a1", "people/b2"}
    # Token must be persisted after successful fetch
    assert store.get("google_contacts") == "T1"


@respx.mock
def test_gg3_second_fetch_sends_sync_token_and_yields_only_changed() -> None:
    """Second fetch sends syncToken=T1; mock returns only one changed contact + T2."""
    store = InMemorySyncTokenStore()
    store.set("google_contacts", "T1")
    source = _make_source(store)

    route = respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "connections": [_PERSON_C],
                "nextSyncToken": "T2",
            },
        )
    )

    records = list(source.fetch(None))

    # Only the changed contact is yielded
    assert len(records) == 1
    assert records[0].identity["google_resource"] == "people/c3"

    # syncToken was sent in the request
    sent_params = route.calls[0].request.url.params
    assert sent_params.get("syncToken") == "T1"

    # Store updated to T2
    assert store.get("google_contacts") == "T2"


@respx.mock
def test_gg3_incremental_request_also_sends_request_sync_token_true() -> None:
    """requestSyncToken=true is sent even during incremental requests."""
    store = InMemorySyncTokenStore()
    store.set("google_contacts", "T1")
    source = _make_source(store)

    route = respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"connections": [_PERSON_C], "nextSyncToken": "T2"},
        )
    )

    list(source.fetch(None))

    sent_params = route.calls[0].request.url.params
    assert sent_params.get("requestSyncToken") == "true"


@respx.mock
def test_gg3_deleted_contacts_are_skipped() -> None:
    """Contacts with metadata.deleted==true are not emitted as RawRecords."""
    store = InMemorySyncTokenStore()
    store.set("google_contacts", "T1")
    source = _make_source(store)

    deleted_person = {
        "resourceName": "people/deleted1",
        "metadata": {"deleted": True, "sources": []},
    }

    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "connections": [_PERSON_C, deleted_person],
                "nextSyncToken": "T2",
            },
        )
    )

    records = list(source.fetch(None))

    # Only non-deleted contact is returned
    assert len(records) == 1
    assert records[0].identity["google_resource"] == "people/c3"


# ---------------------------------------------------------------------------
# GG4: expired sync token recovery
# ---------------------------------------------------------------------------


@respx.mock
def test_gg4_expired_token_triggers_full_sync_and_no_exception() -> None:
    """Store has T1; 400/FAILED_PRECONDITION → clear + retry full sync → T3 stored."""
    store = InMemorySyncTokenStore()
    store.set("google_contacts", "T1")
    source = _make_source(store)

    _EXPIRED_BODY = {
        "error": {
            "code": 400,
            "message": "Sync token is expired. Clear local cache and retry.",
            "status": "FAILED_PRECONDITION",
            "details": [{"reason": "EXPIRED_SYNC_TOKEN"}],
        }
    }

    call_count = 0

    def _side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if "syncToken" in request.url.params:
            # First call: expired token → 400
            return httpx.Response(400, json=_EXPIRED_BODY)
        else:
            # Second call: full sync → success
            return httpx.Response(
                200,
                json={
                    "connections": [_PERSON_A, _PERSON_B],
                    "nextSyncToken": "T3",
                },
            )

    respx.get(_PEOPLE_URL).mock(side_effect=_side_effect)

    # Must NOT raise
    records = list(source.fetch(None))

    assert len(records) == 2
    resource_names = {r.identity["google_resource"] for r in records}
    assert resource_names == {"people/a1", "people/b2"}

    # After successful full sync, store has T3
    assert store.get("google_contacts") == "T3"

    # Two HTTP calls were made (one expired, one full retry)
    assert call_count == 2


@respx.mock
def test_gg4_expired_token_matched_on_status_field() -> None:
    """Expired recovery also works when error.status == 'FAILED_PRECONDITION'."""
    store = InMemorySyncTokenStore()
    store.set("google_contacts", "STALE")
    source = _make_source(store)

    _EXPIRED_BODY = {
        "error": {
            "code": 400,
            "message": "sync token expired",
            "status": "FAILED_PRECONDITION",
        }
    }

    def _side_effect(request: httpx.Request) -> httpx.Response:
        if "syncToken" in request.url.params:
            return httpx.Response(400, json=_EXPIRED_BODY)
        return httpx.Response(
            200,
            json={"connections": [_PERSON_A], "nextSyncToken": "NEW"},
        )

    respx.get(_PEOPLE_URL).mock(side_effect=_side_effect)

    records = list(source.fetch(None))
    assert len(records) == 1
    assert store.get("google_contacts") == "NEW"


@respx.mock
def test_gg4_expired_token_matched_on_body_substring() -> None:
    """Expired recovery works when 'EXPIRED_SYNC_TOKEN' appears in JSON body."""
    store = InMemorySyncTokenStore()
    store.set("google_contacts", "STALE2")
    source = _make_source(store)

    # Status is NOT FAILED_PRECONDITION but body contains EXPIRED_SYNC_TOKEN
    _EXPIRED_BODY = {
        "error": {
            "code": 400,
            "message": "EXPIRED_SYNC_TOKEN: token has expired",
            "status": "INVALID_ARGUMENT",
        }
    }

    def _side_effect(request: httpx.Request) -> httpx.Response:
        if "syncToken" in request.url.params:
            return httpx.Response(400, json=_EXPIRED_BODY)
        return httpx.Response(
            200,
            json={"connections": [_PERSON_B], "nextSyncToken": "NEW2"},
        )

    respx.get(_PEOPLE_URL).mock(side_effect=_side_effect)

    records = list(source.fetch(None))
    assert len(records) == 1
    assert store.get("google_contacts") == "NEW2"


@respx.mock
def test_gg4_non_expired_400_still_raises() -> None:
    """A 400 that is NOT an expired-token error must still raise HTTPStatusError."""
    store = InMemorySyncTokenStore()
    store.set("google_contacts", "T1")
    source = _make_source(store)

    _OTHER_ERROR = {
        "error": {
            "code": 400,
            "message": "Invalid request.",
            "status": "INVALID_ARGUMENT",
        }
    }

    respx.get(_PEOPLE_URL).mock(return_value=httpx.Response(400, json=_OTHER_ERROR))

    with pytest.raises(httpx.HTTPStatusError):
        list(source.fetch(None))


# ---------------------------------------------------------------------------
# GG: no-store mode (backward compat)
# ---------------------------------------------------------------------------


@respx.mock
def test_no_sync_token_store_behaves_as_full_sync() -> None:
    """When sync_token_store=None, fetch behaves exactly as before (always full)."""
    source = GoogleContacts(
        httpx.Client(),
        token=lambda: _TOKEN,
        clock=FixedClock(_FIXED_NOW),
        # No sync_token_store passed
    )

    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"connections": [_PERSON_A], "nextSyncToken": "T99"},
        )
    )

    records = list(source.fetch(None))
    assert len(records) == 1
    assert records[0].identity["google_resource"] == "people/a1"

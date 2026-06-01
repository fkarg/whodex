"""Google Contacts PULL source via People API (P1e-2/P1e-3).

Fetches contacts from the Google People API using an injected ``httpx.Client``
and a token factory callable — no google-auth dependency in this module.
HTTP calls are paginated automatically.  When a ``SyncTokenStore`` is provided,
incremental sync via ``syncToken`` is used; on FAILED_PRECONDITION / expired
token, the store is cleared and a full sync is retried automatically.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, Protocol

import httpx

from whodex.domain.clock import Clock
from whodex.domain.enums import Capability
from whodex.domain.events import ObservationDraft, RawRecord
from whodex.sources.base import FieldMap, FieldSpec, apply_map

__all__ = ["GoogleContacts", "SyncTokenStore"]


class SyncTokenStore(Protocol):
    """Minimal KV interface for sync-token persistence (structural subtyping).

    Any concrete store whose ``get``/``set``/``clear`` match this signature
    is accepted — no import from ``whodex.store`` required.
    """

    def get(self, source_id: str) -> str | None: ...

    def set(self, source_id: str, token: str) -> None: ...

    def clear(self, source_id: str) -> None: ...


_PEOPLE_URL = "https://people.googleapis.com/v1/people/me/connections"
_PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations,metadata"

_FIELD_MAP: list[FieldMap] = [
    FieldMap("names.0.displayName", "name.full"),
    FieldMap("emailAddresses.0.value", "email", transform=str.lower),
    FieldMap("phoneNumbers.0.value", "phone"),
    FieldMap("organizations.0.title", "job.title"),
    FieldMap("organizations.0.name", "job.org"),
]


def _parse_update_time(person: dict[str, Any]) -> datetime | None:
    """Return the most recent updateTime from person.metadata.sources, or None."""
    sources: list[dict[str, Any]] = person.get("metadata", {}).get("sources") or []
    for src in sources:
        raw = src.get("updateTime")
        if raw:
            try:
                # RFC 3339 / ISO 8601 with Z suffix
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def _is_expired_sync_token_error(resp: httpx.Response) -> bool:
    """Return True iff the response indicates an expired sync token.

    People API returns HTTP 400 with:
      - ``error.status == "FAILED_PRECONDITION"``   (primary matcher), OR
      - ``"EXPIRED_SYNC_TOKEN"`` substring in the JSON body (fallback).
    """
    if resp.status_code != 400:
        return False
    try:
        body_text = resp.text
        body: dict[str, Any] = json.loads(body_text)
        error: dict[str, Any] = body.get("error", {})
        if error.get("status") == "FAILED_PRECONDITION":
            return True
        if "EXPIRED_SYNC_TOKEN" in body_text:
            return True
    except (ValueError, KeyError):
        pass
    return False


def _is_deleted(person: dict[str, Any]) -> bool:
    """Return True when the People API marks the contact as deleted."""
    return bool(person.get("metadata", {}).get("deleted"))


class GoogleContacts:
    """Pull source backed by the Google People API.

    Parameters
    ----------
    http:
        An ``httpx.Client`` instance (injected for testability).
    token:
        Zero-argument callable that returns a fresh OAuth2 access-token string.
    clock:
        Injected clock; used as the fallback ``observed_at`` when no
        ``updateTime`` is present in the People API response.
    page_size:
        Number of connections requested per API call (default 200).
    sync_token_store:
        Optional store for persisting ``nextSyncToken`` across fetches.
        When ``None`` (default) the source always performs a full sync.
    source_id:
        Key used to look up and persist the sync token (default
        ``"google_contacts"``).
    """

    id: str = "google_contacts"
    capabilities: Capability = Capability.PULL
    identity_keys: tuple[str, ...] = ("google_resource", "email")
    provides: tuple[FieldSpec, ...] = (
        FieldSpec(canonical="job.title", freshness_ttl_days=90),
        FieldSpec(canonical="email", freshness_ttl_days=365),
    )

    def __init__(
        self,
        http: httpx.Client,
        token: Callable[[], str],
        *,
        clock: Clock,
        page_size: int = 200,
        sync_token_store: SyncTokenStore | None = None,
        source_id: str = "google_contacts",
    ) -> None:
        self._http = http
        self._token = token
        self._clock = clock
        self._page_size = page_size
        self._sync_token_store = sync_token_store
        self._source_id = source_id

    # ------------------------------------------------------------------
    # PullSource.fetch
    # ------------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterable[RawRecord]:  # noqa: ARG002
        """Yield one RawRecord per (non-deleted) Google contact.

        When a ``sync_token_store`` is provided and a stored token exists,
        sends ``syncToken=<token>`` for incremental sync.  On success the
        final page's ``nextSyncToken`` is persisted.

        If the API returns HTTP 400 indicating an expired sync token
        (``error.status == "FAILED_PRECONDITION"`` or ``"EXPIRED_SYNC_TOKEN"``
        in the body), the token is cleared and a full sync is retried
        automatically — no exception is raised.
        """
        stored_token: str | None = None
        if self._sync_token_store is not None:
            stored_token = self._sync_token_store.get(self._source_id)

        result = self._do_fetch(stored_token)

        if result is None:
            # Expired token path: clear and retry full sync
            assert self._sync_token_store is not None
            self._sync_token_store.clear(self._source_id)
            result = self._do_fetch(sync_token=None)
            assert result is not None  # full sync never returns None

        connections, next_sync_token = result

        if self._sync_token_store is not None and next_sync_token:
            self._sync_token_store.set(self._source_id, next_sync_token)

        for person in connections:
            if _is_deleted(person):
                continue

            resource_name: str = person.get("resourceName", "")
            identity: dict[str, str] = {"google_resource": resource_name}

            email_entries: list[dict[str, Any]] = person.get("emailAddresses") or []
            if email_entries:
                first_email = email_entries[0].get("value", "")
                if first_email:
                    identity["email"] = first_email.lower()

            observed_at = _parse_update_time(person) or self._clock.now()

            yield RawRecord(
                source="google_contacts",
                identity=identity,
                payload=person,
                observed_at=observed_at,
            )

    def _do_fetch(
        self,
        sync_token: str | None,
    ) -> tuple[list[dict[str, Any]], str | None] | None:
        """Execute one paginated fetch pass.

        Returns ``(connections, nextSyncToken)`` on success, or ``None``
        when the *first* request indicates an expired sync token
        (HTTP 400 / FAILED_PRECONDITION).

        Raises ``httpx.HTTPStatusError`` for any other non-2xx response.
        """
        params: dict[str, Any] = {
            "personFields": _PERSON_FIELDS,
            "pageSize": self._page_size,
            "requestSyncToken": "true",
        }
        if sync_token is not None:
            params["syncToken"] = sync_token

        connections: list[dict[str, Any]] = []
        next_sync_token: str | None = None

        while True:
            resp = self._http.get(
                _PEOPLE_URL,
                params=params,
                headers={"Authorization": f"Bearer {self._token()}"},
            )

            # Check for expired sync token on the very first page only
            if (
                resp.status_code == 400
                and sync_token is not None
                and not connections
                and _is_expired_sync_token_error(resp)
            ):
                return None
            resp.raise_for_status()

            body: dict[str, Any] = resp.json()
            page_connections: list[dict[str, Any]] = body.get("connections") or []
            connections.extend(page_connections)
            next_sync_token = body.get("nextSyncToken")

            next_page_token = body.get("nextPageToken")
            if not next_page_token:
                break
            params = {**params, "pageToken": next_page_token}

        return connections, next_sync_token

    # ------------------------------------------------------------------
    # Source.normalize
    # ------------------------------------------------------------------

    def normalize(self, record: RawRecord) -> list[ObservationDraft]:
        """Map People API payload to canonical ObservationDrafts."""
        return apply_map(record, _FIELD_MAP)

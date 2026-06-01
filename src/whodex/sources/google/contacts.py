"""Google Contacts PULL source via People API (P1e-2).

Fetches contacts from the Google People API using an injected ``httpx.Client``
and a token factory callable — no google-auth dependency in this module.
HTTP calls are paginated automatically; sync-token persistence is deferred to
P1e-3.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

import httpx

from whodex.domain.clock import Clock
from whodex.domain.enums import Capability
from whodex.domain.events import ObservationDraft, RawRecord
from whodex.sources.base import FieldMap, FieldSpec, apply_map

__all__ = ["GoogleContacts"]

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
    ) -> None:
        self._http = http
        self._token = token
        self._clock = clock
        self._page_size = page_size

    # ------------------------------------------------------------------
    # PullSource.fetch
    # ------------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterable[RawRecord]:  # noqa: ARG002
        """Yield one RawRecord per Google contact.

        Follows ``nextPageToken`` until exhausted.  The ``since`` parameter is
        accepted for interface compatibility; incremental sync via
        ``syncToken`` is implemented in P1e-3.
        """
        params: dict[str, Any] = {
            "personFields": _PERSON_FIELDS,
            "pageSize": self._page_size,
            "requestSyncToken": "true",
        }
        connections: list[dict[str, Any]] = []

        while True:
            resp = self._http.get(
                _PEOPLE_URL,
                params=params,
                headers={"Authorization": f"Bearer {self._token()}"},
            )
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

            page_connections: list[dict[str, Any]] = body.get("connections") or []
            connections.extend(page_connections)

            next_token = body.get("nextPageToken")
            if not next_token:
                break
            params = {**params, "pageToken": next_token}

        for person in connections:
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

    # ------------------------------------------------------------------
    # Source.normalize
    # ------------------------------------------------------------------

    def normalize(self, record: RawRecord) -> list[ObservationDraft]:
        """Map People API payload to canonical ObservationDrafts."""
        return apply_map(record, _FIELD_MAP)

"""Behavioural tests for the FastAPI ingestion app (P1f-3 / P1f-4).

All assertions go through the HTTP API via FastAPI TestClient.
No internals are accessed directly.

P1f-4: /ingest now requires a valid Bearer token.  The ``client`` fixture
issues a token into the app's TokenStore and stores it in ``client.headers``
so tests don't need to repeat the boilerplate.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.ingestion.app import app_from

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T1_STR = "2026-01-01T00:00:00Z"

JANE_RECORD = {
    "source": "linkedin_ext",
    "identity": {"linkedin_url": "https://www.linkedin.com/in/jane"},
    "payload": {
        "name": "Jane",
        "title": "Eng",
        "company": "Acme",
        "linkedin_url": "https://www.linkedin.com/in/jane",
    },
    "observed_at": T1_STR,
}


@pytest.fixture()
def client() -> TestClient:
    """Build a TestClient backed by a fully in-memory whodex App.

    A token is issued into the app's TokenStore and attached to
    ``client.headers`` so that all requests are pre-authenticated.
    """
    wiring = build_app(clock=FixedClock(T1), ids=SequentialIdFactory())
    api = app_from(wiring)
    plaintext = secrets.token_urlsafe(32)
    wiring.tokens.issue("test", token=plaintext, created_at=datetime.now(UTC))
    tc = TestClient(api)
    tc.headers["Authorization"] = f"Bearer {plaintext}"
    return tc


# ---------------------------------------------------------------------------
# Health check (public — no auth needed)
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Happy path: valid batch → 202, entity resolvable
# ---------------------------------------------------------------------------


def test_post_valid_record_accepted(client: TestClient) -> None:
    resp = client.post("/ingest", json={"records": [JANE_RECORD]})
    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] == 1


def test_post_valid_record_entity_resolvable() -> None:
    """After ingesting a linkedin_ext record, the entity must be resolvable in the entity store."""
    wiring = build_app(clock=FixedClock(T1), ids=SequentialIdFactory())
    api = app_from(wiring)
    plaintext = secrets.token_urlsafe(32)
    wiring.tokens.issue("test", token=plaintext, created_at=datetime.now(UTC))
    tc = TestClient(api)
    tc.headers["Authorization"] = f"Bearer {plaintext}"

    resp = tc.post("/ingest", json={"records": [JANE_RECORD]})
    assert resp.status_code == 202

    # The entity must now be resolvable by the linkedin_url identifier.
    entity_id = wiring.entities.find_by_identifiers(
        [("linkedin_url", "https://www.linkedin.com/in/jane")]
    )
    assert entity_id is not None, "expected entity to be resolvable after ingest"


# ---------------------------------------------------------------------------
# Unknown source → 422
# ---------------------------------------------------------------------------


def test_post_unknown_source_returns_422(client: TestClient) -> None:
    bad_record = {**JANE_RECORD, "source": "nope"}
    resp = client.post("/ingest", json={"records": [bad_record]})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Malformed body (missing required field) → 422
# ---------------------------------------------------------------------------


def test_post_missing_observed_at_returns_422(client: TestClient) -> None:
    malformed = {
        "source": "linkedin_ext",
        "identity": {"linkedin_url": "https://www.linkedin.com/in/bob"},
        "payload": {"name": "Bob"},
        # observed_at intentionally omitted
    }
    resp = client.post("/ingest", json={"records": [malformed]})
    assert resp.status_code == 422

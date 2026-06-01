"""Auth tests for POST /ingest token gating (P1f-4).

All assertions go through the HTTP API via FastAPI TestClient.
No internals are accessed directly — only the public token-store API
(issue, revoke) is used to set up state.
"""

from __future__ import annotations

import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.ingestion.app import app_from

T1 = datetime(2026, 1, 1, tzinfo=UTC)

JANE_RECORD = {
    "source": "linkedin_ext",
    "identity": {"linkedin_url": "https://www.linkedin.com/in/jane-auth"},
    "payload": {
        "name": "Jane Auth",
        "title": "Eng",
        "company": "Acme",
        "linkedin_url": "https://www.linkedin.com/in/jane-auth",
    },
    "observed_at": "2026-01-01T00:00:00Z",
}


@pytest.fixture()
def wiring_and_client():
    """Return (wiring, TestClient) for a fresh in-memory app."""
    wiring = build_app(clock=FixedClock(T1), ids=SequentialIdFactory())
    api = app_from(wiring)
    return wiring, TestClient(api)


# ---------------------------------------------------------------------------
# A2: missing / malformed / revoked token → 401
# ---------------------------------------------------------------------------


def test_no_auth_header_returns_401(wiring_and_client):
    """POST /ingest with no Authorization header must return 401."""
    _, tc = wiring_and_client
    resp = tc.post("/ingest", json={"records": [JANE_RECORD]})
    assert resp.status_code == 401


def test_bearer_garbage_returns_401(wiring_and_client):
    """POST /ingest with a Bearer token that was never issued must return 401."""
    _, tc = wiring_and_client
    resp = tc.post(
        "/ingest",
        json={"records": [JANE_RECORD]},
        headers={"Authorization": "Bearer garbage-token-that-was-never-issued"},
    )
    assert resp.status_code == 401


def test_revoked_token_returns_401(wiring_and_client):
    """POST /ingest with a revoked token must return 401."""
    wiring, tc = wiring_and_client
    plaintext = secrets.token_urlsafe(32)
    token_id = wiring.tokens.issue("test", token=plaintext, created_at=datetime.now(UTC))
    wiring.tokens.revoke(token_id)

    resp = tc.post(
        "/ingest",
        json={"records": [JANE_RECORD]},
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Health is still public (no auth)
# ---------------------------------------------------------------------------


def test_health_requires_no_auth(wiring_and_client):
    """GET /health must remain public (no token needed)."""
    _, tc = wiring_and_client
    resp = tc.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# A6: valid token authenticates /ingest → 202
# ---------------------------------------------------------------------------


def test_valid_token_authenticates_ingest(wiring_and_client):
    """POST /ingest with a valid token issued via the app's TokenStore → 202."""
    wiring, tc = wiring_and_client
    plaintext = secrets.token_urlsafe(32)
    wiring.tokens.issue("ci", token=plaintext, created_at=datetime.now(UTC))

    resp = tc.post(
        "/ingest",
        json={"records": [JANE_RECORD]},
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 202
    assert resp.json()["accepted"] == 1


# ---------------------------------------------------------------------------
# A4: idempotency — same linkedin_ext record twice → no duplicate entity
# ---------------------------------------------------------------------------


def test_idempotent_ingest_no_duplicate_entity():
    """Posting the SAME linkedin_ext record twice over a DURABLE (tmp-file db) app
    must not create a duplicate person entity.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        wiring = build_app(db=db_path, clock=FixedClock(T1), ids=SequentialIdFactory())
        api = app_from(wiring)

        plaintext = secrets.token_urlsafe(32)
        wiring.tokens.issue("idempotency-test", token=plaintext, created_at=datetime.now(UTC))
        headers = {"Authorization": f"Bearer {plaintext}"}

        tc = TestClient(api)

        resp1 = tc.post("/ingest", json={"records": [JANE_RECORD]}, headers=headers)
        assert resp1.status_code == 202

        resp2 = tc.post("/ingest", json={"records": [JANE_RECORD]}, headers=headers)
        assert resp2.status_code == 202

        # Count person entities — must be exactly 1
        kinds = wiring.entities.kinds()
        from whodex.domain.enums import EntityKind

        person_count = sum(1 for k in kinds.values() if k == EntityKind.person)
        assert person_count == 1, f"Expected 1 person entity, got {person_count}"

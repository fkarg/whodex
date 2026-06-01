"""Phase-1f end-to-end ingestion-API invariants (P1f-5).

All assertions go through the HTTP API via FastAPI TestClient backed by a
DURABLE (tmp-file SQLite) whodex App.  No internals are accessed directly;
only public store interfaces (tokens, entities) are used to set up state and
assert observable outcomes.

Invariants
----------
A1  Valid token + valid record → 202; entity resolvable via find_by_identifiers.
A4  Idempotent: same record twice → 202 both; person-entity count unchanged (no duplicate).
A2  Missing or garbage Authorization header → 401.
A3  Unknown source with valid token → 422.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from whodex.config.settings import build_app
from whodex.domain.enums import EntityKind
from whodex.ingestion.app import app_from

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

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
def durable_app(tmp_path: Path):
    """Return (app_cfg, plaintext_token, TestClient) backed by a tmp-file SQLite db."""
    db = tmp_path / "whodex.db"
    app_cfg = build_app(db=db)
    plaintext = secrets.token_urlsafe(32)
    app_cfg.tokens.issue("e2e-test", token=plaintext, created_at=datetime.now(UTC))
    api = app_from(app_cfg)
    client = TestClient(api)
    return app_cfg, plaintext, client


# ---------------------------------------------------------------------------
# A1: valid token + valid record → 202; entity must be resolvable
# ---------------------------------------------------------------------------


def test_a1_valid_ingest_accepted_and_entity_resolvable(durable_app) -> None:
    """A1: POST a linkedin_ext record with a valid token → 202;
    entity must be resolvable by find_by_identifiers immediately after."""
    app_cfg, plaintext, client = durable_app

    resp = client.post(
        "/ingest",
        json={"records": [JANE_RECORD]},
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"

    entity_id = app_cfg.entities.find_by_identifiers(
        [("linkedin_url", "https://www.linkedin.com/in/jane")]
    )
    assert entity_id is not None, (
        "A1 FAIL: entity not resolvable by linkedin_url after ingest via durable app"
    )


# ---------------------------------------------------------------------------
# A4: idempotent — same record twice, no duplicate entity
# ---------------------------------------------------------------------------


def test_a4_idempotent_no_duplicate_entity(durable_app) -> None:
    """A4: POST the same record twice with a valid token → 202 both;
    person-entity count must be exactly 1 (no duplicate)."""
    app_cfg, plaintext, client = durable_app
    headers = {"Authorization": f"Bearer {plaintext}"}

    resp1 = client.post("/ingest", json={"records": [JANE_RECORD]}, headers=headers)
    assert resp1.status_code == 202, f"First ingest failed: {resp1.status_code}: {resp1.text}"

    resp2 = client.post("/ingest", json={"records": [JANE_RECORD]}, headers=headers)
    assert resp2.status_code == 202, f"Second ingest failed: {resp2.status_code}: {resp2.text}"

    kinds = app_cfg.entities.kinds()
    person_count = sum(1 for k in kinds.values() if k == EntityKind.person)
    assert person_count == 1, (
        f"A4 FAIL: expected exactly 1 person entity after duplicate ingest, got {person_count}"
    )


# ---------------------------------------------------------------------------
# A2: missing / garbage Authorization → 401
# ---------------------------------------------------------------------------


def test_a2_no_auth_header_returns_401(durable_app) -> None:
    """A2: POST /ingest with no Authorization header → 401."""
    _, _plaintext, client = durable_app

    resp = client.post("/ingest", json={"records": [JANE_RECORD]})
    assert resp.status_code == 401, (
        f"A2 FAIL (no header): expected 401, got {resp.status_code}: {resp.text}"
    )


def test_a2_garbage_bearer_returns_401(durable_app) -> None:
    """A2: POST /ingest with a Bearer token that was never issued → 401."""
    _, _plaintext, client = durable_app

    resp = client.post(
        "/ingest",
        json={"records": [JANE_RECORD]},
        headers={"Authorization": "Bearer garbage-token-never-issued"},
    )
    assert resp.status_code == 401, (
        f"A2 FAIL (garbage bearer): expected 401, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# A3: unknown source with valid token → 422
# ---------------------------------------------------------------------------


def test_a3_unknown_source_returns_422(durable_app) -> None:
    """A3: POST /ingest with an unknown source key → 422."""
    _, plaintext, client = durable_app

    bad_record = {**JANE_RECORD, "source": "nope"}
    resp = client.post(
        "/ingest",
        json={"records": [bad_record]},
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 422, (
        f"A3 FAIL: expected 422 for unknown source, got {resp.status_code}: {resp.text}"
    )

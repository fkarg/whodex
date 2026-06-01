"""Phase-1e end-to-end acceptance invariants (P1e-4).

Tests are fully mocked (respx) — no live network calls are made.

Invariants
----------
E1  GoogleContacts data flows through run_sync:
    a respx-mocked connections.list response produces a person entity
    resolvable by (email, "ada@acme.com"), and the projected job.title
    equals "Engineer" (as returned by the Google mock).

E2  Trust precedence — Google LOSES to Obsidian:
    when BOTH sources observe the same person (same email), the projected
    winner for job.title is "Founder" (Obsidian, trust=80), NOT "Engineer"
    (google_contacts, trust=60).  Google's observation is still recorded but
    does not win the projection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.sources.google.contacts import GoogleContacts
from whodex.sources.obsidian import ObsidianSource
from whodex.sync.engine import run_sync

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 1, tzinfo=UTC)
_PEOPLE_URL = "https://people.googleapis.com/v1/people/me/connections"

# The Google API response for Ada: email ada@acme.com, job.title "Engineer"
_ADA_GOOGLE = {
    "resourceName": "people/c1",
    "names": [{"displayName": "Ada"}],
    "emailAddresses": [{"value": "ada@acme.com"}],
    "organizations": [{"title": "Engineer", "name": "Acme"}],
    "metadata": {"sources": [{"updateTime": "2026-01-10T09:00:00Z"}]},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _google_source(sync_token_store: object) -> GoogleContacts:
    """Build a GoogleContacts source with a fake token and the given token store."""
    return GoogleContacts(
        http=httpx.Client(),
        token=lambda: "fake-bearer-token",
        clock=FixedClock(_NOW),
        sync_token_store=sync_token_store,  # type: ignore[arg-type]
    )


def _obsidian_vault_with_ada(tmp_path: Path, job_title: str, email: str) -> Path:
    """Create a minimal Obsidian vault with a single People note for Ada."""
    vault = tmp_path / "vault"
    (vault / "People").mkdir(parents=True)
    note = vault / "People" / "Ada Tester.md"
    note.write_text(
        "---\n"
        "type: Person\n"
        "tags:\n"
        "  - Person\n"
        f"job_title: {job_title}\n"
        "emails:\n"
        f"  - {email}\n"
        "---\n\n"
        "## Notes\n"
        "- Test fixture for P1e-4 trust precedence.\n"
    )
    return vault


# ---------------------------------------------------------------------------
# Invariant E1 — Google data flows through run_sync
# ---------------------------------------------------------------------------


@respx.mock
def test_e1_google_data_flows_through_run_sync(tmp_path: Path) -> None:
    """E1: A respx-mocked Google Contacts response flows through run_sync.

    After sync:
    - A person entity must be resolvable via (email, ada@acme.com).
    - The projected job.title must equal "Engineer" (the value from Google).
    """
    app = build_app()  # no google_env: we wire the source manually below

    # Mock the Google People API to return one contact
    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "connections": [_ADA_GOOGLE],
                "nextSyncToken": "T1",
            },
        )
    )

    google_source = _google_source(app.sync_tokens)

    run_sync(
        [google_source],
        ledger=app.ledger,
        projection=app.projection,
        hub=app.hub,
        trust=app.trust,
        now=_NOW,
        entities=app.entities,
        derived_store=app.derived,
    )

    # E1a: entity is resolvable by email
    entity_id = app.entities.find_by_identifiers([("email", "ada@acme.com")])
    assert entity_id is not None, (
        "E1 FAIL: no person entity found for (email, ada@acme.com) after Google sync"
    )

    # E1b: projected job.title is "Engineer"
    states = app.projection.load()
    assert entity_id in states, f"E1 FAIL: entity {entity_id} missing from projection"
    state = states[entity_id]
    job_title_fv = state.fields.get("job.title")
    assert job_title_fv is not None, "E1 FAIL: job.title not in projected fields"
    assert job_title_fv.value == "Engineer", (
        f"E1 FAIL: expected projected job.title='Engineer', got {job_title_fv.value!r}"
    )
    assert job_title_fv.source_kind == "google_contacts", (
        f"E1 FAIL: expected source_kind='google_contacts', got {job_title_fv.source_kind!r}"
    )


# ---------------------------------------------------------------------------
# Invariant E2 — Trust precedence: Obsidian (80) beats Google (60)
# ---------------------------------------------------------------------------


@respx.mock
def test_e2_obsidian_beats_google_by_trust(tmp_path: Path) -> None:
    """E2: When both Obsidian (trust=80) and Google (trust=60) observe the same
    person and field, the Obsidian value wins in projection.

    Ada is in both sources with email ada@acme.com:
    - Google says job.title = "Engineer"
    - Obsidian note says job_title = "Founder"

    After run_sync over both sources, the projected winner must be "Founder".
    """
    # Build a vault with Ada having job_title "Founder"
    vault = _obsidian_vault_with_ada(tmp_path, job_title="Founder", email="ada@acme.com")
    app = build_app(vault=vault)

    # Mock the Google People API to return Ada with job.title "Engineer"
    respx.get(_PEOPLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "connections": [_ADA_GOOGLE],
                "nextSyncToken": "T1",
            },
        )
    )

    obsidian_source = ObsidianSource(vault, state_store=app.vault_state_store)
    google_source = _google_source(app.sync_tokens)

    # Run sync over BOTH sources: obsidian first, then google
    run_sync(
        [obsidian_source, google_source],
        ledger=app.ledger,
        projection=app.projection,
        hub=app.hub,
        trust=app.trust,
        now=_NOW,
        entities=app.entities,
        derived_store=app.derived,
    )

    # E2a: entity must be resolvable (identity merged via shared email)
    entity_id = app.entities.find_by_identifiers([("email", "ada@acme.com")])
    assert entity_id is not None, (
        "E2 FAIL: no person entity found for (email, ada@acme.com) after combined sync"
    )

    # E2b: projected job.title winner is Obsidian's "Founder" (trust 80 > 60)
    states = app.projection.load()
    assert entity_id in states, f"E2 FAIL: entity {entity_id} missing from projection"
    state = states[entity_id]
    job_title_fv = state.fields.get("job.title")
    assert job_title_fv is not None, "E2 FAIL: job.title not in projected fields"
    assert job_title_fv.value == "Founder", (
        f"E2 FAIL: expected projected job.title='Founder' (Obsidian wins), "
        f"got {job_title_fv.value!r} from source {job_title_fv.source_kind!r}. "
        "Obsidian (trust=80) must beat Google (trust=60)."
    )
    assert job_title_fv.source_kind == "obsidian", (
        f"E2 FAIL: expected source_kind='obsidian', got {job_title_fv.source_kind!r}. "
        "Google must NOT win over Obsidian."
    )

    # E2c: Google's "Engineer" is recorded but did NOT win — verify Google obs was ingested
    # (by checking that there are conflict suggestions or simply that Google data was seen)
    events = app.ledger.read_events()
    google_obs = [o for o in events.observations if o.source_kind == "google_contacts"]
    assert len(google_obs) > 0, (
        "E2 FAIL: no google_contacts observations in ledger — Google data was not ingested at all"
    )
    # The Google job.title observation exists but lost: verify it recorded "Engineer"
    google_job_obs = [o for o in google_obs if o.field == "job.title"]
    assert len(google_job_obs) > 0, (
        "E2 FAIL: no google_contacts job.title observation found in ledger"
    )
    assert google_job_obs[0].value == "Engineer", (
        f"E2 FAIL: Google job.title observation value should be 'Engineer', "
        f"got {google_job_obs[0].value!r}"
    )

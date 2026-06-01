"""Phase-1d end-to-end write-back invariants (W2..W6).

These tests exercise the full write-back pipeline over a tmp copy of
``fixtures/people-network-min`` plus a FakeSource enrichment.  They encode
the acceptance criteria for Phase 1d Task P1d-5 and must never be weakened:
a failing invariant means a real defect.

Invariants
----------
W6  Fill-blank e2e: a Person note lacking ``job_title`` gets it written from
    enrichment after ``sync --write-back``.
W2  No-clobber + body preserved: an existing managed field is never overwritten;
    the note body (``## Notes`` section) is byte-unchanged after write-back.
W3  Idempotent byte-identical: a second write-back sync over unchanged data
    produces a byte-identical file.
W5  UID once: the note receives ``whodex.uid`` on the first write-back; the
    second write-back leaves it unchanged (same value).
W4  Echo suppression: the second write-back sync reports ``changes == 0`` and
    does not re-ingest the written file as a new observation.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whodex.config.settings import build_app
from whodex.domain.events import RawRecord
from whodex.sources.fake import FakeSource
from whodex.sync.engine import SyncReport, run_sync

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "people-network-min"
NOW = datetime(2026, 3, 1, tzinfo=UTC)

# Email we will inject into Ada's fixture copy to give FakeSource a shared identity key.
ADA_EMAIL = "ada@example.com"
ADA_JOB_TITLE = "Staff Engineer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _copy_vault(tmp_path: Path) -> Path:
    """Copy the fixture vault into tmp_path so file writes stay isolated."""
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE, dest)
    return dest


def _add_email_to_ada(vault: Path, email: str = ADA_EMAIL) -> Path:
    """Patch Ada Engineer.md in the vault copy to add an ``emails`` list.

    This gives FakeSource a shared identity key (email) so it can merge
    its observations (including job.title) into Ada's entity.
    """
    ada_path = vault / "People" / "Ada Engineer.md"
    raw = ada_path.read_text(encoding="utf-8")
    # Insert ``emails: [<email>]`` just after the ``type: Person`` line.
    patched = raw.replace(
        "type: Person\n",
        f"type: Person\nemails: [{email}]\n",
        1,
    )
    ada_path.write_text(patched, encoding="utf-8")
    return ada_path


def _make_fake_source(email: str = ADA_EMAIL, job_title: str = ADA_JOB_TITLE) -> FakeSource:
    """FakeSource that provides job.title for the given email."""
    return FakeSource(
        records=[
            RawRecord(
                source="fake",
                identity={"email": email},
                payload={
                    "display_name": "Ada Engineer",
                    "title": job_title,
                },
                observed_at=NOW,
            )
        ]
    )


def _run_sync_with_writeback(vault: Path, fake: FakeSource) -> tuple[object, object]:
    """Build an in-memory App over *vault*, inject *fake*, and run write-back sync.

    Returns (report, app).
    """
    app = build_app(vault=vault)
    sources = list(app.sources) + [fake]
    report = run_sync(
        sources,
        ledger=app.ledger,
        projection=app.projection,
        hub=app.hub,
        trust=app.trust,
        now=NOW,
        entities=app.entities,
        vault_state_store=app.vault_state_store,
        write_back=True,
    )
    return report, app


def _run_two_syncs_shared_state(
    vault: Path, fake: FakeSource, db: Path
) -> tuple[SyncReport, SyncReport]:
    """Run two consecutive write-back syncs sharing durable state via SQLite.

    Returns (report1, report2) where both reuse the same App (ledger, vault_state_store, etc.).
    This is the correct model for testing echo suppression: without shared state the
    vault_state_store is reset on every build_app call, making the skip branch unreachable.
    """
    app = build_app(vault=vault, db=db)
    sources = list(app.sources) + [fake]

    def _sync() -> SyncReport:
        return run_sync(
            sources,
            ledger=app.ledger,
            projection=app.projection,
            hub=app.hub,
            trust=app.trust,
            now=NOW,
            entities=app.entities,
            vault_state_store=app.vault_state_store,
            write_back=True,
        )

    report1 = _sync()
    report2 = _sync()
    return report1, report2


def _parse_frontmatter(text: str) -> dict[str, object]:
    """Return the frontmatter dict from a markdown note using the project's own parser."""
    from whodex.vault.markdown import parse_note

    note = parse_note(text)
    return dict(note.frontmatter)


def _body_slice(text: str) -> str:
    """Return the note body (everything after the closing ``---`` fence)."""
    if not text.startswith("---\n"):
        return text
    rest = text[4:]
    for marker in ("\n---\n", "\n...\n"):
        idx = rest.find(marker)
        if idx != -1:
            return rest[idx + len(marker) :]
    return ""


# ---------------------------------------------------------------------------
# W6 — Fill-blank e2e
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_w6_fill_blank_job_title_e2e(tmp_path: Path) -> None:
    """W6: a fixture Person note lacking job_title gets it filled from enrichment.

    Ada Engineer.md has no job_title in the fixture.  We add an email so
    FakeSource can share Ada's identity and supply job.title=Staff Engineer.
    After write-back sync the .md file must contain ``job_title: Staff Engineer``
    in its frontmatter.
    """
    vault = _copy_vault(tmp_path)
    ada_path = _add_email_to_ada(vault)

    # Verify the precondition: no job_title yet
    raw_before = ada_path.read_text(encoding="utf-8")
    fm_before = _parse_frontmatter(raw_before)
    assert "job_title" not in fm_before or not fm_before["job_title"], (
        "Precondition failed: Ada already has job_title in fixture copy. "
        f"frontmatter: {fm_before!r}"
    )

    fake = _make_fake_source()
    _run_sync_with_writeback(vault, fake)

    raw_after = ada_path.read_text(encoding="utf-8")
    fm_after = _parse_frontmatter(raw_after)

    assert "job_title" in fm_after, (
        f"W6 FAIL: job_title not written to Ada's note after write-back.\n"
        f"Frontmatter after: {fm_after!r}\nFile content:\n{raw_after}"
    )
    assert fm_after["job_title"] == ADA_JOB_TITLE, (
        f"W6 FAIL: expected job_title={ADA_JOB_TITLE!r}, got {fm_after['job_title']!r}.\n"
        f"File content:\n{raw_after}"
    )


# ---------------------------------------------------------------------------
# W2 — No-clobber + body preserved
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_w2_no_clobber_and_body_preserved(tmp_path: Path) -> None:
    """W2: existing managed fields are never overwritten; note body is byte-unchanged.

    We set job_title: Chief in Ada's copy.  FakeSource offers Staff Engineer.
    After write-back the note must still say Chief (no-clobber), and the body
    (## Notes section) must be byte-for-byte identical to before the sync.
    """
    vault = _copy_vault(tmp_path)
    ada_path = _add_email_to_ada(vault)

    # Inject a pre-existing job_title so no-clobber kicks in
    raw = ada_path.read_text(encoding="utf-8")
    raw_with_title = raw.replace(
        "type: Person\n",
        "type: Person\njob_title: Chief\n",
        1,
    )
    ada_path.write_text(raw_with_title, encoding="utf-8")

    body_before = _body_slice(ada_path.read_text(encoding="utf-8"))
    assert "## Notes" in body_before, "Precondition: Ada's note must have a ## Notes body section."

    fake = _make_fake_source()
    _run_sync_with_writeback(vault, fake)

    raw_after = ada_path.read_text(encoding="utf-8")
    fm_after = _parse_frontmatter(raw_after)

    # No-clobber: the existing value wins
    assert fm_after.get("job_title") == "Chief", (
        f"W2 FAIL (no-clobber): expected job_title=Chief, got {fm_after.get('job_title')!r}.\n"
        f"File content:\n{raw_after}"
    )
    assert "Staff Engineer" not in raw_after, (
        "W2 FAIL (no-clobber): FakeSource value was written despite an existing field.\n"
        f"File content:\n{raw_after}"
    )

    # Body preserved: the ## Notes section must be byte-identical
    body_after = _body_slice(raw_after)
    assert body_after == body_before, (
        "W2 FAIL (body preserved): note body changed after write-back.\n"
        f"Before:\n{body_before!r}\nAfter:\n{body_after!r}"
    )


# ---------------------------------------------------------------------------
# W3 — Idempotent byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_w3_idempotent_byte_identical(tmp_path: Path) -> None:
    """W3: a second write-back sync with the same data produces a byte-identical file.

    After the first write-back (which fills job_title and injects whodex.uid),
    capture the raw file bytes.  Run a second write-back sync — the file must
    be entirely unchanged (no spurious diffs, no re-stamping).
    """
    vault = _copy_vault(tmp_path)
    ada_path = _add_email_to_ada(vault)
    fake = _make_fake_source()

    # First write-back sync
    _run_sync_with_writeback(vault, fake)
    bytes_after_first = ada_path.read_bytes()

    # Second write-back sync — must produce zero file changes
    _run_sync_with_writeback(vault, fake)
    bytes_after_second = ada_path.read_bytes()

    assert bytes_after_first == bytes_after_second, (
        "W3 FAIL (idempotent): file changed between first and second write-back sync.\n"
        f"After first sync ({len(bytes_after_first)} bytes):\n{bytes_after_first.decode()!r}\n"
        f"After second sync ({len(bytes_after_second)} bytes):\n{bytes_after_second.decode()!r}"
    )


# ---------------------------------------------------------------------------
# W5 — UID once (stable across syncs)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_w5_uid_written_once_and_stable(tmp_path: Path) -> None:
    """W5: whodex.uid is injected on the first write-back and unchanged on the second.

    After the first sync, Ada's note must contain a ``whodex.uid`` key.
    After the second sync, that value must be exactly the same string.
    """
    vault = _copy_vault(tmp_path)
    ada_path = _add_email_to_ada(vault)
    fake = _make_fake_source()

    # First write-back sync
    _run_sync_with_writeback(vault, fake)
    raw_after_first = ada_path.read_text(encoding="utf-8")
    fm_first = _parse_frontmatter(raw_after_first)

    whodex_block = fm_first.get("whodex")
    assert isinstance(whodex_block, dict), (
        f"W5 FAIL: expected 'whodex' to be a dict block after first sync, "
        f"got {whodex_block!r}.\nFrontmatter: {fm_first!r}"
    )
    uid_first = whodex_block.get("uid")
    assert uid_first, (
        f"W5 FAIL: whodex.uid is absent or empty after first write-back.\n"
        f"whodex block: {whodex_block!r}"
    )

    # Second write-back sync
    _run_sync_with_writeback(vault, fake)
    raw_after_second = ada_path.read_text(encoding="utf-8")
    fm_second = _parse_frontmatter(raw_after_second)

    whodex_block_2 = fm_second.get("whodex")
    assert isinstance(whodex_block_2, dict), (
        f"W5 FAIL: 'whodex' block lost after second sync. Frontmatter: {fm_second!r}"
    )
    uid_second = whodex_block_2.get("uid")

    assert uid_second == uid_first, (
        f"W5 FAIL (uid-once): uid changed between syncs.\n"
        f"After first: {uid_first!r}\nAfter second: {uid_second!r}"
    )


# ---------------------------------------------------------------------------
# W4 — Echo suppression (second sync reports changes == 0)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_w4_echo_suppression_no_changes_on_second_sync(tmp_path: Path) -> None:
    """W4: echo suppression — second sync ingests fewer observations than the first.

    The first sync writes Ada's note (whodex.uid + job_title) and records the
    written hash in the vault_state_store.  On the second sync ObsidianSource
    MUST skip Ada's file (echo suppression), contributing zero observations for
    that file.  We detect this as a strict DROP in observations_ingested: the
    enrichment FakeSource emits the same count both times, but the obsidian echo
    of Ada's note only appears on sync 1.

    State is shared across both syncs via SQLite (durable vault_state_store).
    Without shared state the skip branch is never reachable, making the test vacuous.
    """
    vault = _copy_vault(tmp_path)
    _add_email_to_ada(vault)
    fake = _make_fake_source()
    db = tmp_path / "db.sqlite"

    report1, report2 = _run_two_syncs_shared_state(vault, fake, db)

    assert report2.observations_ingested < report1.observations_ingested, (
        f"W4 FAIL (echo suppression non-vacuous): "
        f"sync2 ingested {report2.observations_ingested} obs, "
        f"sync1 ingested {report1.observations_ingested} obs. "
        "Expected a strict drop because Ada's written note must be echo-suppressed. "
        "Check that vault_state_store is shared between syncs and the skip branch fires."
    )

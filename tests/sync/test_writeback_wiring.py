"""Behavioral tests for P1d-4: Obsidian write-back wiring + echo suppression (W4).

All tests are behavioral over public interfaces — no internal assertions.

Invariants tested:
- W6 e2e: sync --write-back fills blank frontmatter from projected data
- W4 echo suppression: after write-back, the just-written file is skipped on re-scan
- no-clobber: existing non-empty frontmatter fields are not overwritten
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from pathlib import Path

from whodex.config.settings import App, build_app
from whodex.domain.events import RawRecord
from whodex.sync.engine import SyncReport, run_sync

NOW = datetime(2026, 3, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_note(vault: Path, rel_path: str, content: str) -> Path:
    full = vault / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(textwrap.dedent(content))
    return full


def _sync(
    vault: Path,
    *,
    extra_sources: list[object] | None = None,
    write_back: bool = False,
) -> tuple[SyncReport, App]:
    """Build an in-memory App and run sync. Returns (report, app)."""
    app = build_app(vault=vault)
    sources = list(app.sources)
    if extra_sources:
        sources.extend(extra_sources)  # type: ignore[arg-type]
    report = run_sync(
        sources,
        ledger=app.ledger,
        projection=app.projection,
        hub=app.hub,
        trust=app.trust,
        now=NOW,
        entities=app.entities,
        vault_state_store=app.vault_state_store,
        write_back=write_back,
    )
    return report, app


def _sync_with_app(
    app: App,
    *,
    extra_sources: list[object] | None = None,
    write_back: bool = False,
) -> SyncReport:
    """Run sync reusing an existing App (shares ledger, vault_state_store, etc.)."""
    sources = list(app.sources)
    if extra_sources:
        sources.extend(extra_sources)  # type: ignore[arg-type]
    return run_sync(
        sources,
        ledger=app.ledger,
        projection=app.projection,
        hub=app.hub,
        trust=app.trust,
        now=NOW,
        entities=app.entities,
        vault_state_store=app.vault_state_store,
        write_back=write_back,
    )


# ---------------------------------------------------------------------------
# Test W6 e2e: write-back fills blank job_title from projected data
# ---------------------------------------------------------------------------


def test_writeback_fills_blank_job_title(tmp_path: Path) -> None:
    """W6 e2e: a Person note lacking job_title + a source supplying job.title
    → sync --write-back writes job_title into the note file.
    """
    # A note with NO job_title
    note_path = _write_note(
        vault=tmp_path,
        rel_path="People/Alice.md",
        content="""\
            ---
            type: Person
            emails: [alice@example.com]
            ---
        """,
    )

    # A FakeSource that supplies job.title for alice@example.com
    from whodex.sources.fake import FakeSource

    fake_source = FakeSource(
        records=[
            RawRecord(
                source="fake",
                identity={"email": "alice@example.com"},
                payload={"display_name": "Alice", "title": "Staff Engineer"},
                observed_at=NOW,
            )
        ]
    )

    _sync(tmp_path, extra_sources=[fake_source], write_back=True)

    # Read back the file and verify job_title was written
    updated_content = note_path.read_text()
    assert "job_title" in updated_content, (
        f"Expected job_title to be written to the note, got:\n{updated_content}"
    )
    assert "Staff Engineer" in updated_content, (
        f"Expected 'Staff Engineer' in note content, got:\n{updated_content}"
    )


# ---------------------------------------------------------------------------
# Test W4 echo suppression: re-sync skips written file
# ---------------------------------------------------------------------------


def test_echo_suppression_after_writeback(tmp_path: Path) -> None:
    """W4: after write-back sync, running sync again skips the just-written file.

    Both syncs share the SAME App (ledger + vault_state_store) so that the hash
    recorded by write_back on sync 1 is visible to ObsidianSource.fetch on sync 2.
    Without shared state the vault_state_store is reset on every build_app call,
    making the skip branch unreachable and the test vacuous.

    Assertion: sync2 ingests strictly fewer observations than sync1, because
    Bob's written note is echo-suppressed (skipped) on the second pass while the
    FakeSource record count is the same both times.
    """
    _write_note(
        vault=tmp_path,
        rel_path="People/Bob.md",
        content="""\
            ---
            type: Person
            emails: [bob@example.com]
            ---
        """,
    )

    from whodex.sources.fake import FakeSource

    fake_source = FakeSource(
        records=[
            RawRecord(
                source="fake",
                identity={"email": "bob@example.com"},
                payload={"display_name": "Bob Smith", "title": "Engineer"},
                observed_at=NOW,
            )
        ]
    )

    # Build ONE app that is reused across both syncs (shared state).
    app = build_app(vault=tmp_path)

    # First sync with write-back — writes Bob.md, records hash in vault_state_store.
    report1 = _sync_with_app(app, extra_sources=[fake_source], write_back=True)
    content_after_first = (tmp_path / "People/Bob.md").read_text()

    # Second sync — Bob.md hash matches last_written_hash → echo-suppressed.
    report2 = _sync_with_app(app, extra_sources=[fake_source], write_back=True)
    content_after_second = (tmp_path / "People/Bob.md").read_text()

    # File must be byte-identical (nothing new to write).
    assert content_after_first == content_after_second, (
        "File changed on second sync — echo suppression failed.\n"
        f"After first sync:\n{content_after_first}\n"
        f"After second sync:\n{content_after_second}"
    )

    # Strict drop in observations_ingested: Bob's obsidian echo is suppressed.
    assert report2.observations_ingested < report1.observations_ingested, (
        f"W4 FAIL (echo suppression non-vacuous): "
        f"sync2 ingested {report2.observations_ingested} obs, "
        f"sync1 ingested {report1.observations_ingested} obs. "
        "Expected a strict drop because Bob's written note must be echo-suppressed. "
        "The test would pass trivially if vault_state_store were reset between syncs."
    )


# ---------------------------------------------------------------------------
# Test no-clobber: existing non-empty frontmatter is not overwritten
# ---------------------------------------------------------------------------


def test_no_clobber_existing_job_title(tmp_path: Path) -> None:
    """No-clobber: a note with job_title: Boss is NOT changed by write-back."""
    note_path = _write_note(
        vault=tmp_path,
        rel_path="People/Carol.md",
        content="""\
            ---
            type: Person
            emails: [carol@example.com]
            job_title: Boss
            ---
        """,
    )

    from whodex.sources.fake import FakeSource

    fake_source = FakeSource(
        records=[
            RawRecord(
                source="fake",
                identity={"email": "carol@example.com"},
                payload={"display_name": "Carol", "title": "Junior Developer"},
                observed_at=NOW,
            )
        ]
    )

    _sync(tmp_path, extra_sources=[fake_source], write_back=True)

    updated_content = note_path.read_text()

    # The vault's existing value wins — job_title must not be overwritten
    assert "Boss" in updated_content, f"Expected 'Boss' to remain in note, got:\n{updated_content}"
    assert "Junior Developer" not in updated_content, (
        f"Expected source value NOT to overwrite existing job_title, got:\n{updated_content}"
    )

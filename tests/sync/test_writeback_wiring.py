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

from whodex.config.settings import build_app
from whodex.domain.events import RawRecord
from whodex.sync.engine import run_sync

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
    extra_sources=None,
    write_back: bool = False,
) -> tuple[object, object]:
    """Build an in-memory App and run sync. Returns (report, app)."""
    app = build_app(vault=vault)
    sources = list(app.sources)
    if extra_sources:
        sources.extend(extra_sources)
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

    The second sync should see zero observations contributed by the written note
    (it's our own echo), so report.changes == 0 and the file is byte-identical.
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

    # First sync with write-back
    _sync(tmp_path, extra_sources=[fake_source], write_back=True)

    content_after_first = (tmp_path / "People/Bob.md").read_text()

    # Second sync with write-back — the obsidian source should suppress the echo
    report2, _ = _sync(tmp_path, extra_sources=[fake_source], write_back=True)

    content_after_second = (tmp_path / "People/Bob.md").read_text()

    # File must be byte-identical after second sync
    assert content_after_first == content_after_second, (
        "File changed on second sync — echo suppression failed.\n"
        f"After first sync:\n{content_after_first}\n"
        f"After second sync:\n{content_after_second}"
    )

    # No new changes should be reported from the obsidian echo
    assert report2.changes == 0, (
        f"Expected 0 changes on second sync (echo suppressed), got {report2.changes}. "
        "The written file was re-ingested as new data."
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

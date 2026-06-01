"""Tests for ObsidianSource (P1b-7).

Behavioral / invariant tests only — no asserting internals.
"""
from __future__ import annotations

import textwrap
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from whodex.domain.enums import InteractionKind
from whodex.domain.fields import is_valid_field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_note(vault: Path, rel_path: str, content: str) -> Path:
    full = vault / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(textwrap.dedent(content))
    return full


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Minimal vault with one Person note."""
    _write_note(
        vault=tmp_path,
        rel_path="People/Jane Doe.md",
        content="""\
            ---
            type: Person
            aliases: [Jane, JD]
            emails:
              - jane@example.com
              - jane@work.org
            phones:
              - "+49 123 456"
            linkedin: "https://linkedin.com/in/janedoe"
            job_title: "Staff Engineer"
            organisations:
              - "[[Organisations/Acme|Acme]]"
              - "[[Organisations/Beta]]"
            lives: "[[Locations/Frankfurt am Main|Frankfurt]]"
            tags: [engineering, friend]
            source:
              - LinkedIn
              - Email
            last contact: 2026-02-01
            next contact: 2026-06-15
            ---
            ## Notes
            Some body text.
        """,
    )
    return tmp_path


@pytest.fixture
def source(vault: Path):
    from whodex.sources.obsidian import ObsidianSource

    return ObsidianSource(vault_dir=vault)


# ---------------------------------------------------------------------------
# I6: SourceContract — ObsidianSource must pass the shared contract
# ---------------------------------------------------------------------------


def test_normalize_yields_valid_field_drafts(source, vault):
    """All fields emitted by normalize must be in the registry."""
    for r in source.fetch(None):
        for d in source.normalize(r):
            assert is_valid_field(d.field), f"unknown field: {d.field!r}"


def test_normalize_is_idempotent(source, vault):
    r = next(iter(source.fetch(None)))
    assert source.normalize(r) == source.normalize(r)


def test_id_is_stable_nonempty(source):
    assert isinstance(source.id, str) and source.id


# ---------------------------------------------------------------------------
# Behavioral: correct canonical field mapping
# ---------------------------------------------------------------------------


def test_person_note_maps_to_expected_canonical_fields(source, vault):
    """Behavioral: the set of (field, value) produced for the Jane note matches expected."""
    records = list(source.fetch(None))
    assert len(records) == 1, "expected exactly one record from the one-note vault"
    record = records[0]
    drafts = source.normalize(record)

    actual = {(d.field, d.value) for d in drafts}

    # name.full comes from the file stem
    assert ("name.full", "Jane Doe") in actual

    # emails are lowercased, emitted as individual add-ops or single multi values
    # The connector should emit each email; check both are present
    email_values = {v for f, v in actual if f == "email"}
    assert "jane@example.com" in email_values
    assert "jane@work.org" in email_values

    # linkedin.url
    assert ("linkedin.url", "https://linkedin.com/in/janedoe") in actual

    # job.title
    assert ("job.title", "Staff Engineer") in actual

    # tags
    tag_values = {v for f, v in actual if f == "tags"}
    assert "engineering" in tag_values
    assert "friend" in tag_values

    # person.organisations — raw wikilink strings
    org_values = {v for f, v in actual if f == "person.organisations"}
    assert "[[Organisations/Acme|Acme]]" in org_values
    assert "[[Organisations/Beta]]" in org_values

    # person.lives — raw wikilink string
    lives_values = {v for f, v in actual if f == "person.lives"}
    assert "[[Locations/Frankfurt am Main|Frankfurt]]" in lives_values

    # contact.next_at
    next_values = {v for f, v in actual if f == "contact.next_at"}
    assert len(next_values) == 1  # some value present for next contact

    # aliases (if registered)
    alias_values = {v for f, v in actual if f == "aliases"}
    assert "Jane" in alias_values or len(alias_values) == 0  # present if registry supports it


def test_source_channel_list_is_not_an_observation(source, vault):
    """source: [LinkedIn, Email] must produce NO observation with field 'source' or 'channels'."""
    records = list(source.fetch(None))
    assert records
    for record in records:
        for draft in source.normalize(record):
            assert draft.field not in {"source", "channels"}, (
                f"channel metadata leaked as field: {draft.field!r}"
            )


def test_last_contact_becomes_an_interaction(source, vault):
    """last contact: 2026-02-01 → interactions() yields one InteractionDraft at that date."""
    records = list(source.fetch(None))
    assert records
    record = records[0]

    interactions = source.interactions(record)
    assert len(interactions) == 1

    ia = interactions[0]
    assert ia.kind == InteractionKind.note
    assert ia.occurred_at == datetime(2026, 2, 1, tzinfo=UTC)
    assert ia.occurred_at.tzinfo is not None  # must be tz-aware


def test_no_last_contact_yields_no_interaction(tmp_path: Path):
    """A note without 'last contact' → interactions() returns []."""
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
    from whodex.sources.obsidian import ObsidianSource

    src = ObsidianSource(vault_dir=tmp_path)
    records = list(src.fetch(None))
    assert records
    for record in records:
        assert src.interactions(record) == []


def test_skips_dotfiles_and_system_folders(tmp_path: Path):
    """Scanner must skip .obsidian, .whodex, .trash, and dotfiles."""
    _write_note(tmp_path, "People/Jane.md", "---\ntype: Person\n---\n")
    _write_note(tmp_path, ".obsidian/config.md", "---\ntype: Config\n---\n")
    _write_note(tmp_path, ".whodex/state.md", "---\n---\n")
    _write_note(tmp_path, ".trash/Old.md", "---\ntype: Person\n---\n")
    _write_note(tmp_path, "People/.hidden.md", "---\ntype: Person\n---\n")

    from whodex.sources.obsidian import ObsidianSource

    src = ObsidianSource(vault_dir=tmp_path)
    records = list(src.fetch(None))
    # Only the non-hidden People/Jane.md should appear
    assert len(records) == 1

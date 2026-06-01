"""Behavioral CLI tests for `whodex who-at` (G5 invariant)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from whodex.cli.main import app

runner = CliRunner()


def _write_person(vault: Path, name: str, **fm) -> None:
    (vault / "People").mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        "type: Person",
        *(f"{k}: {v}" for k, v in fm.items()),
        "tags: [Person]",
        "---",
        "## Notes",
    ]
    (vault / "People" / f"{name}.md").write_text("\n".join(lines) + "\n")


def _write_org(vault: Path, name: str) -> None:
    (vault / "Organisations").mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        "type: Organisation",
        "tags: [Organisation]",
        "---",
    ]
    (vault / "Organisations" / f"{name}.md").write_text("\n".join(lines) + "\n")


def test_who_at_returns_person_member_of_org(tmp_path: Path) -> None:
    """After sync, who-at <org> should include person who has that org in organisations."""
    vault = tmp_path / "vault"
    db = tmp_path / "whodex.db"

    _write_org(vault, "Acme")
    _write_person(
        vault,
        "Alice Smith",
        organisations='["[[Organisations/Acme|Acme]]"]',
    )

    sync_res = runner.invoke(app, ["sync", "--vault", str(vault), "--db", str(db)])
    assert sync_res.exit_code == 0, sync_res.stdout

    who_res = runner.invoke(
        app, ["who-at", "Organisations/Acme", "--vault", str(vault), "--db", str(db)]
    )
    assert who_res.exit_code == 0, who_res.stdout
    assert "Alice Smith" in who_res.stdout


def test_who_at_no_entity_prints_helpful_message(tmp_path: Path) -> None:
    """who-at with an unknown query exits 0 with a helpful message."""
    vault = tmp_path / "vault"
    db = tmp_path / "whodex.db"
    vault.mkdir(parents=True, exist_ok=True)

    # sync first so DB is initialised
    runner.invoke(app, ["sync", "--vault", str(vault), "--db", str(db)])

    res = runner.invoke(
        app, ["who-at", "Organisations/Nonexistent", "--vault", str(vault), "--db", str(db)]
    )
    assert res.exit_code == 0
    assert "No entity found" in res.stdout or "Nonexistent" in res.stdout


def test_who_at_stem_name_match(tmp_path: Path) -> None:
    """who-at <stem-name> (e.g. 'Acme') resolves via case-insensitive stem match."""
    vault = tmp_path / "vault"
    db = tmp_path / "whodex.db"

    _write_org(vault, "Acme")
    _write_person(
        vault,
        "Bob Jones",
        organisations='["[[Organisations/Acme|Acme]]"]',
    )

    runner.invoke(app, ["sync", "--vault", str(vault), "--db", str(db)])

    res = runner.invoke(app, ["who-at", "Acme", "--vault", str(vault), "--db", str(db)])
    assert res.exit_code == 0, res.stdout
    assert "Bob Jones" in res.stdout


def test_who_at_org_with_no_members_prints_no_people_message(tmp_path: Path) -> None:
    """who-at an org that exists but has no members exits 0 with an appropriate message."""
    vault = tmp_path / "vault"
    db = tmp_path / "whodex.db"

    _write_org(vault, "EmptyCorp")

    runner.invoke(app, ["sync", "--vault", str(vault), "--db", str(db)])

    res = runner.invoke(
        app, ["who-at", "Organisations/EmptyCorp", "--vault", str(vault), "--db", str(db)]
    )
    assert res.exit_code == 0
    # Either "No people found" or the entity resolved but list is empty
    assert "No people found" in res.stdout or res.stdout.strip() == ""

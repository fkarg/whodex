from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from whodex.cli.main import app

runner = CliRunner()


def _write_person(vault: Path, name: str, **fm):
    (vault / "People").mkdir(parents=True, exist_ok=True)
    lines = ["---", "type: Person", *(f"{k}: {v}" for k, v in fm.items()), "tags: [Person]", "---", "## Notes"]
    (vault / "People" / f"{name}.md").write_text("\n".join(lines) + "\n")


def test_sync_ingests_vault_into_durable_db(tmp_path):
    vault, db = tmp_path / "vault", tmp_path / "whodex.db"
    _write_person(vault, "Jane Doe", emails="[jane@acme.com]", job_title="Engineer")
    res = runner.invoke(app, ["sync", "--vault", str(vault), "--db", str(db)])
    assert res.exit_code == 0
    assert db.exists()


def test_queue_lists_real_vault_people(tmp_path):
    vault, db = tmp_path / "vault", tmp_path / "whodex.db"
    _write_person(vault, "Jane Doe", emails="[jane@acme.com]")
    runner.invoke(app, ["sync", "--vault", str(vault), "--db", str(db)])
    res = runner.invoke(app, ["queue", "--vault", str(vault), "--db", str(db)])
    assert res.exit_code == 0
    assert "Jane Doe" in res.stdout

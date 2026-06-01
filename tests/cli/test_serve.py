"""CLI test: whodex serve --once exits 0."""

from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from whodex.cli.main import app

runner = CliRunner()


def test_serve_once_exits_zero() -> None:
    """whodex serve --once --vault <tmp> --db <tmp> exits 0 and prints a report line."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir) / "vault"
        vault.mkdir()
        db = Path(tmpdir) / "whodex.db"

        result = runner.invoke(app, ["serve", "--once", "--vault", str(vault), "--db", str(db)])

        assert result.exit_code == 0, f"serve --once exited {result.exit_code}:\n{result.output}"
        assert "dispatched=" in result.output, (
            f"Expected 'dispatched=' in output, got:\n{result.output}"
        )


def test_serve_once_without_vault_exits_zero() -> None:
    """whodex serve --once (no vault, in-memory) exits 0."""
    result = runner.invoke(app, ["serve", "--once"])

    assert result.exit_code == 0, f"serve --once exited {result.exit_code}:\n{result.output}"
    assert "dispatched=" in result.output, (
        f"Expected 'dispatched=' in output, got:\n{result.output}"
    )

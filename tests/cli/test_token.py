"""CLI tests for `whodex token issue`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from whodex.cli.main import app
from whodex.domain.ids import SequentialIdFactory
from whodex.store.sqlite import SqliteTokenStore

runner = CliRunner()


def test_token_issue_exits_zero_and_prints_token(tmp_path: Path) -> None:
    """whodex token issue --label firefox --db <tmp> exits 0 and prints a non-empty token."""
    db = tmp_path / "whodex.db"
    result = runner.invoke(app, ["token", "issue", "--label", "firefox", "--db", str(db)])
    assert result.exit_code == 0, result.output
    # Output must contain some non-whitespace token text
    assert result.output.strip()


def test_issued_token_validates_against_same_db(tmp_path: Path) -> None:
    """The printed token must validate True against a TokenStore opened on the same DB."""
    db = tmp_path / "whodex.db"
    result = runner.invoke(app, ["token", "issue", "--label", "firefox", "--db", str(db)])
    assert result.exit_code == 0, result.output

    # Extract the token from output — first non-empty line with no spaces (raw urlsafe string)
    token: str | None = None
    for line in result.output.splitlines():
        stripped = line.strip()
        if stripped and " " not in stripped:
            token = stripped
            break

    assert token is not None, f"Could not find token in output:\n{result.output}"

    # Open a fresh store against the same DB and validate
    url = f"sqlite:///{db}"
    store = SqliteTokenStore(url=url, id_factory=SequentialIdFactory("TK"))
    assert store.validate(token) is True

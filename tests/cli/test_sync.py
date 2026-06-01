from typer.testing import CliRunner

from whodex.cli.main import app

runner = CliRunner()


def test_sync_runs_with_demo_source_and_prints_state():
    result = runner.invoke(app, ["sync", "--demo"])
    assert result.exit_code == 0
    assert "Jane Demo" in result.stdout
    assert "job.title" in result.stdout

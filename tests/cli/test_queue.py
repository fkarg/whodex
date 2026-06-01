from typer.testing import CliRunner

from whodex.cli.main import app

runner = CliRunner()


def test_queue_command_prints_ranked_contacts():
    result = runner.invoke(app, ["queue", "--demo"])
    assert result.exit_code == 0
    assert "Jane Demo" in result.stdout

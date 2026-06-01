from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from whodex.config.settings import build_app
from whodex.engine.queue import priority_queue
from whodex.engine.scoring import ScoringConfig
from whodex.sync.engine import run_sync

app = typer.Typer(help="whodex — local-first people CRM")


@app.command()
def version() -> None:
    """Print the whodex version."""
    typer.echo("whodex 0.0.0")


@app.command()
def sync(
    demo: bool = typer.Option(False, "--demo", help="run with a built-in demo source"),
    vault: Optional[Path] = typer.Option(None, "--vault", help="path to Obsidian vault directory"),
    db: Optional[Path] = typer.Option(None, "--db", help="path to SQLite database file"),
) -> None:
    """Run one sync pass and print the projected state."""
    wiring = build_app(demo=demo, vault=vault, db=db)
    report = run_sync(
        wiring.sources,
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=wiring.clock.now(),
    )
    typer.echo(
        f"ingested={report.observations_ingested} interactions={report.interactions_ingested} "
        f"changes={report.changes} conflicts={report.conflicts}"
    )
    for eid, state in wiring.projection.load().items():
        typer.echo(f"- {state.display_name or eid} ({state.kind.value})")
        for fname, fv in sorted(state.fields.items()):
            typer.echo(f"    {fname}: {fv.value}  [{fv.source_kind}]")


@app.command()
def queue(
    demo: bool = typer.Option(False, "--demo", help="run with a built-in demo source"),
    vault: Optional[Path] = typer.Option(None, "--vault", help="path to Obsidian vault directory"),
    db: Optional[Path] = typer.Option(None, "--db", help="path to SQLite database file"),
) -> None:
    """Run one sync pass, then print the ranked reach-out queue with why-now."""
    wiring = build_app(demo=demo, vault=vault, db=db)
    run_sync(
        wiring.sources,
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=wiring.clock.now(),
    )
    ranked = priority_queue(
        wiring.projection.load(),
        wiring.ledger.read_events(),
        cfg=ScoringConfig(),
        now=wiring.clock.now(),
    )
    if not ranked:
        typer.echo("(no contacts to reach out to)")
        return
    for si, score in ranked:
        typer.echo(
            f"{score.value:7.2f}  {si.display_name or si.entity_id}  — {'; '.join(score.reasons)}"
        )

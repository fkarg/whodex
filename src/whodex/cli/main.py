from __future__ import annotations

from pathlib import Path

import typer

from whodex.config.settings import build_app
from whodex.engine.graph import people_at
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
    vault: Path | None = typer.Option(None, "--vault", help="path to Obsidian vault directory"),
    db: Path | None = typer.Option(None, "--db", help="path to SQLite database file"),
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
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )
    typer.echo(
        f"ingested={report.observations_ingested} interactions={report.interactions_ingested} "
        f"changes={report.changes} conflicts={report.conflicts} "
        f"edges={report.edges} repairs={report.repairs}"
    )
    for eid, state in wiring.projection.load().items():
        typer.echo(f"- {state.display_name or eid} ({state.kind.value})")
        for fname, fv in sorted(state.fields.items()):
            typer.echo(f"    {fname}: {fv.value}  [{fv.source_kind}]")


@app.command()
def queue(
    demo: bool = typer.Option(False, "--demo", help="run with a built-in demo source"),
    vault: Path | None = typer.Option(None, "--vault", help="path to Obsidian vault directory"),
    db: Path | None = typer.Option(None, "--db", help="path to SQLite database file"),
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
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )
    ranked = priority_queue(
        wiring.projection.load(),
        wiring.ledger.read_events(),
        cfg=ScoringConfig(),
        now=wiring.clock.now(),
        open_changes=wiring.derived.changes(),
    )
    if not ranked:
        typer.echo("(no contacts to reach out to)")
        return
    for si, score in ranked:
        typer.echo(
            f"{score.value:7.2f}  {si.display_name or si.entity_id}  — {'; '.join(score.reasons)}"
        )


@app.command(name="who-at")
def who_at(
    query: str = typer.Argument(..., help="vault path or display name of an org/location"),
    vault: Path | None = typer.Option(None, "--vault", help="path to Obsidian vault directory"),
    db: Path | None = typer.Option(None, "--db", help="path to SQLite database file"),
) -> None:
    """List people at an organisation or location (G5)."""
    wiring = build_app(vault=vault, db=db)

    # ------------------------------------------------------------------
    # Resolve <query> to an entity id.
    # Strategy 1: exact vault_path identifier match (with / without .md).
    # ------------------------------------------------------------------
    resolved_id: str | None = wiring.entities.find_by_identifiers(
        [("vault_path", query), ("vault_path", query + ".md")]
    )

    # Strategy 2: try well-known vault folder prefixes for bare stem queries.
    # vault_paths are stored as identifiers (e.g. "Organisations/Acme.md"), not
    # on the entity row itself, so we probe common prefixes.
    if resolved_id is None:
        _VAULT_FOLDERS = ("Organisations", "Locations", "Events", "People")
        candidates = [("vault_path", f"{folder}/{query}.md") for folder in _VAULT_FOLDERS] + [
            ("vault_path", f"{folder}/{query}") for folder in _VAULT_FOLDERS
        ]
        resolved_id = wiring.entities.find_by_identifiers(candidates)

    if resolved_id is None:
        typer.echo(
            f"No entity found for '{query}'. Try the vault path (e.g. 'Organisations/Acme')."
        )
        raise typer.Exit(0)

    # ------------------------------------------------------------------
    # Look up people at that entity and print their display names.
    # ------------------------------------------------------------------
    person_ids = people_at(wiring.edges, resolved_id)
    if not person_ids:
        typer.echo(f"No people found at '{query}'.")
        raise typer.Exit(0)

    # Load projection for display names (best-effort: fall back to entity id).
    projection = wiring.projection.load()
    for pid in person_ids:
        state = projection.get(pid)
        display = (state.display_name if state is not None else None) or pid
        typer.echo(display)

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from whodex.domain.enums import Capability, EntityKind
from whodex.domain.ids import IdFactory
from whodex.sources.base import PullSource
from whodex.store.interfaces import (
    DerivedStore,
    EdgeStore,
    EntityStore,
    LedgerStore,
    ProjectionStore,
    VaultStateStore,
)
from whodex.sync.hub import IngestionHub
from whodex.sync.ingest import ingest_one, reproject_and_persist

# Canonical fields that are managed by write-back (must mirror _CANONICAL_TO_FM in obsidian.py)
_MANAGED_CANONICAL: tuple[str, ...] = ("job.title", "linkedin.url", "email", "phone")

# Canonical → frontmatter key map (mirrors _CANONICAL_TO_FM in obsidian.py)
_CANONICAL_TO_FM: dict[str, str] = {
    "job.title": "job_title",
    "linkedin.url": "linkedin",
    "email": "emails",
    "phone": "phones",
}


@dataclass
class SyncReport:
    observations_ingested: int = 0
    interactions_ingested: int = 0
    changes: int = 0
    conflicts: int = 0
    edges: int = 0
    repairs: int = 0


def run_sync(
    sources: Sequence[PullSource],
    *,
    ledger: LedgerStore,
    projection: ProjectionStore,
    hub: IngestionHub,
    trust: Mapping[str, int],
    now: datetime,
    entities: EntityStore | None = None,
    edge_store: EdgeStore | None = None,
    derived_store: DerivedStore | None = None,
    ids: IdFactory | None = None,
    write_back: bool = False,
    vault_state_store: VaultStateStore | None = None,
) -> SyncReport:
    report = SyncReport()
    # entity_id → vault_path mapping, built during fetch for write-back use
    entity_vault_paths: dict[str, str] = {}
    for run_seq, source in enumerate(sources, start=1):
        run_id = f"RUN-{run_seq}"
        for record in source.fetch(None):
            result = ingest_one(source, record, hub=hub, ledger=ledger, source_run_id=run_id)
            report.observations_ingested += len(result.observations)
            if result.interactions:
                report.interactions_ingested += len(result.interactions)
            # Track vault_path for write-back: ObsidianSource puts vault_path in identity
            if "vault_path" in record.identity:
                entity_vault_paths[result.entity_id] = record.identity["vault_path"]

    changes, conflicts = reproject_and_persist(
        ledger=ledger,
        projection=projection,
        hub=hub,
        trust=trust,
        now=now,
        entities=entities,
        edge_store=edge_store,
        derived_store=derived_store,
        ids=ids,
    )
    report.changes = changes
    report.conflicts = conflicts

    # Fill in edge/repair counts from the store state after reproject_and_persist.
    if edge_store is not None:
        report.edges = len(edge_store.all_edges())
    if derived_store is not None:
        report.repairs = len(derived_store.repairs())

    # --- write-back phase (opt-in) ---
    if write_back and vault_state_store is not None:
        proj_states = projection.load()
        _run_writeback(sources, proj_states, entity_vault_paths, vault_state_store)

    return report


def _run_writeback(
    sources: Sequence[PullSource],
    states: dict[str, Any],
    entity_vault_paths: dict[str, str],
    vault_state_store: VaultStateStore,
) -> None:
    """Write projected data back into vault notes for WRITEBACK-capable sources.

    Only fills blank managed frontmatter fields (no-clobber).  Only processes
    PERSON entities that have a vault_path tracked from the fetch phase.
    """
    # Find the first WRITEBACK-capable source
    writeback_source = None
    for source in sources:
        if Capability.WRITEBACK in source.capabilities:
            writeback_source = source
            break
    if writeback_source is None:
        return

    for entity_id, entity_state in states.items():
        if entity_state.kind != EntityKind.person:
            continue

        vault_path = entity_vault_paths.get(entity_id)
        if not vault_path:
            continue

        # Build projected frontmatter from canonical field state (managed fields only)
        projected: dict[str, Any] = {}
        for canonical, fm_key in _CANONICAL_TO_FM.items():
            fv = entity_state.fields.get(canonical)
            if fv is not None and fv.value is not None:
                value = fv.value
                # For list-typed fields (email, phone), wrap scalars in a list
                if fm_key in ("emails", "phones") and not isinstance(value, list):
                    value = [value]
                if value:
                    projected[fm_key] = value

        if not projected:
            continue

        fn = getattr(writeback_source, "write_back", None)
        if fn is not None:
            fn(
                vault_path,
                projected,
                uid=entity_id,
                state_store=vault_state_store,
            )

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from whodex.projection.project import project
from whodex.sources.base import PullSource
from whodex.store.interfaces import LedgerStore, ProjectionStore
from whodex.sync.hub import IngestionHub


@dataclass
class SyncReport:
    observations_ingested: int = 0
    changes: int = 0
    conflicts: int = 0


def run_sync(
    sources: Sequence[PullSource],
    *,
    ledger: LedgerStore,
    projection: ProjectionStore,
    hub: IngestionHub,
    trust: Mapping[str, int],
    now: datetime,
) -> SyncReport:
    report = SyncReport()
    for run_seq, source in enumerate(sources, start=1):
        run_id = f"RUN-{run_seq}"
        for record in source.fetch(None):
            result = hub.ingest(source, record, source_run_id=run_id)
            ledger.append_observations(result.observations)
            report.observations_ingested += len(result.observations)

    prev = projection.load()
    events = ledger.read_events()
    proj = project(events, prev or None, trust=trust, kinds=hub.identity.kinds, now=now)
    projection.save(proj.states)
    report.changes = len(proj.changes)
    report.conflicts = len(proj.conflict_suggestions)
    return report

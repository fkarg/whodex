from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from whodex.domain.enums import UserActionType
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.projection.edges import build_edges
from whodex.projection.project import project
from whodex.sources.base import PullSource
from whodex.store.interfaces import (
    DerivedStore,
    EdgeStore,
    EntityStore,
    LedgerStore,
    ProjectionStore,
)
from whodex.sync.hub import IngestionHub
from whodex.sync.resolve import make_resolver


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
) -> SyncReport:
    report = SyncReport()
    for run_seq, source in enumerate(sources, start=1):
        run_id = f"RUN-{run_seq}"
        for record in source.fetch(None):
            result = hub.ingest(source, record, source_run_id=run_id)
            ledger.append_observations(result.observations)
            report.observations_ingested += len(result.observations)
            if result.interactions:
                ledger.append_interactions(result.interactions)
                report.interactions_ingested += len(result.interactions)

    prev = projection.load()
    events = ledger.read_events()
    proj = project(events, prev or None, trust=trust, kinds=hub.identity.kinds, now=now)
    projection.save(proj.states)
    report.changes = len(proj.changes)
    report.conflicts = len(proj.conflict_suggestions)

    # --- edge projection ---
    if edge_store is not None and entities is not None:
        id_factory = ids or UlidIdFactory()
        resolve = make_resolver(entities)
        graph_edges, repairs_from_edges = build_edges(
            events.observations, resolve=resolve, ids=id_factory, now=now
        )
        edge_store.replace_edges(graph_edges)
        report.edges = len(graph_edges)
        all_repairs = proj.graph_repairs + repairs_from_edges
    else:
        all_repairs = proj.graph_repairs

    # --- derived row persistence ---
    if derived_store is not None:
        # Collect acked/dismissed fingerprints from user_actions
        acked_fps: set[str] = set()
        dismissed_fps: set[str] = set()
        for a in events.user_actions:
            if a.action_type == UserActionType.ack_change and "fingerprint" in a.payload:
                acked_fps.add(str(a.payload["fingerprint"]))
            elif a.action_type == UserActionType.dismiss and "fingerprint" in a.payload:
                dismissed_fps.add(str(a.payload["fingerprint"]))

        derived_store.replace_changes(proj.changes, acked_fingerprints=acked_fps)
        derived_store.replace_conflicts(
            proj.conflict_suggestions, dismissed_fingerprints=dismissed_fps
        )
        derived_store.replace_repairs(all_repairs, dismissed_fingerprints=dismissed_fps)
        report.repairs = len(all_repairs)

    return report

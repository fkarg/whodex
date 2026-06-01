"""Shared per-record ingest helpers shared by run_sync and the ingestion API.

Both the pull-sync engine and the push ingestion API follow the same pipeline:
  1. hub.ingest → produces observations + interactions
  2. Append to ledger
  3. Re-project from full ledger and persist projection + derived stores

``ingest_one`` handles step 1+2 for a single record.
``reproject_and_persist`` handles step 3 — it is a pure call-through to the projection
machinery and does NOT perform IO beyond the store calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from whodex.domain.enums import UserActionType
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.projection.edges import build_edges
from whodex.projection.project import project
from whodex.sources.base import Source
from whodex.store.interfaces import (
    DerivedStore,
    EdgeStore,
    EntityStore,
    LedgerStore,
    ProjectionStore,
)
from whodex.sync.hub import IngestionHub, IngestResult
from whodex.sync.resolve import make_resolver


def ingest_one(
    source: Source,
    record: object,
    *,
    hub: IngestionHub,
    ledger: LedgerStore,
    source_run_id: str,
) -> IngestResult:
    """Ingest a single RawRecord: call hub, append to ledger, return result.

    The ``record`` parameter is typed as ``object`` so callers that hold a
    ``RawRecord`` do not need to cast; the hub accepts ``RawRecord`` instances.
    """
    from whodex.domain.events import RawRecord

    assert isinstance(record, RawRecord), "record must be a RawRecord"
    result = hub.ingest(source, record, source_run_id=source_run_id)
    ledger.append_observations(result.observations)
    if result.interactions:
        ledger.append_interactions(result.interactions)
    return result


def reproject_and_persist(
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
) -> tuple[int, int]:
    """Re-project from the full ledger and persist to all stores.

    Returns ``(changes, conflicts)`` — a summary suitable for an API response.
    """
    prev = projection.load()
    events = ledger.read_events()
    proj = project(events, prev or None, trust=trust, kinds=hub.identity.kinds, now=now)
    projection.save(proj.states)

    # --- edge projection ---
    all_repairs = proj.graph_repairs
    if edge_store is not None and entities is not None:
        id_factory = ids or UlidIdFactory()
        resolve = make_resolver(entities)
        graph_edges, repairs_from_edges = build_edges(
            events.observations, resolve=resolve, ids=id_factory, now=now
        )
        edge_store.replace_edges(graph_edges)
        all_repairs = proj.graph_repairs + repairs_from_edges

    # --- derived row persistence ---
    if derived_store is not None:
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

    return len(proj.changes), len(proj.conflict_suggestions)

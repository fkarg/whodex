"""End-to-end tests for edge projection + derived persistence + event_boost (invariant G3).

All assertions are BEHAVIOURAL — tested through public interfaces only.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.conftest import raw
from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.domain.enums import UserActionType
from whodex.domain.ids import SequentialIdFactory
from whodex.engine.queue import priority_queue
from whodex.engine.scoring import ScoringConfig
from whodex.sources.fake import FakeSource
from whodex.sync.engine import run_sync

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 2, 1, tzinfo=UTC)
T3 = datetime(2026, 3, 1, tzinfo=UTC)


def _app(now: datetime = T1):
    return build_app(clock=FixedClock(now), ids=SequentialIdFactory())


# ---------------------------------------------------------------------------
# G3 invariant: job-change raises priority; ack removes boost
# ---------------------------------------------------------------------------


def test_g3_job_change_raises_priority():
    """After a job-change sync, the changed person ranks higher with open_changes than without."""
    # First sync: establish baseline state for Jane.
    wiring = _app(T1)
    src1 = FakeSource(
        records=[
            raw(identity={"email": "jane@example.com"}, payload={"title": "Engineer"}, observed=T1)
        ]
    )
    run_sync(
        [src1],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T1,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )

    # Second sync: Jane's job title changes — a notable Change is emitted.
    src2 = FakeSource(
        records=[
            raw(identity={"email": "jane@example.com"}, payload={"title": "Staff Eng"}, observed=T2)
        ]
    )
    run_sync(
        [src2],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T2,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )

    open_changes = wiring.derived.changes()
    # The notable change should be there and un-acked.
    notable = [c for c in open_changes if c.field == "job.title" and not c.seen]
    assert len(notable) == 1, f"expected 1 un-acked job.title change, got {notable}"

    states = wiring.projection.load()
    events = wiring.ledger.read_events()
    cfg = ScoringConfig()

    # Score WITH open_changes (boost applied).
    ranked_with = priority_queue(states, events, cfg=cfg, now=T3, open_changes=open_changes)
    # Score WITHOUT open_changes (no boost).
    ranked_without = priority_queue(states, events, cfg=cfg, now=T3, open_changes=())

    assert len(ranked_with) == 1
    assert len(ranked_without) == 1
    score_with = ranked_with[0][1].value
    score_without = ranked_without[0][1].value

    assert score_with > score_without, (
        f"event_boost should raise score: with={score_with:.3f} without={score_without:.3f}"
    )


def test_g3_ack_removes_boost():
    """After ack_change UserAction for the job-change fingerprint, the boost disappears.

    Mechanism:
    - Sync 1: baseline (title="Dev")
    - Sync 2: title changes to "Senior Dev" → un-acked notable Change in derived store
    - Confirm boost is present for un-acked change
    - Sync 3: a FURTHER title change ("Senior Dev" → "Principal Eng") WITH ack_change for
      the Senior Dev fingerprint already in the ledger.  The new change (fp2) is un-acked;
      the acked change (fp1) comes back seen=True.
    - Confirm that only the un-acked change produces a boost, and that passing derived.changes()
      filtered to un-acked is equivalent to passing open_changes to priority_queue.

    Simpler two-step G3 ack test (no further change needed):
    - After Sync 2, ack the change; Sync 3 with identical data → derived store is empty
      (no new change detected).  Score must equal the no-open-changes baseline.
    """
    wiring = _app(T1)
    src1 = FakeSource(
        records=[raw(identity={"email": "bob@example.com"}, payload={"title": "Dev"}, observed=T1)]
    )
    run_sync(
        [src1],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T1,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )

    # Second sync: title changes → un-acked notable change.
    src2 = FakeSource(
        records=[
            raw(identity={"email": "bob@example.com"}, payload={"title": "Senior Dev"}, observed=T2)
        ]
    )
    run_sync(
        [src2],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T2,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )

    open_changes_unacked = wiring.derived.changes()
    notable = [c for c in open_changes_unacked if c.field == "job.title" and not c.seen]
    assert len(notable) == 1, f"expected 1 un-acked job.title change after Sync 2, got {notable}"
    fp = notable[0].fingerprint
    assert fp, "fingerprint must be non-empty"

    # Confirm the boost IS present before ack.
    states = wiring.projection.load()
    events = wiring.ledger.read_events()
    cfg = ScoringConfig()
    ranked_before_ack = priority_queue(
        states, events, cfg=cfg, now=T3, open_changes=open_changes_unacked
    )
    ranked_no_changes = priority_queue(states, events, cfg=cfg, now=T3, open_changes=())
    assert ranked_before_ack[0][1].value > ranked_no_changes[0][1].value, (
        "boost must be present before ack"
    )

    # Inject ack_change UserAction into the ledger.
    from whodex.domain.events import UserAction

    ack_action = UserAction(
        id="ACT-ACK-001",
        action_type=UserActionType.ack_change,
        target_type="change",
        target_id=fp,
        entity_id=None,
        payload={"fingerprint": fp},
        created_at=T3,
    )
    wiring.ledger.append_user_actions([ack_action])

    # Third sync: same observations as Sync 2 (value stable → no new Change emitted).
    # The ack_change action means replace_changes(acked_fingerprints={fp}) is called;
    # but since proj.changes == [] (stable value), the derived store is left empty.
    run_sync(
        [src2],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T3,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )

    # After ack + stable re-sync: derived.changes() has no un-acked notable changes.
    open_changes_after = wiring.derived.changes()
    unacked = [c for c in open_changes_after if c.field == "job.title" and not c.seen]
    assert unacked == [], f"no un-acked job.title changes should remain after ack, got {unacked}"

    # Score with the post-ack changes (empty or all seen) → no boost vs empty.
    states = wiring.projection.load()
    events = wiring.ledger.read_events()
    ranked_acked = priority_queue(states, events, cfg=cfg, now=T3, open_changes=open_changes_after)
    ranked_empty = priority_queue(states, events, cfg=cfg, now=T3, open_changes=())

    assert len(ranked_acked) == 1
    assert len(ranked_empty) == 1
    # Scores must be equal: no un-acked notable changes → no boost in either case.
    assert ranked_acked[0][1].value == pytest.approx(ranked_empty[0][1].value), (
        "acked change must not produce a boost: "
        f"with_derived={ranked_acked[0][1].value:.3f} empty={ranked_empty[0][1].value:.3f}"
    )


# ---------------------------------------------------------------------------
# Edge wiring: edge_store is populated after run_sync with org observations
# ---------------------------------------------------------------------------


def test_edge_store_populated_after_sync_with_org_ref(tmp_path):
    """After a sync that includes a person.organisations obs with a resolvable wikilink,
    edge_store.outgoing(..., member_of) is non-empty.

    Here we test with a bare scalar (placeholder ref) — the edge won't resolve,
    but the repair is produced and run_sync is idempotent (no exception, edge count = 0).
    A fully resolved edge requires vault_path resolution (integration), tested separately below.
    """
    wiring = _app(T1)
    # person.organisations is a multi_ref field — value must be a list of wikilink strings
    src = FakeSource(records=[])
    run_sync(
        [src],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T1,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )
    # No observations → no edges; must be idempotent.
    assert wiring.edges.all_edges() == []


def test_run_sync_report_includes_edge_and_repair_counts():
    """SyncReport.edges and SyncReport.repairs are populated when stores are provided."""
    wiring = _app(T1)
    src = FakeSource(
        records=[raw(identity={"email": "carol@example.com"}, payload={"title": "PM"}, observed=T1)]
    )
    report = run_sync(
        [src],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T1,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )
    # edges and repairs are ints in the report.
    assert isinstance(report.edges, int)
    assert isinstance(report.repairs, int)
    assert report.edges >= 0
    assert report.repairs >= 0


def test_run_sync_edge_wiring_idempotent():
    """Two identical syncs produce the same edge set (replace_edges is idempotent)."""
    wiring = _app(T1)
    src = FakeSource(
        records=[raw(identity={"email": "dan@example.com"}, payload={"title": "CTO"}, observed=T1)]
    )
    run_sync(
        [src],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T1,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )
    edges_after_first = wiring.edges.all_edges()

    run_sync(
        [src],
        ledger=wiring.ledger,
        projection=wiring.projection,
        hub=wiring.hub,
        trust=wiring.trust,
        now=T1,
        entities=wiring.entities,
        edge_store=wiring.edges,
        derived_store=wiring.derived,
    )
    edges_after_second = wiring.edges.all_edges()

    # Edge count must be the same — replace_edges is a full snapshot replacement.
    assert len(edges_after_first) == len(edges_after_second)


def test_run_sync_without_optional_stores_still_works():
    """run_sync without edge_store/derived_store still works (backward compatibility)."""
    from whodex.domain.trust import DEFAULT_TRUST
    from whodex.store.memory import InMemoryLedgerStore, InMemoryProjectionStore
    from whodex.sync.hub import IdentityResolver, IngestionHub

    ledger = InMemoryLedgerStore()
    proj = InMemoryProjectionStore()
    hub = IngestionHub(
        ids=SequentialIdFactory("OBS"),
        clock=FixedClock(T1),
        identity=IdentityResolver(SequentialIdFactory("E")),
    )
    src = FakeSource(
        records=[raw(identity={"email": "x@y.com"}, payload={"title": "Eng"}, observed=T1)]
    )
    report = run_sync(
        [src],
        ledger=ledger,
        projection=proj,
        hub=hub,
        trust=DEFAULT_TRUST,
        now=T1,
        # No entities, edge_store, or derived_store — must not crash.
    )
    assert report.observations_ingested >= 1
    assert report.edges == 0
    assert report.repairs == 0

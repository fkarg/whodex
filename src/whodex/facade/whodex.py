"""Headless Whodex facade — the single object every front-end calls.

All reads return pure DTOs (no store objects leak out).
All writes append to the ledger, then reproject_and_persist so subsequent
reads immediately reflect the change.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from whodex.config.settings import App
from whodex.domain.clock import Clock
from whodex.domain.enums import InteractionKind, Significance, SuggestionStatus, UserActionType
from whodex.domain.events import Interaction, UserAction
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.domain.state import Notification
from whodex.engine.freshness import FreshnessConfig, staleness
from whodex.engine.graph import contact_points as _contact_points
from whodex.engine.graph import people_at as _people_at
from whodex.engine.queue import priority_queue as _priority_queue
from whodex.engine.scoring import ScoringConfig, build_score_inputs, score_contact
from whodex.facade.dto import (
    ContactDetail,
    FieldEntry,
    RankedContact,
    ReviewItem,
    TimelineEntry,
)
from whodex.sync.engine import run_sync
from whodex.sync.ingest import reproject_and_persist


class Whodex:
    """Headless application facade.

    Constructed from a fully-wired ``App`` (from ``build_app``).  All reads go
    through projected state; all writes append events then reproject so reads
    are consistent immediately after any write.
    """

    def __init__(
        self,
        app: App,
        *,
        ids: IdFactory | None = None,
        clock: Clock | None = None,
        scoring_cfg: ScoringConfig | None = None,
        freshness_cfg: FreshnessConfig | None = None,
    ) -> None:
        self._app = app
        self._ids: IdFactory = ids or app.clock and UlidIdFactory()  # type: ignore[assignment]
        if self._ids is None:
            self._ids = UlidIdFactory()
        self._clock: Clock = clock or app.clock
        self._scoring_cfg = scoring_cfg or ScoringConfig()
        self._freshness_cfg = freshness_cfg or FreshnessConfig()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return self._clock.now()

    def _new_id(self) -> str:
        return self._ids.new()

    def _reproject(self) -> None:
        """Re-project the full ledger and persist all derived stores."""
        app = self._app
        reproject_and_persist(
            ledger=app.ledger,
            projection=app.projection,
            hub=app.hub,
            trust=app.trust,
            now=self._now(),
            entities=app.entities,
            edge_store=app.edges,
            derived_store=app.derived,
            ids=self._ids,
        )

    def _append_user_action(self, action: UserAction) -> None:
        self._app.ledger.append_user_actions([action])
        self._reproject()

    def _append_interaction(self, interaction: Interaction) -> None:
        self._app.ledger.append_interactions([interaction])
        self._reproject()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def priority_queue(
        self, limit: int = 50, *, include_snoozed: bool = False
    ) -> list[RankedContact]:
        """Return contacts ranked by urgency, highest first.

        Snoozed contacts are excluded unless *include_snoozed* is True.
        When include_snoozed is True, snoozed contacts appear last with score=-inf.
        """
        app = self._app
        states = app.projection.load()
        events = app.ledger.read_events()
        open_changes = app.derived.changes()
        now = self._now()

        if include_snoozed:
            # Build all score inputs and score them, including snoozed (-inf)
            score_inputs = build_score_inputs(
                states, events, cfg=self._scoring_cfg, now=now, open_changes=open_changes
            )
            scored = [(si, score_contact(si, self._scoring_cfg, now)) for si in score_inputs]
            # Sort: live (non-inf) descending, then snoozed (-inf) at end
            live = sorted(
                [(si, sc) for si, sc in scored if sc.value != float("-inf")],
                key=lambda p: p[1].value,
                reverse=True,
            )
            snoozed = [(si, sc) for si, sc in scored if sc.value == float("-inf")]
            ranked = live + snoozed
        else:
            ranked = _priority_queue(
                states,
                events,
                cfg=self._scoring_cfg,
                now=now,
                open_changes=open_changes,
            )

        result: list[RankedContact] = []
        for si, score in ranked:
            result.append(
                RankedContact(
                    entity_id=si.entity_id,
                    display_name=si.display_name,
                    score=score.value,
                    why=score.reasons,
                    tier=si.tier,
                    last_interaction_at=si.last_interaction_at,
                )
            )
            if len(result) >= limit:
                break

        return result

    def contact_detail(self, entity_id: str) -> ContactDetail | None:
        """Return full detail for a single contact, or None if not found."""
        app = self._app
        states = app.projection.load()
        state = states.get(entity_id)
        if state is None:
            return None

        now = self._now()
        events = app.ledger.read_events()

        # Build fields with freshness
        fields: dict[str, FieldEntry] = {}
        for field_name, fv in state.fields.items():
            s = staleness(field_name, fv.ingested_at, self._freshness_cfg, now)
            fields[field_name] = FieldEntry(
                value=fv.value,
                source_kind=fv.source_kind,
                observed_at=fv.observed_at,
                staleness=s.value,
            )

        # Contact points (entity IDs of orgs/locations/events linked via edges)
        cp_ids = _contact_points(app.edges, entity_id)

        # Interleaved timeline: interactions + changes, sorted descending
        timeline: list[TimelineEntry] = []
        for ix in events.interactions:
            if entity_id in ix.participant_ids:
                timeline.append(
                    TimelineEntry(
                        kind="interaction",
                        occurred_at=ix.occurred_at,
                        summary=ix.summary or ix.kind.value,
                        detail={"interaction_kind": ix.kind.value},
                    )
                )
        open_changes_for_entity = [c for c in app.derived.changes() if c.entity_id == entity_id]
        for ch in open_changes_for_entity:
            timeline.append(
                TimelineEntry(
                    kind="change",
                    occurred_at=ch.detected_at,
                    summary=f"{ch.field}: {ch.old_value!r} → {ch.new_value!r}",
                    detail={"field": ch.field, "old": ch.old_value, "new": ch.new_value},
                )
            )
        timeline.sort(key=lambda t: t.occurred_at, reverse=True)

        # Open changes as plain dicts for front-end flexibility
        open_changes_dicts = [
            {
                "id": ch.id,
                "field": ch.field,
                "old_value": ch.old_value,
                "new_value": ch.new_value,
                "fingerprint": ch.fingerprint,
                "significance": ch.significance,
                "seen": ch.seen,
            }
            for ch in open_changes_for_entity
        ]

        return ContactDetail(
            entity_id=entity_id,
            display_name=state.display_name,
            kind=state.kind.value,
            fields=fields,
            contact_points=cp_ids,
            timeline=timeline,
            open_changes=open_changes_dicts,
        )

    def review_queue(self) -> list[ReviewItem]:
        """Return open conflicts + graph repair suggestions as ReviewItems."""
        app = self._app
        items: list[ReviewItem] = []

        for c in app.derived.conflicts():
            if c.status == SuggestionStatus.open:
                items.append(
                    ReviewItem(
                        kind="conflict",
                        id=c.id,
                        summary=f"Conflict on {c.field} for entity {c.entity_id}: {c.reason}",
                        payload={
                            "entity_id": c.entity_id,
                            "field": c.field,
                            "fingerprint": c.fingerprint,
                            "winning_observation_id": c.winning_observation_id,
                            "disagreeing_observation_id": c.disagreeing_observation_id,
                        },
                    )
                )

        for r in app.derived.repairs():
            if r.status == SuggestionStatus.open:
                items.append(
                    ReviewItem(
                        kind="repair",
                        id=r.id,
                        summary=(
                            f"Graph repair ({r.repair_type}) {r.src_entity_id} → {r.dst_entity_id}"
                        ),
                        payload={
                            "repair_type": r.repair_type,
                            "src_entity_id": r.src_entity_id,
                            "dst_entity_id": r.dst_entity_id,
                            "fingerprint": r.fingerprint,
                            **r.payload,
                        },
                    )
                )

        return items

    def people_at(self, entity_id: str) -> list[RankedContact]:
        """Return ranked contacts at a given org or location entity."""
        app = self._app
        person_ids = _people_at(app.edges, entity_id)
        if not person_ids:
            return []

        states = app.projection.load()
        events = app.ledger.read_events()
        open_changes = app.derived.changes()
        now = self._now()

        ranked = _priority_queue(
            states,
            events,
            cfg=self._scoring_cfg,
            now=now,
            open_changes=open_changes,
        )

        id_set = set(person_ids)
        return [
            RankedContact(
                entity_id=si.entity_id,
                display_name=si.display_name,
                score=score.value,
                why=score.reasons,
                tier=si.tier,
                last_interaction_at=si.last_interaction_at,
            )
            for si, score in ranked
            if si.entity_id in id_set and score.value != float("-inf")
        ]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def log_interaction(
        self,
        entity_id: str,
        kind: InteractionKind | str = InteractionKind.note,
        *,
        note: str | None = None,
        when: datetime | None = None,
    ) -> None:
        """Log an interaction with a contact and reproject."""
        interaction_kind = InteractionKind(kind) if not isinstance(kind, InteractionKind) else kind
        occurred_at = when or self._now()
        ix = Interaction(
            id=self._new_id(),
            kind=interaction_kind,
            occurred_at=occurred_at,
            participant_ids=(entity_id,),
            summary=note,
            created_at=self._now(),
        )
        self._append_interaction(ix)

    def pin(self, entity_id: str, *, on: bool = True) -> None:
        """Pin (or unpin) a contact."""
        action_type = UserActionType.pin if on else UserActionType.unpin
        action = UserAction(
            id=self._new_id(),
            action_type=action_type,
            target_type="contact",
            target_id=entity_id,
            entity_id=entity_id,
            payload={},
            created_at=self._now(),
        )
        self._append_user_action(action)

    def snooze(self, entity_id: str, until: datetime) -> None:
        """Snooze a contact until a given datetime."""
        action = UserAction(
            id=self._new_id(),
            action_type=UserActionType.snooze,
            target_type="contact",
            target_id=entity_id,
            entity_id=entity_id,
            payload={"until": until.isoformat()},
            created_at=self._now(),
        )
        self._append_user_action(action)

    def dismiss_reminder(self, fingerprint: str) -> None:
        """Dismiss a reminder by its fingerprint."""
        action = UserAction(
            id=self._new_id(),
            action_type=UserActionType.dismiss,
            target_type="reminder",
            target_id=fingerprint,
            entity_id=None,
            payload={"fingerprint": fingerprint},
            created_at=self._now(),
        )
        self._append_user_action(action)

    def acknowledge_change(self, fingerprint: str) -> None:
        """Acknowledge a field change by its fingerprint (removes event boost)."""
        action = UserAction(
            id=self._new_id(),
            action_type=UserActionType.ack_change,
            target_type="change",
            target_id=fingerprint,
            entity_id=None,
            payload={"fingerprint": fingerprint},
            created_at=self._now(),
        )
        self._append_user_action(action)

    def apply_graph_repair(self, repair_id: str) -> None:
        """Record that a graph repair has been applied.

        This appends a UserAction and triggers a reproject.  The repair will be
        marked as dismissed in the derived store on the next reproject because
        the dismiss_fingerprint overlay in replace_repairs uses the
        ``dismiss`` action type — here we use ``apply_graph_repair`` to record
        intent, and also directly mark it resolved in the derived store by
        re-running the reproject with the repair's fingerprint.

        Note: the actual vault write for graph repairs is out-of-scope here;
        this records the intent and removes it from review_queue.
        """
        # Find the repair's fingerprint
        repairs = self._app.derived.repairs()
        repair = next((r for r in repairs if r.id == repair_id), None)
        fp = repair.fingerprint if repair is not None else repair_id

        # Record the action
        action = UserAction(
            id=self._new_id(),
            action_type=UserActionType.apply_graph_repair,
            target_type="graph_repair",
            target_id=repair_id,
            entity_id=None,
            payload={"repair_id": repair_id, "fingerprint": fp},
            created_at=self._now(),
        )
        self._app.ledger.append_user_actions([action])

        # Mark the repair resolved directly in the derived store so it's
        # immediately absent from review_queue() without a full sync.
        if repair is not None:
            resolved = repair.model_copy(update={"status": SuggestionStatus.resolved})
            # replace_repairs with the updated set (repair removed from open)
            current_repairs = [r for r in repairs if r.id != repair_id]
            # We don't call replace_repairs here because it's a full snapshot and
            # would overwrite the resolved state; instead we let reproject handle it.
            # For immediate effect, rebuild with the resolved repair.
            updated_repairs = current_repairs + [resolved]
            self._app.derived.replace_repairs(updated_repairs)

        # Reproject to sync all derived stores
        self._reproject()

    def set_cadence(self, entity_id: str, days: int) -> None:
        """Record a cadence preference for a contact.

        NOTE: This appends a ``cadence_set`` UserAction to the ledger for audit
        purposes, but the cadence value does NOT currently affect scoring
        automatically — scoring reads ``person.cadence_days`` from projected
        observations, not from UserActions.  To have cadence take effect in
        scoring, an Observation with field ``person.cadence_days`` must be
        ingested (e.g. from the vault source).  This is a known limitation;
        full cadence-from-UserAction support is deferred.
        """
        action = UserAction(
            id=self._new_id(),
            action_type=UserActionType.cadence_set,
            target_type="contact",
            target_id=entity_id,
            entity_id=entity_id,
            payload={"days": days},
            created_at=self._now(),
        )
        self._append_user_action(action)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def _generate_notifications(self) -> None:
        """Generate Notification objects from notable un-acked Changes and due Reminders.

        Builds ``Notification`` objects with a stable ``dedupe_key`` so repeated
        calls across syncs are idempotent (the store silently skips duplicates).
        Only ``Significance.notable`` changes and all pending reminders become
        notifications.
        """
        notification_store = getattr(self._app, "notifications", None)
        if notification_store is None:
            return

        now = self._now()
        notifications: list[Notification] = []

        # Notable un-acked changes → notifications
        for change in self._app.derived.changes():
            if change.significance != Significance.notable:
                continue
            if change.seen or change.notified:
                continue
            fp = (
                change.fingerprint
                or hashlib.sha256(
                    f"{change.entity_id}:{change.field}:{change.new_value}".encode()
                ).hexdigest()
            )
            dedupe_key = f"change:{change.entity_id}:{fp}"
            notifications.append(
                Notification(
                    id=self._new_id(),
                    kind="change",
                    entity_id=change.entity_id,
                    payload={
                        "field": change.field,
                        "old_value": change.old_value,
                        "new_value": change.new_value,
                        "fingerprint": fp,
                    },
                    dedupe_key=dedupe_key,
                    created_at=now,
                )
            )

        # Due/pending reminders → notifications
        for reminder in self._app.derived.reminders():
            if reminder.due_at > now:
                continue
            dedupe_key = f"reminder:{reminder.entity_id}:{reminder.fingerprint}"
            notifications.append(
                Notification(
                    id=self._new_id(),
                    kind="reminder",
                    entity_id=reminder.entity_id,
                    payload={
                        "reason": reminder.reason,
                        "score": reminder.score,
                        "why": reminder.why,
                        "fingerprint": reminder.fingerprint,
                    },
                    dedupe_key=dedupe_key,
                    created_at=now,
                )
            )

        if notifications:
            notification_store.append(notifications)

    def sync(self) -> None:
        """Pull all configured sources, reproject, and generate notifications."""
        app = self._app
        run_sync(
            app.sources,
            ledger=app.ledger,
            projection=app.projection,
            hub=app.hub,
            trust=app.trust,
            now=self._now(),
            entities=app.entities,
            edge_store=app.edges,
            derived_store=app.derived,
            ids=self._ids,
        )
        self._generate_notifications()

    def dispatch_notifications(self) -> int:
        """Dispatch pending notifications to all registered notifiers.

        Returns the number of (notification, sink) deliveries made.
        If no notification store is configured on the App, this is a no-op.
        """
        notification_store = getattr(self._app, "notifications", None)
        if notification_store is None:
            return 0

        notifiers = getattr(self._app, "notifiers", [])
        if not notifiers:
            return 0

        from whodex.notifiers.dispatch import NotificationDispatcher

        dispatcher = NotificationDispatcher(notifiers=notifiers, store=notification_store)
        return dispatcher.dispatch()

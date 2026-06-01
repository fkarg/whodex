from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime

from whodex.domain.canonical import canonicalize
from whodex.domain.enums import EntityKind, Significance, UserActionType
from whodex.domain.events import Observation
from whodex.domain.fields import field_def
from whodex.domain.state import (
    Change,
    ConflictSuggestion,
    EntityGraphState,
    EntityState,
    EventStream,
    ProjectionResult,
)
from whodex.projection.conflict import resolve_field


def _conflict_fingerprint(entity_id: str, field: str, winner_id: str, loser: Observation) -> str:
    """Stable, opaque fingerprint for a (winner, loser) conflict pair."""
    key = f"{entity_id}|{field}|{winner_id}|{loser.id}|{loser.value_hash}"
    return hashlib.sha256(key.encode()).hexdigest()


def _pins(events: EventStream) -> dict[tuple[str, str], object]:
    """Latest pin value per (entity, field); cleared by unpin."""
    pins: dict[tuple[str, str], object] = {}
    for a in sorted(events.user_actions, key=lambda x: x.created_at):
        if a.action_type == UserActionType.pin and a.entity_id:
            pins[(a.entity_id, a.payload["field"])] = a.payload["value"]
        elif a.action_type == UserActionType.unpin and a.entity_id:
            pins.pop((a.entity_id, a.payload["field"]), None)
    return pins


def _significance(field: str) -> Significance:
    return Significance.notable if field_def(field).volatile else Significance.minor


def project(
    events: EventStream,
    prev: EntityGraphState | None = None,
    *,
    trust: Mapping[str, int],
    kinds: Mapping[str, EntityKind],
    now: datetime,
) -> ProjectionResult:
    """Pure fold: event streams -> entity state + Changes + ConflictSuggestions.

    `kinds` maps entity_id -> EntityKind (resolved upstream by identity resolution).
    `now` stamps detected_at. No IO, no ambient clock.
    """
    prev = prev or {}
    by_field: dict[str, dict[str, list[Observation]]] = defaultdict(lambda: defaultdict(list))
    for o in events.observations:
        if o.entity_id is None:
            continue
        by_field[o.entity_id][o.field].append(o)

    pins = _pins(events)
    result = ProjectionResult()
    seq = 0

    for entity_id, fields in by_field.items():
        state = EntityState(entity_id=entity_id, kind=kinds.get(entity_id, EntityKind.person))
        for field, obs_list in fields.items():
            pinned = pins.get((entity_id, field))
            fv, winner, losers = resolve_field(obs_list, pinned=pinned, trust=trust)
            state.fields[field] = fv

            # change detection (§6.4): only when the winning *canonical* value flips
            prev_entity = prev.get(entity_id)
            prev_fv = prev_entity.fields.get(field) if prev_entity is not None else None
            if (
                prev_fv is not None
                and winner is not None
                and canonicalize(field, prev_fv.value) != canonicalize(field, fv.value)
            ):
                seq += 1
                result.changes.append(
                    Change(
                        id=f"CHG-{seq:06d}",
                        entity_id=entity_id,
                        field=field,
                        old_value=prev_fv.value,
                        new_value=fv.value,
                        caused_by_observation=winner.id,
                        detected_at=now,
                        significance=_significance(field),
                    )
                )

            # conflict suggestion (§6.5): a LOWER-TRUST source reports a materially different
            # value from the winner.  Equal-trust losers are normal value supersession (history)
            # and must NOT produce a conflict suggestion.
            if winner is not None:
                win_trust = trust.get(winner.source_kind, 0)
                win_canon = canonicalize(field, fv.value)
                for loser in losers:
                    if trust.get(loser.source_kind, 0) >= win_trust:
                        continue  # equal/higher trust → supersession, not a §6.5 conflict
                    if canonicalize(field, loser.value) != win_canon:
                        seq += 1
                        fp = _conflict_fingerprint(entity_id, field, winner.id, loser)
                        result.conflict_suggestions.append(
                            ConflictSuggestion(
                                id=f"CON-{seq:06d}",
                                entity_id=entity_id,
                                field=field,
                                winning_observation_id=winner.id,
                                disagreeing_observation_id=loser.id,
                                reason="lower_trust_disagrees",
                                fingerprint=fp,
                                detected_at=now,
                            )
                        )
                        break  # one suggestion per field is enough for the queue

        if "name.full" in state.fields:
            state.display_name = state.fields["name.full"].value
        result.states[entity_id] = state

    return result

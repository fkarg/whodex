from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.store.memory import InMemoryEntityStore, InMemoryLedgerStore
from whodex.sync.hub import StoreIdentityResolver

_NOW = datetime(2026, 1, 1, tzinfo=UTC)

# Small pool of plausible identity values
_EMAILS = ["alice@example.com", "bob@example.com", "carol@example.com"]
_LINKEDIN = ["https://linkedin.com/in/alice", "https://linkedin.com/in/bob"]

# Each identity uses exactly ONE strong key to keep the test's scope on the
# single-key resolution invariant. Multi-key (cross-key) entity merging is
# a separate concern (entity-merge) not in scope for P1b-4.
_identity_strategy = st.one_of(
    st.builds(lambda e: {"email": e}, st.sampled_from(_EMAILS)),
    st.builds(lambda u: {"linkedin_url": u}, st.sampled_from(_LINKEDIN)),
)


def _fresh() -> tuple[StoreIdentityResolver, dict[str, str]]:
    """Return a fresh resolver and a dict to track (identity_value -> entity_id) for consistency."""
    entities = InMemoryEntityStore(SequentialIdFactory("E"))
    ledger = InMemoryLedgerStore()
    resolver = StoreIdentityResolver(
        entities, ledger, ids=SequentialIdFactory("ACT"), clock=FixedClock(_NOW)
    )
    return resolver


@given(identities=st.lists(_identity_strategy, min_size=1, max_size=20))
@settings(max_examples=200)
def test_no_identity_value_maps_to_two_entity_ids(identities: list[dict[str, str]]):
    """
    Consistency invariant: across any sequence of resolve calls on one resolver,
    no individual identity key-value pair resolves to two different entity ids.
    """
    resolver = _fresh()
    seen: dict[tuple[str, str], str] = {}  # (key, value) -> entity_id

    for identity in identities:
        eid = resolver.resolve(identity)
        for kv_pair in identity.items():
            if kv_pair in seen:
                # Same key-value pair must always map to the same entity
                assert seen[kv_pair] == eid, (
                    f"Identity pair {kv_pair!r} previously resolved to {seen[kv_pair]!r} "
                    f"but now resolves to {eid!r}"
                )
            else:
                seen[kv_pair] = eid


@given(identities=st.lists(_identity_strategy, min_size=1, max_size=20))
@settings(max_examples=200)
def test_re_resolving_same_dict_is_stable(identities: list[dict[str, str]]):
    """
    Stability invariant: re-resolving any previously-seen identity dict returns the same entity id.
    """
    resolver = _fresh()
    prior: dict[frozenset, str] = {}  # frozenset(items) -> entity_id

    for identity in identities:
        key = frozenset(identity.items())
        eid = resolver.resolve(identity)
        if key in prior:
            assert prior[key] == eid, (
                f"Identity {dict(key)!r} previously resolved to {prior[key]!r} "
                f"but now resolves to {eid!r}"
            )
        else:
            prior[key] = eid

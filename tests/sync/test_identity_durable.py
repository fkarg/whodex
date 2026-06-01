from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.clock import FixedClock
from whodex.domain.enums import EntityKind, UserActionType
from whodex.domain.ids import SequentialIdFactory
from whodex.store.memory import InMemoryEntityStore, InMemoryLedgerStore
from whodex.sync.hub import StoreIdentityResolver

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _resolver(entities: InMemoryEntityStore, ledger: InMemoryLedgerStore) -> StoreIdentityResolver:
    return StoreIdentityResolver(
        entities,
        ledger,
        ids=SequentialIdFactory("ACT"),
        clock=FixedClock(_NOW),
    )


def test_same_identity_resolves_across_independent_resolver_instances():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    eid = _resolver(entities, ledger).resolve({"email": "a@b.com"})
    # NEW resolver over the SAME durable entity store == a separate process run
    assert _resolver(entities, ledger).resolve({"email": "a@b.com"}) == eid


def test_resolution_is_order_independent():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    r = _resolver(entities, ledger)
    a = r.resolve({"email": "a@b.com", "linkedin_url": "https://x/in/a"})
    b = r.resolve({"linkedin_url": "https://x/in/a", "email": "a@b.com"})
    assert a == b


def test_creating_entity_appends_entity_create_to_ledger():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    _resolver(entities, ledger).resolve({"email": "a@b.com"})
    actions = ledger.read_events().user_actions
    assert any(a.action_type == UserActionType.entity_create for a in actions)


def test_resolving_same_identity_twice_does_not_duplicate_ledger_entry():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    r = _resolver(entities, ledger)
    r.resolve({"email": "a@b.com"})
    r.resolve({"email": "a@b.com"})
    creates = [
        a
        for a in ledger.read_events().user_actions
        if a.action_type == UserActionType.entity_create
    ]
    assert len(creates) == 1


def test_different_identities_produce_different_entity_ids():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    r = _resolver(entities, ledger)
    eid1 = r.resolve({"email": "a@b.com"})
    eid2 = r.resolve({"email": "c@d.com"})
    assert eid1 != eid2


def test_entity_create_action_payload_contains_kind():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    _resolver(entities, ledger).resolve({"email": "a@b.com"}, kind=EntityKind.person)
    actions = ledger.read_events().user_actions
    create_action = next(a for a in actions if a.action_type == UserActionType.entity_create)
    assert create_action.payload == {"kind": EntityKind.person.value}


def test_kinds_reflects_created_entities():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    r = _resolver(entities, ledger)
    eid = r.resolve({"email": "a@b.com"}, kind=EntityKind.person)
    assert r.kinds[eid] == EntityKind.person


def test_primary_ref_uses_strong_key_priority():
    entities, ledger = InMemoryEntityStore(SequentialIdFactory("E")), InMemoryLedgerStore()
    r = _resolver(entities, ledger)
    # vault_uid takes priority
    assert r.primary_ref({"email": "a@b.com", "vault_uid": "uid-1"}) == "vault_uid:uid-1"
    # email fallback
    assert r.primary_ref({"email": "a@b.com"}) == "email:a@b.com"
    # unknown fallback
    ref = r.primary_ref({"some_custom": "val"})
    assert ref.startswith("unknown:")

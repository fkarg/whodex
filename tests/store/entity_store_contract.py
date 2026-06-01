"""Behavioural contract every EntityStore must satisfy. Subclass and override make_store."""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.enums import EntityKind


def _utc(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


class EntityStoreContract:
    def make_store(self):  # override -> returns a fresh EntityStore
        raise NotImplementedError

    # ── Basic create + find ──────────────────────────────────────────────────

    def test_create_then_find_returns_same_entity(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        s.add_identifiers(eid, [("email", "a@b.com")])
        assert s.find_by_identifiers([("email", "a@b.com")]) == eid

    def test_unknown_identifier_returns_none(self) -> None:
        assert self.make_store().find_by_identifiers([("email", "x@y.com")]) is None

    def test_empty_identifier_list_returns_none(self) -> None:
        assert self.make_store().find_by_identifiers([]) is None

    # ── Normalisation ────────────────────────────────────────────────────────

    def test_identifier_lookup_is_normalized(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        s.add_identifiers(eid, [("email", "Jane@Acme.COM")])
        # Query with already-normalised form finds the same entity
        assert s.find_by_identifiers([("email", "jane@acme.com")]) == eid

    def test_add_identifiers_normalizes_on_store(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        # Store using mixed-case
        s.add_identifiers(eid, [("email", "JANE@ACME.COM")])
        # Query with lowercase
        assert s.find_by_identifiers([("email", "jane@acme.com")]) == eid

    def test_phone_normalization_strips_dashes_and_spaces(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        s.add_identifiers(eid, [("phone", "+49 173 123-456")])
        assert s.find_by_identifiers([("phone", "+49173123456")]) == eid

    def test_linkedin_url_normalization_strips_trailing_slash(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        s.add_identifiers(eid, [("linkedin_url", "https://www.linkedin.com/in/jane/")])
        assert s.find_by_identifiers([("linkedin_url", "https://www.linkedin.com/in/jane")]) == eid

    # ── kinds() ─────────────────────────────────────────────────────────────

    def test_kinds_reflects_created_entities(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.organisation, created_at=_utc(1))
        assert s.kinds()[eid] == EntityKind.organisation

    def test_kinds_contains_all_created_entities(self) -> None:
        s = self.make_store()
        e1 = s.create_entity(EntityKind.person, created_at=_utc(1))
        e2 = s.create_entity(EntityKind.organisation, created_at=_utc(2))
        k = s.kinds()
        assert k[e1] == EntityKind.person
        assert k[e2] == EntityKind.organisation

    def test_empty_store_has_no_kinds(self) -> None:
        assert self.make_store().kinds() == {}

    # ── find_by_identifiers first-match semantics ────────────────────────────

    def test_find_uses_first_matching_pair(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        s.add_identifiers(eid, [("linkedin_url", "https://www.linkedin.com/in/jane")])
        result = s.find_by_identifiers(
            [
                ("email", "none@x.com"),
                ("linkedin_url", "https://www.linkedin.com/in/jane"),
            ]
        )
        assert result == eid

    def test_find_returns_none_when_no_pair_matches(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        s.add_identifiers(eid, [("email", "real@acme.com")])
        assert s.find_by_identifiers([("email", "other@acme.com")]) is None

    # ── get() ────────────────────────────────────────────────────────────────

    def test_get_returns_entity_row(self) -> None:
        s = self.make_store()
        eid = s.create_entity(
            EntityKind.person,
            created_at=_utc(1),
            subtype="Contact",
            vault_path="People/Jane.md",
            vault_uid="UID-001",
        )
        row = s.get(eid)
        assert row is not None
        assert row.kind == EntityKind.person
        assert row.subtype == "Contact"
        assert row.vault_path == "People/Jane.md"
        assert row.vault_uid == "UID-001"
        assert not row.archived

    def test_get_unknown_id_returns_none(self) -> None:
        assert self.make_store().get("DOES-NOT-EXIST") is None

    # ── Multiple identifiers per entity ─────────────────────────────────────

    def test_entity_can_have_multiple_identifier_kinds(self) -> None:
        s = self.make_store()
        eid = s.create_entity(EntityKind.person, created_at=_utc(1))
        s.add_identifiers(eid, [("email", "a@b.com"), ("phone", "+1234567890")])
        assert s.find_by_identifiers([("email", "a@b.com")]) == eid
        assert s.find_by_identifiers([("phone", "+1234567890")]) == eid

    # ── IDs are distinct per entity ──────────────────────────────────────────

    def test_two_entities_get_distinct_ids(self) -> None:
        s = self.make_store()
        e1 = s.create_entity(EntityKind.person, created_at=_utc(1))
        e2 = s.create_entity(EntityKind.person, created_at=_utc(2))
        assert e1 != e2

"""Read-only Obsidian vault connector (P1b-7).

Scans an Obsidian vault directory, parses each markdown note, and produces
RawRecord objects for ingestion into the hub.

NOTE (deferred): observed_at uses file mtime; git-based observed_at is a
planned follow-up (P1b-8 or later).
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from whodex.domain.enums import Capability, InteractionKind
from whodex.domain.events import InteractionDraft, ObservationDraft, RawRecord
from whodex.domain.enums import ObsOp
from whodex.sources.base import FieldSpec
from whodex.vault.fs import scan
from whodex.vault.markdown import parse_note
from whodex.vault.routing import route

__all__ = ["ObsidianSource"]


class ObsidianSource:
    """Read-only pull source from an Obsidian markdown vault."""

    id: str = "obsidian"
    capabilities: Capability = Capability.PULL
    identity_keys: tuple[str, ...] = ("vault_uid", "vault_path", "linkedin_url", "email")
    provides: tuple[FieldSpec, ...] = (
        FieldSpec(canonical="name.full"),
        FieldSpec(canonical="aliases"),
        FieldSpec(canonical="email"),
        FieldSpec(canonical="phone"),
        FieldSpec(canonical="linkedin.url"),
        FieldSpec(canonical="job.title", freshness_ttl_days=90),
        FieldSpec(canonical="tags"),
        FieldSpec(canonical="person.organisations"),
        FieldSpec(canonical="person.lives"),
        FieldSpec(canonical="contact.next_at"),
        FieldSpec(canonical="contact.last_at"),
    )

    def __init__(self, vault_dir: Path) -> None:
        self._vault_dir = vault_dir

    # ------------------------------------------------------------------
    # PullSource.fetch
    # ------------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterable[RawRecord]:  # noqa: ARG002
        for vf in scan(self._vault_dir):
            try:
                note = parse_note(vf.text)
            except Exception:
                # Malformed notes are silently skipped; we never crash the sync.
                continue

            fm = note.frontmatter

            # Build identity dict
            identity: dict[str, str] = {}

            # vault_uid: from nested whodex.uid or top-level whodex_uid
            whodex_block = fm.get("whodex")
            if isinstance(whodex_block, dict) and whodex_block.get("uid"):
                identity["vault_uid"] = str(whodex_block["uid"])

            # vault_path: always present
            identity["vault_path"] = vf.path

            # linkedin_url
            linkedin = fm.get("linkedin")
            if linkedin and isinstance(linkedin, str):
                identity["linkedin_url"] = linkedin

            # first email
            emails_raw = fm.get("emails", [])
            if isinstance(emails_raw, str):
                emails_raw = [emails_raw]
            if emails_raw:
                identity["email"] = str(emails_raw[0]).lower()

            # Routing to determine _kind and _subtype
            tags_raw = fm.get("tags", [])
            if isinstance(tags_raw, str):
                tags_raw = [tags_raw]
            kind, subtype = route(
                vf.folder,
                fm.get("type"),
                [str(t) for t in tags_raw] if tags_raw else [],
            )

            # observed_at: file mtime (follow-up: git-based timestamp)
            try:
                mtime = os.path.getmtime(self._vault_dir / vf.path)
                observed_at = datetime.fromtimestamp(mtime, tz=UTC)
            except OSError:
                observed_at = datetime.now(UTC)

            # Payload: raw frontmatter + computed routing fields
            payload: dict[str, Any] = dict(fm)
            payload["_kind"] = kind.value
            payload["_subtype"] = subtype
            payload["_folder"] = vf.folder
            payload["_stem"] = vf.stem
            payload["_path"] = vf.path
            # Store computed lists for normalize to use
            payload["_emails"] = [str(e).lower() for e in emails_raw] if emails_raw else []
            payload["_tags"] = [str(t) for t in tags_raw] if tags_raw else []

            yield RawRecord(
                source="obsidian",
                identity=identity,
                payload=payload,
                observed_at=observed_at,
            )

    # ------------------------------------------------------------------
    # Source.normalize
    # ------------------------------------------------------------------

    def normalize(self, record: RawRecord) -> list[ObservationDraft]:
        fm = record.payload
        ts = record.observed_at
        drafts: list[ObservationDraft] = []

        def _emit(field: str, value: Any, *, op: ObsOp = ObsOp.set) -> None:
            if value is None:
                return
            if isinstance(value, str) and not value.strip():
                return
            drafts.append(ObservationDraft(field=field, value=value, observed_at=ts, op=op))

        def _emit_multi(field: str, values: list[Any]) -> None:
            for v in values:
                if v is not None and str(v).strip():
                    drafts.append(
                        ObservationDraft(field=field, value=v, observed_at=ts, op=ObsOp.add)
                    )

        # name.full — from file stem (filename is the display name)
        stem = fm.get("_stem")
        if stem:
            _emit("name.full", stem)

        # aliases — MULTI (added to registry in P1b-7)
        aliases = fm.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        _emit_multi("aliases", [str(a) for a in aliases] if aliases else [])

        # email — MULTI, lowercased
        emails = fm.get("_emails", [])
        _emit_multi("email", emails)

        # phone — MULTI
        phones = fm.get("phones", [])
        if isinstance(phones, str):
            phones = [phones]
        _emit_multi("phone", [str(p) for p in phones] if phones else [])

        # linkedin.url — SCALAR
        linkedin = fm.get("linkedin")
        if linkedin and isinstance(linkedin, str):
            _emit("linkedin.url", linkedin)

        # job.title — SCALAR
        job_title = fm.get("job_title")
        if job_title and isinstance(job_title, str):
            _emit("job.title", job_title)

        # person.organisations — MULTI_REF: raw wikilink strings
        orgs = fm.get("organisations", [])
        if isinstance(orgs, str):
            orgs = [orgs]
        _emit_multi("person.organisations", [str(o) for o in orgs] if orgs else [])

        # person.lives — REF: prefer 'lives' key, fallback to 'city'
        lives = fm.get("lives") or fm.get("city")
        if lives:
            _emit("person.lives", str(lives))

        # tags — MULTI
        tags = fm.get("_tags", [])
        _emit_multi("tags", tags)

        # contact.next_at — from 'next contact' key (note the space)
        next_contact = fm.get("next contact")
        if next_contact is not None:
            _emit("contact.next_at", _coerce_date_str(next_contact))

        # contact.last_at — from 'last contact' key
        last_contact = fm.get("last contact")
        if last_contact is not None:
            _emit("contact.last_at", _coerce_date_str(last_contact))

        # NOTE: 'source:' list (LinkedIn/Email/etc.) is channel metadata — NOT emitted.

        return drafts

    # ------------------------------------------------------------------
    # Interaction extraction
    # ------------------------------------------------------------------

    def interactions(self, record: RawRecord) -> list[InteractionDraft]:
        """Return InteractionDraft list from 'last contact' frontmatter key."""
        last_contact = record.payload.get("last contact")
        if last_contact is None:
            return []

        occurred_at = _coerce_to_utc_datetime(last_contact)
        if occurred_at is None:
            return []

        return [
            InteractionDraft(
                kind=InteractionKind.note,
                occurred_at=occurred_at,
                summary="last contact (vault)",
            )
        ]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _coerce_date_str(value: Any) -> str | None:
    """Turn a date/datetime/string into an ISO date string."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _coerce_to_utc_datetime(value: Any) -> datetime | None:
    """Turn a date/datetime/string into a tz-aware UTC datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        # Try ISO date: YYYY-MM-DD
        try:
            d = date.fromisoformat(stripped)
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        except ValueError:
            pass
        # Try full datetime
        try:
            dt = datetime.fromisoformat(stripped)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            pass
    return None

from __future__ import annotations

from enum import Flag, StrEnum, auto


class ObsOp(StrEnum):
    set = "set"
    add = "add"
    remove = "remove"
    assert_absent = "assert_absent"


class EntityKind(StrEnum):
    person = "person"
    organisation = "organisation"
    location = "location"
    event = "event"


class IdKind(StrEnum):
    email = "email"
    phone = "phone"
    linkedin_url = "linkedin_url"
    google_resource = "google_resource"
    vault_uid = "vault_uid"
    vault_path = "vault_path"
    canonical_name = "canonical_name"
    wikilink = "wikilink"


class EdgeType(StrEnum):
    knows = "knows"
    member_of = "member_of"
    lives_in = "lives_in"
    located_in = "located_in"
    part_of = "part_of"
    hosted_at = "hosted_at"
    organized_by = "organized_by"
    attended = "attended"


class Significance(StrEnum):
    trivial = "trivial"
    minor = "minor"
    notable = "notable"


class InteractionKind(StrEnum):
    met = "met"
    call = "call"
    message = "message"
    email = "email"
    note = "note"
    introduced = "introduced"


class UserActionType(StrEnum):
    entity_create = "entity_create"
    pin = "pin"
    unpin = "unpin"
    snooze = "snooze"
    dismiss = "dismiss"
    ack_change = "ack_change"
    merge = "merge"
    unmerge = "unmerge"
    archive = "archive"
    cadence_set = "cadence_set"
    apply_graph_repair = "apply_graph_repair"


class Capability(Flag):
    PULL = auto()
    PUSH = auto()
    WRITEBACK = auto()
    WATCH = auto()


class ReminderReason(StrEnum):
    cadence_lapsed = "cadence_lapsed"
    data_stale = "data_stale"
    change_detected = "change_detected"
    manual = "manual"


class Staleness(StrEnum):
    fresh = "fresh"
    stale = "stale"
    expired = "expired"


class SuggestionStatus(StrEnum):
    open = "open"
    dismissed = "dismissed"
    resolved = "resolved"

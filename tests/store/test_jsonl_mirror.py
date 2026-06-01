from __future__ import annotations

from tests.conftest import action, interaction, obs
from whodex.domain.enums import InteractionKind, UserActionType
from whodex.store.jsonl import read_events_from_jsonl
from whodex.store.sqlite import SqliteLedgerStore


def test_jsonl_mirror_reconstructs_same_eventstream(tmp_path):
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)
    store.append_observations([obs(entity="E1", field="job.title", value="Eng")])
    store.append_interactions([interaction(entities=("E1",))])
    store.append_user_actions(
        [
            action(
                action_type=UserActionType.pin,
                target_type="contact",
                target_id="E1",
                entity="E1",
            )
        ]
    )
    # INVARIANT: JSONL mirror reconstructs the same EventStream as SQLite truth
    assert read_events_from_jsonl(tmp_path) == store.read_events()


def test_mirror_is_append_only_across_calls(tmp_path):
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)
    store.append_observations([obs(entity="E1", field="email", value="a@b.com")])
    store.append_observations([obs(entity="E1", field="job.title", value="Eng")])
    assert len(read_events_from_jsonl(tmp_path).observations) == 2


def test_no_mirror_when_dir_not_set(tmp_path):
    store = SqliteLedgerStore("sqlite://")  # no jsonl_dir
    store.append_observations([obs(entity="E1", field="email", value="a@b.com")])
    assert not list(tmp_path.iterdir())  # nothing written


def test_empty_directory_returns_empty_eventstream(tmp_path):
    """read_events_from_jsonl on an empty dir returns an empty EventStream."""
    from whodex.domain.state import EventStream

    result = read_events_from_jsonl(tmp_path)
    assert result == EventStream()


def test_mirror_observations_roundtrip(tmp_path):
    """Observations survive JSONL round-trip with correct values."""
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)
    o1 = obs(entity="E1", field="email", value="a@b.com")
    o2 = obs(entity="E2", field="job.title", value="CEO")
    store.append_observations([o1, o2])
    recovered = read_events_from_jsonl(tmp_path)
    assert recovered.observations == [o1, o2]
    assert recovered.interactions == []
    assert recovered.user_actions == []


def test_mirror_interactions_roundtrip(tmp_path):
    """Interactions survive JSONL round-trip including participant_ids tuple."""
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)
    i = interaction(entities=("E1", "E2"), kind=InteractionKind.call)
    store.append_interactions([i])
    recovered = read_events_from_jsonl(tmp_path)
    assert recovered.interactions == [i]
    assert recovered.interactions[0].participant_ids == ("E1", "E2")


def test_mirror_user_actions_roundtrip(tmp_path):
    """UserActions survive JSONL round-trip."""
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)
    a = action(
        action_type=UserActionType.snooze,
        target_type="contact",
        target_id="E1",
        entity="E1",
    )
    store.append_user_actions([a])
    recovered = read_events_from_jsonl(tmp_path)
    assert recovered.user_actions == [a]


def test_mirror_accumulates_across_multiple_append_calls(tmp_path):
    """Each append call adds to the JSONL, not replaces."""
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)
    i1 = interaction(entities=("E1",))
    i2 = interaction(entities=("E2",))
    store.append_interactions([i1])
    store.append_interactions([i2])
    recovered = read_events_from_jsonl(tmp_path)
    assert recovered.interactions == [i1, i2]

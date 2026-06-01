"""Reusable contract suite every Source must satisfy (DESIGN §12 L2)."""

import pytest

from tests.conftest import raw
from whodex.sources.fake import FakeSource


@pytest.fixture
def source():
    return FakeSource(
        records=[
            raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
        ]
    )


def test_normalize_yields_valid_field_drafts(source):
    from whodex.domain.fields import is_valid_field

    for r in source.fetch(None):
        for d in source.normalize(r):
            assert is_valid_field(d.field)


def test_normalize_is_idempotent(source):
    r = next(iter(source.fetch(None)))
    assert source.normalize(r) == source.normalize(r)


def test_id_is_stable_nonempty(source):
    assert isinstance(source.id, str) and source.id

from tests.conftest import raw
from whodex.sources.base import Capability
from whodex.sources.fake import FakeSource


def test_fake_source_fetches_seeded_records():
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    src = FakeSource(records=[r])
    assert list(src.fetch(None)) == [r]
    assert Capability.PULL in src.capabilities


def test_fake_source_normalizes_via_map():
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    drafts = FakeSource(records=[r]).normalize(r)
    fields = {d.field: d.value for d in drafts}
    assert fields == {"name.full": "Jane", "job.title": "Eng"}

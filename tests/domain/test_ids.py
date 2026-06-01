from whodex.domain.ids import SequentialIdFactory, UlidIdFactory


def test_sequential_ids_are_stable_and_ordered():
    f = SequentialIdFactory(prefix="OBS")
    assert f.new() == "OBS-00000001"
    assert f.new() == "OBS-00000002"


def test_ulid_ids_are_unique_and_sortable():
    f = UlidIdFactory()
    a, b = f.new(), f.new()
    assert a != b
    assert len(a) == 26

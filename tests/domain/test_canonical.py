from whodex.domain.canonical import canonicalize, value_hash
from whodex.domain.enums import ObsOp


def test_canonicalize_strips_and_collapses_whitespace():
    assert canonicalize("job.title", "  Staff   Engineer ") == "Staff Engineer"


def test_canonicalize_lowercases_email():
    assert canonicalize("email", "Jane@Acme.COM") == "jane@acme.com"


def test_value_hash_is_stable_across_equivalent_values():
    a = value_hash("job.title", ObsOp.set, "Staff   Engineer")
    b = value_hash("job.title", ObsOp.set, "Staff Engineer")
    assert a == b


def test_value_hash_differs_on_field():
    a = value_hash("job.title", ObsOp.set, "X")
    b = value_hash("job.org", ObsOp.set, "X")
    assert a != b

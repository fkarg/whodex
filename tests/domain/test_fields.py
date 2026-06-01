import pytest

from whodex.domain.fields import FIELDS, FieldKind, field_def, is_valid_field


def test_known_fields_present():
    assert is_valid_field("job.title")
    assert is_valid_field("person.organisations")
    assert is_valid_field("email")


def test_unknown_field_is_invalid():
    assert not is_valid_field("totally.bogus")


def test_field_def_exposes_kind_and_volatility():
    d = field_def("person.organisations")
    assert d.kind == FieldKind.MULTI_REF
    assert field_def("job.title").volatile is True
    assert field_def("email").volatile is False


def test_field_def_raises_on_unknown():
    with pytest.raises(KeyError):
        field_def("nope")


def test_registry_has_about_twenty_fields():
    assert 18 <= len(FIELDS) <= 24

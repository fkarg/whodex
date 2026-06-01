from whodex.domain.refs import EntityRef


def test_parse_aliased_wikilink():
    r = EntityRef.parse("[[Organisations/Kolai|Kolai]]")
    assert r.target_path == "Organisations/Kolai"
    assert r.label == "Kolai"
    assert r.raw == "[[Organisations/Kolai|Kolai]]"
    assert r.resolution == "unresolved"


def test_parse_bare_wikilink():
    r = EntityRef.parse("[[Kolai]]")
    assert r.target_path == "Kolai"
    assert r.label == "Kolai"


def test_parse_scalar_placeholder():
    r = EntityRef.parse("Sydney")
    assert r.target_path is None
    assert r.label == "Sydney"
    assert r.raw == "Sydney"

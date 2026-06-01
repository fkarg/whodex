from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given

from whodex.vault.markdown import parse_note, render_with_changes


def test_no_change_roundtrip_preserves_frontmatter_keys_and_body():
    raw = (
        '---\ntype: Person\naliases: [Jane]\nlives: "[[Locations/Berlin|Berlin]]"\n'
        "---\n## Notes\n- x\n"
    )
    out = render_with_changes(raw, {})
    p_in, p_out = parse_note(raw), parse_note(out)
    assert p_out.frontmatter == p_in.frontmatter
    assert p_out.body == p_in.body == "## Notes\n- x\n"


def test_applies_only_the_changed_key_and_preserves_others_and_body():
    raw = "---\ntype: Person\nweird_key: keep\n---\nBODY\n"
    out = render_with_changes(raw, {"job_title": "Engineer"})
    p = parse_note(out)
    assert p.frontmatter["job_title"] == "Engineer"
    assert p.frontmatter["weird_key"] == "keep"  # untouched key survives
    assert p.frontmatter["type"] == "Person"
    assert p.body == "BODY\n"  # body verbatim


def test_uid_injected_once_and_not_overwritten():
    raw = "---\ntype: Person\n---\nb\n"
    out1 = render_with_changes(raw, {}, set_uid="01ABC")
    assert parse_note(out1).frontmatter["whodex"]["uid"] == "01ABC"
    out2 = render_with_changes(out1, {}, set_uid="02XYZ")  # already has uid
    assert parse_note(out2).frontmatter["whodex"]["uid"] == "01ABC"  # unchanged


def test_no_frontmatter_gets_one_when_changes_given():
    out = render_with_changes("just a body\n", {"job_title": "Eng"})
    p = parse_note(out)
    assert p.frontmatter["job_title"] == "Eng"
    assert "just a body" in p.body


@given(body=st.text().filter(lambda b: not b.lstrip().startswith("---")))
def test_body_preserved_verbatim_through_render(body):
    raw = f"---\ntype: Person\n---\n{body}"
    # W1: body byte-verbatim
    assert parse_note(render_with_changes(raw, {"job_title": "X"})).body == body

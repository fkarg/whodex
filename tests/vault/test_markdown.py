from __future__ import annotations

import hypothesis.strategies as st
import pytest
from hypothesis import given

from whodex.vault.markdown import parse_note


def test_parses_frontmatter_and_preserves_body():
    note = parse_note("---\ntype: Person\naliases: [Jane]\n---\n## Notes\n- Kennenlernen: x\n")
    assert note.frontmatter["type"] == "Person"
    assert note.frontmatter["aliases"] == ["Jane"]
    assert note.body == "## Notes\n- Kennenlernen: x\n"


def test_unknown_keys_preserved():
    note = parse_note("---\ntype: Person\nweird_key: keep-me\n---\nb\n")
    assert note.frontmatter["weird_key"] == "keep-me"


def test_no_frontmatter():
    note = parse_note("just a body\nno fence\n")
    assert note.frontmatter == {}
    assert note.body == "just a body\nno fence\n"


def test_wikilink_refs_scalar_and_list():
    note = parse_note(
        '---\nlives: "[[Locations/Frankfurt am Main|Frankfurt]]"\n'
        'organisations:\n  - "[[Organisations/Kolai|Kolai]]"\n  - "[[Wld]]"\n---\nbody\n'
    )
    assert note.refs("lives")[0].target_path == "Locations/Frankfurt am Main"
    assert [r.label for r in note.refs("organisations")] == ["Kolai", "Wld"]
    assert note.refs("missing") == []


def test_parse_is_deterministic():
    text = '---\ntype: Person\ncity: "[[Sydney]]"\n---\nbody\n'
    assert parse_note(text) == parse_note(text)


# INVARIANT I4: body preserved verbatim for arbitrary bodies that don't contain a frontmatter fence
@given(body=st.text().filter(lambda b: not b.lstrip().startswith("---")))
def test_body_preserved_verbatim(body):
    text = f"---\ntype: Person\n---\n{body}"
    assert parse_note(text).body == body


# --- Additional behavioral cases ---


def test_dotdotdot_closing_fence():
    """YAML documents can also be closed with '...' instead of '---'."""
    note = parse_note("---\ntype: Person\nfoo: bar\n...\nbody after dots\n")
    assert note.frontmatter["foo"] == "bar"
    assert note.body == "body after dots\n"


@pytest.mark.parametrize("closing", ["---", "..."])
def test_body_after_closing_fence_is_verbatim(closing):
    """Everything after the closing fence line is preserved verbatim, including inner ---."""
    inner = "Some text\n---\nmore\n"
    note = parse_note(f"---\ntype: X\n{closing}\n{inner}")
    assert note.body == inner


def test_raw_is_full_original_text():
    text = "---\ntype: Person\n---\nbody\n"
    assert parse_note(text).raw == text


def test_empty_frontmatter_block():
    """A '---\n---\n' gives empty dict frontmatter and correct body."""
    note = parse_note("---\n---\nbody only\n")
    assert note.frontmatter == {}
    assert note.body == "body only\n"


def test_refs_with_none_value():
    """A frontmatter key set to null/None should return []."""
    note = parse_note("---\ntype: Person\nfriends:\n---\nbody\n")
    assert note.refs("friends") == []


def test_refs_empty_list():
    note = parse_note("---\ntype: Person\nfriends: []\n---\nbody\n")
    assert note.refs("friends") == []


def test_text_not_starting_with_fence_is_plain_body():
    """A note that starts with spaces before --- is not treated as having frontmatter."""
    text = "  ---\ntype: Person\n---\nbody\n"
    note = parse_note(text)
    assert note.frontmatter == {}
    assert note.body == text

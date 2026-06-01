"""Paranoid tests for plan_writeback (P1d-3).

Test taxonomy
-------------
W2  no-clobber: never overwrite a field the note already has.
W3  idempotent: second call on new_text returns new_text=None.
W5  uid-once: uid injected once, then never replaced.
W6  fill-blank: missing/empty fields are filled from projected.
no-op: nothing to fill + uid present → new_text is None.
property: hypothesis over arbitrary present/absent field subsets.
"""

from __future__ import annotations

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from whodex.vault.markdown import parse_note
from whodex.vault.writeback import plan_writeback

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MANAGED = ["job_title", "linkedin", "emails", "phones"]
PROJECTED: dict[str, object] = {
    "job_title": "Engineer",
    "linkedin": "https://linkedin.com/in/jane",
    "emails": ["jane@example.com"],
    "phones": ["+1-555-0100"],
}


def _note(frontmatter_lines: str = "", body: str = "## Notes\n") -> str:
    if frontmatter_lines:
        return f"---\n{frontmatter_lines}\n---\n{body}"
    return f"---\n---\n{body}"


# ---------------------------------------------------------------------------
# W6: fill-blank
# ---------------------------------------------------------------------------


def test_w6_fill_blank_missing_field_is_written() -> None:
    raw = _note()  # no job_title
    result = plan_writeback(
        raw=raw,
        projected={"job_title": "Eng"},
        managed_fields=["job_title"],
    )
    assert result.new_text is not None
    assert parse_note(result.new_text).frontmatter["job_title"] == "Eng"
    assert result.wrote_fields == ["job_title"]
    assert result.injected_uid is False


def test_w6_fill_blank_empty_string_value_is_filled() -> None:
    raw = _note("job_title: ''")
    result = plan_writeback(
        raw=raw,
        projected={"job_title": "Eng"},
        managed_fields=["job_title"],
    )
    assert result.new_text is not None
    assert parse_note(result.new_text).frontmatter["job_title"] == "Eng"
    assert "job_title" in result.wrote_fields


def test_w6_fill_blank_empty_list_value_is_filled() -> None:
    raw = _note("emails: []")
    result = plan_writeback(
        raw=raw,
        projected={"emails": ["a@b.com"]},
        managed_fields=["emails"],
    )
    assert result.new_text is not None
    assert parse_note(result.new_text).frontmatter["emails"] == ["a@b.com"]


def test_w6_fill_blank_null_value_is_filled() -> None:
    raw = _note("job_title: null")
    result = plan_writeback(
        raw=raw,
        projected={"job_title": "Boss"},
        managed_fields=["job_title"],
    )
    assert result.new_text is not None
    assert parse_note(result.new_text).frontmatter["job_title"] == "Boss"


def test_w6_wrote_fields_lists_all_filled_keys() -> None:
    raw = _note()
    result = plan_writeback(
        raw=raw,
        projected=PROJECTED,
        managed_fields=MANAGED,
    )
    assert result.new_text is not None
    assert set(result.wrote_fields) == set(MANAGED)


# ---------------------------------------------------------------------------
# W2: no-clobber — parametric over several managed fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "existing_value,projected_value",
    [
        ("Boss", "Eng"),
        ("CTO", "Engineer"),
        ("Director", "Manager"),
    ],
)
def test_w2_no_clobber_existing_string_not_overwritten(
    existing_value: str, projected_value: str
) -> None:
    raw = _note(f"job_title: {existing_value}")
    result = plan_writeback(
        raw=raw,
        projected={"job_title": projected_value},
        managed_fields=["job_title"],
    )
    # Either no change at all, or the value was preserved
    if result.new_text is None:
        # no-op is fine
        return
    assert parse_note(result.new_text).frontmatter["job_title"] == existing_value


def test_w2_no_clobber_returns_none_when_all_fields_present() -> None:
    fm = "job_title: Boss\nlinkedin: https://li.com\nemails:\n  - x@y.com\nphones:\n  - '555'"
    raw = _note(fm)
    result = plan_writeback(
        raw=raw,
        projected=PROJECTED,
        managed_fields=MANAGED,
    )
    assert result.new_text is None
    assert result.wrote_fields == []
    assert result.injected_uid is False


@pytest.mark.parametrize("field", MANAGED)
def test_w2_no_clobber_single_present_field_not_overwritten(field: str) -> None:
    """Each managed field, when already set, must not be overwritten."""
    if field == "emails":
        raw = _note(f"{field}:\n  - existing@example.com")
    elif field == "phones":
        raw = _note(f"{field}:\n  - '+1-000-0000'")
    else:
        raw = _note(f"{field}: existing-value")

    result = plan_writeback(
        raw=raw,
        projected={field: "new-value-should-not-appear"},
        managed_fields=[field],
    )
    # Must not write this field
    assert field not in result.wrote_fields
    if result.new_text is not None:
        note = parse_note(result.new_text)
        existing = note.frontmatter.get(field)
        assert existing != "new-value-should-not-appear"


def test_w2_non_managed_keys_never_touched() -> None:
    raw = _note("unknown_key: keep-me\njob_title: Boss")
    result = plan_writeback(
        raw=raw,
        projected={"job_title": "Eng", "unknown_key": "DELETE"},
        managed_fields=["job_title"],  # unknown_key is NOT managed
    )
    # unknown_key must survive unchanged regardless
    if result.new_text is not None:
        note = parse_note(result.new_text)
        assert note.frontmatter.get("unknown_key") == "keep-me"
    else:
        assert parse_note(raw).frontmatter.get("unknown_key") == "keep-me"


def test_w2_body_never_touched() -> None:
    body = "## My special body\n- item\n\nParagraph.\n"
    raw = _note("job_title: Boss", body=body)
    result = plan_writeback(
        raw=raw,
        projected={"job_title": "Eng"},
        managed_fields=["job_title"],
    )
    # Body must be byte-identical regardless of outcome
    target = result.new_text if result.new_text is not None else raw
    assert parse_note(target).body == body


# ---------------------------------------------------------------------------
# W3: idempotent
# ---------------------------------------------------------------------------


def test_w3_idempotent_second_call_is_noop() -> None:
    raw = _note()
    result1 = plan_writeback(
        raw=raw,
        projected=PROJECTED,
        managed_fields=MANAGED,
    )
    assert result1.new_text is not None  # first call should write something
    result2 = plan_writeback(
        raw=result1.new_text,
        projected=PROJECTED,
        managed_fields=MANAGED,
    )
    assert result2.new_text is None


def test_w3_idempotent_with_uid() -> None:
    raw = _note()
    result1 = plan_writeback(
        raw=raw,
        projected=PROJECTED,
        managed_fields=MANAGED,
        uid="01ABC",
    )
    assert result1.new_text is not None
    result2 = plan_writeback(
        raw=result1.new_text,
        projected=PROJECTED,
        managed_fields=MANAGED,
        uid="01ABC",
    )
    assert result2.new_text is None


def test_w3_render_deterministic_two_fills_same_result() -> None:
    raw = _note()
    result_a = plan_writeback(
        raw=raw,
        projected=PROJECTED,
        managed_fields=MANAGED,
        uid="01ABC",
    )
    result_b = plan_writeback(
        raw=raw,
        projected=PROJECTED,
        managed_fields=MANAGED,
        uid="01ABC",
    )
    assert result_a.new_text == result_b.new_text


# ---------------------------------------------------------------------------
# W5: uid-once
# ---------------------------------------------------------------------------


def test_w5_uid_injected_when_absent() -> None:
    raw = _note()
    result = plan_writeback(
        raw=raw,
        projected={},
        managed_fields=[],
        uid="01ABC",
    )
    assert result.new_text is not None
    assert result.injected_uid is True
    note = parse_note(result.new_text)
    assert note.frontmatter["whodex"]["uid"] == "01ABC"


def test_w5_uid_not_replaced_on_second_call() -> None:
    raw = _note()
    result1 = plan_writeback(
        raw=raw,
        projected={},
        managed_fields=[],
        uid="01ABC",
    )
    assert result1.new_text is not None

    # Second call with a *different* uid — must be no-op
    result2 = plan_writeback(
        raw=result1.new_text,
        projected={},
        managed_fields=[],
        uid="99XYZ",  # different uid
    )
    assert result2.new_text is None
    assert result2.injected_uid is False
    # Original uid still in place
    note = parse_note(result1.new_text)
    assert note.frontmatter["whodex"]["uid"] == "01ABC"


def test_w5_uid_none_no_injection() -> None:
    raw = _note()
    result = plan_writeback(
        raw=raw,
        projected={},
        managed_fields=[],
        uid=None,
    )
    assert result.new_text is None
    assert result.injected_uid is False


# ---------------------------------------------------------------------------
# no-op: nothing to fill, uid already present
# ---------------------------------------------------------------------------


def test_noop_when_all_managed_fields_present_and_uid_set() -> None:
    fm = (
        "job_title: Boss\nlinkedin: https://li.com\n"
        "emails:\n  - x@y.com\nphones:\n  - '555'\n"
        "whodex:\n  uid: EXISTING"
    )
    raw = _note(fm)
    result = plan_writeback(
        raw=raw,
        projected=PROJECTED,
        managed_fields=MANAGED,
        uid="OTHER",
    )
    assert result.new_text is None
    assert result.wrote_fields == []
    assert result.injected_uid is False


def test_noop_when_projected_is_empty() -> None:
    raw = _note()
    result = plan_writeback(
        raw=raw,
        projected={},
        managed_fields=MANAGED,
    )
    assert result.new_text is None


def test_noop_projected_fields_not_in_managed() -> None:
    """Fields in projected but not in managed_fields must never be written."""
    raw = _note()
    result = plan_writeback(
        raw=raw,
        projected={"secret_field": "value"},
        managed_fields=[],  # empty managed list
    )
    assert result.new_text is None
    assert result.wrote_fields == []


# ---------------------------------------------------------------------------
# property: hypothesis — no-clobber invariant + body preservation
# ---------------------------------------------------------------------------

_FIELD_NAMES = ["job_title", "linkedin", "emails", "phones"]
_FIELD_VALUES: dict[str, object] = {
    "job_title": "ExistingTitle",
    "linkedin": "https://existing.li/",
    "emails": ["existing@example.com"],
    "phones": ["+1-000-0000"],
}
_PROJECTED_VALUES: dict[str, object] = {
    "job_title": "NewTitle",
    "linkedin": "https://new.li/",
    "emails": ["new@example.com"],
    "phones": ["+1-111-1111"],
}


@given(
    present_fields=st.frozensets(st.sampled_from(_FIELD_NAMES)),
    body=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        max_size=200,
    ).filter(lambda b: not b.lstrip().startswith("---")),
)
@settings(max_examples=200)
def test_property_no_clobber_and_body_preserved(
    present_fields: frozenset[str],
    body: str,
) -> None:
    """For any subset of managed fields already present in the note:
    - plan_writeback must NOT overwrite any of them.
    - The body must be preserved byte-verbatim.
    """
    # Build frontmatter with the already-present fields
    fm_lines: list[str] = []
    for field in _FIELD_NAMES:
        if field in present_fields:
            val = _FIELD_VALUES[field]
            if isinstance(val, list):
                items = "\n".join(f"  - '{item}'" for item in val)
                fm_lines.append(f"{field}:\n{items}")
            else:
                fm_lines.append(f"{field}: {val!r}")

    fm_block = "\n".join(fm_lines)
    raw = f"---\n{fm_block}\n---\n{body}" if fm_block else f"---\n---\n{body}"

    result = plan_writeback(
        raw=raw,
        projected=dict(_PROJECTED_VALUES),  # type: ignore[arg-type]
        managed_fields=_FIELD_NAMES,
    )

    note_after = parse_note(result.new_text if result.new_text is not None else raw)

    # Body preserved
    assert note_after.body == body

    # No-clobber: every pre-existing non-empty field must be unchanged
    note_before = parse_note(raw)
    for field in present_fields:
        before_val = note_before.frontmatter.get(field)
        after_val = note_after.frontmatter.get(field)
        assert before_val == after_val, (
            f"Field {field!r} was clobbered: {before_val!r} → {after_val!r}"
        )


@given(
    present_fields=st.frozensets(st.sampled_from(_FIELD_NAMES)),
)
@settings(max_examples=100)
def test_property_idempotent(present_fields: frozenset[str]) -> None:
    """Applying plan_writeback twice must be a no-op on the second call."""
    fm_lines: list[str] = []
    for field in _FIELD_NAMES:
        if field in present_fields:
            val = _FIELD_VALUES[field]
            if isinstance(val, list):
                items = "\n".join(f"  - '{item}'" for item in val)
                fm_lines.append(f"{field}:\n{items}")
            else:
                fm_lines.append(f"{field}: {val!r}")

    fm_block = "\n".join(fm_lines)
    raw = f"---\n{fm_block}\n---\nBody text.\n" if fm_block else "---\n---\nBody text.\n"

    result1 = plan_writeback(
        raw=raw,
        projected=dict(_PROJECTED_VALUES),  # type: ignore[arg-type]
        managed_fields=_FIELD_NAMES,
        uid="TESTUID",
    )

    text2 = result1.new_text if result1.new_text is not None else raw
    result2 = plan_writeback(
        raw=text2,
        projected=dict(_PROJECTED_VALUES),  # type: ignore[arg-type]
        managed_fields=_FIELD_NAMES,
        uid="TESTUID",
    )
    assert result2.new_text is None, (
        f"Second call was not a no-op; wrote_fields={result2.wrote_fields}, "
        f"injected_uid={result2.injected_uid}"
    )

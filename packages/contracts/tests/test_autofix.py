from __future__ import annotations

import pytest

from sarj_rule_contracts import TextEdit, apply_edits


def test_edits_share_original_unicode_offsets_and_preserve_unmodified_bytes() -> None:
    source = "α = 1\r\nβ = 2\r\n"
    assert apply_edits(source, (TextEdit(11, 12, "3"), TextEdit(4, 5, "10"))) == "α = 10\r\nβ = 3\r\n"
    assert apply_edits(source, ()) == source


def test_identical_fixes_from_two_rules_apply_once() -> None:
    edit = TextEdit(0, 2, "")
    assert apply_edits("#\nvalue\n", (edit, edit)) == "value\n"


@pytest.mark.parametrize(
    "edits",
    [
        (TextEdit(0, 3, "a"), TextEdit(2, 4, "b")),
        (TextEdit(2, 2, "a"), TextEdit(2, 2, "b")),
        (TextEdit(2, 2, "a"), TextEdit(2, 3, "b")),
        (TextEdit(0, 5, "a"),),
    ],
)
def test_conflicting_or_stale_ranges_fail_without_producing_partial_output(edits: tuple[TextEdit, ...]) -> None:
    with pytest.raises(ValueError, match=r"overlap|ambiguous|exceeds"):
        apply_edits("text", edits)


@pytest.mark.parametrize(("start", "end"), [(-1, 0), (2, 1)])
def test_invalid_ranges_fail_at_construction(start: int, end: int) -> None:
    with pytest.raises(ValueError, match="nonnegative, ordered"):
        TextEdit(start, end, "")


def test_adjacent_replacements_and_boundary_insertions_have_stable_order() -> None:
    assert apply_edits("ab", (TextEdit(0, 1, "A"), TextEdit(1, 2, "B"), TextEdit(2, 2, "!"))) == "AB!"

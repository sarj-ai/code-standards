from dataclasses import replace

import pytest

from sarj_python_lint._fixes import apply_fixes, python_source_hash
from sarj_python_lint.rule_base import AutofixPolicy, Fix, TextEdit


SOURCE = "item = 1\n"
FIX = Fix("Use another constant", AutofixPolicy.SAFE, python_source_hash(SOURCE), (TextEdit(1, 8, 1, 9, "2"),))


def test_apply_safe_group() -> None:
    assert apply_fixes(SOURCE, (FIX,)) == "item = 2\n"


@pytest.mark.parametrize("identifier", ["item", "\u00e9lement"])
@pytest.mark.parametrize("prefix", ["", "\ufeff"], ids=("plain", "bom"))
def test_first_line_edits_use_decoded_utf8_columns(identifier: str, prefix: str) -> None:
    source = f"{identifier} = 1\n"
    column = len(f"{identifier} = ".encode()) + 1
    fix = Fix(
        "Use another constant",
        AutofixPolicy.SAFE,
        python_source_hash(source),
        (TextEdit(1, column, 1, column + 1, "2"),),
    )
    assert apply_fixes(prefix + source, (fix,)) == f"{prefix}{identifier} = 2\n"


@pytest.mark.parametrize("prefix", ["", "\ufeff"], ids=("plain", "bom"))
def test_edit_cannot_insert_an_encoding_prefix(prefix: str) -> None:
    fix = replace(FIX, edits=(TextEdit(1, 1, 1, 1, "\ufeff"),))
    with pytest.raises(SyntaxError):
        apply_fixes(prefix + SOURCE, (fix,))


@pytest.mark.parametrize("prefix", ["", "\ufeff"], ids=("plain", "bom"))
def test_edit_cannot_split_a_utf8_character(prefix: str) -> None:
    source = "\u00e9lement = 1\n"
    fix = replace(FIX, source_hash=python_source_hash(source), edits=(TextEdit(1, 2, 1, 3, "x"),))
    with pytest.raises(UnicodeError):
        apply_fixes(prefix + source, (fix,))


@pytest.mark.parametrize(
    "fixes",
    [
        (replace(FIX, source_hash="stale"),),
        (replace(FIX, safety=AutofixPolicy.SUGGESTION),),
        (replace(FIX, edits=()),),
        (replace(FIX, edits=(TextEdit(2, 2, 2, 3, "2"),)),),
        (replace(FIX, edits=(TextEdit(1, 9, 1, 8, "2"),)),),
        (FIX, FIX),
    ],
    ids=("stale-source", "suggestion", "empty-group", "outside-source", "backwards-range", "overlap"),
)
def test_invalid_group_is_rejected(fixes: tuple[Fix, ...]) -> None:
    with pytest.raises(ValueError, match="fix"):
        apply_fixes(SOURCE, fixes)


def test_complete_revision_guard_includes_unedited_text() -> None:
    with pytest.raises(ValueError, match="revision"):
        apply_fixes("other = 1\n", (FIX,))


def test_reject_malformed_result() -> None:
    with pytest.raises(SyntaxError):
        apply_fixes(SOURCE, (replace(FIX, edits=(TextEdit(1, 8, 1, 9, "("),)),))


@pytest.mark.parametrize(
    "edits",
    [
        (TextEdit(1, 1, 1, 1, "# first\n"), TextEdit(1, 1, 1, 1, "# second\n")),
        (TextEdit(1, 1, 1, 1, "# same\n"), TextEdit(1, 1, 1, 1, "# same\n")),
        (TextEdit(1, 1, 1, 1, "# before\n"), TextEdit(1, 1, 1, 5, "other")),
    ],
    ids=("distinct-insertions", "duplicate-insertion", "insertion-and-replacement"),
)
@pytest.mark.parametrize("separate_groups", [False, True], ids=("one-group", "two-groups"))
def test_rejects_edits_that_share_a_start(edits: tuple[TextEdit, TextEdit], *, separate_groups: bool) -> None:
    fixes = tuple(replace(FIX, edits=(edit,)) for edit in edits) if separate_groups else (replace(FIX, edits=edits),)
    with pytest.raises(ValueError, match="fix groups overlap"):
        apply_fixes(SOURCE, fixes)


def test_accepts_insertion_at_previous_replacement_end() -> None:
    fixes = (replace(FIX, edits=(TextEdit(1, 1, 1, 5, "value"), TextEdit(1, 5, 1, 5, "s"))),)
    assert apply_fixes(SOURCE, fixes) == "values = 1\n"

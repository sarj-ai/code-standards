"""Direct tests for the comment scanner shared by SARJ038 and SARJ054."""

import tokenize

import pytest

from sarj_python_lint.rules._suppression_comments import scan_comments


_MODULE = '''\
# ruff: noqa: E501
"""Docstring."""

import os  # noqa: F401

x = 1  # sarj-noqa: SARJ023 — measured
'''


def test_every_comment_is_described_in_source_order() -> None:
    assert [comment.body for comment in scan_comments(_MODULE)] == [
        "ruff: noqa: E501",
        "noqa: F401",
        "sarj-noqa: SARJ023 — measured",
    ]


def test_a_comment_alone_on_its_line_is_standalone() -> None:
    first, second, third = scan_comments(_MODULE)
    assert first.standalone
    assert not second.standalone
    assert not third.standalone


def test_only_the_comment_above_the_first_statement_is_file_level() -> None:
    """The module docstring is the first statement, so a directive below it is local."""
    first, second, third = scan_comments(_MODULE)
    assert first.before_first_statement
    assert not second.before_first_statement
    assert not third.before_first_statement


def test_columns_are_one_based_for_diagnostics() -> None:
    (comment,) = scan_comments("    # indented\n")
    assert comment.line == 1
    assert comment.col == 5


def test_a_comment_trailing_the_first_statement_is_not_above_it() -> None:
    """Strictly above, not on the same line -- `x = 1  # noqa` is a LOCAL suppression."""
    (comment,) = scan_comments("x = 1  # sarj-noqa: SARJ023\n")
    assert not comment.before_first_statement


def test_a_file_of_nothing_but_comments_has_them_all_before_the_first_statement() -> None:
    assert all(comment.before_first_statement for comment in scan_comments("# a\n# b\n"))


def test_an_unlexable_file_propagates_rather_than_reading_as_comment_free() -> None:
    # Callers treat the raised error as "no diagnostics"; swallowing it here
    # would instead claim the file carries no suppression directives.
    with pytest.raises((tokenize.TokenError, SyntaxError, IndentationError)):
        _ = scan_comments("x = (\n")

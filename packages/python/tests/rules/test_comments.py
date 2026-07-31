"""Direct tests for the comment helpers shared by SARJ016/049/050/051 and SARJ038/054.

Two surfaces, both consumed by several rules and neither tested on its own:

* the nine-signal protected class, which is an EXEMPTION FLOOR -- widening it
  silences rules, narrowing it deletes good comments across a whole corpus; and
* the single tokenize pass the comment and suppression rules share, whose
  standalone/trailing/nesting classification decides which comments each rule
  even sees.
"""

import tokenize

import pytest

from sarj_python_lint.rules._comments import (
    STOPWORDS,
    all_comments,
    code_tokens,
    comment_runs,
    content_tokens,
    has_external_reference,
    is_protected,
    nested_comment_lines,
    restates,
    split_identifier,
    standalone_comments,
    stem,
    trailing_comments,
)


@pytest.mark.parametrize(
    ("signal", "body"),
    [
        ("ref", "see https://example.com/issue"),
        ("ref-ticket", "EN-only for now — AR needs audio (PROJ-249)"),
        ("ref-issue", "works around #1234 in the parser"),
        ("version", "only on ruff >= 0.14"),
        ("units", "retry after 250 ms"),
        ("units-status", "the API answers 429 under load"),
        ("causal", "hoisted because the lock must already be held"),
        ("negation", "NOT a typo"),
        ("upstream", "workaround for the vendored parser"),
        ("invariant", "must run before any worker starts"),
        ("security", "compared in constant-time to avoid a timing attack"),
        ("vendor", "Twilio rejects a body over 1600 characters"),
    ],
)
def test_each_protected_signal_exempts_a_comment(signal: str, body: str) -> None:
    assert is_protected(body), signal


@pytest.mark.parametrize(
    "body",
    [
        "increment the counter",
        "set the value",
        "Create the prompt for Gemini",
        "encoded as UTF-8",
        "hashed with SHA-256",
    ],
)
def test_the_floor_does_not_protect_a_pure_narration(body: str) -> None:
    """The negative controls that keep the leak rate at ~1%.

    A vendor name as the mere OBJECT of a narration verb carries nothing, and
    `UTF-8` / `SHA-256` share the shape of a ticket key without being one.
    """
    assert not is_protected(body)


def test_the_external_reference_signal_is_available_on_its_own() -> None:
    # SARJ051 needs S1 alone: a note with an owner is not an unowned admission.
    assert has_external_reference("blocked on PROJ-249")
    assert has_external_reference("see https://example.com")
    assert not has_external_reference("hacky, fix later")


def test_identifier_splitting_covers_the_three_casings() -> None:
    assert split_identifier("get_user_id") == ["get", "user", "id"]
    assert split_identifier("getUserID") == ["get", "user", "id"]
    assert split_identifier("HTTPResponse") == ["http", "response"]


def test_stemming_is_symmetric_across_the_e_forms() -> None:
    """Without the trailing-`e` strip, `create` and `creates` never match.

    That asymmetry is what most often made a restatement look novel.
    """
    assert stem("creates") == stem("creating") == stem("create")
    assert stem("updated") == stem("updates") == stem("update")
    assert stem("retries") == stem("retry")


def test_a_short_word_is_left_alone() -> None:
    # Below the minimum stem length the inflection strip would eat the word.
    assert stem("is") == "is"
    assert stem("ads") == "ads"


def test_restating_requires_an_exact_or_stemmed_match_not_a_prefix() -> None:
    """Prefix matching is deliberately absent; it drove a ~60% false-positive rate.

    A comment word that is merely a PREFIX of an identifier says something the
    identifier does not; treating it as a restatement is what sank the first
    attempt at this shape (PR #98).
    """
    assert restates(content_tokens("updating the widgets"), code_tokens("def update_widget(): ..."))
    assert not restates(["loc"], code_tokens("location = 1"))


def test_stopwords_are_dropped_from_a_comment_but_not_invented() -> None:
    assert content_tokens("this is the widget") == ["widget"]
    assert "the" in STOPWORDS
    assert "widget" not in STOPWORDS


_SOURCE = """\
# leading note
import os  # trailing note

VALUES = [
    # inside a bracket
    1,
]
"""


def test_standalone_and_trailing_comments_are_separated() -> None:
    standalone, first_code_line = standalone_comments(_SOURCE)
    assert [body for _line, _col, body in standalone] == ["leading note", "inside a bracket"]
    assert [body for _line, _col, body in trailing_comments(_SOURCE)] == ["trailing note"]
    assert first_code_line == 2


def test_a_comment_inside_brackets_is_reported_as_nested() -> None:
    """Depth is the only thing separating "annotates an element" from "signposts the file"."""
    assert nested_comment_lines(_SOURCE) == {5}


def test_consecutive_standalone_comments_group_into_one_run() -> None:
    standalone, _ = standalone_comments("# one\n# two\n\n# far\nx = 1\n")
    assert [[body for _line, _col, body in run] for run in comment_runs(standalone)] == [["one", "two"], ["far"]]


def test_the_suppression_view_shares_the_same_pass() -> None:
    """`all_comments` exists so the suppression rules do not tokenize a second time.

    SARJ038 alone spent ~4% of total rule time on the duplicate pass, deriving
    the same three facts from identical token-class sets.
    """
    ordered, first_code_line = all_comments(_SOURCE)
    assert [(body, standalone) for _line, _col, body, standalone in ordered] == [
        ("leading note", True),
        ("trailing note", False),
        ("inside a bracket", True),
    ]
    assert first_code_line == 2


def test_a_file_the_tokenizer_rejects_raises_rather_than_reading_as_comment_free() -> None:
    # Every caller catches this and returns no diagnostics; swallowing it here
    # would instead report a broken file as having no comments at all.
    with pytest.raises((tokenize.TokenError, SyntaxError, IndentationError)):
        _ = standalone_comments("def f(:\n")

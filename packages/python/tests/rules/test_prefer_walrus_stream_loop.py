from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_walrus_stream_loop import PreferWalrusStreamLoop


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return PreferWalrusStreamLoop().check(Path("example.py"), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferWalrusStreamLoop.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferWalrusStreamLoop().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_while_true_loop_with_assignment_and_break() -> None:
    source = """
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        process(chunk)
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ077"
    assert "while (chunk := ...)" in diags[0].message


def test_flags_none_sentinel_break_after_assignment() -> None:
    source = """
    while True:
        message = queue.receive()
        if message is None:
            break
        consume(message)
    """
    assert len(_check(source)) == 1


def test_leaves_a_while_true_without_the_read_break_shape_alone() -> None:
    """SARJ077 is about the assign-then-break-on-falsy idiom, not `while True` generally."""
    source = """
    while True:
        tick()
        if should_stop():
            break
    """
    assert _check(source) == []


def test_leaves_a_loop_already_using_the_walrus_alone() -> None:
    """Rewriting as the rule asks must silence it, or the advice is unfollowable."""
    source = """
    while (chunk := stream.read(8192)):
        process(chunk)
    """
    assert _check(source) == []


def test_leaves_a_break_on_a_different_variable_alone() -> None:
    """The break has to test the variable that was just assigned; otherwise it is a different loop."""
    source = """
    while True:
        chunk = stream.read(8192)
        if not done:
            break
        process(chunk)
    """
    assert _check(source) == []


def test_leaves_a_loop_with_an_else_clause_alone() -> None:
    source = """
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        process(chunk)
    else:
        finish()
    """
    assert _check(source) == []


def test_leaves_a_non_simple_assignment_target_alone() -> None:
    source = """
    while True:
        state.chunk = stream.read(8192)
        if not state.chunk:
            break
        process(state.chunk)
    """
    assert _check(source) == []


def test_requires_the_break_check_immediately_after_the_assignment() -> None:
    source = """
    while True:
        chunk = stream.read(8192)
        record(chunk)
        if not chunk:
            break
        process(chunk)
    """
    assert _check(source) == []


def test_leaves_a_conditional_with_more_than_the_break_alone() -> None:
    source = """
    while True:
        chunk = stream.read(8192)
        if not chunk:
            close_stream()
            break
        process(chunk)
    """
    assert _check(source) == []


def test_respects_inline_suppression_on_the_assignment() -> None:
    source = """
    while True:
        chunk = stream.read(8192)  # sarj-noqa: SARJ077 — intentional loop shape
        if not chunk:
            break
        process(chunk)
    """
    assert _check(source) == []

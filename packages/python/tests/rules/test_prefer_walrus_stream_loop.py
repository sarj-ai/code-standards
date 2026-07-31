from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

from sarj_python_lint.rules.prefer_walrus_stream_loop import PreferWalrusStreamLoop


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return PreferWalrusStreamLoop().check(Path("example.py"), textwrap.dedent(source))


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

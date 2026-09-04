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
    assert "while (chunk := stream.read(8192))" in diags[0].message


def test_flags_parenthesized_true_condition() -> None:
    source = """
    while (True):
        chunk = stream.read()
        if not chunk:
            break
        consume(chunk)
    """
    assert len(_check(source)) == 1


def test_flags_none_sentinel_break_after_assignment() -> None:
    source = """
    while True:
        message = queue.receive()
        if message is None:
            break
        consume(message)
    """
    diags = _check(source)
    assert len(diags) == 1
    assert "while (message := queue.receive()) is not None:" in diags[0].message


def test_flags_reversed_none_sentinel_without_changing_truthiness() -> None:
    source = """
    while True:
        message = queue.receive()
        if None is message:
            break
        consume(message)
    """
    diags = _check(source)
    assert len(diags) == 1
    assert "is not None:" in diags[0].message


def test_requires_a_nonempty_rewritten_loop_body() -> None:
    source = """
    while True:
        message = receive()
        if message is None:
            break
    """
    assert _check(source) == []


def test_leaves_a_sentinel_guard_with_else_alone() -> None:
    source = """
    while True:
        message = receive()
        if message is None:
            break
        else:
            audit(message)
        consume(message)
    """
    assert _check(source) == []


def test_requires_a_call_based_producer() -> None:
    source = """
    while True:
        enabled = state.enabled
        if not enabled:
            break
        process()
    """
    assert _check(source) == []


def test_accepts_an_awaited_producer_call() -> None:
    source = """
    async def consume_stream() -> None:
        while True:
            chunk = await stream.read()
            if not chunk:
                break
            consume(chunk)
    """
    assert len(_check(source)) == 1


def test_leaves_a_type_commented_assignment_alone() -> None:
    source = """
    while True:
        chunk = stream.read()  # type: bytes
        if not chunk:
            break
        consume(chunk)
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(Path("tests/test_stream.py"), id="test-path"),
        pytest.param(Path("generated/client.py"), id="generated-path"),
    ],
)
def test_excludes_tests_and_generated_files(path: Path) -> None:
    source = textwrap.dedent(
        """
        while True:
            chunk = stream.read()
            if not chunk:
                break
            consume(chunk)
        """
    )
    assert PreferWalrusStreamLoop().check(path, source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
            while True:
                chunk = stream.read()

                if not chunk:
                    break
                consume(chunk)
            """,
            id="blank-line",
        ),
        pytest.param(
            """
            while True:
                chunk = stream.read()  # Keep the read visible for protocol tracing.
                if not chunk:
                    break
                consume(chunk)
            """,
            id="assignment-comment",
        ),
        pytest.param(
            """
            while True:
                chunk = stream.read()
                if not chunk:  # Empty bytes terminate this transport.
                    break
                consume(chunk)
            """,
            id="guard-comment",
        ),
    ],
)
def test_leaves_comments_and_blank_lines_alone(source: str) -> None:
    assert _check(source) == []


def test_leaves_multiline_or_overlong_rewrites_alone() -> None:
    multiline = """
    while True:
        chunk = stream.read(
            8192,
        )
        if not chunk:
            break
        consume(chunk)
    """
    long_name = "producer_with_a_name_that_would_make_the_rewritten_while_condition_far_too_long_for_the_project_limit"
    overlong = f"""
    while True:
        chunk = {long_name}()
        if not chunk:
            break
        consume(chunk)
    """
    assert _check(multiline) == []
    assert _check(overlong) == []


def test_malformed_source_is_ignored() -> None:
    assert _check("while True:\n    chunk = read(\n    break\n") == []


def test_leaves_a_while_true_without_the_read_break_shape_alone() -> None:
    source = """
    while True:
        tick()
        if should_stop():
            break
    """
    assert _check(source) == []


def test_leaves_a_loop_already_using_the_walrus_alone() -> None:
    source = """
    while (chunk := stream.read(8192)):
        process(chunk)
    """
    assert _check(source) == []


def test_leaves_a_break_on_a_different_variable_alone() -> None:
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

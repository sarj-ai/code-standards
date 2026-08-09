from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_walrus_comprehension_filter import PreferWalrusComprehensionFilter


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return PreferWalrusComprehensionFilter().check(Path("example.py"), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferWalrusComprehensionFilter.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferWalrusComprehensionFilter().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_repeated_function_call_in_comprehension() -> None:
    source = """
    def collect():
        return [compute(x) for x in range(10) if compute(x)]
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ076"
    assert "Repeated function call in comprehension filter" in diags[0].message


def test_leaves_repeated_attribute_lookup_alone() -> None:
    source = """
    def collect(items):
        return [item.value for item in items if item.value is not None]
    """
    assert _check(source) == []


def test_flags_an_exact_repeated_method_call() -> None:
    source = """
    def collect(items):
        return [item.render() for item in items if item.render()]
    """
    assert len(_check(source)) == 1


def test_leaves_the_same_method_with_different_arguments_alone() -> None:
    source = """
    def collect(items, renderer):
        return [renderer.render(item.output) for item in items if renderer.render(item.input)]
    """
    assert _check(source) == []


def test_leaves_a_filter_that_does_not_repeat_the_element_alone() -> None:
    """The only shape SARJ076 exists for is the repeated call."""
    source = """
    def collect():
        return [compute(x) for x in range(10) if x > 0]
    """
    assert _check(source) == []


def test_leaves_a_filter_already_using_the_walrus_alone() -> None:
    """Rewriting as the rule asks must silence it, or the advice is unfollowable."""
    source = """
    def collect():
        return [value for x in range(10) if (value := compute(x))]
    """
    assert _check(source) == []


def test_leaves_isinstance_style_guards_alone() -> None:
    """`isinstance(x, T)` in the filter is a type narrowing, not a repeated computation."""
    source = """
    def collect(values):
        return [isinstance(x, str) for x in values if isinstance(x, str)]
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("items = [compute(x) for x in values if compute(x)]", id="module"),
        pytest.param("items = (compute(x) for x in values if compute(x))", id="module-generator"),
        pytest.param(
            """
            class Values:
                items = [compute(x) for x in values if compute(x)]
            """,
            id="class",
        ),
        pytest.param(
            """
            def outer():
                class Values:
                    items = [compute(x) for x in values if compute(x)]
            """,
            id="nested-class",
        ),
        pytest.param(
            """
            def collect(items=[compute(x) for x in values if compute(x)]):
                return items
            """,
            id="function-default",
        ),
        pytest.param(
            """
            def collect():
                items: [compute(x) for x in values if compute(x)]
            """,
            id="local-annotation",
        ),
        pytest.param(
            """
            def collect():
                type Items = [compute(x) for x in values if compute(x)]
            """,
            id="type-alias",
        ),
        pytest.param(
            """
            def outer():
                def collect[T: [compute(x) for x in values if compute(x)]]():
                    return T
            """,
            id="type-parameter-bound",
        ),
        pytest.param(
            """
            from __future__ import annotations

            def outer():
                def collect(value: [compute(x) for x in values if compute(x)]):
                    return value
            """,
            id="postponed-annotation",
        ),
        pytest.param(
            """
            def outer():
                def collect() -> [compute(x) for x in values if compute(x)]:
                    return []
            """,
            id="return-annotation",
        ),
    ],
)
def test_leaves_calls_outside_callable_bodies_alone(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
            class Values:
                def collect(self):
                    return [compute(x) for x in self.values if compute(x)]
            """,
            id="method",
        ),
        pytest.param(
            "collect = lambda values: [compute(x) for x in values if compute(x)]",
            id="lambda",
        ),
        pytest.param(
            """
            def collect(values):
                items: list = [compute(x) for x in values if compute(x)]
                return items
            """,
            id="annotated-value",
        ),
    ],
)
def test_flags_calls_inside_callable_bodies(source: str) -> None:
    assert len(_check(source)) == 1

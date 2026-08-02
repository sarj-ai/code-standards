from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

from sarj_python_lint.rules.prefer_walrus_comprehension_filter import PreferWalrusComprehensionFilter


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return PreferWalrusComprehensionFilter().check(Path("example.py"), textwrap.dedent(source))


def test_flags_repeated_expression_in_comprehension() -> None:
    source = """
    items = [compute(x) for x in range(10) if compute(x)]
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ076"
    assert "Repeated expression in comprehension filter" in diags[0].message


def test_flags_repeated_attribute_lookup_in_comprehension() -> None:
    source = """
    values = [item.value for item in items if item.value is not None]
    """
    assert len(_check(source)) == 1


def test_leaves_a_filter_that_does_not_repeat_the_element_alone() -> None:
    """The only shape SARJ076 exists for is the repeated call. A different one is fine."""
    source = """
    items = [compute(x) for x in range(10) if x > 0]
    """
    assert _check(source) == []


def test_leaves_a_filter_already_using_the_walrus_alone() -> None:
    """Rewriting as the rule asks must silence it, or the advice is unfollowable."""
    source = """
    items = [value for x in range(10) if (value := compute(x))]
    """
    assert _check(source) == []


def test_leaves_isinstance_style_guards_alone() -> None:
    """`isinstance(x, T)` in the filter is a type narrowing, not a repeated computation."""
    source = """
    names = [isinstance(x, str) for x in values if isinstance(x, str)]
    """
    assert _check(source) == []

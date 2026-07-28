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

from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

from sarj_python_lint.rules.prefer_walrus_regex_match import PreferWalrusRegexMatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return PreferWalrusRegexMatch().check(Path("example.py"), textwrap.dedent(source))


def test_flags_regex_search_before_if() -> None:
    source = """
    import re

    def f(text):
        m = re.search(r"\\d+", text)
        if m:
            return m.group(0)
        return None
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ081"
    assert "Regex match pre-assignment `m = ...` before `if`" in diags[0].message


def test_does_not_flag_non_regex_assignments() -> None:
    source = """
    def f(x):
        val = compute(x)
        if val:
            return val
        return None
    """
    diags = _check(source)
    assert len(diags) == 0

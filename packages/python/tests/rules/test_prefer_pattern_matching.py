from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

from sarj_python_lint.rules.prefer_pattern_matching import PreferPatternMatching


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return PreferPatternMatching().check(Path("example.py"), textwrap.dedent(source))


def test_flags_or_patterns_in_match():
    source = """
    def f(x):
        match x:
            case Foo():
                res = 1
            case Bar():
                res = 1
        return res
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ079"
    assert "consecutive `case` arms repeat an identical body" in diags[0].message


def test_flags_regex_walrus_match():
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
    assert diags[0].code == "SARJ079"
    assert "Regex match pre-assignment" in diags[0].message

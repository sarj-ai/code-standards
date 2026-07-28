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

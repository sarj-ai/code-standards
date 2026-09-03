from pathlib import Path

from sarj_python_lint.rule_base import Diagnostic, is_suppressed


def test_sarj_noqa_suppresses_diag():
    src = "query = 'SELECT * FROM calls'  # sarj-noqa: SARJ021 — grandfathered 2026-05-20\n"
    assert is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def test_bare_sarj_noqa_also_suppresses():
    src = "query = 'SELECT * FROM calls'  # sarj-noqa\n"
    assert is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def test_sarj_noqa_with_different_code_does_not_suppress():
    src = "query = 'SELECT * FROM calls'  # sarj-noqa: SARJ999\n"
    assert not is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def test_ruff_noqa_does_not_suppress_sarj():
    """Plain `# noqa: SARJ021` does NOT suppress — must use `# sarj-noqa:`."""
    src = "query = 'SELECT * FROM calls'  # noqa: SARJ021 — old syntax\n"
    assert not is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def _diagnostic() -> Diagnostic:
    return Diagnostic(path=Path("<t>.py"), line=1, col=1, code="SARJ021", message="test")

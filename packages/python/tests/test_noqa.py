"""Test that # sarj-noqa: SARJ00X suppression works on real diagnostics."""

from pathlib import Path

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.no_sequential_await import NoSequentialAwait


def test_sarj_noqa_suppresses_diag():
    src = """
async def f(items):
    for x in items:
        result = await call(x)  # sarj-noqa: SARJ001 — grandfathered 2026-05-20
"""
    diags = NoSequentialAwait().check(Path("<t>.py"), src)
    # Rule still fires
    assert len(diags) == 1
    # But the helper detects the suppression on that line
    assert is_suppressed(src.splitlines(), diags[0].line, "SARJ001")


def test_bare_sarj_noqa_also_suppresses():
    src = "async def f():\n    for x in []:\n        await g(x)  # sarj-noqa\n"
    diags = NoSequentialAwait().check(Path("<t>.py"), src)
    assert len(diags) == 1
    assert is_suppressed(src.splitlines(), diags[0].line, "SARJ001")


def test_sarj_noqa_with_different_code_does_not_suppress():
    src = """
async def f():
    for x in []:
        await g(x)  # sarj-noqa: SARJ999
"""
    diags = NoSequentialAwait().check(Path("<t>.py"), src)
    assert len(diags) == 1
    assert not is_suppressed(src.splitlines(), diags[0].line, "SARJ001")


def test_ruff_noqa_does_not_suppress_sarj():
    """Plain `# noqa: SARJ001` does NOT suppress — must use `# sarj-noqa:`."""
    src = """
async def f():
    for x in []:
        await g(x)  # noqa: SARJ001 — old syntax
"""
    diags = NoSequentialAwait().check(Path("<t>.py"), src)
    assert len(diags) == 1
    assert not is_suppressed(src.splitlines(), diags[0].line, "SARJ001")

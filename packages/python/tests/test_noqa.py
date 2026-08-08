"""Test that # sarj-noqa: SARJ00X suppression works on real diagnostics."""

from pathlib import Path

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.no_stdlib_logging import NoStdlibLogging


def test_sarj_noqa_suppresses_diag():
    src = "import logging  # sarj-noqa: SARJ052 — grandfathered 2026-05-20\n"
    diags = NoStdlibLogging().check(Path("<t>.py"), src)
    # Rule still fires
    assert len(diags) == 1
    # But the helper detects the suppression on that line
    assert is_suppressed(src.splitlines(), diags[0].line, "SARJ052")


def test_bare_sarj_noqa_also_suppresses():
    src = "import logging  # sarj-noqa\n"
    diags = NoStdlibLogging().check(Path("<t>.py"), src)
    assert len(diags) == 1
    assert is_suppressed(src.splitlines(), diags[0].line, "SARJ052")


def test_sarj_noqa_with_different_code_does_not_suppress():
    src = "import logging  # sarj-noqa: SARJ999\n"
    diags = NoStdlibLogging().check(Path("<t>.py"), src)
    assert len(diags) == 1
    assert not is_suppressed(src.splitlines(), diags[0].line, "SARJ052")


def test_ruff_noqa_does_not_suppress_sarj():
    """Plain `# noqa: SARJ052` does NOT suppress — must use `# sarj-noqa:`."""
    src = "import logging  # noqa: SARJ052 — old syntax\n"
    diags = NoStdlibLogging().check(Path("<t>.py"), src)
    assert len(diags) == 1
    assert not is_suppressed(src.splitlines(), diags[0].line, "SARJ052")

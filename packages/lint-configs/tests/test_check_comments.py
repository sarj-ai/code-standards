from __future__ import annotations

from pathlib import Path
import pytest

from sarj_lint_configs.check_comments import check_file


def test_check_comments_detects_useless_restatements(tmp_path: Path) -> None:
    code_file = tmp_path / "sample.py"
    code_file.write_text(
        "# return x\n"
        "def foo(x):\n"
        "    # increment i\n"
        "    i = 1\n"
        "    return x\n"
    )
    issues = check_file(str(code_file))
    assert len(issues) >= 1
    assert any("Useless translational comment" in issue for issue in issues)


def test_check_comments_allows_explanatory_context(tmp_path: Path) -> None:
    code_file = tmp_path / "sample.py"
    code_file.write_text(
        "# Return raw value when type is unknown\n"
        "def get_raw(val):\n"
        "    # Set PYTHONUNBUFFERED for immediate log flushing\n"
        "    return val\n"
    )
    issues = check_file(str(code_file))
    assert not any("Useless translational comment" in issue for issue in issues)


def test_check_comments_detects_ascii_banners(tmp_path: Path) -> None:
    code_file = tmp_path / "sample.py"
    code_file.write_text(
        "# ===== RESPONSES API =====\n"
        "def handle_resp():\n"
        "    pass\n"
    )
    issues = check_file(str(code_file))
    assert any("ASCII visual banner" in issue for issue in issues)


def test_check_comments_detects_untracked_todos(tmp_path: Path) -> None:
    code_file = tmp_path / "sample.py"
    code_file.write_text(
        "# TODO fix this later # noqa: TD002\n"
        "def handle_resp():\n"
        "    pass\n"
    )
    issues = check_file(str(code_file))
    assert any("Untracked TODO/FIXME" in issue for issue in issues)


def test_check_comments_allows_tracked_todos(tmp_path: Path) -> None:
    code_file = tmp_path / "sample.py"
    code_file.write_text(
        "# TODO: JIRA-1234 remove when Python 3.10 support is dropped\n"
        "def handle_resp():\n"
        "    pass\n"
    )
    issues = check_file(str(code_file))
    assert not any("Untracked TODO/FIXME" in issue for issue in issues)


def test_check_comments_detects_trivial_docstrings(tmp_path: Path) -> None:
    code_file = tmp_path / "sample.py"
    code_file.write_text(
        "def get_user():\n"
        '    """Get user."""\n'
        "    pass\n"
    )
    issues = check_file(str(code_file))
    assert any("Trivial docstring duplicates signature" in issue for issue in issues)

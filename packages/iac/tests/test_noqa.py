"""End-to-end `# sarj-noqa` suppression through the CLI entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_iac_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_bare_noqa_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_NOQA_BARE)])
    assert rc == 0
    assert not capsys.readouterr().out


def test_coded_noqa_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_NOQA_CODE)])
    assert rc == 0
    assert not capsys.readouterr().out


def test_wrong_code_does_not_suppress(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_NOQA_WRONG)])
    assert rc == 1
    assert "SARJ201" in capsys.readouterr().out


def test_absent_noqa_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_PLAIN)])
    assert rc == 1
    assert "SARJ201" in capsys.readouterr().out


def _write(tmp_path: Path, content: str) -> str:
    f = tmp_path / "main.tf"
    _ = f.write_text(content, encoding="utf-8")
    return str(f)


_SQL_PLAIN = """
resource "google_sql_database_instance" "main" {
  name = "prod"
}
"""

_SQL_NOQA_BARE = """
resource "google_sql_database_instance" "main" {  # sarj-noqa
  name = "prod"
}
"""

_SQL_NOQA_CODE = """
resource "google_sql_database_instance" "main" {  # sarj-noqa: SARJ201 — ephemeral
  name = "prod"
}
"""

_SQL_NOQA_WRONG = """
resource "google_sql_database_instance" "main" {  # sarj-noqa: SARJ999
  name = "prod"
}
"""

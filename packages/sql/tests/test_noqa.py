"""End-to-end suppression: `-- sarj-noqa[: CODE]` on a diagnostic's line drops it."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from sarj_sql_lint.__main__ import main
from sarj_sql_lint.rule_base import is_suppressed


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(tmp_path: Path, text: str) -> Path:
    f = tmp_path / "migration.sql"
    _ = f.write_text(text, encoding="utf-8")
    return f


class _RunResult(NamedTuple):
    exit_code: int
    lines: list[str]


def _run(rule: str, f: Path, capsys: pytest.CaptureFixture[str]) -> _RunResult:
    code = main(["check", "--rule", rule, str(f)])
    out = capsys.readouterr().out
    return _RunResult(code, [line for line in out.splitlines() if line])


def test_bare_noqa_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "-- dialect: postgresql\ncreated_at TIMESTAMP NOT NULL -- sarj-noqa\n")
    result = _run("enforce-timestamptz", f, capsys)
    assert result.exit_code == 0
    assert result.lines == []


def test_noqa_with_matching_code_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "-- dialect: postgresql\ncreated_at TIMESTAMP NOT NULL -- sarj-noqa: SARJ101\n")
    result = _run("enforce-timestamptz", f, capsys)
    assert result.exit_code == 0
    assert result.lines == []


def test_noqa_with_other_code_does_not_suppress(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "-- dialect: postgresql\ncreated_at TIMESTAMP NOT NULL -- sarj-noqa: SARJ999\n")
    result = _run("enforce-timestamptz", f, capsys)
    assert result.exit_code == 1
    assert len(result.lines) == 1


def test_no_noqa_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "-- dialect: postgresql\ncreated_at TIMESTAMP NOT NULL\n")
    result = _run("enforce-timestamptz", f, capsys)
    assert result.exit_code == 1
    assert len(result.lines) == 1


def test_noqa_only_suppresses_its_own_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(
        tmp_path,
        "CREATE TABLE a (id INT); -- sarj-noqa: SARJ102\nCREATE TABLE b (id INT);\n",
    )
    result = _run("idempotent-ddl", f, capsys)
    assert result.exit_code == 1
    assert len(result.lines) == 1
    assert ":2:" in result.lines[0]


def test_is_suppressed_unit():
    source_lines = ["DROP TABLE x; -- sarj-noqa: SARJ102, SARJ108"]
    assert is_suppressed(source_lines, 1, "SARJ102")
    assert is_suppressed(source_lines, 1, "sarj108")
    assert not is_suppressed(source_lines, 1, "SARJ101")

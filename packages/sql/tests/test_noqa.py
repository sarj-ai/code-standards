"""End-to-end suppression: `-- sarj-noqa[: CODE]` on a diagnostic's line drops it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_sql_lint.__main__ import main
from sarj_sql_lint.rule_base import is_suppressed


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(tmp_path: Path, text: str) -> Path:
    f = tmp_path / "migration.sql"
    _ = f.write_text(text, encoding="utf-8")
    return f


def _run(rule: str, f: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
    code = main(["check", "--rule", rule, str(f)])
    out = capsys.readouterr().out
    return code, [line for line in out.splitlines() if line]


def test_bare_noqa_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "created_at TIMESTAMP NOT NULL -- sarj-noqa\n")
    code, lines = _run("enforce-timestamptz", f, capsys)
    assert code == 0
    assert lines == []


def test_noqa_with_matching_code_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "created_at TIMESTAMP NOT NULL -- sarj-noqa: SARJ101\n")
    code, lines = _run("enforce-timestamptz", f, capsys)
    assert code == 0
    assert lines == []


def test_noqa_with_other_code_does_not_suppress(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "created_at TIMESTAMP NOT NULL -- sarj-noqa: SARJ999\n")
    code, lines = _run("enforce-timestamptz", f, capsys)
    assert code == 1
    assert len(lines) == 1


def test_no_noqa_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(tmp_path, "created_at TIMESTAMP NOT NULL\n")
    code, lines = _run("enforce-timestamptz", f, capsys)
    assert code == 1
    assert len(lines) == 1


def test_noqa_only_suppresses_its_own_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    f = _write(
        tmp_path,
        "CREATE TABLE a (id INT); -- sarj-noqa: SARJ102\nCREATE TABLE b (id INT);\n",
    )
    code, lines = _run("idempotent-ddl", f, capsys)
    assert code == 1
    assert len(lines) == 1
    assert ":2:" in lines[0]


def test_is_suppressed_unit():
    source_lines = ["DROP TABLE x; -- sarj-noqa: SARJ102, SARJ108"]
    assert is_suppressed(source_lines, 1, "SARJ102")
    assert is_suppressed(source_lines, 1, "sarj108")
    assert not is_suppressed(source_lines, 1, "SARJ101")

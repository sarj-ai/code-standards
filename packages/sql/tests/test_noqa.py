from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sarj_sql_lint.__main__ import analyze, main
from sarj_sql_lint.rule_base import is_suppressed


if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, text: str) -> Path:
    f = tmp_path / "migration.sql"
    f.write_text(text, encoding="utf-8")
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


@pytest.mark.parametrize(
    "source",
    [
        "SELECT id FROM event LIMIT :limit OFFSET :offset; SELECT `-- sarj-noqa: SARJ107 -- source data` FROM event;\n",
        "SELECT id FROM event LIMIT :limit OFFSET :offset; SELECT `prefix``-- sarj-noqa: SARJ107 -- source data` FROM event;\n",
    ],
)
@pytest.mark.parametrize("crlf", [False, True])
def test_unannotated_backtick_identifier_data_cannot_waive_queries(source: str, tmp_path: Path, *, crlf: bool) -> None:
    source = source.replace("\n", "\r\n") if crlf else source
    path = tmp_path / "events.sql"
    path.write_bytes(source.encode())
    findings = analyze(["no-offset-pagination"], [path])
    assert len(findings) == 1
    assert findings == analyze(["no-offset-pagination"], [path])


@pytest.mark.parametrize(
    "source",
    [
        "SELECT id FROM event LIMIT :limit OFFSET :offset; SELECT public_values[1 -- sarj-noqa: SARJ107 -- reason mentions ] as text\n] FROM event;\n",
        "-- dialect: postgresql\nSELECT id FROM event LIMIT :limit OFFSET :offset; SELECT public_values[1 -- sarj-noqa: SARJ107 -- reason mentions ] as text\n] FROM event;\n",
    ],
)
@pytest.mark.parametrize("crlf", [False, True])
def test_postgres_array_comment_prose_keeps_existing_waiver(source: str, tmp_path: Path, *, crlf: bool) -> None:
    source = source.replace("\n", "\r\n") if crlf else source
    path = tmp_path / "events.sql"
    path.write_bytes(source.encode())
    assert analyze(["no-offset-pagination"], [path]) == []


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("-- sarj-noqa: SARJ104,,SARJ105", 1),
        ("-- sarj-noqa: ,SARJ104", 1),
        ("-- sarj-noqa: SARJ104,", 1),
        ("-- sarj-noqa: 1,SARJ104", 1),
        ("-- sarj-noqa: SARJ104,SARJ 105", 1),
        ("-- sarj-noqa: SARJ104 - external contract", 0),
        ("-- sarj-noqa: SARJ104 -\texternal contract", 0),
        ("-- sarj-noqa: SARJ104 -external contract", 0),
        ("-- sarj-noqa: SARJ104\t- external contract", 0),
        ("-- sarj-noqa: SARJ104\t-- external contract", 0),
        ("-- sarj-noqa: SARJ104-extra", 1),
        ("-- sarj-noqa: SARJ104- external contract", 1),
        ("-- sarj-noqa: SARJ104,\tSARJ105 -- contract", 0),
        ("-- sarj-noqa: SARJ104, SARJ104 -- duplicate code", 0),
        ("-- sarj-noqa: SARJ104extra -- unrelated code", 1),
        ("-- SaRj-NoQa: sarj104 — external contract", 0),
    ],
)
@pytest.mark.parametrize("crlf", [False, True])
def test_noqa_requires_complete_codes_and_preserves_reason_boundaries(
    marker: str, expected: int, tmp_path: Path, *, crlf: bool
) -> None:
    source = f"CREATE TABLE public_example (name VARCHAR(20)); {marker}\n"
    source = source.replace("\n", "\r\n") if crlf else source
    path = tmp_path / "migration.sql"
    path.write_bytes(source.encode())
    findings = analyze(["prefer-text-over-varchar"], [path])
    assert len(findings) == expected
    assert findings == analyze(["prefer-text-over-varchar"], [path])

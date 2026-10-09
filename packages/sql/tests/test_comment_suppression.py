from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.rule_base import is_suppressed
from sarj_sql_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("tail", "count"),
    [
        pytest.param(", note TEXT DEFAULT '-- sarj-noqa: SARJ104 -- external contract');", 1, id="string-data"),
        pytest.param(
            ", note TEXT DEFAULT E'escaped\\' -- sarj-noqa: SARJ104 -- source data');", 1, id="escaped-string"
        ),
        pytest.param(
            ", note TEXT DEFAULT 'doubled'' -- sarj-noqa: SARJ104 -- source data');", 1, id="doubled-string-quote"
        ),
        pytest.param(", note TEXT DEFAULT $doc$-- sarj-noqa: SARJ104 -- source data$doc$);", 1, id="dollar-data"),
        pytest.param('); SELECT "-- sarj-noqa: SARJ104 -- source data";', 1, id="quoted-identifier"),
        pytest.param(", note TEXT DEFAULT '-- sarj-noqa: SARJ104", 1, id="unterminated-string"),
        pytest.param(", note TEXT DEFAULT $doc$-- sarj-noqa: SARJ104", 1, id="unterminated-dollar"),
        pytest.param("); /* -- sarj-noqa: SARJ104 -- source data */", 1, id="block-comment-prose"),
        pytest.param("); /* nested /* -- sarj-noqa: SARJ104 -- source data */ */", 1, id="nested-block-comment"),
        pytest.param("); /* -- sarj-noqa: SARJ104", 1, id="unterminated-block"),
        pytest.param("); -- sarj-noqa: SARJ104 -- required by external field contract", 0, id="reasoned-comment"),
        pytest.param("); -- SARJ-NOQA: sarj104 -- external field contract", 0, id="case-insensitive-code"),
        pytest.param("); -- sarj-noqa: SARJ101, SARJ104 -- external field contract", 0, id="exact-code-list"),
        pytest.param("); -- sarj-noqa -- retained legacy bare waiver", 0, id="legacy-bare"),
        pytest.param("); -- sarj-noqa: SARJ101 -- unrelated rule", 1, id="other-code"),
        pytest.param("); -- sarj-noqax: SARJ104", 1, id="directive-prefix-near-miss"),
        pytest.param("); -- prose explains -- sarj-noqa: SARJ104", 1, id="quoted-comment-documentation"),
        pytest.param("); -- sarj-noqa:", 1, id="empty-explicit-code"),
        pytest.param("); -- sarj-noqa-example: SARJ104", 1, id="hyphenated-directive-near-miss"),
        pytest.param("); -- sarj-noqa: SARJ104???", 1, id="malformed-code-tail"),
    ],
)
def test_data_cannot_waive_sql_findings(*, tmp_path: Path, tail: str, count: int) -> None:
    path = tmp_path / "migrations/001_public.sql"
    path.parent.mkdir()
    source = f"CREATE TABLE public_example (name VARCHAR(20){tail}\n"
    path.write_text(source, encoding="utf-8")
    first = analyze(["prefer-text-over-varchar"], [path])
    second = analyze(["prefer-text-over-varchar"], [path])
    assert first == second
    assert len(first) == count
    assert len({(finding.line, finding.col, finding.code) for finding in first}) == count
    assert is_suppressed(source.splitlines(), 1, "SARJ104") is (count == 0)


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_line_scope_and_string_context_survive_line_endings(*, tmp_path: Path, line_ending: str) -> None:
    path = tmp_path / "migrations/001_public.sql"
    path.parent.mkdir()
    source = line_ending.join(
        [
            "-- sarj-noqa: SARJ104 -- applies only to this line",
            "CREATE TABLE first_public (name VARCHAR(20), note TEXT DEFAULT '",
            "-- sarj-noqa: SARJ104'); CREATE TABLE second_public (name VARCHAR(20));",
            "CREATE TABLE third_public (name VARCHAR(20)); -- sarj-noqa: SARJ104 -- external contract",
        ]
    )
    path.write_bytes(source.encode())
    findings = analyze(["prefer-text-over-varchar"], [path])
    assert [finding.line for finding in findings] == [2, 3]
    assert len({(finding.line, finding.col) for finding in findings}) == len(findings)


@pytest.mark.parametrize(
    ("dialect", "marker"),
    [
        ("mysql", "`-- sarj-noqa: SARJ107 -- source data`"),
        ("mariadb", "`-- sarj-noqa: SARJ107 -- source data`"),
        ("sqlite", "`-- sarj-noqa: SARJ107 -- source data`"),
        ("sqlite", "[-- sarj-noqa: SARJ107 -- source data]"),
    ],
)
def test_declared_cross_dialect_identifiers_are_data(*, tmp_path: Path, dialect: str, marker: str) -> None:
    path = tmp_path / "queries/events.sql"
    path.parent.mkdir()
    source = f"-- dialect: {dialect}\nSELECT id FROM event LIMIT :limit OFFSET :offset; SELECT {marker};\n"
    path.write_text(source, encoding="utf-8")
    findings = analyze(["no-offset-pagination"], [path])
    assert len(findings) == 1
    assert not is_suppressed(source.splitlines(), 2, "SARJ107")


@pytest.mark.parametrize("prefix", ["", "-- dialect: postgresql\n", "SELECT $doc$\n-- dialect: sqlite\n$doc$;\n"])
def test_postgresql_array_comments_keep_valid_waivers(*, tmp_path: Path, prefix: str) -> None:
    path = tmp_path / "queries/events.sql"
    path.parent.mkdir()
    query = (
        "SELECT id FROM event LIMIT :limit OFFSET :offset; "
        "SELECT public_values[1 -- sarj-noqa: SARJ107 -- bounded request contract\n];\n"
    )
    source = prefix + query
    path.write_text(source, encoding="utf-8")
    assert analyze(["no-offset-pagination"], [path]) == []


@pytest.mark.parametrize(
    "source",
    [
        "DO $$ CREATE TABLE public_example (name VARCHAR(20)); -- sarj-noqa: SARJ104 -- external contract\n$$;",
        "CREATE FUNCTION public_example() RETURNS void AS $body$ CREATE TABLE public_values (name VARCHAR(20)); -- sarj-noqa: SARJ104 -- external contract\n$body$ LANGUAGE sql;",
    ],
)
def test_executable_dollar_body_comments_remain_local_waivers(*, tmp_path: Path, source: str) -> None:
    path = tmp_path / "migrations/001_public.sql"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    assert analyze(["prefer-text-over-varchar"], [path]) == []


def test_changed_source_does_not_reuse_old_waiver(*, tmp_path: Path) -> None:
    path = tmp_path / "migrations/001_public.sql"
    path.parent.mkdir()
    path.write_text("CREATE TABLE public_example (name VARCHAR(20)); -- sarj-noqa: SARJ104 -- external contract\n")
    assert analyze(["prefer-text-over-varchar"], [path]) == []
    path.write_text("CREATE TABLE public_example (name VARCHAR(20), note TEXT DEFAULT '-- sarj-noqa: SARJ104');\n")
    assert len(analyze(["prefer-text-over-varchar"], [path])) == 1


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_all_registered_sql_examples_preserve_counts(*, tmp_path: Path, rule_id: str, line_ending: str) -> None:
    specification = REGISTRY[rule_id].native_spec()
    assert specification is not None
    for index, example in enumerate(specification.examples):
        root = tmp_path / str(index)
        (root / ".git").mkdir(parents=True)
        for file in example.files:
            path = root / file.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file.source.replace("\r\n", "\n").replace("\n", line_ending).encode())
        findings = analyze([rule_id], [root / example.focus_path])
        assert len(findings) == example.expected_count
        assert len({(finding.path, finding.line, finding.col, finding.code) for finding in findings}) == len(findings)

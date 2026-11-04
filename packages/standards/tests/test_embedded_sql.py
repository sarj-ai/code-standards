from __future__ import annotations

from dataclasses import replace
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import Standards
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, CoverageDisposition
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.embedded_sql import analyze_sources, with_embedded_sql
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.linting.process import ProcessCapabilities, ProcessOutput, ProcessRequest, RequestExecutor


if TYPE_CHECKING:
    from pathlib import Path


def _write_query(root: Path, expression: str) -> Path:
    path = root / "store.py"
    path.write_text(
        f"from psycopg import Connection\ndef query(conn: Connection):\n    return conn.execute({expression})\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT a UNION SELECT a, b", {"AM07"}),
        ("SELECT a.id FROM a JOIN b", {"AM08"}),
        ("SELECT a UNION SELECT b", set[str]()),
        ("SELECT a.id FROM a JOIN b ON a.id = b.id", set[str]()),
        ("SELECT a.id FROM a CROSS JOIN b", set[str]()),
        ("SELECT a FROM calls WHERE id = %s", set[str]()),
        ("SELECT a FROM calls WHERE id = %(call_id)s", set[str]()),
    ],
    ids=[
        "union-column-mismatch",
        "missing-join-condition",
        "matching-union",
        "explicit-join",
        "explicit-cross-join",
        "positional-parameter",
        "named-parameter",
    ],
)
def test_native_sqlfluff_checks_static_python_queries(tmp_path: Path, query: str, expected: set[str]) -> None:
    path = _write_query(tmp_path, repr(query))

    report = analyze_sources((str(path),), root=tmp_path)

    assert report.completion is Completion.COMPLETE
    assert not report.issues
    assert {item.code for item in report.diagnostics} == expected


def test_reports_native_failure_on_the_original_python_line(tmp_path: Path) -> None:
    path = _write_query(tmp_path, '"""SELECT a\nUNION SELECT a, b"""')

    report = analyze_sources((str(path),), root=tmp_path)

    assert report.diagnostics
    for finding in report.diagnostics:
        assert finding.location.path == "store.py"
        assert finding.location.position is not None
        assert finding.location.position.line in {2, 3}
        assert finding.location.position.byte_offset >= path.read_bytes().index(b"SELECT")


def test_dynamic_sql_is_a_visible_nonblocking_coverage_gap(tmp_path: Path) -> None:
    path = _write_query(tmp_path, 'f"SELECT {column} FROM calls"')

    report = analyze_sources((str(path),), root=tmp_path)

    assert not report.diagnostics
    assert not report.issues
    assert len(report.coverage) == 1
    assert report.coverage[0].disposition is CoverageDisposition.UNSUPPORTED
    assert report.coverage[0].file_count == 1


def test_manifest_upgrade_does_not_enable_embedded_sql_implicitly() -> None:
    previous = manifest.Manifest(
        version="8.183.4", configs=("ruff", "pyright"), python_dest=".", typescript_dest=".", disabled_capabilities=()
    )
    upgraded = replace(previous, version="8.190.0", disabled_capabilities=manifest.OPTIONAL_ANALYZERS)
    enabled = replace(upgraded, disabled_capabilities=manifest.QUALITY_ANALYZERS)

    assert "sqlfluff" not in previous.enabled_capabilities
    assert "sqlfluff" not in upgraded.enabled_capabilities
    assert "sqlfluff" in enabled.enabled_capabilities


def test_native_report_obeys_existing_rule_exclusions(tmp_path: Path) -> None:
    path = _write_query(tmp_path, repr("SELECT a UNION SELECT a, b"))
    adopted = manifest.Manifest(
        version="8.190.0",
        configs=("ruff", "pyright"),
        python_dest=".",
        typescript_dest=".",
        disabled_capabilities=manifest.QUALITY_ANALYZERS,
        excluded_rules=("sqlfluff:AM07",),
    )
    policy = Policy.from_manifest(tmp_path, adopted)

    report = with_embedded_sql(report_from_tools(tmp_path, ()), files=(str(path),), adopted=adopted, policy=policy)

    assert report.tools
    assert not report.diagnostics
    assert not report.issues


@pytest.mark.parametrize("query", ["SELECT (", "-- sqlfluff:templater:jinja\nSELECT {{ unsafe() }}"])
def test_unparseable_sql_and_inline_configuration_are_coverage_gaps(tmp_path: Path, query: str) -> None:
    path = _write_query(tmp_path, '"""' + query + '"""')

    report = analyze_sources((str(path),), root=tmp_path)

    assert not report.issues
    assert not report.diagnostics
    assert report.coverage[0].disposition is CoverageDisposition.UNSUPPORTED


@pytest.mark.parametrize(
    "output",
    [
        ProcessOutput(1, "", "parser failed"),
        ProcessOutput(0, "not json", ""),
        ProcessOutput(0, '{"version":"4.2.2","version":"4.2.2","results":[{}]}', ""),
        ProcessOutput(0, '{"version":"4.2.1","results":[{}]}', ""),
        ProcessOutput(0, '{"version":"4.2.2","results":[]}', ""),
        ProcessOutput(
            0,
            '{"version":"4.2.2","results":[{"violations":[{"code":"AM99","description":"wrong rule","line":1,"column":1}]}]}',
            "",
        ),
        ProcessOutput(
            0,
            '{"version":"4.2.2","results":[{"violations":[{"code":"AM07","description":"outside source","line":999,"column":1}]}]}',
            "",
        ),
        ProcessOutput(0, '{"version":"4.2.2","results":[{}]}', "unexpected stderr"),
    ],
    ids=[
        "failed-exit",
        "malformed-json",
        "duplicate-json-key",
        "wrong-version",
        "omitted-query",
        "unexpected-rule",
        "invalid-position",
        "stderr",
    ],
)
def test_broken_worker_protocol_never_reports_clean_success(tmp_path: Path, output: ProcessOutput) -> None:
    path = _write_query(tmp_path, repr("SELECT a"))

    def execute(request: ProcessRequest) -> ProcessOutput:
        assert request.argv[1:3] == ("-I", "-m")
        assert request.timeout_seconds == 60
        assert request.deadline is not None
        assert request.input_bytes is not None
        assert request.max_input_bytes == 1024 * 1024
        return output

    report = analyze_sources((str(path),), root=tmp_path, runner=RequestExecutor(execute, ProcessCapabilities()))

    assert report.completion is not Completion.COMPLETE
    assert report.issues
    assert not report.diagnostics


def test_worker_timeout_is_an_execution_issue(tmp_path: Path) -> None:
    path = _write_query(tmp_path, repr("SELECT a"))

    def execute(request: ProcessRequest) -> ProcessOutput:
        raise subprocess.TimeoutExpired(request.argv, request.timeout_seconds)

    report = analyze_sources((str(path),), root=tmp_path, runner=RequestExecutor(execute, ProcessCapabilities()))

    assert report.issues
    assert report.completion is not Completion.COMPLETE


def test_source_outside_repository_is_an_execution_issue(tmp_path: Path) -> None:
    report = analyze_sources((str(tmp_path.parent / "outside.py"),), root=tmp_path)

    assert report.issues
    assert report.completion is not Completion.COMPLETE


def test_repository_sqlfluff_config_cannot_change_embedded_checks(tmp_path: Path) -> None:
    (tmp_path / ".sqlfluff").write_text("[sqlfluff]\ndialect = sqlite\nexclude_rules = AM07,AM08\n", encoding="utf-8")
    path = _write_query(tmp_path, repr("SELECT a UNION SELECT a, b"))

    report = analyze_sources((str(path),), root=tmp_path)

    assert not report.issues
    assert {item.code for item in report.diagnostics} == {"AM07"}


@pytest.mark.parametrize(
    ("expression", "expected", "has_gap"),
    [(repr("SELECT a UNION SELECT a, b"), {"AM07"}, False), ('f"SELECT {column}"', set[str](), True)],
)
def test_public_full_check_preserves_sql_findings_and_coverage(
    tmp_path: Path, expression: str, expected: set[str], has_gap: bool
) -> None:
    path = _write_query(tmp_path, expression)
    adopted = manifest.Manifest(
        version="8.190.0",
        configs=("pyright",),
        python_dest=".",
        typescript_dest=".",
        disabled_capabilities=tuple(name for name in manifest.ALL_CAPABILITIES if name not in {"sqlfluff", "pyright"}),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    report = Standards(tmp_path).analyze((str(path),), external=True, mode="corpus", python_type_check=False)

    assert any(tool.name == "sqlfluff" for tool in report.tools), report
    assert {item.code for item in report.diagnostics if item.source == "sqlfluff"} == expected
    assert any(item.source == "sqlfluff" for item in report.coverage) is has_gap
    assert not report.issues

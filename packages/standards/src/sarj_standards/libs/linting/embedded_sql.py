from __future__ import annotations

from dataclasses import dataclass
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catch bounded native runner failures.
import sys
from time import monotonic
from typing import TYPE_CHECKING, Final

from sarj_python_lint.sql_literals import SQLLiteral, extract_sql_literals

from sarj_standards.libs.diagnostics import (
    AnalysisReport,
    AnalyzerId,
    Completion,
    CoverageDisposition,
    CoverageNotice,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    ToolReport,
)
from sarj_standards.libs.json_boundary import parse_unique_json

from .analysis import PythonSourceDocument, report_from_tools
from .external import DEFAULT_EXECUTOR, process_request
from .result_cache import CachedResult, cached_python_analysis
from .sqlfluff_protocol import MAX_INPUT_BYTES, MAX_QUERIES, SQLFLUFF_VERSION, SQLRequest, SQLResponse, SQLViolation


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from sarj_standards.libs.adoption.manifest import Manifest

    from .policy import Policy
    from .process import ProcessExecutor


_MAX_BATCH_BYTES: Final = MAX_INPUT_BYTES // 2
_TIMEOUT_SECONDS: Final = 60
_ANALYSIS_SECONDS: Final = 300


@dataclass(frozen=True, slots=True)
class _Query:
    literal: SQLLiteral
    document: PythonSourceDocument
    relative: str


@dataclass(frozen=True, slots=True)
class _BatchReport:
    diagnostics: tuple[Diagnostic, ...]
    unsupported_paths: frozenset[str]


def with_embedded_sql(
    report: AnalysisReport, *, files: Sequence[str], adopted: Manifest | None, policy: Policy
) -> AnalysisReport:
    return merge_embedded_sql(report, embedded_sql_result(report.root, files=files, adopted=adopted), policy=policy)


def embedded_sql_result(root: Path, *, files: Sequence[str], adopted: Manifest | None) -> CachedResult | None:
    # Reads only the selected Python sources, so it may run beside the analysis groups.
    if adopted is None or "sqlfluff" not in adopted.enabled_capabilities or not files:
        return None

    def run() -> CachedResult:
        analyzed = analyze_sources(files, root=root)
        return CachedResult(analyzed.tools, analyzed.coverage)

    return cached_python_analysis("sqlfluff-embedded", root, selected=files, parameters=(), compute=run)


class EmbeddedSQLPass:
    # Runs the SQL pass beside the analysis groups and merges it after both, so
    # the report and any failure match running it after the groups.
    def __init__(self, root: Path, *, files: Sequence[str], adopted: Manifest | None, enabled: bool) -> None:
        self._root = root
        self._files = files
        self._adopted = adopted
        self._enabled = enabled
        self._outcome: list[CachedResult | Exception | None] = []

    def run(self) -> None:
        if not self._enabled or self._outcome:
            return
        try:
            self._outcome.append(embedded_sql_result(self._root, files=self._files, adopted=self._adopted))
        except Exception as error:  # ruff: ignore[blind-except] -- re-raised by merge, after both groups.
            self._outcome.append(error)

    def merge(self, report: AnalysisReport, *, policy: Policy) -> AnalysisReport:
        if not self._enabled:
            return report
        # A failed external group never reached the pass; run it now, as before.
        self.run()
        [outcome] = self._outcome
        if isinstance(outcome, Exception):
            raise outcome
        return merge_embedded_sql(report, outcome, policy=policy)


def merge_embedded_sql(report: AnalysisReport, embedded: CachedResult | None, *, policy: Policy) -> AnalysisReport:
    if embedded is None:
        return report
    filtered = tuple(
        ToolReport(
            tool.name,
            tool.completion,
            diagnostics=policy.filter_diagnostics(tool.diagnostics),
            issues=tool.issues,
            analyzer_id=tool.analyzer_id,
            version=tool.version,
            file_count=tool.file_count,
        )
        for tool in embedded.reports
    )
    return report_from_tools(report.root, (*report.tools, *filtered), coverage=(*report.coverage, *embedded.coverage))


def analyze_sources(files: Sequence[str], *, root: Path, runner: ProcessExecutor = DEFAULT_EXECUTOR) -> AnalysisReport:
    root = root.resolve()
    diagnostics: list[Diagnostic] = []
    issues: list[ExecutionIssue] = []
    uncovered: set[str] = set()
    queries: list[_Query] = []
    for name in files:
        try:
            _collect_queries(root, name, queries, uncovered)
        except (OSError, UnicodeError, ValueError, RecursionError) as error:
            issues.append(
                ExecutionIssue("sqlfluff", "source-failure", f"Cannot extract SQL from {name}: {type(error).__name__}")
            )
    deadline = monotonic() + _ANALYSIS_SECONDS
    try:
        for batch in _batches(queries):
            result = _analyze_batch(batch, root=root, deadline=deadline, runner=runner)
            diagnostics.extend(result.diagnostics)
            uncovered.update(result.unsupported_paths)
    except (OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        issues.append(ExecutionIssue("sqlfluff", "tool-failure", f"SQL parser failed: {type(error).__name__}"))
    notices = (
        (
            CoverageNotice(
                "sqlfluff",
                "Dynamic, escaped, concatenated, oversized or unparseable SQL remains uncovered; only proven static psycopg queries were linted.",
                len(uncovered),
                CoverageDisposition.UNSUPPORTED,
            ),
        )
        if uncovered
        else ()
    )
    tool = ToolReport(
        "sqlfluff",
        Completion.PARTIAL if issues else Completion.COMPLETE,
        diagnostics=tuple(diagnostics),
        issues=tuple(issues),
        analyzer_id=AnalyzerId("sqlfluff"),
        version=SQLFLUFF_VERSION,
        file_count=len(files),
    )
    return report_from_tools(root, (tool,), coverage=notices)


def _collect_queries(root: Path, name: str, queries: list[_Query], uncovered: set[str]) -> None:
    path = (root / name).resolve()
    relative = path.relative_to(root).as_posix()
    document = PythonSourceDocument.read(path)
    extracted = extract_sql_literals(path, document.document.text)
    if extracted.gaps:
        uncovered.add(relative)
    for literal in extracted.literals:
        size = len(SQLRequest(queries=(literal.text,)).model_dump_json().encode("utf-8"))
        if size > _MAX_BATCH_BYTES:
            uncovered.add(relative)
        else:
            queries.append(_Query(literal, document, relative))


def _batches(queries: Sequence[_Query]) -> Iterator[tuple[_Query, ...]]:
    batch: list[_Query] = []
    size = 0
    for query in queries:
        query_size = len(SQLRequest(queries=(query.literal.text,)).model_dump_json().encode("utf-8"))
        if batch and (size + query_size > _MAX_BATCH_BYTES or len(batch) >= MAX_QUERIES):
            yield tuple(batch)
            batch = []
            size = 0
        batch.append(query)
        size += query_size
    if batch:
        yield tuple(batch)


def _analyze_batch(batch: tuple[_Query, ...], *, root: Path, deadline: float, runner: ProcessExecutor) -> _BatchReport:
    request = SQLRequest(queries=tuple(query.literal.text for query in batch)).model_dump_json().encode("utf-8")
    output = runner.run(
        process_request(
            (sys.executable, "-I", "-m", "sarj_standards.libs.linting.sqlfluff_worker"),
            cwd=root,
            input_bytes=request,
            max_input_bytes=MAX_INPUT_BYTES,
            timeout_seconds=_TIMEOUT_SECONDS,
            deadline=deadline,
        )
    )
    if output.returncode or output.stderr.strip():
        message = "SQL worker returned an execution failure"
        raise ValueError(message)
    parse_unique_json(output.stdout)
    response = SQLResponse.model_validate_json(output.stdout)
    if response.version != SQLFLUFF_VERSION or len(response.results) != len(batch):
        message = "SQL worker version or query count does not match the request"
        raise ValueError(message)
    diagnostics: list[Diagnostic] = []
    uncovered: set[str] = set()
    for query, result in zip(batch, response.results, strict=True):
        if result.unsupported:
            uncovered.add(query.relative)
        else:
            diagnostics.extend(_diagnostic(item, query) for item in result.violations)
    return _BatchReport(tuple(diagnostics), frozenset(uncovered))


def _diagnostic(violation: SQLViolation, query: _Query) -> Diagnostic:
    source = query.literal.source_point(line=violation.line, column=violation.column)
    point = query.document.point(line=source.line, column=source.column)
    if point is None:
        message = "SQLFluff diagnostic could not be mapped to Python source"
        raise ValueError(message)
    return Diagnostic(
        code=violation.code,
        rule_id=violation.code,
        message=violation.description,
        severity=Severity.ERROR,
        source="sqlfluff",
        location=Location(query.relative, position=point),
    )

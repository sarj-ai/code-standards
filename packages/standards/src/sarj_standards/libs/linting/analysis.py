"""In-process adapters from native Sarj analyzers to the canonical protocol."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from pathlib import Path
import time
from typing import TYPE_CHECKING, NamedTuple, Protocol, runtime_checkable

from sarj_standards.libs.diagnostics import (
    AnalysisReport,
    AnalyzerId,
    Completion,
    Conclusion,
    Diagnostic,
    ExecutionIssue,
    InvocationId,
    Location,
    Severity,
    SourceDocument,
    ToolReport,
    diagnostic_fingerprint,
)
from sarj_standards.libs.rules import RuleEngine, RuleSelection

from . import textlint
from .runner import GroupedPaths, group_paths


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .policy import Policy


@runtime_checkable
class _NativeDiagnostic(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def line(self) -> int: ...

    @property
    def col(self) -> int: ...

    @property
    def code(self) -> str: ...

    @property
    def message(self) -> str: ...

    @property
    def column_encoding(self) -> object: ...


@runtime_checkable
class _SeverityDiagnostic(_NativeDiagnostic, Protocol):
    @property
    def severity(self) -> object: ...


class _RuleMetadata(Protocol):
    code: str
    id: str
    description: str


@runtime_checkable
class _CheckerModule(Protocol):
    def analyze(self, rule_ids: list[str], paths: list[Path]) -> list[_NativeDiagnostic]: ...


@runtime_checkable
class _RegistryModule(Protocol):
    REGISTRY: Mapping[str, type[_RuleMetadata]]


class _LoadedNative(NamedTuple):
    checker: _CheckerModule
    registry: _RegistryModule


def analyze(
    files: Sequence[str],
    *,
    root: Path,
    python_baseline: Path | None = None,
    policy: Policy | None = None,
    grouped: GroupedPaths | None = None,
    rule_selection: RuleSelection | None = None,
) -> AnalysisReport:
    """Run applicable bundled analyzers without parsing their console output."""
    root = root.resolve()
    try:
        contained = tuple(_contained_path(item, root) for item in files)
        routed = grouped if grouped is not None else group_paths(contained, policy=policy)
    except (OSError, ValueError) as exc:
        issue = ExecutionIssue("sarj-standards", "invalid-input", str(exc).replace(str(root), "."))
        tool = ToolReport("sarj-standards", Completion.FAILED, issues=(issue,))
        return AnalysisReport(root, Completion.FAILED, Conclusion.INCONCLUSIVE, (tool,))

    reports = tuple(
        report
        for report in (
            _native_report(
                "sarj-python-lint",
                "sarj_python_lint",
                routed.python,
                root,
                python_baseline=python_baseline,
                rule_ids=_selected_ids(rule_selection, RuleEngine.PYTHON),
            ),
            _native_report(
                "sarj-sql-lint",
                "sarj_sql_lint",
                routed.sql,
                root,
                rule_ids=_selected_ids(rule_selection, RuleEngine.SQL),
            ),
            _native_report(
                "sarj-iac-lint",
                "sarj_iac_lint",
                routed.iac,
                root,
                rule_ids=_selected_ids(rule_selection, RuleEngine.IAC),
            ),
            _text_report(
                routed,
                root,
                rule_ids=_selected_ids(rule_selection, RuleEngine.TEXT),
            ),
        )
        if report is not None
    )
    report = report_from_tools(root, reports)
    if policy is None:
        return report
    filtered = tuple(
        ToolReport(
            item.name,
            item.completion,
            diagnostics=policy.filter_diagnostics(item.diagnostics),
            issues=item.issues,
            analyzer_id=item.analyzer_id,
            invocation_id=item.invocation_id,
            version=item.version,
            duration_ms=item.duration_ms,
            file_count=item.file_count,
            cache_status=item.cache_status,
        )
        for item in report.tools
    )
    return report_from_tools(root, filtered)


def _selected_ids(selection: RuleSelection | None, engine: RuleEngine) -> frozenset[str] | None:
    if selection is None:
        return None
    return frozenset(str(value) for value in selection.ids_for(engine))


def _contained_path(value: str, root: Path) -> str:
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        msg = "analysis path is outside the repository root"
        raise ValueError(msg) from exc
    return str(resolved)


def report_from_tools(root: Path, reports: Sequence[ToolReport]) -> AnalysisReport:
    """Derive consistent report axes from independent tool reports."""
    normalized = tuple(
        ToolReport(
            report.name,
            report.completion,
            diagnostics=tuple(
                sorted(
                    (
                        item
                        if item.fingerprint is not None
                        else replace(item, fingerprint=diagnostic_fingerprint(item, anchor=item.message))
                        for item in report.diagnostics
                    ),
                    key=_diagnostic_key,
                )
            ),
            issues=tuple(sorted(report.issues, key=lambda issue: (issue.source, issue.kind, issue.message))),
            analyzer_id=report.analyzer_id,
            invocation_id=report.invocation_id,
            version=report.version,
            duration_ms=report.duration_ms,
            file_count=report.file_count,
            cache_status=report.cache_status,
        )
        for report in sorted(reports, key=lambda report: report.name)
    )
    issues = tuple(issue for report in normalized for issue in report.issues)
    diagnostics = tuple(item for report in normalized for item in report.diagnostics)
    if issues:
        completion = (
            Completion.FAILED
            if normalized and all(report.completion is Completion.FAILED for report in normalized)
            else Completion.PARTIAL
        )
        conclusion = Conclusion.FINDINGS if diagnostics else Conclusion.INCONCLUSIVE
    else:
        completion = Completion.COMPLETE
        conclusion = Conclusion.FINDINGS if diagnostics else Conclusion.PASSED
    return AnalysisReport(root, completion, conclusion, normalized)


def _diagnostic_key(diagnostic: Diagnostic) -> tuple[object, ...]:
    location = diagnostic.location
    position = location.region.start if location.region is not None else location.position
    end = location.region.end if location.region is not None else None
    return (
        diagnostic.source,
        diagnostic.code,
        location.path,
        -1 if position is None else position.line,
        -1 if position is None else position.character,
        -1 if end is None else end.line,
        -1 if end is None else end.character,
        diagnostic.severity.value,
        diagnostic.message,
    )


def _native_report(
    name: str,
    package: str,
    files: Sequence[str],
    root: Path,
    *,
    python_baseline: Path | None = None,
    rule_ids: frozenset[str] | None = None,
) -> ToolReport | None:
    if not files or rule_ids == frozenset():
        return None
    try:
        return _run_native(name, package, files, root, python_baseline=python_baseline, rule_ids=rule_ids)
    except Exception as exc:  # ruff: ignore[blind-except] -- one analyzer failure must not erase other tool results.
        issue = ExecutionIssue(name, "analyzer-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport(name, Completion.FAILED, issues=(issue,))


def _run_native(
    name: str,
    package: str,
    files: Sequence[str],
    root: Path,
    *,
    python_baseline: Path | None,
    rule_ids: frozenset[str] | None,
) -> ToolReport:
    started = time.monotonic()
    checker_module, registry_module = _load_native(package)
    metadata = _metadata(registry_module.REGISTRY)
    selected_rules = sorted(registry_module.REGISTRY) if rule_ids is None else sorted(rule_ids)
    unknown = sorted(set(selected_rules) - registry_module.REGISTRY.keys())
    if unknown:
        msg = f"unknown {package} rule(s): {', '.join(unknown)}"
        raise ValueError(msg)
    paths = [Path(item) for item in files]
    native_result: Sequence[_NativeDiagnostic]
    if package == "sarj_python_lint":
        from sarj_python_lint.__main__ import analyze as analyze_python  # ruff: ignore[import-outside-top-level]

        native_result = analyze_python(
            selected_rules,
            paths,
            baseline=python_baseline,
            root=root,
        )
    else:
        native_result = checker_module.analyze(selected_rules, paths)
    cache: dict[Path, SourceDocument | None] = {}
    diagnostics = tuple(
        _normalize_native(item, source=name, root=root, metadata=metadata, documents=cache) for item in native_result
    )
    return ToolReport(
        name,
        Completion.COMPLETE,
        diagnostics=diagnostics,
        analyzer_id=AnalyzerId(name),
        invocation_id=InvocationId(name),
        duration_ms=round((time.monotonic() - started) * 1_000),
        file_count=len(files),
    )


def _load_native(package: str) -> _LoadedNative:
    checker_module = import_module(f"{package}.__main__")
    registry_module = import_module(f"{package}.rules")
    if not isinstance(checker_module, _CheckerModule) or not isinstance(registry_module, _RegistryModule):
        msg = f"{package} does not expose the expected in-process analysis API"
        raise TypeError(msg)
    return _LoadedNative(checker_module, registry_module)


def _metadata(registry: Mapping[str, type[_RuleMetadata]]) -> dict[str, tuple[str, str]]:
    by_code: dict[str, tuple[str, str]] = {}
    for rule_id, rule_type in registry.items():
        rule = rule_type()
        by_code[rule.code] = (rule_id, rule.description)
    return by_code


def _normalize_native(
    item: _NativeDiagnostic,
    *,
    source: str,
    root: Path,
    metadata: Mapping[str, tuple[str, str]],
    documents: dict[Path, SourceDocument | None],
) -> Diagnostic:
    resolved = item.path.resolve()
    document = documents.get(resolved)
    if resolved not in documents:
        try:
            document = SourceDocument.read(resolved)
        except OSError:
            document = None
        documents[resolved] = document
    position = None
    if document is not None:
        position = (
            document.byte_point(line=item.line, column=item.col)
            if source == "sarj-python-lint" and str(item.column_encoding) == "utf8-bytes"
            else document.point(line=item.line, column=item.col)
        )
    rule_id, help_text = metadata.get(item.code, (None, None))
    return Diagnostic(
        code=item.code,
        rule_id=rule_id,
        message=item.message,
        severity=_severity(item),
        source=source,
        location=Location(_relative_path(resolved, root), position=position),
        help=help_text,
    )


def _severity(item: _NativeDiagnostic) -> Severity:
    if isinstance(item, _SeverityDiagnostic) and str(item.severity) == "warning":
        return Severity.WARNING
    return Severity.ERROR


def _text_report(
    grouped: GroupedPaths,
    root: Path,
    *,
    rule_ids: frozenset[str] | None = None,
) -> ToolReport | None:
    if not grouped.text or rule_ids == frozenset():
        return None
    try:
        return _run_text(grouped.text, root, rule_ids=rule_ids)
    except Exception as exc:  # ruff: ignore[blind-except] -- retain results from independent analyzers.
        issue = ExecutionIssue("sarj-text-lint", "analyzer-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport("sarj-text-lint", Completion.FAILED, issues=(issue,))


def _run_text(files: Sequence[str], root: Path, *, rule_ids: frozenset[str] | None) -> ToolReport:
    selected = frozenset(textlint.REGISTRY) if rule_ids is None else rule_ids
    unknown = sorted(selected - textlint.REGISTRY.keys())
    if unknown:
        msg = f"unknown text rule(s): {', '.join(unknown)}"
        raise ValueError(msg)
    raw = tuple(
        finding
        for finding in textlint.check_paths(files, root=root)
        if any(meta.code == finding.code and rule_id in selected for rule_id, meta in textlint.REGISTRY.items())
    )
    by_code = {meta.code: (rule_id, meta.description, meta.blocking) for rule_id, meta in textlint.REGISTRY.items()}
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics = tuple(_normalize_text(item, root, by_code, documents) for item in raw)
    return ToolReport("sarj-text-lint", Completion.COMPLETE, diagnostics=diagnostics)


def _normalize_text(
    item: textlint.Finding,
    root: Path,
    metadata: Mapping[str, tuple[str, str, bool]],
    documents: dict[Path, SourceDocument | None],
) -> Diagnostic:
    resolved = item.path.resolve()
    document = documents.get(resolved)
    if resolved not in documents:
        try:
            document = SourceDocument.read(resolved)
        except OSError:
            document = None
        documents[resolved] = document
    rule_id, help_text, blocking = metadata[item.code]
    return Diagnostic(
        code=item.code,
        rule_id=rule_id,
        message=item.message,
        severity=Severity.ERROR if blocking else Severity.WARNING,
        source="sarj-text-lint",
        location=Location(
            _relative_path(resolved, root),
            position=None if document is None else document.point(line=item.line, column=1),
        ),
        help=help_text,
    )


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        msg = "analyzer reported a path outside the repository root"
        raise ValueError(msg) from exc

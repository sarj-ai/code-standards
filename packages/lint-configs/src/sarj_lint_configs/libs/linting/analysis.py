"""In-process adapters from native Sarj analyzers to the canonical protocol."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sarj_lint_configs.libs.diagnostics import (
    AnalysisReport,
    Completion,
    Conclusion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    SourceDocument,
    ToolReport,
)

from . import textlint
from .runner import GroupedPaths, group_paths


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@runtime_checkable
class _NativeDiagnostic(Protocol):
    path: Path
    line: int
    col: int
    code: str
    message: str


@runtime_checkable
class _SeverityDiagnostic(_NativeDiagnostic, Protocol):
    severity: object


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


def analyze(files: Sequence[str], *, root: Path) -> AnalysisReport:
    """Run applicable bundled analyzers without parsing their console output."""
    try:
        grouped = group_paths(files)
    except (OSError, ValueError) as exc:
        issue = ExecutionIssue("sarj-standards", "invalid-input", str(exc))
        tool = ToolReport("sarj-standards", Completion.FAILED, issues=(issue,))
        return AnalysisReport(root, Completion.FAILED, Conclusion.FAILED, (tool,))

    reports = tuple(
        report
        for report in (
            _native_report("sarj-python-lint", "sarj_python_lint", grouped.python, root),
            _native_report("sarj-sql-lint", "sarj_sql_lint", grouped.sql, root),
            _native_report("sarj-iac-lint", "sarj_iac_lint", grouped.iac, root),
            _text_report(grouped, root),
        )
        if report is not None
    )
    issues = tuple(issue for report in reports for issue in report.issues)
    diagnostics = tuple(item for report in reports for item in report.diagnostics)
    if issues:
        completion = Completion.FAILED if reports and all(report.issues for report in reports) else Completion.PARTIAL
        conclusion = Conclusion.FAILED
    else:
        completion = Completion.COMPLETE
        conclusion = Conclusion.FINDINGS if diagnostics else Conclusion.PASSED
    return AnalysisReport(root, completion, conclusion, reports)


def _native_report(name: str, package: str, files: Sequence[str], root: Path) -> ToolReport | None:
    if not files:
        return None
    try:
        return _run_native(name, package, files, root)
    except Exception as exc:  # ruff: ignore[blind-except] -- one analyzer failure must not erase other tool results.
        issue = ExecutionIssue(name, "analyzer-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport(name, Completion.FAILED, issues=(issue,))


def _run_native(name: str, package: str, files: Sequence[str], root: Path) -> ToolReport:
    checker_module, registry_module = _load_native(package)
    metadata = _metadata(registry_module.REGISTRY)
    raw = checker_module.analyze(sorted(registry_module.REGISTRY), [Path(item) for item in files])
    cache: dict[Path, SourceDocument | None] = {}
    diagnostics = tuple(
        _normalize_native(item, source=name, root=root, metadata=metadata, documents=cache) for item in raw
    )
    return ToolReport(name, Completion.COMPLETE, diagnostics=diagnostics)


def _load_native(package: str) -> tuple[_CheckerModule, _RegistryModule]:
    checker_module = import_module(f"{package}.__main__")
    registry_module = import_module(f"{package}.rules")
    if not isinstance(checker_module, _CheckerModule) or not isinstance(registry_module, _RegistryModule):
        msg = f"{package} does not expose the expected in-process analysis API"
        raise TypeError(msg)
    return checker_module, registry_module


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
    position = None if document is None else document.point(line=item.line, column=item.col)
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


def _text_report(grouped: GroupedPaths, root: Path) -> ToolReport | None:
    if not grouped.text:
        return None
    try:
        return _run_text(grouped.text, root)
    except Exception as exc:  # ruff: ignore[blind-except] -- retain results from independent analyzers.
        issue = ExecutionIssue("sarj-text-lint", "analyzer-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport("sarj-text-lint", Completion.FAILED, issues=(issue,))


def _run_text(files: Sequence[str], root: Path) -> ToolReport:
    raw = textlint.check_paths(files, root=root)
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
    except ValueError:
        return str(path)

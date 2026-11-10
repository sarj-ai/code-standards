from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
import os
from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- report bounded immutable Git provenance failures.
import time
from typing import TYPE_CHECKING, NamedTuple, Protocol, runtime_checkable

from sarj_rule_contracts import SourceCatalog, SourceSnapshot

from sarj_standards.libs.diagnostics import (
    AnalysisReport,
    AnalyzerId,
    Completion,
    Conclusion,
    CoverageNotice,
    Diagnostic,
    ExecutionIssue,
    Fix,
    FixSafety,
    InvocationId,
    Location,
    Position,
    Region,
    Severity,
    SourceDocument,
    TextEdit,
    ToolReport,
    diagnostic_fingerprint,
)
from sarj_standards.libs.rules import RuleEngine, RuleSelection

from . import shell_ast, textlint
from .process import raise_if_cancelled
from .read_tracking import tracked_reads
from .result_cache import (
    KEEP_PER_UNIT,
    CachedResult,
    ResultCache,
    TrackedResult,
    UnknownInputsError,
    cached_python_analysis,
    cached_tracked_analysis,
    executable_identity,
    file_identity,
    notice_outcomes,
)
from .runner import GroupedPaths, group_paths


# Native Python reaches its 512-entry module-resolution quota only on large
# selections; workers then check the files after that quota is spent.
_PARALLEL_PYTHON_FILES = 512


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from typing import Self

    from sarj_iac_lint.guard_contracts import GuardContracts
    from sarj_python_lint.rule_base import Fix as PythonFix

    from .policy import Policy


class _DiagnosticKey(NamedTuple):
    source: str
    code: str
    path: str
    line: int
    character: int
    end_line: int
    end_character: int
    severity: str
    message: str


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


@runtime_checkable
class _ColumnEncodingDiagnostic(Protocol):
    @property
    def column_encoding(self) -> object: ...


@runtime_checkable
class _SeverityDiagnostic(Protocol):
    @property
    def severity(self) -> object: ...


@runtime_checkable
class _BaselineDiagnostic(Protocol):
    @property
    def baselineable(self) -> bool: ...


@runtime_checkable
class _FixDiagnostic(Protocol):
    @property
    def fixes(self) -> tuple[PythonFix, ...]: ...


class _RuleMetadata(Protocol):
    @property
    def code(self) -> str: ...

    @property
    def id(self) -> str: ...

    @property
    def description(self) -> str: ...


class _NativeAnalyzer(Protocol):
    def __call__(
        self, rule_ids: Sequence[str], paths: list[Path], *, sources: SourceCatalog | None = None
    ) -> Sequence[_NativeDiagnostic]: ...


class _LoadedNative(NamedTuple):
    analyze: _NativeAnalyzer
    registry: Mapping[str, type[_RuleMetadata]]


class _NativeRuleMetadata(NamedTuple):
    rule_id: str
    description: str


def analyze(
    files: Sequence[str],
    *,
    root: Path,
    python_baseline: Path | None = None,
    policy: Policy | None = None,
    grouped: GroupedPaths | None = None,
    rule_selection: RuleSelection | None = None,
    python_jobs: int = 1,
    staged: bool = False,
    use_guard_contracts: bool = True,
    module_summaries: bool = False,
) -> AnalysisReport:
    root = root.resolve()
    try:
        contained = tuple(_contained_path(item, root) for item in files)
        routed = grouped if grouped is not None else group_paths(contained, policy=policy)
    except (OSError, ValueError) as exc:
        issue = ExecutionIssue("sarj-standards", "invalid-input", str(exc).replace(str(root), "."))
        tool = ToolReport("sarj-standards", Completion.FAILED, issues=(issue,))
        return AnalysisReport(root, Completion.FAILED, Conclusion.INCONCLUSIVE, (tool,))

    sources = SourceCatalog()
    iac_contracts = _iac_contracts(root, staged=staged) if use_guard_contracts else _PreparedIAC()
    reports = tuple(
        report
        for report in (
            iac_contracts.report,
            _native_report(
                "sarj-python-lint",
                "sarj_python_lint",
                routed.python,
                root,
                sources=sources,
                python_baseline=python_baseline,
                rule_ids=_selected_ids(rule_selection, RuleEngine.PYTHON),
                python_jobs=python_jobs,
            ),
            _native_report(
                "sarj-sql-lint",
                "sarj_sql_lint",
                routed.sql,
                root,
                sources=sources,
                rule_ids=_selected_ids(rule_selection, RuleEngine.SQL),
            ),
            _native_report(
                "sarj-iac-lint",
                "sarj_iac_lint",
                routed.iac,
                root,
                sources=sources,
                rule_ids=_selected_ids(rule_selection, RuleEngine.IAC),
                guard_contracts=iac_contracts.contracts,
                module_summaries=module_summaries,
            ),
            _text_report(
                routed,
                root,
                sources=sources,
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
            rule_executions=item.rule_executions,
        )
        for item in report.tools
    )
    return report_from_tools(root, filtered, coverage=report.coverage)


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


def report_from_tools(
    root: Path, reports: Sequence[ToolReport], *, coverage: tuple[CoverageNotice, ...] = ()
) -> AnalysisReport:
    normalized = tuple(
        _normalized_tool_report(report)
        for report in sorted(reports, key=lambda report: (report.name, str(report.invocation_id or "")))
    )
    return AnalysisReport.from_tools(root, normalized, coverage=coverage)


def _normalized_tool_report(report: ToolReport) -> ToolReport:
    return replace(
        report,
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
    )


def _diagnostic_key(diagnostic: Diagnostic) -> _DiagnosticKey:
    location = diagnostic.location
    position = location.region.start if location.region is not None else location.position
    end = location.region.end if location.region is not None else None
    return _DiagnosticKey(
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
    sources: SourceCatalog,
    python_baseline: Path | None = None,
    rule_ids: frozenset[str] | None = None,
    python_jobs: int = 1,
    guard_contracts: GuardContracts | None = None,
    module_summaries: bool = False,
) -> ToolReport | None:
    if not files or rule_ids == frozenset():
        return None
    raise_if_cancelled(None)

    def run() -> ToolReport:
        return _run_native(
            name,
            package,
            files,
            root,
            sources=sources,
            python_baseline=python_baseline,
            rule_ids=rule_ids,
            python_jobs=python_jobs,
            guard_contracts=guard_contracts,
            module_summaries=module_summaries,
        )

    try:
        if package != "sarj_python_lint":
            return run()
        cached = cached_python_analysis(
            name,
            root,
            selected=files,
            parameters=(
                f"rules={','.join(sorted(rule_ids)) if rule_ids is not None else '*'}",
                f"baseline={python_baseline.read_text(encoding='utf-8') if python_baseline is not None else ''}",
            ),
            compute=lambda: CachedResult((run(),)),
        )
    except Exception as exc:  # ruff: ignore[blind-except] -- one analyzer failure must not erase other tool results.
        issue = ExecutionIssue(name, "analyzer-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    [report] = cached.reports
    return report


def _run_native(
    name: str,
    package: str,
    files: Sequence[str],
    root: Path,
    *,
    sources: SourceCatalog,
    python_baseline: Path | None,
    rule_ids: frozenset[str] | None,
    python_jobs: int = 1,
    guard_contracts: GuardContracts | None = None,
    module_summaries: bool = False,
) -> ToolReport:
    started = time.monotonic()
    analyzer, registry = _load_native(package)
    selected_rules = sorted(registry) if rule_ids is None else sorted(rule_ids)
    unknown = sorted(set(selected_rules) - set(registry))
    if unknown:
        msg = f"unknown {package} rule(s): {', '.join(unknown)}"
        raise ValueError(msg)
    metadata = native_metadata(
        registry if rule_ids is None else {rule_id: registry[rule_id] for rule_id in selected_rules}
    )
    paths = [Path(item) for item in files]
    native_result: Sequence[_NativeDiagnostic]
    if package == "sarj_python_lint":
        from sarj_python_lint.__main__ import analyze as analyze_python  # ruff: ignore[import-outside-top-level] -- load sarj_python_lint.__main__ only when this selected operation executes.
        from sarj_python_lint.rules import DEFAULT_REGISTRY  # ruff: ignore[import-outside-top-level] -- load sarj_python_lint.rules only when this selected operation executes.

        if rule_ids is None:
            selected_rules = sorted(DEFAULT_REGISTRY)

        native_result = analyze_python(
            selected_rules,
            paths,
            baseline=python_baseline,
            root=root,
            # Smaller selections keep the established serial path and its startup cost.
            jobs=python_jobs if len(paths) >= _PARALLEL_PYTHON_FILES else 1,
            sources=sources,
        )
    elif package == "sarj_iac_lint":
        from sarj_iac_lint.__main__ import analyze as analyze_iac  # ruff: ignore[import-outside-top-level] -- selected IaC engine only.

        native_result = analyze_iac(
            selected_rules, paths, sources=sources, guard_contracts=guard_contracts, module_summaries=module_summaries
        )
    else:
        native_result = analyzer(selected_rules, paths, sources=sources)
    raise_if_cancelled(None)
    cache: dict[Path, SourceDocument | PythonSourceDocument | None] = {}
    resolved_paths: dict[Path, Path] = {}
    diagnostics = tuple(
        normalize_native(
            item,
            source=name,
            root=root,
            metadata=metadata,
            documents=cache,
            resolved_paths=resolved_paths,
            sources=sources,
        )
        for item in native_result
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
    match package:
        case "sarj_python_lint":
            from sarj_python_lint.__main__ import analyze as analyze_python  # ruff: ignore[import-outside-top-level] -- bind the actual typed entry point only for the selected Python engine.
            from sarj_python_lint.rules import REGISTRY as PYTHON_RULES  # ruff: ignore[import-outside-top-level] -- retain the selected engine's live registry and constructor metadata.

            return _LoadedNative(analyze_python, PYTHON_RULES)
        case "sarj_sql_lint":
            from sarj_sql_lint.__main__ import analyze as analyze_sql  # ruff: ignore[import-outside-top-level] -- bind the actual typed entry point only for the selected SQL engine.
            from sarj_sql_lint.rules import REGISTRY as SQL_RULES  # ruff: ignore[import-outside-top-level] -- retain the selected engine's live registry and constructor metadata.

            return _LoadedNative(analyze_sql, SQL_RULES)
        case "sarj_iac_lint":
            from sarj_iac_lint.__main__ import analyze as analyze_iac  # ruff: ignore[import-outside-top-level] -- bind the actual typed entry point only for the selected IaC engine.
            from sarj_iac_lint.rules import REGISTRY as IAC_RULES  # ruff: ignore[import-outside-top-level] -- retain the selected engine's live registry and constructor metadata.

            return _LoadedNative(analyze_iac, IAC_RULES)
        case _:
            msg = f"unsupported in-process analysis package: {package}"
            raise ValueError(msg)


def native_metadata(registry: Mapping[str, type[_RuleMetadata]]) -> dict[str, _NativeRuleMetadata]:
    by_code: dict[str, _NativeRuleMetadata] = {}
    for rule_id, rule_type in registry.items():
        rule = rule_type()
        by_code[rule.code] = _NativeRuleMetadata(rule_id, rule.description)
    return by_code


@dataclass(frozen=True, slots=True)
class PythonSourceDocument:
    document: SourceDocument
    raw: bytes
    encoding: str
    utf8_source: bytes
    source_hash: str
    _raw_source_hash: str | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def raw_source_hash(self) -> str:
        digest = self._raw_source_hash
        if digest is None:
            digest = sha256(self.raw).hexdigest()
            object.__setattr__(self, "_raw_source_hash", digest)  # ruff: ignore[unnecessary-dunder-call] -- frozen documents permit only their private lazy cache to change.
        return digest

    @classmethod
    def read(cls, path: Path) -> Self:
        return cls.from_snapshot(SourceSnapshot.read(path))

    @classmethod
    def from_snapshot(cls, snapshot: SourceSnapshot) -> Self:
        from sarj_python_lint import python_source_encoding, python_source_hash  # ruff: ignore[import-outside-top-level] -- only the selected Python engine needs these source contracts.

        raw = snapshot.raw
        encoding = python_source_encoding(raw)
        text = snapshot.decode(encoding).text
        return cls(
            SourceDocument(snapshot.path, text),
            raw,
            encoding,
            raw if encoding == "utf-8" else text.encode("utf-8"),
            python_source_hash(text),
        )

    def point(self, *, line: int, column: int) -> Position | None:
        return self._physical_point(self.document.point(line=line, column=column))

    def byte_point(self, *, line: int, column: int) -> Position | None:
        return self._physical_point(self.document.byte_point(line=line, column=column))

    def _physical_point(self, position: Position | None) -> Position | None:
        if position is None or self.encoding == "utf-8":
            return position
        if self.encoding == "utf-8-sig":
            return replace(position, byte_offset=position.byte_offset + 3)
        prefix = self.utf8_source[: position.byte_offset].decode("utf-8")
        encoded = prefix.encode(self.encoding)
        # Never invent a physical offset for a codec whose prefix does not round-trip.
        return replace(position, byte_offset=len(encoded)) if self.raw.startswith(encoded) else None


def normalize_native(
    item: _NativeDiagnostic,
    *,
    source: str,
    root: Path,
    metadata: Mapping[str, _NativeRuleMetadata],
    documents: dict[Path, SourceDocument | PythonSourceDocument | None],
    resolved_paths: dict[Path, Path] | None = None,
    sources: SourceCatalog | None = None,
) -> Diagnostic:
    snapshot = None if sources is None else sources.get(item.path)
    if sources is not None and snapshot is None:
        msg = f"native diagnostic source was not captured: {item.path}"
        raise ValueError(msg)
    resolved = None if resolved_paths is None else resolved_paths.get(item.path)
    if resolved is None:
        resolved = item.path.resolve()
        if resolved_paths is not None:
            resolved_paths[item.path] = resolved
    document_key = item.path if sources is not None else resolved
    document = documents.get(document_key)
    if document_key not in documents:
        try:
            captured = snapshot if snapshot is not None else SourceSnapshot.read(resolved)
            document = _native_document(captured, source)
        except OSError, UnicodeError, SyntaxError:
            document = None
        documents[document_key] = document
    position = _native_position(item, source, document)
    rule_id, help_text = metadata.get(item.code, (None, None))
    tags: tuple[str, ...] = ()
    if source == "sarj-python-lint":
        from sarj_python_lint.suppression_policy import PROTECTED_SUPPRESSION_CODES  # ruff: ignore[import-outside-top-level] -- only the Python engine owns these rule identities.

        if item.code in PROTECTED_SUPPRESSION_CODES:
            tags = ("non-baselineable", "required-source-policy")
    if source == "sarj-iac-lint" and isinstance(item, _BaselineDiagnostic) and not item.baselineable:
        tags = ("non-baselineable", "required-source-policy")
    relative_path = _relative_path(resolved, root)
    return Diagnostic(
        code=item.code,
        rule_id=rule_id,
        message=item.message,
        severity=_severity(item),
        source=source,
        location=Location(relative_path, position=position),
        help=help_text,
        tags=tags,
        fixes=_python_fixes(item, document, relative_path) if source == "sarj-python-lint" else (),
    )


def _native_document(snapshot: SourceSnapshot, source: str) -> SourceDocument | PythonSourceDocument:
    if source == "sarj-python-lint":
        return PythonSourceDocument.from_snapshot(snapshot)
    if source in {"sarj-sql-lint", "sarj-iac-lint"}:
        # Replacement decoding can collapse invalid byte sequences; only strict UTF-8 proves this coordinate view.
        return SourceDocument(snapshot.path, snapshot.decode("utf-8").text)
    return SourceDocument.from_snapshot(snapshot)


def _native_position(
    item: _NativeDiagnostic, source: str, document: SourceDocument | PythonSourceDocument | None
) -> Position | None:
    if source != "sarj-python-lint":
        return None if document is None else document.point(line=item.line, column=item.col)
    if not isinstance(item, _ColumnEncodingDiagnostic):
        msg = "Python diagnostic does not declare its column encoding"
        raise TypeError(msg)
    match str(item.column_encoding):
        case "utf8-bytes":
            return None if document is None else document.byte_point(line=item.line, column=item.col)
        case "codepoints":
            return None if document is None else document.point(line=item.line, column=item.col)
        case _:
            msg = "Python diagnostic column encoding must be utf8-bytes or codepoints"
            raise ValueError(msg)


def _python_fixes(
    item: _NativeDiagnostic, document: SourceDocument | PythonSourceDocument | None, relative: str
) -> tuple[Fix, ...]:
    if not isinstance(document, PythonSourceDocument) or not isinstance(item, _FixDiagnostic) or not item.fixes:
        return ()
    digest = document.source_hash
    fixes: list[Fix] = []
    for fix in item.fixes:
        if str(fix.safety) != "safe" or fix.source_hash != digest:
            continue
        edits: list[TextEdit] = []
        for edit in fix.edits:
            start = document.byte_point(line=edit.start_line, column=edit.start_col)
            end = document.byte_point(line=edit.end_line, column=edit.end_col)
            if start is None or end is None:
                break
            edits.append(
                TextEdit(
                    Location(relative, region=Region(start, end)),
                    edit.replacement,
                    sha256(document.raw[start.byte_offset : end.byte_offset]).hexdigest(),
                    expected_source_hash=document.raw_source_hash,
                )
            )
        else:
            if edits:
                fixes.append(Fix(fix.title, FixSafety.SAFE, tuple(edits)))
    return tuple(fixes)


def _severity(item: _NativeDiagnostic) -> Severity:
    if not isinstance(item, _SeverityDiagnostic):
        return Severity.ERROR
    match str(item.severity):
        case "warning":
            return Severity.WARNING
        case "error":
            return Severity.ERROR
        case _:
            msg = "native diagnostic severity must be error or warning"
            raise ValueError(msg)


def _text_report(
    grouped: GroupedPaths,
    root: Path,
    *,
    sources: SourceCatalog,
    rule_ids: frozenset[str] | None = None,
) -> ToolReport | None:
    if not grouped.text or rule_ids == frozenset():
        return None
    raise_if_cancelled(None)
    try:
        return _run_text(grouped.text, root, sources=sources, rule_ids=rule_ids)
    except Exception as exc:  # ruff: ignore[blind-except] -- retain results from independent analyzers.
        issue = ExecutionIssue("sarj-text-lint", "analyzer-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport("sarj-text-lint", Completion.FAILED, issues=(issue,))


def _run_text(
    files: Sequence[str], root: Path, *, sources: SourceCatalog, rule_ids: frozenset[str] | None
) -> ToolReport:
    selected = frozenset(textlint.REGISTRY) if rule_ids is None else rule_ids
    unknown = sorted(selected - textlint.REGISTRY.keys())
    if unknown:
        msg = f"unknown text rule(s): {', '.join(unknown)}"
        raise ValueError(msg)
    by_code = {meta.code: (rule_id, meta.description, meta.blocking) for rule_id, meta in textlint.REGISTRY.items()}
    documents: dict[Path, SourceDocument] = {}

    def normalized(findings: Iterable[textlint.Finding]) -> tuple[Diagnostic, ...]:
        raw = tuple(
            finding
            for finding in findings
            if any(meta.code == finding.code and rule_id in selected for rule_id, meta in textlint.REGISTRY.items())
        )
        raise_if_cancelled(None)
        return tuple(_normalize_text(item, root, by_code, documents, sources=sources) for item in raw)

    if ResultCache.from_environment() is None:
        diagnostics = normalized(textlint.check_paths(files, root=root, rule_ids=rule_ids, sources=sources))
    else:
        diagnostics = _cached_text_diagnostics(files, root, rule_ids=rule_ids, sources=sources, normalized=normalized)
    return ToolReport("sarj-text-lint", Completion.COMPLETE, diagnostics=diagnostics)


def _cached_text_diagnostics(
    files: Sequence[str],
    root: Path,
    *,
    rule_ids: frozenset[str] | None,
    sources: SourceCatalog,
    normalized: Callable[[Iterable[textlint.Finding]], tuple[Diagnostic, ...]],
) -> tuple[Diagnostic, ...]:
    # Each file's findings depend on its bytes, the manifest's text policy, the
    # selected rules, the shell parser, and any file a rule reads by reference.
    resolved = root.resolve()
    checker = textlint.TextChecker(root=root, rule_ids=rule_ids, sources=sources)
    shared: list[str] = []
    outcomes: list[bool] = []

    def shared_inputs() -> list[str]:
        if not shared:
            try:
                parser = executable_identity(shell_ast.checked_executable())
            except shell_ast.ShellParseError as error:
                raise UnknownInputsError(str(error)) from error
            shared.extend(
                (
                    f"manifest={file_identity(resolved / '.sarj-standards.toml')}",
                    f"rules={','.join(sorted(rule_ids)) if rule_ids is not None else '*'}",
                    f"shell-parser={parser}",
                )
            )
        return shared

    def identity(relative: str) -> str:
        path = Path(os.path.normpath(resolved / relative))
        target = path.resolve()
        if not target.is_relative_to(resolved):
            return "outside"
        return f"{target.relative_to(resolved).as_posix()}:{file_identity(path)}"

    def analyze(raw: str) -> TrackedResult:
        with tracked_reads() as reads:
            diagnostics = normalized(checker.check(raw))
        return TrackedResult(
            CachedResult((ToolReport("sarj-text-lint", Completion.COMPLETE, diagnostics=diagnostics),)),
            tuple(os.path.relpath(path, resolved) for path in reads),
        )

    def inputs(raw: str) -> list[str]:
        path = Path(raw)
        return [
            *shared_inputs(),
            f"path={path.resolve().relative_to(resolved).as_posix()}",
            f"source={file_identity(path)}",
        ]

    diagnostics: list[Diagnostic] = []
    for raw in files:
        result = cached_tracked_analysis(
            "text-lint",
            inputs=lambda raw=raw: inputs(raw),
            compute=lambda raw=raw: analyze(raw),
            identity=identity,
            keep=KEEP_PER_UNIT,
            outcomes=outcomes,
        )
        diagnostics.extend(diagnostic for report in result.reports for diagnostic in report.diagnostics)
    notice_outcomes("text-lint", outcomes)
    return tuple(diagnostics)


def _normalize_text(
    item: textlint.Finding,
    root: Path,
    metadata: Mapping[str, tuple[str, str, bool]],
    documents: dict[Path, SourceDocument],
    *,
    sources: SourceCatalog,
) -> Diagnostic:
    snapshot = sources.get(item.path)
    if snapshot is None:
        msg = f"text diagnostic source was not captured: {item.path}"
        raise ValueError(msg)
    document = documents.get(item.path)
    if document is None:
        document = SourceDocument.from_snapshot(snapshot)
        documents[item.path] = document
    rule_id, help_text, blocking = metadata[item.code]
    location = _text_location(item, root, document)
    return Diagnostic(
        code=item.code,
        rule_id=rule_id,
        message=item.message,
        severity=Severity.ERROR if blocking else Severity.WARNING,
        source="sarj-text-lint",
        location=location,
        help=help_text,
    )


def _text_location(item: textlint.Finding, root: Path, document: SourceDocument) -> Location:
    path = _relative_path(document.path, root)
    if item.code == "SARJ310" and item.end_line is None:
        return Location(path)
    start = document.point(line=item.line, column=1)
    if item.end_line is not None and item.end_column is not None:
        end = document.point(line=item.end_line, column=item.end_column)
        return Location(path, region=Region(start, end)) if start is not None and end is not None else Location(path)
    return Location(path, position=start)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        msg = "analyzer reported a path outside the repository root"
        raise ValueError(msg) from exc


@dataclass(frozen=True)
class _PreparedIAC:
    contracts: "GuardContracts | None" = None
    report: ToolReport | None = None


def _iac_contracts(root: Path, *, staged: bool) -> _PreparedIAC:
    from .iac_guard_contracts import CoreIAC  # ruff: ignore[import-outside-top-level] -- load the IaC contract adapter only during native analysis.

    try:
        return _PreparedIAC(contracts=CoreIAC(root, staged=staged).prepare())
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        issue = ExecutionIssue("sarj-iac-lint", "guard-contract-failure", f"{type(exc).__name__}: {exc}")
        return _PreparedIAC(report=ToolReport("sarj-iac-lint", Completion.FAILED, issues=(issue,)))

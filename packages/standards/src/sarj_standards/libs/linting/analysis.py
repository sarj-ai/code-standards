from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import time
from typing import TYPE_CHECKING, NamedTuple, Protocol, runtime_checkable

from sarj_rule_contracts import SourceCatalog, SourceSnapshot

from sarj_standards.libs.diagnostics import (
    AnalysisReport,
    AnalyzerId,
    Completion,
    Conclusion,
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

from . import textlint
from .runner import GroupedPaths, group_paths


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Self

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
class _FixDiagnostic(Protocol):
    @property
    def fixes(self) -> tuple[PythonFix, ...]: ...


class _RuleMetadata(Protocol):
    code: str
    id: str
    description: str


@runtime_checkable
class _CheckerModule(Protocol):
    def analyze(
        self, rule_ids: list[str], paths: list[Path], *, sources: SourceCatalog | None = None
    ) -> Sequence[_NativeDiagnostic]: ...


@runtime_checkable
class _RegistryModule(Protocol):
    REGISTRY: Mapping[str, type[_RuleMetadata]]


class _LoadedNative(NamedTuple):
    checker: _CheckerModule
    registry: _RegistryModule


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
    reports = tuple(
        report
        for report in (
            _native_report(
                "sarj-python-lint",
                "sarj_python_lint",
                routed.python,
                root,
                sources=sources,
                python_baseline=python_baseline,
                rule_ids=_selected_ids(rule_selection, RuleEngine.PYTHON),
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
    normalized = tuple(
        _normalized_tool_report(report)
        for report in sorted(reports, key=lambda report: (report.name, str(report.invocation_id or "")))
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
) -> ToolReport | None:
    if not files or rule_ids == frozenset():
        return None
    try:
        return _run_native(
            name, package, files, root, sources=sources, python_baseline=python_baseline, rule_ids=rule_ids
        )
    except Exception as exc:  # ruff: ignore[blind-except] -- one analyzer failure must not erase other tool results.
        issue = ExecutionIssue(name, "analyzer-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport(name, Completion.FAILED, issues=(issue,))


def _run_native(
    name: str,
    package: str,
    files: Sequence[str],
    root: Path,
    *,
    sources: SourceCatalog,
    python_baseline: Path | None,
    rule_ids: frozenset[str] | None,
) -> ToolReport:
    started = time.monotonic()
    checker_module, registry_module = _load_native(package)
    metadata = native_metadata(registry_module.REGISTRY)
    selected_rules = sorted(registry_module.REGISTRY) if rule_ids is None else sorted(rule_ids)
    unknown = sorted(set(selected_rules) - registry_module.REGISTRY.keys())
    if unknown:
        msg = f"unknown {package} rule(s): {', '.join(unknown)}"
        raise ValueError(msg)
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
            sources=sources,
        )
    else:
        native_result = checker_module.analyze(selected_rules, paths, sources=sources)
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
    checker_module = import_module(f"{package}.__main__")
    registry_module = import_module(f"{package}.rules")
    if not isinstance(checker_module, _CheckerModule) or not isinstance(registry_module, _RegistryModule):
        msg = f"{package} does not expose the expected in-process analysis API"
        raise TypeError(msg)
    return _LoadedNative(checker_module, registry_module)


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
        for finding in textlint.check_paths(files, root=root, rule_ids=rule_ids)
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


def _text_location(item: textlint.Finding, root: Path, document: SourceDocument | None) -> Location:
    path = _relative_path(item.path.resolve(), root)
    if document is None or (item.code == "SARJ310" and item.end_line is None):
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

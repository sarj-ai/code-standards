from __future__ import annotations

import ast
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from fnmatch import fnmatch
import json
from pathlib import Path
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, NamedTuple

from sarj_rule_contracts import RuleId
import typer

from sarj_python_lint import __version__
from sarj_python_lint._filesystem import atomic_write_text
from sarj_python_lint._prepared_sources import PreparedSourceInputs
from sarj_python_lint._source import read_python_source
from sarj_python_lint.json_boundary import is_object_mapping, parse_json
from sarj_python_lint.rule_base import Diagnostic, DiagnosticSubject, ProjectRule, Rule, Severity, is_suppressed
from sarj_python_lint.suppression_policy import PROTECTED_SUPPRESSION_CODES


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sarj_rule_contracts import SourceCatalog

    from sarj_python_lint._analysis_session import AnalysisSession
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules import REGISTRY as REGISTRY  # ruff: ignore[runtime-import-in-type-checking-block] -- the lazy compatibility export has this type; eager loading would import every rule during help/version.


def _rule_registry() -> Mapping[str, type[Rule]]:
    try:
        return REGISTRY
    except NameError:
        from sarj_python_lint.rules import REGISTRY as _REGISTRY  # ruff: ignore[import-outside-top-level] -- ordinary operations load the canonical owner; legacy module overrides take precedence.

        return _REGISTRY


def __getattr__(name: str) -> object:
    if name == "REGISTRY":
        from sarj_python_lint.rules._registry import REGISTRY as _REGISTRY  # ruff: ignore[import-outside-top-level] -- preserve the published export independently of temporary facade overrides.

        return _REGISTRY
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        ".git",
        "dist",
        "build",
        ".next",
        "coverage",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        ".mypy_cache",
        ".turbo",
        ".yarn",
        ".pnpm-store",
    }
)

# Bound resource use, but never turn an unanalyzed selected file into success.
_MAX_FILE_BYTES = 500_000


def _checked_size(path: Path) -> Path:
    if path.stat().st_size > _MAX_FILE_BYTES:
        msg = f"selected Python source exceeds {_MAX_FILE_BYTES} bytes: {path}; use an explicit path exclusion for generated source"
        raise ValueError(msg)
    return path


def expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            msg = f"input does not exist: {p}"
            raise ValueError(msg)
        if p.is_file():
            out.append(_checked_size(p))
            continue
        out.extend(_python_files(p))
    return out


def _python_files(p: Path) -> list[Path]:
    if not SKIP_DIR_NAMES.isdisjoint(p.parts):
        return []
    out: list[Path] = []
    for directory, directories, filenames in p.walk():
        directories[:] = [name for name in directories if name not in SKIP_DIR_NAMES]
        for name in filenames:
            if not fnmatch(name, "*.py"):
                continue
            child = directory / name
            if child.is_file():
                out.append(_checked_size(child))
    return sorted(out)


def _canonical_rule_ids(rule_names: Sequence[str]) -> list[RuleId]:
    from sarj_python_lint.rules._runtime_registry import canonical_aliases  # ruff: ignore[import-outside-top-level] -- class-free alias data is needed only by rule selection.

    registry = _rule_registry()
    aliases = canonical_aliases(registry)
    if aliases is None:
        aliases = {
            alias: rule_id
            for rule_id, cls in registry.items()
            if (documentation := cls.documentation) is not None
            for alias in documentation.aliases
        }
    return list(dict.fromkeys(RuleId(name if name in registry else aliases.get(name, name)) for name in rule_names))


def _check(
    rule_names: Sequence[str], paths: list[Path], *, jobs: int = 1, sources: SourceCatalog | None = None
) -> list[Diagnostic]:
    from sarj_python_lint._analysis_session import AnalysisSession  # ruff: ignore[import-outside-top-level] -- construct semantic state only for analysis.
    from sarj_python_lint.rules._paths import clear_path_caches  # ruff: ignore[import-outside-top-level] -- analysis owns semantic cache lifetime.

    registry = _rule_registry()
    rule_ids = _canonical_rule_ids(rule_names)
    unknown = [rid for rid in rule_ids if rid not in registry]
    if unknown:
        sys.stderr.write(f"unknown rule(s): {', '.join(unknown)}\n")
        sys.stderr.write(f"available: {', '.join(sorted(registry))}\n")
        raise SystemExit(2)
    rules = [registry[rid]() for rid in rule_ids]
    source_inputs = None if sources is None else PreparedSourceInputs(sources)
    session = AnalysisSession() if source_inputs is None else AnalysisSession(source_inputs=source_inputs)
    for rule in rules:
        rule.prepare_session(session)
    clear_path_caches()
    expanded = expand_paths(paths)
    loaded = (
        _load_python_sources(expanded, sources)
        if source_inputs is None
        else _load_python_sources(expanded, sources, source_inputs=source_inputs)
    )
    _prepare_project(rules, expanded, loaded, session, source_inputs=source_inputs)
    parallel = _parallel_diagnostics(rules, loaded, session, jobs=jobs, source_inputs=source_inputs)
    if parallel is not None:
        return parallel
    diags: list[Diagnostic] = []
    for p, source in loaded.items():
        diags.extend(check_source(rules, p, source, session=session))
    return diags


def _load_python_sources(
    paths: Sequence[Path], sources: SourceCatalog | None, *, source_inputs: PreparedSourceInputs | None = None
) -> dict[Path, str]:
    if sources is None:
        return {path: read_python_source(path) for path in paths}
    loaded = {path: read_python_source(path, sources=sources) for path in paths}
    if source_inputs is not None:
        for path in loaded:
            snapshot = sources.get(path)
            if snapshot is not None:
                source_inputs.remember_selected(path, snapshot)
    return loaded


def _prepare_project(
    rules: list[Rule],
    expanded: list[Path],
    loaded: dict[Path, str],
    session: AnalysisSession,
    *,
    source_inputs: PreparedSourceInputs | None,
) -> None:
    project_rules = [rule for rule in rules if isinstance(rule, ProjectRule)]
    if not project_rules:
        return
    from sarj_python_lint.rules._project_index import ProjectIndexSet  # ruff: ignore[import-outside-top-level] -- project rules own project indexing.

    indexes = (
        ProjectIndexSet.build(expanded, loaded, facts=session.first_party)
        if source_inputs is None
        else ProjectIndexSet.build(expanded, loaded, facts=session.first_party, source_inputs=source_inputs)
    )
    session.project = indexes
    for rule in project_rules:
        rule.prepare(indexes)


def _parallel_diagnostics(
    rules: list[Rule],
    loaded: dict[Path, str],
    session: AnalysisSession,
    *,
    jobs: int,
    source_inputs: PreparedSourceInputs | None,
) -> list[Diagnostic] | None:
    if jobs <= 1 or len(loaded) <= 1:
        return None
    from sarj_python_lint._parallel import check_parallel  # ruff: ignore[import-outside-top-level] -- serial API users do not need multiprocessing.

    if source_inputs is None:
        return check_parallel([type(rule) for rule in rules], loaded, session.project, jobs=jobs)
    return check_parallel(
        [type(rule) for rule in rules], loaded, session.project, jobs=jobs, source_inputs=source_inputs
    )


def check_source(
    rules: list[Rule], p: Path, source: str, *, session: AnalysisSession | None = None
) -> list[Diagnostic]:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- source checks own native AST context construction.

    return check_context(rules, PythonFileContext(p, source, session))


def check_context(rules: list[Rule], context: PythonFileContext) -> list[Diagnostic]:
    if rules and context.tree is None:
        msg = f"selected Python source could not be parsed: {context.path}"
        raise ValueError(msg)
    source_lines = context.source_lines
    raw = [diagnostic for rule in rules for diagnostic in rule.check_context(context)]
    return deduplicate_diagnostics(
        [diagnostic for diagnostic in raw if not is_suppressed(source_lines, diagnostic.line, diagnostic.code)],
        source=context.source,
        context=context,
    )


def analyze(
    rule_ids: Sequence[str],  # sarj-noqa: SARJ093 -- Public parsing boundary accepts raw names.
    paths: list[Path],
    *,
    baseline: Path | None = None,
    root: Path | None = None,
    jobs: int = 1,
    sources: SourceCatalog | None = None,
) -> list[Diagnostic]:
    if jobs < 1:
        msg = "jobs must be at least 1"
        raise ValueError(msg)
    diagnostics = _check(rule_ids, paths, jobs=jobs, sources=sources)
    return diagnostics if baseline is None else _apply_baseline(diagnostics, _read_baseline(baseline), root=root)


_DIAGNOSTIC_PRECEDENCE = MappingProxyType(
    {
        "SARJ556": frozenset({"SARJ421"}),
        "SARJ020": frozenset({"SARJ437"}),
        "SARJ054": frozenset({"SARJ419"}),
        "SARJ448": frozenset({"SARJ419"}),
        "SARJ523": frozenset({"SARJ419"}),
        "SARJ050": frozenset({"SARJ420"}),
        "SARJ084": frozenset({"SARJ050", "SARJ420"}),
        "SARJ085": frozenset({"SARJ420"}),
        "SARJ086": frozenset({"SARJ420"}),
        "SARJ087": frozenset({"SARJ420"}),
        "SARJ088": frozenset({"SARJ050", "SARJ085", "SARJ420"}),
        "SARJ089": frozenset({"SARJ551"}),
        "SARJ092": frozenset({"SARJ086", "SARJ087", "SARJ420"}),
        "SARJ093": frozenset({"SARJ034"}),
        # Visible FastAPI operations have a route-aware contract diagnostic.
        # Keep the annotation diagnostics when SARJ094 is absent, including
        # when a concrete response_model makes the route contract complete.
        "SARJ094": frozenset({"SARJ008", "SARJ447"}),
        "SARJ095": frozenset({"SARJ468"}),
        "SARJ099": frozenset({"SARJ420"}),
        # A proven external or nested request boundary already requires schema
        # validation at this field read. Retain standalone shape advice when
        # that more specific rule is unselected or locally suppressed.
        "SARJ411": frozenset({"SARJ521", "SARJ535"}),
        # Any-valued mappings are the stronger correctness failure. SARJ008
        # still owns every fixed dictionary return when selected alone, while
        # an all-rules run emits one actionable diagnostic for this overlap.
        "SARJ447": frozenset({"SARJ008"}),
        "SARJ450": frozenset({"SARJ521", "SARJ535"}),
        "SARJ521": frozenset({"SARJ535"}),
        "SARJ457": frozenset({"SARJ045", "SARJ526"}),
        "SARJ465": frozenset({"SARJ071"}),
        "SARJ491": frozenset({"SARJ400"}),
    }
)

_DOCSTRING_PRECEDENCE_CODES = frozenset(
    {"SARJ050", "SARJ084", "SARJ085", "SARJ086", "SARJ087", "SARJ088", "SARJ092", "SARJ099"}
)


class _OwnerLocation(NamedTuple):
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class _DiagnosticOwners:
    docstrings: dict[int, _OwnerLocation]
    signatures: dict[int, _OwnerLocation]
    fields: tuple[ast.AnnAssign, ...]

    def location(self, diagnostic: Diagnostic) -> _OwnerLocation:
        if diagnostic.code in {"SARJ400", "SARJ491"}:
            return _field_owner_location(diagnostic, self.fields)
        owners = (
            self.signatures
            if diagnostic.code in {"SARJ008", "SARJ034", "SARJ093", "SARJ094", "SARJ447"}
            else self.docstrings
        )
        return _OwnerLocation(*owners.get(diagnostic.line, (diagnostic.line, diagnostic.col)))

    def presence(self, diags: list[Diagnostic]) -> dict[tuple[Path, int, int], dict[str, set[Severity]]]:
        present: dict[tuple[Path, int, int], dict[str, set[Severity]]] = {}
        for diagnostic in diags:
            if diagnostic.code == "SARJ094" and diagnostic.subject is not DiagnosticSubject.RETURN:
                continue
            location = self.location(diagnostic)
            by_code = present.setdefault((diagnostic.path, location.line, location.column), {})
            by_code.setdefault(diagnostic.code, set()).add(diagnostic.severity)
        return present


def deduplicate_diagnostics(
    diags: list[Diagnostic], *, source: str | None = None, context: PythonFileContext | None = None
) -> list[Diagnostic]:
    codes = frozenset(diagnostic.code for diagnostic in diags)
    needs_docstring_owners = ("SARJ092" in codes and not codes.isdisjoint(_DIAGNOSTIC_PRECEDENCE["SARJ092"])) or (
        "SARJ420" in codes and not codes.isdisjoint(_DOCSTRING_PRECEDENCE_CODES)
    )
    needs_signature_owners = (
        ("SARJ093" in codes and "SARJ034" in codes)
        or ("SARJ447" in codes and "SARJ008" in codes)
        or ("SARJ094" in codes and not codes.isdisjoint(_DIAGNOSTIC_PRECEDENCE["SARJ094"]))
    )
    needs_composition_owners = {"SARJ066", "SARJ457"} <= codes
    needs_field_owners = {"SARJ400", "SARJ491"} <= codes
    tree = (
        _diagnostic_owner_tree(source, context)
        if needs_docstring_owners or needs_signature_owners or needs_composition_owners or needs_field_owners
        else None
    )
    diags = _deduplicate_test_composition(diags, tree)
    owners = _DiagnosticOwners(
        docstrings=_docstring_owner_locations(tree) if needs_docstring_owners else {},
        signatures=_function_signature_owner_locations(tree) if needs_signature_owners else {},
        fields=_field_owners(tree) if needs_field_owners else (),
    )

    suppressed = _suppressed_diagnostics(owners.presence(diags))
    return [
        diagnostic
        for diagnostic in diags
        if (
            (
                (
                    diagnostic.path,
                    owners.location(diagnostic).line,
                    owners.location(diagnostic).column,
                ),
                diagnostic.code,
                diagnostic.severity,
            )
            not in suppressed
        )
    ]


def _diagnostic_owner_tree(source: str | None, context: PythonFileContext | None) -> ast.Module | None:
    if source is None:
        return None
    if context is not None and context.source == source:
        return context.tree
    with suppress(SyntaxError):
        return ast.parse(source)
    return None


def _field_owners(tree: ast.Module | None) -> tuple[ast.AnnAssign, ...]:
    if tree is None:
        return ()
    return tuple(node for node in ast.walk(tree) if isinstance(node, ast.AnnAssign))


def _field_owner_location(diagnostic: Diagnostic, fields: tuple[ast.AnnAssign, ...]) -> _OwnerLocation:
    location = (diagnostic.line, diagnostic.col - 1)
    for field in fields:
        start = (field.lineno, field.col_offset)
        end = (field.end_lineno or field.lineno, field.end_col_offset or field.col_offset)
        if start <= location < end:
            return _OwnerLocation(field.lineno, field.col_offset + 1)
    return _OwnerLocation(diagnostic.line, diagnostic.col)


def _deduplicate_test_composition(diags: list[Diagnostic], tree: ast.Module | None) -> list[Diagnostic]:
    codes = {diagnostic.code for diagnostic in diags}
    if tree is None or not {"SARJ066", "SARJ457"} <= codes:
        return diags
    whole_tests = {
        (diagnostic.path, diagnostic.line): diagnostic.severity for diagnostic in diags if diagnostic.code == "SARJ066"
    }
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def redundant(diagnostic: Diagnostic) -> bool:
        if diagnostic.code != "SARJ457":
            return False
        owners = [node for node in functions if node.lineno <= diagnostic.line <= (node.end_lineno or node.lineno)]
        if not owners:
            return False
        owner = max(owners, key=lambda node: node.lineno)
        severity = whole_tests.get((diagnostic.path, owner.lineno))
        return severity is not None and (severity is Severity.ERROR or diagnostic.severity is Severity.WARNING)

    return [diagnostic for diagnostic in diags if not redundant(diagnostic)]


def _suppressed_diagnostics(
    present: dict[tuple[Path, int, int], dict[str, set[Severity]]],
) -> set[tuple[tuple[Path, int, int], str, Severity]]:
    return {
        (location, generic, severity)
        for location, codes in present.items()
        for generic, severity in _suppressed_codes(codes)
    }


def _suppressed_codes(codes: dict[str, set[Severity]]) -> set[tuple[str, Severity]]:
    suppressed = _precedence_suppressions(codes)
    # SARJ094 warning staging owns the overlapping return failure; its blocking twin would defeat that policy.
    if "SARJ094" in codes:
        suppressed.update(_route_contract_suppressions(codes))
    if _typed_docstring_warning_is_superseded(codes):
        suppressed.add(("SARJ092", Severity.WARNING))
    return suppressed


def _precedence_suppressions(codes: dict[str, set[Severity]]) -> set[tuple[str, Severity]]:
    suppressed: set[tuple[str, Severity]] = set()
    for specific, generics in _DIAGNOSTIC_PRECEDENCE.items():
        if specific not in codes:
            continue
        specific_severities = codes[specific]
        for generic in generics:
            for generic_severity in codes.get(generic, set()):
                if generic_severity is Severity.WARNING or Severity.ERROR in specific_severities:
                    suppressed.add((generic, generic_severity))
    return suppressed


def _route_contract_suppressions(codes: dict[str, set[Severity]]) -> set[tuple[str, Severity]]:
    return {
        (generic, severity) for generic in _DIAGNOSTIC_PRECEDENCE["SARJ094"] for severity in codes.get(generic, set())
    }


def _typed_docstring_warning_is_superseded(codes: dict[str, set[Severity]]) -> bool:
    if Severity.WARNING not in codes.get("SARJ092", set()):
        return False
    return any(Severity.ERROR in codes.get(generic, set()) for generic in ("SARJ086", "SARJ087"))


def _function_signature_owner_locations(tree: ast.Module | None) -> dict[int, _OwnerLocation]:
    if tree is None:
        return {}
    owners: dict[int, _OwnerLocation] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body_line = node.body[0].lineno if node.body else node.lineno + 1
        end_line = max(node.lineno, body_line - 1)
        owners.update(dict.fromkeys(range(node.lineno, end_line + 1), _OwnerLocation(node.lineno, node.col_offset + 1)))
    return owners


def _docstring_owner_locations(tree: ast.Module | None) -> dict[int, _OwnerLocation]:
    if tree is None:
        return {}
    owners: dict[int, _OwnerLocation] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        expression = node.body[0]
        if not (
            isinstance(expression, ast.Expr)
            and isinstance(expression.value, ast.Constant)
            and isinstance(expression.value.value, str)
        ):
            continue
        location = _OwnerLocation(expression.lineno, expression.col_offset + 1)
        lines = range(expression.lineno, (expression.end_lineno or expression.lineno) + 1)
        owners.update(dict.fromkeys(lines, location))
    return owners


@dataclass
class _Result:
    code: int = 0


def _explain(wanted: str) -> int:
    registry = _rule_registry()
    key = wanted.strip()
    cls = registry.get(key) or next((c for c in registry.values() if c.code.upper() == key.upper()), None)
    if cls is None:
        sys.stderr.write(f"unknown rule: {wanted}\navailable: {', '.join(sorted(registry))}\n")
        return 2
    sys.stdout.write(f"{cls.code}  {cls.id}\n{cls.description}\nexamples: {cls.examples_url()}\n")
    return 0


def _baseline_counts(diags: list[Diagnostic]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for d in diags:
        if d.severity is Severity.WARNING or d.code in PROTECTED_SUPPRESSION_CODES:
            continue
        key = _baseline_path(d.path)
        counts.setdefault(key, {})
        counts[key][d.code] = counts[key].get(d.code, 0) + 1
    return counts


def _baseline_path(path: Path, *, root: Path | None = None) -> str:
    try:
        return path.resolve().relative_to((Path.cwd() if root is None else root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_baseline(path: Path) -> dict[str, dict[str, int]]:
    raw = parse_json(path.read_text(encoding="utf-8"))
    if not is_object_mapping(raw):
        msg = "baseline must be an object of file paths and diagnostic counts"
        raise ValueError(msg)
    counts: dict[str, dict[str, int]] = {}
    for file_key, per_code in raw.items():
        if not isinstance(file_key, str) or not file_key or not is_object_mapping(per_code):
            msg = "baseline entries must map non-empty file paths to diagnostic counts"
            raise ValueError(msg)
        validated: dict[str, int] = {}
        for code, count in per_code.items():
            if (
                not isinstance(code, str)
                or not code
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
            ):
                msg = "baseline counts must map non-empty diagnostic codes to non-negative integers"
                raise ValueError(msg)
            validated[code] = count
        counts[file_key] = validated
    return counts


def _apply_baseline(
    diags: list[Diagnostic],
    baseline: dict[str, dict[str, int]],
    *,
    root: Path | None = None,
) -> list[Diagnostic]:
    seen: Counter[tuple[str, str]] = Counter()
    out: list[Diagnostic] = []
    for d in diags:
        if d.severity is Severity.WARNING or d.code in PROTECTED_SUPPRESSION_CODES:
            out.append(d)
            continue
        path_key = _baseline_path(d.path, root=root)
        key = (path_key, d.code)
        seen[key] += 1
        # The raw lookup preserves compatibility with baselines written before
        # repository-relative keys were introduced.
        allowance = max(
            baseline.get(path_key, {}).get(d.code, 0),
            baseline.get(str(d.path), {}).get(d.code, 0),
        )
        if seen[key] > allowance:
            out.append(d)
    return out


def _run_check(
    rule: list[str], files: list[Path], baseline: Path | None, update_baseline: Path | None, *, jobs: int = 1
) -> int:
    try:
        diags = analyze(rule, files, jobs=jobs)
    except (OSError, ValueError, SyntaxError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    if update_baseline is not None:
        counts = _baseline_counts(diags)
        blocking = sum(d.severity is Severity.ERROR for d in diags)
        warnings = len(diags) - blocking
        try:
            atomic_write_text(update_baseline, json.dumps(counts, indent=2, sort_keys=True) + "\n")
        except OSError as exc:
            sys.stderr.write(f"error: cannot write baseline {update_baseline}: {exc}\n")
            return 2
        sys.stdout.write(
            f"baseline written: {update_baseline} "
            f"({blocking} blocking diagnostics over {len(counts)} files; {warnings} warnings excluded)\n"
        )
        return 0
    if baseline is not None:
        try:
            diags = _apply_baseline(diags, _read_baseline(baseline))
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"error: invalid baseline {baseline}: {exc}\n")
            return 2
    for d in diags:
        sys.stdout.write(d.format() + "\n")
    return 1 if any(d.severity is Severity.ERROR for d in diags) else 0


app = typer.Typer(
    help="Custom Python lint rules.",
    add_completion=False,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _show_version(*, value: bool) -> None:
    if value:
        sys.stdout.write(f"sarj-python-lint {__version__}\n")
        raise typer.Exit


@app.callback()
def _root(
    *,
    _version: Annotated[bool, typer.Option("--version", callback=_show_version, is_eager=True)] = False,
) -> None:
    pass


@app.command("list-rules", help="List available rule IDs.")
def _list_rules() -> None:
    for rid, cls in sorted(_rule_registry().items()):
        inst = cls()
        sys.stdout.write(f"{inst.code:8}  {rid:40}  {inst.description}\n")


@app.command("explain", help="Print one rule's summary and the links to its examples and evidence.")
def _explain_command(
    context: typer.Context, which: Annotated[str, typer.Argument(metavar="rule", help="Rule ID or SARJ code.")]
) -> None:
    context.ensure_object(_Result).code = _explain(which)


@app.command("check", help="Run rules over files.")
def _check_command(
    context: typer.Context,
    files: Annotated[list[Path], typer.Argument()],
    rule: Annotated[list[str], typer.Option("--rule", help="Rule ID (repeat for multiple).")],
    *,
    baseline: Annotated[
        Path | None, typer.Option(help="Per-file shrink-only baseline JSON: {path: {CODE: count}}.")
    ] = None,
    update_baseline: Annotated[
        Path | None, typer.Option(help="Write current per-file diagnostic counts to JSON and exit 0.")
    ] = None,
    fix: Annotated[
        bool, typer.Option("--fix", help="Apply proven safe fixes before checking the remaining diagnostics.")
    ] = False,
    jobs: Annotated[int, typer.Option(min=1, help="Analysis worker budget (up to 2); default is serial.")] = 1,
) -> None:
    if fix:
        from sarj_python_lint.autofix import fix_paths  # ruff: ignore[import-outside-top-level] -- load mutation support only for an explicit fix request.

        registry = _rule_registry()
        canonical = _canonical_rule_ids(rule)
        unknown = [rule_id for rule_id in canonical if rule_id not in registry]
        if unknown:
            context.ensure_object(_Result).code = _run_check(rule, files, baseline, update_baseline, jobs=jobs)
            return
        try:
            fix_paths(files, rule_ids=canonical)
        except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
            sys.stderr.write(f"error: {exc}\n")
            context.ensure_object(_Result).code = 2
            return
    context.ensure_object(_Result).code = _run_check(rule, files, baseline, update_baseline, jobs=jobs)


def main(argv: list[str] | None = None) -> int:
    result = _Result()
    try:
        app(args=argv, prog_name="sarj-python-lint", obj=result)
    except SystemExit as exc:
        if exc.code != 0:
            raise
    return result.code


if __name__ == "__main__":
    sys.exit(main())

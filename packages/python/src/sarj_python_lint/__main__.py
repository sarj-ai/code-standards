from __future__ import annotations

import ast
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from fnmatch import fnmatch
import json
import multiprocessing
import os
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Annotated, NamedTuple

import typer

from sarj_python_lint import __version__
from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint._filesystem import atomic_write_text
from sarj_python_lint._source import read_python_source
from sarj_python_lint.json_boundary import is_object_mapping, parse_json
from sarj_python_lint.rule_base import Diagnostic, ProjectRule, Rule, Severity, is_suppressed
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._paths import clear_path_caches
from sarj_python_lint.rules._project_index import ProjectIndexSet


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

# Skip files larger than this — they are almost always generated/vendored, not
# hand-written source worth linting.
_MAX_FILE_BYTES = 500_000

# Per-file rule evaluation dominates large trees and is independent once the
# project index exists, so large inputs fan out to worker processes.
_PARALLEL_MIN_FILES = 200
_PARALLEL_CHUNK_FILES = 32


def expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            msg = f"input does not exist: {p}"
            raise ValueError(msg)
        if p.is_file():
            try:
                if p.stat().st_size <= _MAX_FILE_BYTES:
                    out.append(p)
            except OSError:
                pass
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
            try:
                if child.is_file() and child.stat().st_size <= _MAX_FILE_BYTES:
                    out.append(child)
            except OSError:
                continue
    return sorted(out)


def _canonical_rule_ids(rule_ids: list[str]) -> list[str]:
    aliases = {
        alias: rule_id
        for rule_id, cls in REGISTRY.items()
        if (documentation := cls.documentation) is not None
        for alias in documentation.aliases
    }
    return list(dict.fromkeys(rid if rid in REGISTRY else aliases.get(rid, rid) for rid in rule_ids))


@dataclass(slots=True)
class _PreparedCheck:
    rules: list[Rule]
    session: AnalysisSession
    loaded: dict[Path, str]


def _prepare_check(rule_ids: list[str], paths: list[Path]) -> _PreparedCheck:
    rules = [REGISTRY[rid]() for rid in rule_ids]
    session = AnalysisSession()
    for rule in rules:
        rule.prepare_session(session)
    clear_path_caches()
    expanded = expand_paths(paths)
    loaded: dict[Path, str] = {}
    for path in expanded:
        try:
            loaded[path] = read_python_source(path)
        except OSError:
            continue
    project_rules = [rule for rule in rules if isinstance(rule, ProjectRule)]
    if project_rules:
        indexes = ProjectIndexSet.build(expanded, loaded, facts=session.first_party)
        session.project = indexes
        for rule in project_rules:
            rule.prepare(indexes)
    return _PreparedCheck(rules, session, loaded)


def _check(rule_ids: list[str], paths: list[Path]) -> list[Diagnostic]:
    rule_ids = _canonical_rule_ids(rule_ids)
    unknown = [rid for rid in rule_ids if rid not in REGISTRY]
    if unknown:
        sys.stderr.write(f"unknown rule(s): {', '.join(unknown)}\n")
        sys.stderr.write(f"available: {', '.join(sorted(REGISTRY))}\n")
        raise SystemExit(2)
    expanded = expand_paths(paths)
    workers = _worker_count(len(expanded))
    if workers > 1:
        return _check_in_processes(rule_ids, paths, expanded, workers)
    prepared = _prepare_check(rule_ids, paths)
    diags: list[Diagnostic] = []
    for p, source in prepared.loaded.items():
        diags.extend(check_source(prepared.rules, p, source, session=prepared.session))
    return diags


def _worker_count(file_count: int) -> int:
    configured = os.environ.get("SARJ_PYTHON_LINT_JOBS", "")  # ruff: ignore[banned-api] -- explicit operator override.
    available = int(configured) if configured.isdigit() else os.process_cpu_count() or 1
    if file_count < _PARALLEL_MIN_FILES:
        return 1
    return max(1, min(available, file_count // _PARALLEL_CHUNK_FILES))


_worker_state: _PreparedCheck | None = None


def _initialize_worker(rule_ids: list[str], paths: list[Path]) -> None:
    global _worker_state  # noqa: PLW0603 -- one prepared analysis per worker process.
    _worker_state = _prepare_check(rule_ids, paths)


def _check_chunk(files: list[Path]) -> list[Diagnostic]:
    state = _worker_state
    if state is None:
        msg = "worker analysis was not prepared"
        raise RuntimeError(msg)
    diags: list[Diagnostic] = []
    for p in files:
        source = state.loaded.get(p)
        if source is not None:
            diags.extend(check_source(state.rules, p, source, session=state.session))
    return diags


def _check_in_processes(rule_ids: list[str], paths: list[Path], files: list[Path], workers: int) -> list[Diagnostic]:
    chunks = [files[start : start + _PARALLEL_CHUNK_FILES] for start in range(0, len(files), _PARALLEL_CHUNK_FILES)]
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize_worker,
        initargs=(rule_ids, paths),
    ) as pool:
        return [diagnostic for chunk in pool.map(_check_chunk, chunks) for diagnostic in chunk]


def check_source(
    rules: list[Rule], p: Path, source: str, *, session: AnalysisSession | None = None
) -> list[Diagnostic]:
    context = PythonFileContext(p, source, session)
    source_lines = context.source_lines
    raw = [diagnostic for rule in rules for diagnostic in rule.check_context(context)]
    return deduplicate_diagnostics(
        [
            diagnostic
            for diagnostic in raw
            if diagnostic.code == "SARJ419" or not is_suppressed(source_lines, diagnostic.line, diagnostic.code)
        ],
        source=source,
        context=context,
    )


def analyze(
    rule_ids: list[str],
    paths: list[Path],
    *,
    baseline: Path | None = None,
    root: Path | None = None,
) -> list[Diagnostic]:
    diagnostics = _check(rule_ids, paths)
    return diagnostics if baseline is None else _apply_baseline(diagnostics, _read_baseline(baseline), root=root)


_DIAGNOSTIC_PRECEDENCE = MappingProxyType(
    {
        "SARJ050": frozenset({"SARJ420"}),
        "SARJ084": frozenset({"SARJ050", "SARJ420"}),
        "SARJ085": frozenset({"SARJ420"}),
        "SARJ086": frozenset({"SARJ420"}),
        "SARJ087": frozenset({"SARJ420"}),
        "SARJ088": frozenset({"SARJ050", "SARJ085", "SARJ420"}),
        "SARJ092": frozenset({"SARJ086", "SARJ087", "SARJ420"}),
        "SARJ093": frozenset({"SARJ034"}),
        # Visible FastAPI operations have a route-aware contract diagnostic.
        # Keep the annotation diagnostics when SARJ094 is absent, including
        # when a concrete response_model makes the route contract complete.
        "SARJ094": frozenset({"SARJ008", "SARJ447"}),
        "SARJ095": frozenset({"SARJ468"}),
        "SARJ099": frozenset({"SARJ420"}),
        # Any-valued mappings are the stronger correctness failure. SARJ008
        # still owns every fixed dictionary return when selected alone, while
        # an all-rules run emits one actionable diagnostic for this overlap.
        "SARJ447": frozenset({"SARJ008"}),
        "SARJ457": frozenset({"SARJ045"}),
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
            if diagnostic.code == "SARJ094" and not diagnostic.message.startswith("[return]"):
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
    # SARJ094 is deliberately staged as a warning while teams calibrate the
    # FastAPI contract policy. Its route-aware return finding still owns the
    # overlapping annotation failure: emitting the blocking SARJ447 twin would
    # defeat warning staging and give two remediations for one return contract.
    if "SARJ094" in codes:
        suppressed.update(_route_contract_suppressions(codes))
    # The promoted signature-restatement rules now block. Keep their errors and
    # drop only the lower-severity typed-docstring twin at the same owner.
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
    key = wanted.strip()
    cls = REGISTRY.get(key) or next((c for c in REGISTRY.values() if c.code.upper() == key.upper()), None)
    if cls is None:
        sys.stderr.write(f"unknown rule: {wanted}\navailable: {', '.join(sorted(REGISTRY))}\n")
        return 2
    sys.stdout.write(f"{cls.code}  {cls.id}\n{cls.description}\nexamples: {cls.examples_url()}\n")
    return 0


def _baseline_counts(diags: list[Diagnostic]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for d in diags:
        if d.severity is Severity.WARNING:
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
        if d.severity is Severity.WARNING:
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


def _run_check(rule: list[str], files: list[Path], baseline: Path | None, update_baseline: Path | None) -> int:
    try:
        diags = analyze(rule, files)
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
    for rid, cls in sorted(REGISTRY.items()):
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
    baseline: Annotated[
        Path | None, typer.Option(help="Per-file shrink-only baseline JSON: {path: {CODE: count}}.")
    ] = None,
    update_baseline: Annotated[
        Path | None, typer.Option(help="Write current per-file diagnostic counts to JSON and exit 0.")
    ] = None,
) -> None:
    context.ensure_object(_Result).code = _run_check(rule, files, baseline, update_baseline)


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

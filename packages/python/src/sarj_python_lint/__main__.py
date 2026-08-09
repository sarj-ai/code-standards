"""CLI: sarj-python-lint check --rule <id> [--rule <id2>] [--baseline <json>] <files>."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import sys
from types import MappingProxyType

from sarj_python_lint import __version__
from sarj_python_lint.rule_base import Diagnostic, Severity, is_suppressed
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._paths import clear_path_caches


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


def _expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            continue
        if p.is_file():
            try:
                if p.stat().st_size <= _MAX_FILE_BYTES:
                    out.append(p)
            except OSError:
                pass
            continue
        for child in p.rglob("*.py"):
            if not child.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in child.parts):
                continue
            try:
                if child.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            out.append(child)
    return out


def _check(rule_ids: list[str], paths: list[Path]) -> list[Diagnostic]:
    unknown = [rid for rid in rule_ids if rid not in REGISTRY]
    if unknown:
        sys.stderr.write(f"unknown rule(s): {', '.join(unknown)}\n")
        sys.stderr.write(f"available: {', '.join(sorted(REGISTRY))}\n")
        raise SystemExit(2)
    rules = [REGISTRY[rid]() for rid in rule_ids]
    clear_path_caches()
    expanded = _expand_paths(paths)
    diags: list[Diagnostic] = []
    for p in expanded:
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source_lines = source.splitlines()
        raw = [diagnostic for rule in rules for diagnostic in rule.check(p, source)]
        diags.extend(
            diagnostic
            for diagnostic in deduplicate_diagnostics(
                [diagnostic for diagnostic in raw if not is_suppressed(source_lines, diagnostic.line, diagnostic.code)],
                source=source,
            )
        )
    return diags


def analyze(
    rule_ids: list[str],
    paths: list[Path],
    *,
    baseline: Path | None = None,
    root: Path | None = None,
) -> list[Diagnostic]:
    """Return native diagnostics without rendering CLI output."""
    diagnostics = _check(rule_ids, paths)
    return diagnostics if baseline is None else _apply_baseline(diagnostics, _read_baseline(baseline), root=root)


_DIAGNOSTIC_PRECEDENCE = MappingProxyType(
    {
        "SARJ003": frozenset({"SARJ080"}),
        "SARJ084": frozenset({"SARJ050", "SARJ091"}),
        "SARJ088": frozenset({"SARJ050", "SARJ085", "SARJ091"}),
        "SARJ092": frozenset({"SARJ086", "SARJ087"}),
        "SARJ093": frozenset({"SARJ034"}),
    }
)


def deduplicate_diagnostics(diags: list[Diagnostic], *, source: str | None = None) -> list[Diagnostic]:
    """Keep the most specific remediation at a source location."""
    codes = frozenset(diagnostic.code for diagnostic in diags)
    needs_docstring_owners = "SARJ092" in codes and not codes.isdisjoint(_DIAGNOSTIC_PRECEDENCE["SARJ092"])
    docstring_owners = _docstring_owner_locations(source) if source is not None and needs_docstring_owners else {}
    needs_signature_owners = "SARJ093" in codes and "SARJ034" in codes
    signature_owners = (
        _function_signature_owner_locations(source) if source is not None and needs_signature_owners else {}
    )

    def owner_location(diagnostic: Diagnostic) -> tuple[int, int]:
        if diagnostic.code in {"SARJ034", "SARJ093"}:
            return signature_owners.get(diagnostic.line, (diagnostic.line, diagnostic.col))
        return docstring_owners.get(diagnostic.line, (diagnostic.line, diagnostic.col))

    present: dict[tuple[Path, int, int], dict[str, set[Severity]]] = {}
    for diagnostic in diags:
        line, col = owner_location(diagnostic)
        by_code = present.setdefault((diagnostic.path, line, col), {})
        by_code.setdefault(diagnostic.code, set()).add(diagnostic.severity)
    suppressed = {
        (location, generic, generic_severity)
        for location, codes in present.items()
        for specific, generics in _DIAGNOSTIC_PRECEDENCE.items()
        if specific in codes
        for generic in generics
        for generic_severity in codes.get(generic, set())
        if generic_severity is Severity.WARNING or Severity.ERROR in codes[specific]
    }
    return [
        diagnostic
        for diagnostic in diags
        if (
            (
                (
                    diagnostic.path,
                    *owner_location(diagnostic),
                ),
                diagnostic.code,
                diagnostic.severity,
            )
            not in suppressed
        )
    ]


def _function_signature_owner_locations(source: str) -> dict[int, tuple[int, int]]:
    """Map signature lines to their function opening for cross-rule precedence."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    owners: dict[int, tuple[int, int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body_line = node.body[0].lineno if node.body else node.lineno + 1
        end_line = max(node.lineno, body_line - 1)
        owners.update(dict.fromkeys(range(node.lineno, end_line + 1), (node.lineno, node.col_offset + 1)))
    return owners


def _docstring_owner_locations(source: str) -> dict[int, tuple[int, int]]:
    """Map every physical docstring line to the opening expression that owns it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is None:
        return {}
    owners: dict[int, tuple[int, int]] = {}
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
        location = (expression.lineno, expression.col_offset + 1)
        lines = range(expression.lineno, (expression.end_lineno or expression.lineno) + 1)
        owners.update(dict.fromkeys(lines, location))
    return owners


class _Args(argparse.Namespace):
    cmd: str | None
    rule: list[str]
    # `explain` takes exactly one rule, so it cannot share `--rule`'s list slot
    # without widening the type and losing the check on every `check` call site.
    which: str
    files: list[Path]
    baseline: Path | None
    update_baseline: Path | None

    def __init__(self) -> None:
        super().__init__()
        self.cmd = None
        self.rule = []
        self.which = ""
        self.files = []
        self.baseline = None
        self.update_baseline = None


def _explain(wanted: str) -> int:
    """Print a rule's description and its derived examples link."""
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
    """Make baselines portable when a caller supplies repository-absolute paths."""
    try:
        return path.resolve().relative_to((Path.cwd() if root is None else root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_baseline(path: Path) -> dict[str, dict[str, int]]:
    """Load a baseline file, keeping only well-formed `{path: {CODE: count}}` entries."""
    raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        path.read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, dict[str, int]] = {}
    for file_key, per_code in raw.items():  # pyright: ignore[reportUnknownVariableType] — json.loads yields Any leaves
        if not isinstance(file_key, str) or not isinstance(per_code, dict):
            continue
        counts[file_key] = {
            code: n
            for code, n in per_code.items()  # pyright: ignore[reportUnknownVariableType] — same
            if isinstance(code, str) and isinstance(n, int)
        }
    return counts


def _apply_baseline(
    diags: list[Diagnostic],
    baseline: dict[str, dict[str, int]],
    *,
    root: Path | None = None,
) -> list[Diagnostic]:
    """Suppress up to the baselined count per (path, code); excess diags survive."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sarj-python-lint",
        description="Custom Python + SQL lint rules.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("check", help="Run rules over files.")
    check_p.add_argument(
        "--rule",
        action="append",
        required=True,
        help="Rule ID (repeat for multiple).",
    )
    check_p.add_argument(
        "--baseline",
        type=Path,
        help="Per-file shrink-only baseline JSON: {path: {CODE: count}}. Diags up to the baselined count are suppressed.",
    )
    check_p.add_argument(
        "--update-baseline",
        type=Path,
        help="Write the current per-file diagnostic counts to this JSON and exit 0.",
    )
    check_p.add_argument("files", nargs="+", type=Path)

    sub.add_parser("list-rules", help="List available rule IDs.")

    explain_p = sub.add_parser("explain", help="Print one rule's summary and the links to its examples and evidence.")
    explain_p.add_argument("which", metavar="rule", help="Rule ID or SARJ code.")

    args = parser.parse_args(argv, namespace=_Args())

    if args.cmd == "list-rules":
        for rid, cls in sorted(REGISTRY.items()):
            inst = cls()
            sys.stdout.write(f"{inst.code:8}  {rid:40}  {inst.description}\n")
        return 0

    if args.cmd == "explain":
        return _explain(args.which)

    diags = analyze(args.rule, args.files)
    if args.update_baseline is not None:
        counts = _baseline_counts(diags)
        blocking = sum(d.severity is Severity.ERROR for d in diags)
        warnings = len(diags) - blocking
        args.update_baseline.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
        sys.stdout.write(
            f"baseline written: {args.update_baseline} "
            f"({blocking} blocking diagnostics over {len(counts)} files; {warnings} warnings excluded)\n"
        )
        return 0
    if args.baseline is not None:
        diags = _apply_baseline(diags, _read_baseline(args.baseline))
    for d in diags:
        sys.stdout.write(d.format() + "\n")
    return 1 if any(d.severity is Severity.ERROR for d in diags) else 0


if __name__ == "__main__":
    sys.exit(main())

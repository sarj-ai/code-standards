"""CLI: sarj-python-lint check --rule <id> [--rule <id2>] [--baseline <json>] <files>."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from sarj_python_lint import __version__
from sarj_python_lint.rule_base import Diagnostic, Severity, is_suppressed
from sarj_python_lint.rules import REGISTRY


SKIP_DIR_NAMES = {
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
    ".mypy_cache",
    ".turbo",
    ".yarn",
    ".pnpm-store",
}

# Skip files larger than this — they are almost always generated/vendored, not
# hand-written source worth linting.
_MAX_FILE_BYTES = 500_000


def _expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            continue
        if p.is_file():
            out.append(p)
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
    expanded = _expand_paths(paths)
    diags: list[Diagnostic] = []
    for p in expanded:
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source_lines = source.splitlines()
        for rule in rules:
            for d in rule.check(p, source):
                if is_suppressed(source_lines, d.line, d.code):
                    continue
                diags.append(d)
    return diags


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
    """Print a rule's summary plus the derived links to its examples and evidence.

    This is the runtime consumer of the one-line module docstring: it is what
    makes an inaccurate summary visible rather than merely unread.

    """
    key = wanted.strip()
    cls = REGISTRY.get(key) or next((c for c in REGISTRY.values() if c.code.upper() == key.upper()), None)
    if cls is None:
        sys.stderr.write(f"unknown rule: {wanted}\navailable: {', '.join(sorted(REGISTRY))}\n")
        return 2
    summary = (sys.modules[cls.__module__].__doc__ or "").strip().splitlines()
    sys.stdout.write(
        f"{cls.code}  {cls.id}\n{summary[0] if summary else cls.description}\nexamples: {cls.examples_url()}\n"
    )
    if cls.has_evidence:
        sys.stdout.write(f"evidence: {cls.evidence_url()}\n")
    return 0


def _baseline_counts(diags: list[Diagnostic]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for d in diags:
        if d.severity is Severity.WARNING:
            continue
        counts.setdefault(str(d.path), {})
        counts[str(d.path)][d.code] = counts[str(d.path)].get(d.code, 0) + 1
    return counts


def _read_baseline(path: Path) -> dict[str, dict[str, int]]:
    """Load a baseline file, keeping only well-formed `{path: {CODE: count}}` entries.

    `json.loads` returns `Any`, so the shape is narrowed here rather than
    asserted — a hand-edited baseline should degrade to "not baselined" rather
    than crash the run or silently suppress on a malformed entry.

    """
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


def _apply_baseline(diags: list[Diagnostic], baseline: dict[str, dict[str, int]]) -> list[Diagnostic]:
    """Suppress up to the baselined count per (path, code); excess diags survive."""
    seen: Counter[tuple[str, str]] = Counter()
    out: list[Diagnostic] = []
    for d in diags:
        if d.severity is Severity.WARNING:
            out.append(d)
            continue
        key = (str(d.path), d.code)
        seen[key] += 1
        if seen[key] > baseline.get(key[0], {}).get(key[1], 0):
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

    diags = _check(args.rule, args.files)
    if args.update_baseline is not None:
        args.update_baseline.write_text(json.dumps(_baseline_counts(diags), indent=2, sort_keys=True) + "\n")
        sys.stdout.write(
            f"baseline written: {args.update_baseline} ({len(diags)} diagnostics over {len(_baseline_counts(diags))} files)\n"
        )
        return 0
    if args.baseline is not None:
        diags = _apply_baseline(diags, _read_baseline(args.baseline))
    for d in diags:
        sys.stdout.write(d.format() + "\n")
    return 1 if any(d.severity is Severity.ERROR for d in diags) else 0


if __name__ == "__main__":
    sys.exit(main())

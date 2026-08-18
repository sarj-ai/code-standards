from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile

from sarj_iac_lint import __version__
from sarj_iac_lint.rule_base import Diagnostic, is_suppressed
from sarj_iac_lint.rules import REGISTRY


SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        ".git",
        "dist",
        "build",
        ".terraform",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
)

# YAML files are included for banner checks while HCL rules self-filter by extension.
# `.json` is collected so that a root whose inputs are JSON-only still reaches a
# rule: no rule parses JSON, and the ones that care report that they are blind
# rather than passing a tree they never read.
_SCANNED_SUFFIXES = frozenset({".tf", ".hcl", ".tfvars", ".yaml", ".yml", ".json"})

_MAX_FILE_BYTES = 500_000


def _expand_paths(paths: list[Path]) -> list[Path]:
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
        for child in p.rglob("*"):
            if not child.is_file() or child.suffix not in _SCANNED_SUFFIXES:
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
    diags: list[Diagnostic] = []
    for p in _expand_paths(paths):
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source_lines = source.splitlines()
        for rule in rules:
            for d in rule.check(p, source):
                if d.suppressible and is_suppressed(source_lines, d.line, d.code):
                    continue
                diags.append(d)
    return diags


def analyze(rule_ids: list[str], paths: list[Path]) -> list[Diagnostic]:
    return _check(rule_ids, paths)


def _baseline_path(path: Path, *, root: Path | None = None) -> str:
    try:
        return path.resolve().relative_to((Path.cwd() if root is None else root).resolve()).as_posix()
    except ValueError:
        return str(path)


def baseline_counts(diags: list[Diagnostic], *, root: Path | None = None) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for d in diags:
        key = _baseline_path(d.path, root=root)
        per_code = counts.setdefault(key, {})
        per_code[d.code] = per_code.get(d.code, 0) + 1
    return counts


def read_baseline(path: Path) -> dict[str, dict[str, int]]:
    raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        path.read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, dict[str, int]] = {}
    for file_key, per_code in raw.items():  # pyright: ignore[reportUnknownVariableType] — json leaves are Any; narrowed below
        if not isinstance(file_key, str) or not isinstance(per_code, dict):
            continue
        counts[file_key] = {
            code: n
            for code, n in per_code.items()  # pyright: ignore[reportUnknownVariableType] — same
            if isinstance(code, str) and isinstance(n, int) and not isinstance(n, bool)
        }
    return counts


def apply_baseline(
    diags: list[Diagnostic],
    baseline: dict[str, dict[str, int]],
    *,
    root: Path | None = None,
) -> list[Diagnostic]:
    seen: Counter[tuple[str, str]] = Counter()
    out: list[Diagnostic] = []
    for d in diags:
        path_key = _baseline_path(d.path, root=root)
        key = (path_key, d.code)
        seen[key] += 1
        # The raw lookup keeps baselines written with absolute paths working.
        allowance = max(
            baseline.get(path_key, {}).get(d.code, 0),
            baseline.get(str(d.path), {}).get(d.code, 0),
        )
        if not d.baselineable or seen[key] > allowance:
            out.append(d)
    return out


def _atomic_write_text(path: Path, text: str) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class _Args(argparse.Namespace):
    cmd: str | None
    rule: list[str]
    files: list[Path]
    exit_zero: bool
    baseline: Path | None
    update_baseline: Path | None

    def __init__(self) -> None:
        super().__init__()
        self.cmd = None
        self.rule = []
        self.files = []
        self.exit_zero = False
        self.baseline = None
        self.update_baseline = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sarj-iac-lint",
        description="Custom Terraform / IaC lint rules.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("check", help="Run rules over files.")
    check_p.add_argument("--rule", action="append", required=True, help="Rule ID.")
    check_p.add_argument("--exit-zero", action="store_true", help="Report but exit 0.")
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

    args = parser.parse_args(argv, namespace=_Args())

    if args.cmd == "list-rules":
        for rid, cls in sorted(REGISTRY.items()):
            inst = cls()
            sys.stdout.write(f"{inst.code:8}  {rid:34}  {inst.description}\n")
        return 0

    try:
        diags = analyze(args.rule, args.files)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    if args.update_baseline is not None:
        counts = baseline_counts(diags)
        try:
            _atomic_write_text(args.update_baseline, json.dumps(counts, indent=2, sort_keys=True) + "\n")
        except OSError as exc:
            sys.stderr.write(f"error: cannot write baseline {args.update_baseline}: {exc}\n")
            return 2
        sys.stdout.write(
            f"baseline written: {args.update_baseline} ({len(diags)} diagnostics over {len(counts)} files)\n"
        )
        return 0
    if args.baseline is not None:
        try:
            diags = apply_baseline(diags, read_baseline(args.baseline))
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"error: invalid baseline {args.baseline}: {exc}\n")
            return 2
    for d in diags:
        sys.stdout.write(d.format() + "\n")
    if args.exit_zero:
        return 0
    return 1 if diags else 0


if __name__ == "__main__":
    sys.exit(main())

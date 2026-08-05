"""CLI: sarj-sql-lint check --rule <id> [--rule <id2>] <files>."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sarj_sql_lint import __version__
from sarj_sql_lint.rule_base import Diagnostic, clear_path_caches, is_suppressed
from sarj_sql_lint.rules import REGISTRY


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
        ".mypy_cache",
        ".turbo",
        ".yarn",
        ".pnpm-store",
    }
)
MAX_FILE_BYTES = 500_000


def _expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            continue
        if p.is_file():
            try:
                if p.stat().st_size <= MAX_FILE_BYTES:
                    out.append(p)
            except OSError:
                pass
            continue
        for child in p.rglob("*.sql"):
            if not child.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in child.parts):
                continue
            try:
                if child.stat().st_size > MAX_FILE_BYTES:
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
        for rule in rules:
            diags.extend(d for d in rule.check(p, source) if not is_suppressed(source_lines, d.line, d.code))
    return diags


class _Args(argparse.Namespace):
    cmd: str | None
    rule: list[str]
    files: list[Path]

    def __init__(self) -> None:
        super().__init__()
        self.cmd = None
        self.rule = []
        self.files = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sarj-sql-lint", description="Custom SQL lint rules.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("check", help="Run rules over .sql files.")
    check_p.add_argument("--rule", action="append", required=True, help="Rule ID (repeat for multiple).")
    check_p.add_argument("files", nargs="+", type=Path)

    sub.add_parser("list-rules", help="List available rule IDs.")

    args = parser.parse_args(argv, namespace=_Args())

    if args.cmd == "list-rules":
        for rid, cls in sorted(REGISTRY.items()):
            inst = cls()
            sys.stdout.write(f"{inst.code:8}  {rid:40}  {inst.description}\n")
        return 0

    diags = _check(args.rule, args.files)
    for d in diags:
        sys.stdout.write(d.format() + "\n")
    return 1 if diags else 0


if __name__ == "__main__":
    sys.exit(main())

"""CLI: sarj-iac-lint check --rule <id> [--rule <id2>] <files>."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sarj_iac_lint import __version__
from sarj_iac_lint.rule_base import Diagnostic, is_suppressed
from sarj_iac_lint.rules import REGISTRY


SKIP_DIR_NAMES = {
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

# `.yaml`/`.yml` are collected so `no-comment-cruft` banner detection reaches
# Helm/k8s/Compose IaC. The CIDR and deletion-protection rules self-filter to
# `.tf`/`.hcl`, so on YAML only the (HCL-agnostic) banner check runs.
_SCANNED_SUFFIXES = frozenset({".tf", ".hcl", ".tfvars", ".yaml", ".yml"})

_MAX_FILE_BYTES = 500_000


def _expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            continue
        if p.is_file():
            out.append(p)
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
                if is_suppressed(source_lines, d.line, d.code):
                    continue
                diags.append(d)
    return diags


class _Args(argparse.Namespace):
    cmd: str | None
    rule: list[str]
    files: list[Path]
    exit_zero: bool

    def __init__(self) -> None:
        super().__init__()
        self.cmd = None
        self.rule = []
        self.files = []
        self.exit_zero = False


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
    check_p.add_argument("files", nargs="+", type=Path)

    sub.add_parser("list-rules", help="List available rule IDs.")

    args = parser.parse_args(argv, namespace=_Args())

    if args.cmd == "list-rules":
        for rid, cls in sorted(REGISTRY.items()):
            inst = cls()
            sys.stdout.write(f"{inst.code:8}  {rid:34}  {inst.description}\n")
        return 0

    diags = _check(args.rule, args.files)
    for d in diags:
        sys.stdout.write(d.format() + "\n")
    if args.exit_zero:
        return 0
    return 1 if diags else 0


if __name__ == "__main__":
    sys.exit(main())

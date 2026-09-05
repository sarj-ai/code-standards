from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Annotated

import typer

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
            msg = f"input does not exist: {p}"
            raise ValueError(msg)
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


def analyze(rule_ids: list[str], paths: list[Path]) -> list[Diagnostic]:
    return _check(rule_ids, paths)


@dataclass
class _Result:
    code: int = 0


app = typer.Typer(
    help="Custom SQL lint rules.",
    add_completion=False,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _show_version(*, value: bool) -> None:
    if value:
        sys.stdout.write(f"sarj-sql-lint {__version__}\n")
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


@app.command("check", help="Run rules over .sql files.")
def _check_command(
    context: typer.Context,
    files: Annotated[list[Path], typer.Argument(parser=Path)],
    rule: Annotated[list[str], typer.Option("--rule", help="Rule ID (repeat for multiple).")],
) -> None:
    context.ensure_object(_Result).code = _run_check(rule, files)


def _run_check(rule: list[str], files: list[Path]) -> int:
    try:
        diags = analyze(rule, files)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    for d in diags:
        sys.stdout.write(d.format() + "\n")
    return 1 if diags else 0


def main(argv: list[str] | None = None) -> int:
    result = _Result()
    try:
        app(args=argv, prog_name="sarj-sql-lint", obj=result)
    except SystemExit as exc:
        if exc.code != 0:
            raise
    return result.code


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed local Ruff introspection only
import sys
from typing import TYPE_CHECKING, Annotated, TypeGuard

import typer

from sarj_python_lint._filesystem import atomic_write_text
from sarj_python_lint._version import __version__
from sarj_python_lint.ratchet import (
    DEFAULT_PER_FILE_CEILING,
    Baseline,
    discover_packages,
    dump_baseline,
    gate,
    improvements,
    load_baseline,
    measure,
    seed,
)


if TYPE_CHECKING:
    from sarj_python_lint.ratchet import Measurement


_DEFAULT_BASELINE_NAME = "suppression-baseline.json"


@dataclass(frozen=True)
class _Options:
    root: Path
    baseline: Path | None
    package: list[str]
    exclude_subtree: list[str]
    per_file_ceiling: int | None
    update: bool
    allow_increase: bool


def _run(args: _Options) -> int:
    root = args.root.resolve()
    baseline_path = args.baseline if args.baseline is not None else root / _DEFAULT_BASELINE_NAME

    if args.allow_increase and not args.update:
        sys.stderr.write("sarj-ratchet: --allow-increase requires --update\n")
        return 2
    if args.baseline is not None and not baseline_path.exists() and not args.update:
        sys.stderr.write(f"sarj-ratchet: baseline does not exist: {baseline_path}\n")
        return 2
    try:
        baseline = load_baseline(baseline_path) if baseline_path.exists() else Baseline()
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"sarj-ratchet: invalid baseline {baseline_path}: {exc}\n")
        return 2
    if args.per_file_ceiling is not None:
        baseline = Baseline(
            codes=baseline.codes,
            packages=baseline.packages,
            per_file_ceiling=args.per_file_ceiling,
            file_exceptions=baseline.file_exceptions,
            excluded_subtrees=baseline.excluded_subtrees,
        )

    packages = args.package or sorted(baseline.packages) or discover_packages(root)
    invalid_packages = [
        package
        for package in args.package
        if not (root / package).is_dir() or not next((root / package).rglob("*.py"), None)
    ]
    if invalid_packages:
        sys.stderr.write(f"sarj-ratchet: package has no Python sources: {', '.join(invalid_packages)}\n")
        return 2
    if not packages:
        sys.stderr.write(f"sarj-ratchet: no Python packages found under {root}\n")
        return 1

    excluded_subtrees = tuple(args.exclude_subtree) or baseline.excluded_subtrees
    baseline = Baseline(
        codes=baseline.codes,
        packages=baseline.packages,
        per_file_ceiling=baseline.per_file_ceiling,
        file_exceptions=baseline.file_exceptions,
        excluded_subtrees=excluded_subtrees,
    )
    try:
        ruff_aliases = _ruff_selector_aliases()
        measurement = measure(
            root,
            packages,
            excluded_subtrees=excluded_subtrees,
            ruff_aliases=ruff_aliases,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"sarj-ratchet: cannot measure suppressions: {exc}\n")
        return 2

    if args.update:
        # A first seed has nothing to raise: every ceiling is 0 only because no
        # baseline exists yet, and refusing that would make the tool unusable
        # on the run that adopts it.
        return _update(
            measurement,
            baseline,
            baseline_path,
            packages,
            allow_increase=args.allow_increase or not baseline_path.exists(),
        )

    sys.stdout.write(
        f"{measurement.total} suppressions across {len(measurement.codes)} codes "
        f"in {len(packages)} package(s) (baseline total {sum(baseline.codes.values())})\n"
    )
    failures = gate(measurement, baseline)
    for failure in failures:
        sys.stdout.write(f"{failure.format()}\n")
    if failures:
        return 1

    won = improvements(measurement, baseline)
    if won:
        shrunk = ", ".join(f"{key} {ceiling}->{actual}" for key, (ceiling, actual) in sorted(won.items()))
        sys.stdout.write(f"Counts dropped below baseline ({shrunk}) — lock it in: sarj-ratchet --update\n")
    return 0


def _ruff_selector_aliases() -> dict[str, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "rule", "--all", "--output-format", "json"],
        check=True,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    raw: object = json.loads(completed.stdout)  # pyright: ignore[reportAny] -- validated below
    if not _is_object_list(raw):
        msg = "Ruff rule catalog was not a JSON list"
        raise TypeError(msg)
    aliases: dict[str, str] = {}
    for raw_item in raw:
        if not _is_string_object_mapping(raw_item):
            msg = "Ruff rule catalog contains a non-object entry"
            raise TypeError(msg)
        code = raw_item.get("code")
        name = raw_item.get("name")
        if code is None and isinstance(name, str):
            # Ruff accepts the name as the stable selector until it allocates
            # a code, so preserve that suppression identity rather than
            # rejecting a valid Ruff directive.
            canonical = name.lower()
            aliases[canonical] = canonical
            continue
        if not isinstance(code, str) or not isinstance(name, str):
            msg = "Ruff rule catalog entry lacks a string code or name"
            raise TypeError(msg)
        canonical = code.upper()
        aliases[canonical] = canonical
        aliases[name.lower()] = canonical
    return aliases


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_string_object_mapping(value: object) -> TypeGuard[dict[str, object]]:
    # JSON object keys are strings by definition; json.loads supplied `value`.
    return isinstance(value, dict)


@dataclass
class _Result:
    code: int = 0


app = typer.Typer(
    help="Ratchet on lint/type suppressions: per-code, per-package and per-file ceilings that may only shrink.",
    add_completion=False,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _show_version(*, value: bool) -> None:
    if value:
        sys.stdout.write(f"sarj-ratchet {__version__}\n")
        raise typer.Exit


@app.command()
def _command(
    context: typer.Context,
    *,
    root: Annotated[Path, typer.Argument(help="tree to scan (default: cwd)")] = Path(),
    baseline: Annotated[
        Path | None, typer.Option(help=f"baseline JSON (default: <root>/{_DEFAULT_BASELINE_NAME})")
    ] = None,
    package: Annotated[
        list[str] | None,
        typer.Option(
            "--package", help="package directory relative to root (repeatable; default: baseline or auto-discovered)"
        ),
    ] = None,
    exclude_subtree: Annotated[
        list[str] | None, typer.Option("--exclude-subtree", help="root-relative path prefix to skip (repeatable)")
    ] = None,
    per_file_ceiling: Annotated[
        int | None,
        typer.Option(help=f"max suppressions in any one file (default: baseline or {DEFAULT_PER_FILE_CEILING})"),
    ] = None,
    update: Annotated[
        bool, typer.Option("--update", help="rewrite baseline from current counts (refuses to raise a ceiling)")
    ] = False,
    allow_increase: Annotated[
        bool, typer.Option("--allow-increase", help="with --update: permit ceilings to rise (requires explicit review)")
    ] = False,
    _version: Annotated[bool, typer.Option("--version", callback=_show_version, is_eager=True)] = False,
) -> None:
    context.ensure_object(_Result).code = _run(
        _Options(root, baseline, package or [], exclude_subtree or [], per_file_ceiling, update, allow_increase)
    )


def main(argv: list[str] | None = None) -> int:
    result = _Result()
    try:
        app(args=argv, prog_name="sarj-ratchet", obj=result)
    except SystemExit as exc:
        if exc.code != 0:
            raise
    return result.code


def _update(
    measurement: Measurement,
    baseline: Baseline,
    baseline_path: Path,
    packages: list[str],
    *,
    allow_increase: bool,
) -> int:
    would_raise = gate(measurement, baseline)
    if would_raise and not allow_increase:
        sys.stderr.write("REFUSED: --update would raise ceilings; pass --allow-increase if this was reviewed:\n")
        for failure in would_raise:
            sys.stderr.write(f"  [{failure.dimension}] {failure.key}: {failure.ceiling} -> {failure.actual}\n")
        return 1
    try:
        atomic_write_text(baseline_path, dump_baseline(seed(measurement, baseline), packages))
    except OSError as exc:
        sys.stderr.write(f"sarj-ratchet: cannot write baseline {baseline_path}: {exc}\n")
        return 2
    sys.stdout.write(
        f"Baseline updated: {measurement.total} suppressions across {len(measurement.codes)} codes -> {baseline_path}\n"
    )
    return 0


run_ratchet = main


if __name__ == "__main__":
    sys.exit(main())

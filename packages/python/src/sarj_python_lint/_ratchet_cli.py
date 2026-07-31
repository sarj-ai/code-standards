"""CLI: `sarj-ratchet [--baseline PATH] [--package DIR]... [--update [--allow-increase]] [ROOT]`."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from sarj_python_lint import __version__
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


class _Args(argparse.Namespace):
    root: Path
    baseline: Path | None
    package: list[str]
    exclude_subtree: list[str]
    per_file_ceiling: int | None
    update: bool
    allow_increase: bool

    def __init__(self) -> None:
        super().__init__()
        self.root = Path()
        self.baseline = None
        self.package = []
        self.exclude_subtree = []
        self.per_file_ceiling = None
        self.update = False
        self.allow_increase = False


def _build_parser() -> argparse.ArgumentParser:
    """Assemble the argument parser."""
    parser = argparse.ArgumentParser(
        prog="sarj-ratchet",
        description=(
            "Ratchet on lint/type suppressions: per-code, per-package and per-file ceilings that may only shrink."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("root", nargs="?", type=Path, default=Path(), help="tree to scan (default: cwd)")
    parser.add_argument(
        "--baseline",
        type=Path,
        help=f"baseline JSON (default: <root>/{_DEFAULT_BASELINE_NAME})",
    )
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="package directory relative to root (repeatable; default: the baseline's, else auto-discovered)",
    )
    parser.add_argument(
        "--exclude-subtree",
        action="append",
        default=[],
        help="root-relative path prefix to skip, e.g. generated client output (repeatable)",
    )
    parser.add_argument(
        "--per-file-ceiling",
        type=int,
        help=f"max suppressions in any one file (default: the baseline's, else {DEFAULT_PER_FILE_CEILING})",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline from current counts (refuses to raise a ceiling)",
    )
    parser.add_argument(
        "--allow-increase",
        action="store_true",
        help="with --update: permit ceilings to rise (requires explicit review)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ratchet."""
    args = _build_parser().parse_args(argv, namespace=_Args())
    root = args.root.resolve()
    baseline_path = args.baseline if args.baseline is not None else root / _DEFAULT_BASELINE_NAME

    baseline = load_baseline(baseline_path) if baseline_path.exists() else Baseline()
    if args.per_file_ceiling is not None:
        baseline = Baseline(
            codes=baseline.codes,
            packages=baseline.packages,
            per_file_ceiling=args.per_file_ceiling,
            file_exceptions=baseline.file_exceptions,
        )

    packages = args.package or sorted(baseline.packages) or discover_packages(root)
    if not packages:
        sys.stderr.write(f"sarj-ratchet: no Python packages found under {root}\n")
        return 1

    measurement = measure(root, packages, excluded_subtrees=args.exclude_subtree)

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


def _update(
    measurement: Measurement,
    baseline: Baseline,
    baseline_path: Path,
    packages: list[str],
    *,
    allow_increase: bool,
) -> int:
    """Re-seed the baseline, refusing raises unless they were explicitly reviewed."""
    would_raise = gate(measurement, baseline)
    if would_raise and not allow_increase:
        sys.stderr.write("REFUSED: --update would raise ceilings; pass --allow-increase if this was reviewed:\n")
        for failure in would_raise:
            sys.stderr.write(f"  [{failure.dimension}] {failure.key}: {failure.ceiling} -> {failure.actual}\n")
        return 1
    baseline_path.write_text(dump_baseline(seed(measurement, baseline), packages), encoding="utf-8")
    sys.stdout.write(
        f"Baseline updated: {measurement.total} suppressions across {len(measurement.codes)} codes -> {baseline_path}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

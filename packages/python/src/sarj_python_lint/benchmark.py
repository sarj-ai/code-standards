from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from os.path import commonpath
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from typing import Annotated

import typer

from sarj_python_lint.__main__ import analyze, expand_paths
from sarj_python_lint.rules import REGISTRY


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    seconds: float
    diagnostics: int
    diagnostic_digest: str
    peak_memory_bytes: int | None


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    files: int
    source_bytes: int
    source_digest: str
    rules: tuple[str, ...]
    samples: tuple[BenchmarkSample, ...]
    median_seconds: float


def peak_memory_bytes() -> int | None:
    try:
        import resource  # ruff: ignore[import-outside-top-level] — optional Unix-only memory instrumentation.
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def measure(paths: list[Path], rule_ids: list[str] | None = None, *, repeats: int = 5) -> BenchmarkReport:
    if repeats < 1:
        msg = "repeats must be positive"
        raise ValueError(msg)
    selected = sorted(REGISTRY) if rule_ids is None else sorted(rule_ids)
    unknown = sorted(set(selected) - REGISTRY.keys())
    if unknown:
        msg = f"unknown rule(s): {', '.join(unknown)}"
        raise ValueError(msg)
    expanded = sorted(set(expand_paths(paths)))
    if not expanded:
        msg = "benchmark requires at least one Python source file"
        raise ValueError(msg)
    corpus_root = Path(commonpath([path.absolute().parent for path in expanded]))
    source_digest = hashlib.sha256()
    source_bytes = 0
    for path in expanded:
        source = path.read_bytes()
        source_bytes += len(source)
        source_digest.update(str(path.absolute().relative_to(corpus_root)).encode())
        source_digest.update(b"\0")
        source_digest.update(source)
        source_digest.update(b"\0")
    samples: list[BenchmarkSample] = []
    for _ in range(repeats):
        start = perf_counter()
        diagnostics = analyze(selected, expanded)
        elapsed = perf_counter() - start
        digest = hashlib.sha256()
        for diagnostic in diagnostics:
            digest.update(
                json.dumps(
                    [
                        str(diagnostic.path.absolute().relative_to(corpus_root)),
                        diagnostic.line,
                        diagnostic.col,
                        diagnostic.code,
                        diagnostic.message,
                        diagnostic.severity.value,
                        diagnostic.column_encoding.value,
                    ],
                    ensure_ascii=False,
                ).encode()
            )
            digest.update(b"\n")
        samples.append(BenchmarkSample(elapsed, len(diagnostics), digest.hexdigest(), peak_memory_bytes()))
    if len({sample.diagnostic_digest for sample in samples}) != 1:
        msg = "diagnostics changed between benchmark repetitions"
        raise RuntimeError(msg)
    return BenchmarkReport(
        len(expanded),
        source_bytes,
        source_digest.hexdigest(),
        tuple(selected),
        tuple(samples),
        median(sample.seconds for sample in samples),
    )


def _run(
    paths: Annotated[list[Path], typer.Argument(help="Python files or directories to analyze.")],
    repeats: Annotated[int, typer.Option(min=1)] = 5,
    rule: Annotated[list[str] | None, typer.Option(help="Repeat to select rules; defaults to all rules.")] = None,
) -> None:
    try:
        report = measure(paths, rule, repeats=repeats)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    typer.run(_run)

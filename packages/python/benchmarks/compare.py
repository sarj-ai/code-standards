from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
from statistics import median
import subprocess  # ruff: ignore[suspicious-subprocess-import] — fresh workers isolate timing and peak memory.
import sys
from time import perf_counter
from typing import Annotated, Literal, Never

import typer


_DEFAULT_PYTHON = Path(sys.executable)
_PACKAGES = ("python", "contracts")
_ARTIFACT_ROOTS = tuple(
    f"packages/{package}/{directory}"
    for package in _PACKAGES
    for directory in ("src", "native", "rust", "build", "dist")
)
_MANIFEST_NAMES = (
    "pyproject.toml",
    "uv.lock",
    "uv.toml",
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain",
    "rust-toolchain.toml",
    "build.rs",
    "CMakeLists.txt",
    "meson.build",
    "meson_options.txt",
    "setup.py",
    "setup.cfg",
    "MANIFEST.in",
)
_ARTIFACT_MANIFESTS = (
    "mise.toml",
    ".python-version",
    ".node-version",
    *_MANIFEST_NAMES,
    *(f"packages/{package}/{name}" for package in _PACKAGES for name in _MANIFEST_NAMES),
)
_EXCLUDED_DIRECTORIES = frozenset({"__pycache__", "node_modules", "target", "venv"})
_PRIVATE_NAMES = frozenset({"credentials", "credentials.json", "credentials.toml", "secrets.json", "secrets.toml"})
_EXCLUDED_SUFFIXES = frozenset({".key", ".pem", ".pfx", ".p12", ".pyc", ".pyo"})

type MemoryScope = Literal["process-lifetime-self", "unsupported"]

_WORKER = """
import hashlib, json, sys, time
from pathlib import Path
import sarj_python_lint
from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules import REGISTRY
corpus = Path(sys.argv[1])
paths = sorted(corpus.rglob('*.py'))
start = time.perf_counter()
findings = analyze(sorted(REGISTRY), paths)
elapsed = time.perf_counter() - start
rows = [[str(d.path.relative_to(corpus)), d.line, d.col, d.code, d.message, d.severity.value,
         d.column_encoding.value] for d in findings]
peak = None
if sys.platform in {'linux', 'darwin'}:
    try:
        import resource
    except ImportError:
        pass
    else:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({
    'native_seconds': elapsed,
    'diagnostics': len(findings),
    'diagnostic_digest': hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
    'peak_memory_bytes': peak if peak is None or sys.platform == 'darwin' else peak * 1024,
    'memory_scope': 'unsupported' if peak is None else 'process-lifetime-self',
    'rules': len(REGISTRY),
    'imported_from': sarj_python_lint.__file__,
    'python_version': sys.version,
}))
"""


@dataclass(frozen=True, slots=True)
class BaselineIdentity:
    commit: str
    source_tree: str
    source_digest: str
    implementation: ImplementationIdentity


@dataclass(frozen=True, slots=True)
class ImplementationIdentity:
    python_source_digest: str
    contracts_source_digest: str
    harness_digest: str
    artifact_digest: str
    artifact_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Sample:
    native_seconds: float
    diagnostics: int
    diagnostic_digest: str
    peak_memory_bytes: int | None
    rules: int
    imported_from: str
    python_version: str
    memory_scope: MemoryScope
    startup_inclusive_seconds: float = 0.0
    round: int = 0


@dataclass(frozen=True, slots=True)
class Median:
    native_seconds: float
    startup_inclusive_seconds: float
    peak_memory_bytes: float | None
    memory_scope: MemoryScope


@dataclass(frozen=True, slots=True)
class Comparison:
    baseline: BaselineIdentity
    candidate: ImplementationIdentity
    corpus: str
    files: int
    bytes: int
    source_digest: str
    platform: str
    samples: dict[str, list[Sample]]
    summary: dict[str, Median]
    speedup: float
    time_reduction_pct: float


def fingerprint(root: Path, *, paths: list[Path] | None = None) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py") if paths is None else paths):
        if path.is_symlink():
            msg = f"benchmark input must not be a symlink: {path}"
            raise ValueError(msg)
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_output(checkout: Path, *arguments: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        msg = "Git is required to verify the baseline checkout"
        raise RuntimeError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] — fixed read-only Git commands, no shell.
        [executable, "-C", str(checkout), *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


def baseline_identity(checkout: Path) -> BaselineIdentity:
    if git_output(checkout, "status", "--porcelain"):
        msg = "baseline checkout must be clean"
        raise ValueError(msg)
    implementation = implementation_identity(checkout)
    return BaselineIdentity(
        git_output(checkout, "rev-parse", "HEAD"),
        git_output(checkout, "rev-parse", "HEAD:packages/python/src"),
        fingerprint(checkout / "packages/python/src"),
        implementation,
    )


def implementation_identity(checkout: Path) -> ImplementationIdentity:
    artifacts = _implementation_artifacts(checkout)
    digest = hashlib.sha256()
    for path in artifacts:
        digest.update(path.relative_to(checkout).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    python_root = checkout / "packages/python/src"
    contracts_root = checkout / "packages/contracts/src"
    return ImplementationIdentity(
        fingerprint(
            python_root, paths=[path for path in artifacts if path.suffix == ".py" and path.is_relative_to(python_root)]
        ),
        fingerprint(
            contracts_root,
            paths=[path for path in artifacts if path.suffix == ".py" and path.is_relative_to(contracts_root)],
        ),
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        digest.hexdigest(),
        tuple(path.relative_to(checkout).as_posix() for path in artifacts),
    )


def _implementation_artifacts(checkout: Path) -> list[Path]:
    paths: set[Path] = set()
    for relative in ("packages", *(f"packages/{package}" for package in _PACKAGES)):
        _artifact_stat(checkout / relative)
    for relative in _ARTIFACT_MANIFESTS:
        path = checkout / relative
        metadata = _artifact_stat(path)
        if metadata is None:
            continue
        if not stat.S_ISREG(metadata.st_mode):
            msg = f"implementation manifest must be a regular file: {path}"
            raise ValueError(msg)
        paths.add(path)
    for relative in _ARTIFACT_ROOTS:
        root = checkout / relative
        metadata = _artifact_stat(root)
        if metadata is None:
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            msg = f"implementation artifact root must be a directory: {root}"
            raise ValueError(msg)
        for directory, subdirectories, files in os.walk(root, onerror=_raise_artifact_error):
            paths.update(_directory_artifacts(checkout, Path(directory), subdirectories, files))
    return sorted(paths)


def _directory_artifacts(
    checkout: Path, directory: Path, subdirectories: list[str], filenames: list[str]
) -> list[Path]:
    subdirectories[:] = [
        name for name in subdirectories if not _excluded_artifact((directory / name).relative_to(checkout))
    ]
    for name in subdirectories:
        if _artifact_stat(directory / name) is None:
            raise FileNotFoundError(directory / name)
    paths: list[Path] = []
    for name in filenames:
        path = directory / name
        if _excluded_artifact(path.relative_to(checkout)):
            continue
        metadata = _artifact_stat(path)
        if metadata is None or not stat.S_ISREG(metadata.st_mode):
            msg = f"implementation artifact must be a regular file: {path}"
            raise ValueError(msg)
        paths.append(path)
    return paths


def _excluded_artifact(path: Path) -> bool:
    return (
        any(part.startswith(".") or part in _EXCLUDED_DIRECTORIES for part in path.parts)
        or path.name.lower() in _PRIVATE_NAMES
        or path.suffix.lower() in _EXCLUDED_SUFFIXES
    )


def _artifact_stat(path: Path) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        msg = f"implementation artifact must not be a symlink: {path}"
        raise ValueError(msg)
    return metadata


def _raise_artifact_error(error: OSError) -> Never:
    raise error


def sample(checkout: Path, interpreter: Path, corpus: Path, round_number: int) -> Sample:
    search_path = os.pathsep.join(str(checkout / "packages" / package / "src") for package in ("python", "contracts"))
    start = perf_counter()
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] — explicit local interpreter, fixed worker code, no shell.
        [str(interpreter), "-c", _WORKER, str(corpus)],
        env=dict(os.environ, PYTHONPATH=search_path),  # ruff: ignore[banned-api] — preserve the benchmark interpreter's execution environment.
        cwd=checkout,
        text=True,
        capture_output=True,
        check=True,
        timeout=300,
    )
    result = Sample(**json.loads(completed.stdout))  # pyright: ignore[reportAny] -- the fixed worker emits the Sample protocol.
    imported_from = Path(result.imported_from)
    if not imported_from.is_relative_to(checkout):
        msg = f"wrong engine imported: {imported_from}"
        raise RuntimeError(msg)
    return replace(
        result,
        imported_from=str(imported_from.relative_to(checkout)),
        round=round_number,
        startup_inclusive_seconds=perf_counter() - start,
    )


def summarize(rows: list[Sample]) -> Median:
    memory = [item.peak_memory_bytes for item in rows if item.peak_memory_bytes is not None]
    return Median(
        median(item.native_seconds for item in rows),
        median(item.startup_inclusive_seconds for item in rows),
        median(memory) if memory else None,
        "process-lifetime-self" if memory else "unsupported",
    )


def comparison(
    samples: dict[str, list[Sample]], corpus: Path, before: BaselineIdentity, candidate: ImplementationIdentity
) -> Comparison:
    if fingerprint(corpus) != before.source_digest:
        msg = "corpus changed during measurement"
        raise RuntimeError(msg)
    if len({item.diagnostic_digest for rows in samples.values() for item in rows}) != 1:
        msg = "diagnostics differ between checkouts or repetitions"
        raise RuntimeError(msg)
    summary = {kind: summarize(rows) for kind, rows in samples.items()}
    speedup = summary["baseline"].native_seconds / summary["candidate"].native_seconds
    paths = sorted(corpus.rglob("*.py"))
    return Comparison(
        before,
        candidate,
        "baseline:packages/python/src",
        len(paths),
        sum(path.stat().st_size for path in paths),
        before.source_digest,
        platform.platform(),
        samples,
        summary,
        speedup,
        100 * (1 - 1 / speedup),
    )


def main(
    baseline: Path,
    candidate: Path,
    output: Annotated[Path, typer.Option()],
    python_executable: Annotated[Path, typer.Option("--python")] = _DEFAULT_PYTHON,
    repeats: Annotated[int, typer.Option(min=1)] = 5,
) -> None:
    baseline = baseline.resolve()
    candidate = candidate.resolve()
    # absolute() preserves a virtualenv's interpreter symlink and therefore its dependencies.
    interpreter = python_executable.absolute()
    corpus = baseline / "packages/python/src"
    before = baseline_identity(baseline)
    candidate_before = implementation_identity(candidate)
    samples: dict[str, list[Sample]] = {"baseline": [], "candidate": []}
    for round_number in range(repeats):
        order = ("baseline", "candidate") if round_number % 2 == 0 else ("candidate", "baseline")
        for kind in order:
            checkout = baseline if kind == "baseline" else candidate
            result = sample(checkout, interpreter, corpus, round_number)
            samples[kind].append(result)
            typer.echo(json.dumps({"kind": kind, **asdict(result)}))
    if baseline_identity(baseline) != before or implementation_identity(candidate) != candidate_before:
        msg = "baseline or implementation changed during measurement"
        raise RuntimeError(msg)
    output.write_text(
        json.dumps(asdict(comparison(samples, corpus, before, candidate_before)), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    typer.run(main)

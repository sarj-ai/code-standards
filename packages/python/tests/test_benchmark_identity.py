from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from typing import Protocol, runtime_checkable

import pytest


class _Identity(Protocol):
    artifact_digest: str
    artifact_files: tuple[str, ...]


class _Baseline(Protocol):
    commit: str
    implementation: _Identity


class _Sample(Protocol):
    peak_memory_bytes: int | None
    memory_scope: str


@runtime_checkable
class _Harness(Protocol):
    def implementation_identity(self, checkout: Path) -> _Identity: ...

    def baseline_identity(self, checkout: Path) -> _Baseline: ...

    def fingerprint(self, root: Path) -> str: ...

    def sample(self, checkout: Path, interpreter: Path, corpus: Path, round_number: int) -> _Sample: ...


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    path = Path(__file__).parents[1] / "benchmarks/compare.py"
    spec = spec_from_file_location("_sarj_benchmark_compare_tests", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert isinstance(module, _Harness)
    return module


def _write(checkout: Path, relative: str, content: bytes = b"original\n") -> Path:
    path = checkout / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.parametrize(
    "relative",
    [
        "packages/python/src/engine/kernel.so",
        "packages/python/src/engine/kernel.pyd",
        "packages/python/src/engine/kernel.dll",
        "packages/python/src/engine/kernel.dylib",
        "packages/python/src/engine/schema.json",
        "packages/contracts/src/contracts/kernel.so",
        "packages/python/native/kernel.rs",
        "packages/python/rust/Cargo.toml",
        "packages/python/build/kernel.a",
        "packages/python/dist/engine.whl",
        "packages/contracts/native/kernel.c",
        "packages/contracts/build/kernel.wasm",
        "packages/python/pyproject.toml",
        "packages/python/uv.lock",
        "packages/contracts/pyproject.toml",
        "packages/contracts/uv.lock",
        "pyproject.toml",
        "uv.lock",
        "mise.toml",
        ".python-version",
        ".node-version",
        "Cargo.lock",
        "rust-toolchain.toml",
    ],
)
def test_identity_detects_artifact_addition_change_and_removal(
    harness: _Harness,
    tmp_path: Path,
    relative: str,
) -> None:
    _write(tmp_path, "packages/python/src/engine/app.py", b"value = 1\n")
    before = harness.implementation_identity(tmp_path)
    corpus_digest = harness.fingerprint(tmp_path / "packages/python/src")
    artifact = _write(tmp_path, relative)
    added = harness.implementation_identity(tmp_path)
    assert added.artifact_digest != before.artifact_digest
    assert relative in added.artifact_files
    artifact.write_bytes(b"changed\n")
    assert harness.implementation_identity(tmp_path).artifact_digest != added.artifact_digest
    assert harness.fingerprint(tmp_path / "packages/python/src") == corpus_digest
    artifact.unlink()
    assert harness.implementation_identity(tmp_path) == before


def test_identity_is_independent_of_checkout_location(harness: _Harness, tmp_path: Path) -> None:
    identities: list[_Identity] = []
    for name in ("first", "second"):
        checkout = tmp_path / name
        _write(checkout, "packages/python/src/engine/app.py", b"value = 1\n")
        _write(checkout, "packages/contracts/src/contracts/types.py", b"value = 2\n")
        _write(checkout, "packages/python/src/engine/kernel.so")
        _write(checkout, "packages/python/rust/Cargo.toml")
        identities.append(harness.implementation_identity(checkout))
    assert identities[0] == identities[1]


@pytest.mark.parametrize(
    "relative", ["packages/python/src/engine/tokens.py", "packages/contracts/src/contracts/types.py"]
)
def test_python_and_contracts_source_changes_remain_guarded(harness: _Harness, tmp_path: Path, relative: str) -> None:
    source = _write(tmp_path, relative, b"value = 1\n")
    before = harness.implementation_identity(tmp_path)
    source.write_bytes(b"value = 2\n")
    assert harness.implementation_identity(tmp_path).artifact_digest != before.artifact_digest


@pytest.mark.parametrize(
    "relative",
    [
        "packages/python/src/engine/__pycache__/cached.py",
        "packages/python/src/engine/cached.pyc",
        "packages/python/src/engine/.env",
        "packages/python/src/engine/credentials.json",
        "packages/python/src/engine/private.pem",
        "packages/python/rust/target/release/kernel.so",
        "packages/python/build/.cache/kernel.so",
        "packages/python/.venv/engine.so",
        "packages/typescript/dist/index.js",
    ],
)
def test_identity_does_not_read_excluded_paths(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    _write(tmp_path, "packages/python/src/engine/app.py", b"value = 1\n")
    before = harness.implementation_identity(tmp_path)
    excluded = _write(tmp_path, relative)
    read_bytes = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        assert path != excluded
        return read_bytes(path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe real reads to prove excluded payloads never reach I/O; injecting preselected artifacts would bypass filtering.
        Path, "read_bytes", guarded_read
    )
    assert harness.implementation_identity(tmp_path) == before


@pytest.mark.skipif(sys.platform == "win32", reason="Creating symlinks can require elevated Windows privileges")
@pytest.mark.parametrize(
    ("relative", "directory"),
    [
        ("packages/python/src/engine/kernel.so", False),
        ("packages/python/src/engine/linked", True),
        ("packages/python/src", True),
        ("packages/python/native", True),
        ("packages/python", True),
        ("packages", True),
        ("pyproject.toml", False),
    ],
)
def test_identity_rejects_symlinks_before_reading_targets(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str, *, directory: bool
) -> None:
    checkout = tmp_path / "checkout"
    target = tmp_path / "outside"
    if directory:
        _write(target, "secret.txt")
    else:
        target.write_bytes(b"private target\n")
    link = checkout / relative
    link.parent.mkdir(parents=True)
    link.symlink_to(target, target_is_directory=directory)
    read_bytes = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        assert path.is_relative_to(checkout)
        return read_bytes(path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the actual read boundary to prove symlink rejection precedes target reads rather than replacing artifact admission.
        Path, "read_bytes", guarded_read
    )
    with pytest.raises(ValueError, match="must not be a symlink"):
        harness.implementation_identity(checkout)


def test_artifact_read_errors_are_not_missing_artifacts(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _write(tmp_path, "packages/python/src/engine/kernel.so")
    read_bytes = Path.read_bytes

    def inaccessible(path: Path) -> bytes:
        if path == artifact:
            raise PermissionError(path)
        return read_bytes(path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- fail the actual selected payload read to prove I/O errors propagate; a precomputed identity would bypass that boundary.
        Path, "read_bytes", inaccessible
    )
    with pytest.raises(PermissionError):
        harness.implementation_identity(tmp_path)


def test_baseline_identity_guards_artifacts_even_with_clean_git_status(
    harness: _Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "packages/python/src/engine/app.py", b"value = 1\n")
    artifact = _write(tmp_path, "packages/python/src/engine/kernel.so")

    def clean_git(_checkout: Path, *arguments: str) -> str:
        return "" if arguments == ("status", "--porcelain") else "0" * 40

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- hold Git cleanliness/ref facts constant while real hashing independently detects ignored artifact changes.
        harness, "git_output", clean_git
    )
    before = harness.baseline_identity(tmp_path)
    artifact.write_bytes(b"changed ignored binary\n")
    after = harness.baseline_identity(tmp_path)
    assert before.commit == after.commit
    assert before.implementation.artifact_digest != after.implementation.artifact_digest
    assert before != after


@pytest.mark.skipif(
    sys.platform not in {"linux", "darwin"},
    reason="RUSAGE_SELF units are supported on Linux and macOS",
)
def test_worker_memory_scope_excludes_large_child(harness: _Harness, tmp_path: Path) -> None:
    child = (
        "import resource, sys\n"
        "payload = bytearray(64 * 1024 * 1024)\n"
        "for index in range(0, len(payload), 4096):\n    payload[index] = 1\n"
        "peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "print(peak if sys.platform == 'darwin' else peak * 1024)\n"
    )
    checkout = tmp_path / "checkout"
    _write(checkout, "packages/python/src/sarj_python_lint/__init__.py", b"")
    _write(checkout, "packages/python/src/sarj_python_lint/rules.py", b"REGISTRY = {'noop': object()}\n")
    analysis = (
        "from pathlib import Path\nimport subprocess, sys\n"
        "def analyze(rules, paths):\n"
        "    path = paths[0]\n"
        "    if path.with_suffix('.spawn').exists():\n"
        f"        result = subprocess.run([sys.executable, '-c', {child!r}],\n"
        "                                check=True, capture_output=True, text=True, timeout=30)\n"
        "        path.with_suffix('.child-memory').write_text(result.stdout, encoding='utf-8')\n"
        "    return []\n"
    )
    _write(checkout, "packages/python/src/sarj_python_lint/__main__.py", analysis.encode())
    corpus = tmp_path / "corpus"
    source = _write(corpus, "app.py", b"value = 1\n")
    before = harness.sample(checkout, Path(sys.executable), corpus, 0)
    source.with_suffix(".spawn").touch()
    after = harness.sample(checkout, Path(sys.executable), corpus, 1)
    child_peak = int(source.with_suffix(".child-memory").read_text(encoding="utf-8"))
    assert before.memory_scope == after.memory_scope == "process-lifetime-self"
    assert before.peak_memory_bytes is not None
    assert after.peak_memory_bytes is not None
    assert child_peak >= 64 * 1024 * 1024
    assert after.peak_memory_bytes - before.peak_memory_bytes < 16 * 1024 * 1024


def test_worker_reports_unsupported_memory(harness: _Harness, tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    _write(checkout, "packages/python/src/sarj_python_lint/__init__.py", b"")
    _write(checkout, "packages/python/src/sarj_python_lint/rules.py", b"REGISTRY = {'noop': object()}\n")
    _write(
        checkout,
        "packages/python/src/sarj_python_lint/__main__.py",
        b"import sys\ndef analyze(rules, paths):\n    sys.platform = 'unsupported'\n    return []\n",
    )
    corpus = tmp_path / "corpus"
    _write(corpus, "app.py", b"value = 1\n")
    result = harness.sample(checkout, Path(sys.executable), corpus, 0)
    assert result.peak_memory_bytes is None
    assert result.memory_scope == "unsupported"

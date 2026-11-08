from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from functools import cache
from hashlib import sha256
from importlib import metadata
import json
from operator import attrgetter
import os
from pathlib import Path
import platform
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- a timed-out tool probe leaves its analyzer uncached.
import sys
import tempfile
import threading
from typing import TYPE_CHECKING, Final, Protocol

from sarj_standards.libs.diagnostics import (
    CacheStatus,
    Completion,
    CoverageDisposition,
    CoverageNotice,
    Diagnostic,
    ExecutionIssue,
    Fix,
    FixSafety,
    Location,
    Position,
    Region,
    RelatedLocation,
    RuleExecution,
    RuleExecutionState,
    Severity,
    TextEdit,
    ToolReport,
)
from sarj_standards.libs.json_boundary import parse_unique_json


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from _typeshed import DataclassInstance
    from pydantic import JsonValue

type _Field = bool | int | str | StrEnum | tuple[_Field, ...] | DataclassInstance | None


# Reuse an analyzer's complete normalized result only when every input it can
# observe is unchanged. Any missing, unreadable or ambiguous input runs it.
_CACHE_ENV: Final = "SARJ_STANDARDS_RESULT_CACHE"
_WRITE_ENV: Final = "SARJ_STANDARDS_RESULT_CACHE_WRITE"
_SCHEMA: Final = 1
_KEEP_PER_ANALYZER: Final = 8
# Per-file and per-project analyzers keep one entry per input unit.
KEEP_PER_UNIT: Final = 4096
# These only locate executables, and every executable an analyzer runs is keyed
# by its own identity. PATH also names each run's temporary tool environment.
_LOCATION_ENVIRONMENT: Final = frozenset({"PATH"})
_ENGINE_DISTRIBUTIONS: Final = (
    "code-standards",
    "sarj-python-lint",
    "sarj-sql-lint",
    "sarj-iac-lint",
    "sarj-rule-contracts",
)
# Native Python never selects, loads or resolves modules below these names.
_PRUNED_DIRECTORIES: Final = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".next",
        ".pnpm-store",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".turbo",
        ".uv-cache",
        ".venv",
        ".yarn",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
# Content read by Python analysis, Ruff configuration and SQL extraction.
_PYTHON_SUFFIXES: Final = frozenset({".py", ".pyi", ".toml", ".cfg", ".ini"})
# Names whose presence native Python probes: codegen and repository markers.
PYTHON_MARKER_NAMES: Final = frozenset(
    {
        ".git",
        ".gitignore",
        ".openapi-generator",
        ".openapi-generator-ignore",
        ".sqlfluff",
        ".swagger-codegen-ignore",
        "buf.gen.yaml",
        "buf.gen.yml",
        "codegen.config.yaml",
        "codegen.config.yml",
        "codegen.yaml",
        "codegen.yml",
        "openapi-python-client.yaml",
        "openapi-python-client.yml",
        "py.typed",
    }
)


@dataclass(frozen=True, slots=True)
class CachedResult:
    reports: tuple[ToolReport, ...]
    coverage: tuple[CoverageNotice, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultCache:
    directory: Path
    writable: bool

    @classmethod
    def from_environment(cls) -> ResultCache | None:
        value = os.environ.get(_CACHE_ENV, "").strip()  # ruff: ignore[banned-api] -- explicit CI cache boundary.
        if not value or value.lower() in {"0", "false", "off", "none"}:
            return None
        writable = os.environ.get(_WRITE_ENV, "").strip() == "1"  # ruff: ignore[banned-api] -- only trusted pushes write.
        return cls(Path(value), writable)


# An analyzer may read inputs that cannot be enumerated, so it always runs.
class UnknownInputsError(ValueError):
    pass


def cached_python_analysis(
    analyzer: str,
    root: Path,
    *,
    selected: Sequence[str],
    parameters: Iterable[str],
    compute: Callable[[], CachedResult],
) -> CachedResult:
    return cached_analysis(analyzer, inputs=lambda: _python_inputs(root, selected, parameters), compute=compute)


def cached_analysis(
    analyzer: str,
    *,
    inputs: Callable[[], Iterable[str]],
    compute: Callable[[], CachedResult],
    keep: int = _KEEP_PER_ANALYZER,
    outcomes: list[bool] | None = None,
) -> CachedResult:
    # `inputs` must name every input the analyzer can observe; any error runs it.
    # With `outcomes`, per-unit hits are recorded instead of one notice per unit.
    cache = ResultCache.from_environment()
    if cache is None:
        return compute()
    try:
        fingerprint = _fingerprint(analyzer, inputs())
    except (OSError, ValueError, subprocess.SubprocessError, metadata.PackageNotFoundError) as error:
        _notice(analyzer, f"runs: fingerprint unavailable ({type(error).__name__})")
        return compute()
    entry = cache.directory / f"v{_SCHEMA}" / analyzer / f"{fingerprint}.json"
    loaded = _load(entry, analyzer, fingerprint)
    if outcomes is not None:
        outcomes.append(loaded is not None)
    if loaded is not None:
        if outcomes is None:
            _notice(analyzer, f"reused {fingerprint[:12]}")
        if cache.writable:
            _touch(entry)
        return loaded
    result = compute()
    if cache.writable and _storable(result):
        try:
            _store(entry, analyzer, fingerprint, result)
            _prune_once(entry.parent, keep)
        except OSError as error:
            _notice(analyzer, f"result not stored ({type(error).__name__})")
    if outcomes is None:
        _notice(analyzer, f"ran {fingerprint[:12]}")
    return result


@dataclass(frozen=True, slots=True)
class TrackedResult:
    result: CachedResult
    # Repository-relative paths the analysis read beyond its keyed inputs.
    reads: tuple[str, ...] = ()


def cached_tracked_analysis(
    analyzer: str,
    *,
    inputs: Callable[[], Iterable[str]],
    compute: Callable[[], TrackedResult],
    identity: Callable[[str], str],
    keep: int = _KEEP_PER_ANALYZER,
    outcomes: list[bool] | None = None,
) -> CachedResult:
    # The entry records every extra path the analysis read with its identity;
    # it is reused only while each of them is unchanged.
    cache = ResultCache.from_environment()
    if cache is None:
        return compute().result
    try:
        fingerprint = _fingerprint(analyzer, inputs())
    except (OSError, ValueError, subprocess.SubprocessError, metadata.PackageNotFoundError) as error:
        _notice(analyzer, f"runs: fingerprint unavailable ({type(error).__name__})")
        return compute().result
    entry = cache.directory / f"v{_SCHEMA}" / analyzer / f"{fingerprint}.json"
    loaded = _load(entry, analyzer, fingerprint, identity=identity)
    if outcomes is not None:
        outcomes.append(loaded is not None)
    if loaded is not None:
        if cache.writable:
            _touch(entry)
        return loaded
    tracked = compute()
    if cache.writable and _storable(tracked.result):
        try:
            reads = tuple((path, identity(path)) for path in dict.fromkeys(tracked.reads))
            _store(entry, analyzer, fingerprint, tracked.result, reads=reads)
            _prune_once(entry.parent, keep)
        except (OSError, ValueError) as error:
            _notice(analyzer, f"result not stored ({type(error).__name__})")
    return tracked.result


def notice_outcomes(analyzer: str, outcomes: Sequence[bool]) -> None:
    if outcomes:
        _notice(analyzer, f"reused {sum(outcomes)} of {len(outcomes)} units")


def file_identity(path: Path) -> str:
    # Missing and directory inputs are part of what an analyzer can observe.
    if not path.exists() and not path.is_symlink():
        return "missing"
    if path.is_symlink():
        return f"symlink:{path.readlink()}"
    return _file_digest(path)


def executable_identity(path: Path) -> str:
    resolved = path.resolve(strict=True)
    status = resolved.stat()
    # A replaced binary has a new stat identity, so its digest is recomputed.
    return _executable_digest(_ExecutableStat(str(resolved), status.st_size, status.st_mtime_ns, status.st_ino))


def environment_parts(environment: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        f"environment={key}={value}"
        for key, value in sorted(environment.items())
        if key not in _LOCATION_ENVIRONMENT and not key.startswith(("MISE_", "UV_"))
    )


@dataclass(frozen=True, slots=True)
class _ExecutableStat:
    path: str
    size: int
    modified: int
    inode: int


@cache
def _executable_digest(executable: _ExecutableStat) -> str:
    return f"{executable.path}:{_file_digest(Path(executable.path))}"


def python_inputs_digest(root: Path) -> str:
    # Never memoize: one process may analyze, fix and analyze the tree again.
    return _walk_digest(root.resolve())


def encode_result(result: CachedResult) -> JsonValue:
    return {
        "reports": [_encode(item) for item in result.reports],
        "coverage": [_encode(item) for item in result.coverage],
    }


def decode_result(payload: JsonValue) -> CachedResult:
    if not isinstance(payload, dict) or set(payload) != {"reports", "coverage"}:
        msg = "cached result must contain reports and coverage"
        raise TypeError(msg)
    reports = _decode_list(payload["reports"], ToolReport)
    coverage = _decode_list(payload["coverage"], CoverageNotice)
    return CachedResult(reports, coverage)


def _fingerprint(analyzer: str, inputs: Iterable[str]) -> str:
    digest = sha256()
    for part in (
        f"schema={_SCHEMA}",
        f"analyzer={analyzer}",
        f"engine={_engine_identity()}",
        f"python={sys.version}",
        f"platform={platform.platform()}",
        *inputs,
    ):
        _feed(digest, part)
    return digest.hexdigest()


def _python_inputs(root: Path, selected: Sequence[str], parameters: Iterable[str]) -> Iterable[str]:
    yield f"inputs={python_inputs_digest(root)}"
    yield from (f"parameter={item}" for item in parameters)
    resolved = root.resolve()
    for name in selected:
        # Selection order is part of native Python semantics.
        path = (resolved / name).resolve()
        if resolved not in path.parents and path != resolved:
            msg = f"selected input escapes the repository: {name}"
            raise ValueError(msg)
        yield f"selected={name}"
        yield _file_digest(path)


@cache
def _engine_identity() -> str:
    # Installed distributions cannot change within one analysis process.
    digest = sha256()
    installed = sorted(
        f"{dist.metadata['Name']}=={dist.version}".lower() for dist in metadata.distributions() if dist.metadata["Name"]
    )
    for item in installed:
        _feed(digest, item)
    for name in _ENGINE_DISTRIBUTIONS:
        distribution = metadata.distribution(name)
        record = distribution.read_text("RECORD")
        if record is None or editable_distribution(distribution.read_text("direct_url.json")):
            # Editable source can change without a version or record change.
            msg = f"{name} has no immutable installed record"
            raise ValueError(msg)
        _feed(digest, f"{name}:{record}")
    ruff = shutil.which("ruff", path=str(Path(sys.executable).parent)) or shutil.which("ruff")
    _feed(digest, "ruff=missing" if ruff is None else f"ruff={_file_digest(Path(ruff).resolve())}")
    return digest.hexdigest()


def editable_distribution(direct_url: str | None) -> bool:
    if direct_url is None:
        return False
    payload = parse_unique_json(direct_url)
    directory = payload.get("dir_info") if isinstance(payload, dict) else None
    return isinstance(directory, dict) and directory.get("editable") is True


def _walk_digest(root: Path) -> str:
    digest = sha256()
    for current, directories, files in os.walk(root, followlinks=False):
        directory = Path(current)
        _feed_directory(digest, directory.relative_to(root).as_posix(), directories)
        directories[:] = sorted(set(directories) - _PRUNED_DIRECTORIES)
        for name in sorted(files):
            path = directory / name
            if name in PYTHON_MARKER_NAMES or path.suffix in _PYTHON_SUFFIXES or name == "setup.py":
                _feed(digest, f"file={directory.relative_to(root).as_posix()}/{name}:{path.is_symlink()}")
                _feed(digest, _file_digest(path))
    return digest.hexdigest()


def _feed_directory(digest: _Digest, relative: str, directories: Sequence[str]) -> None:
    # Import resolution can probe any visible directory; dot directories only carry markers.
    if not any(part.startswith(".") for part in Path(relative).parts):
        _feed(digest, f"directory={relative}")
    for name in sorted(PYTHON_MARKER_NAMES.intersection(directories)):
        _feed(digest, f"marker-directory={relative}/{name}")


def _file_digest(path: Path) -> str:
    if path.is_dir():
        return "directory"
    file_digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            file_digest.update(block)
    return file_digest.hexdigest()


class _Digest(Protocol):
    def update(self, data: bytes, /) -> None: ...


def _feed(digest: _Digest, text: str) -> None:
    # Length prefixes keep adjacent parts from colliding.
    data = text.encode("utf-8", "surrogateescape")
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


def _load(
    entry: Path, analyzer: str, fingerprint: str, *, identity: Callable[[str], str] | None = None
) -> CachedResult | None:
    try:
        payload = parse_unique_json(entry.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as error:
        _notice(analyzer, f"ignores unreadable entry ({type(error).__name__})")
        return None
    try:
        result = _entry_result(payload, analyzer, fingerprint)
        if identity is not None and not _reads_unchanged(payload, identity):
            return None
    except (TypeError, ValueError) as error:
        _notice(analyzer, f"ignores invalid entry ({error})")
        return None
    return result


def _reads_unchanged(payload: JsonValue, identity: Callable[[str], str]) -> bool:
    reads = payload.get("reads") if isinstance(payload, dict) else None
    if not isinstance(reads, list):
        msg = "tracked cache entry has no reads"
        raise TypeError(msg)
    for item in reads:
        match item:
            case [str() as path, str() as recorded]:
                pass
            case _:
                msg = "tracked cache entry read must be a path and identity"
                raise TypeError(msg)
        try:
            if identity(path) != recorded:
                return False
        except OSError, ValueError:
            return False
    return True


def _entry_result(payload: JsonValue, analyzer: str, fingerprint: str) -> CachedResult:
    if not isinstance(payload, dict):
        msg = "cache entry must be an object"
        raise TypeError(msg)
    if payload.get("schema") != _SCHEMA or payload.get("analyzer") != analyzer:
        msg = "cache entry schema or analyzer differs"
        raise ValueError(msg)
    if payload.get("fingerprint") != fingerprint:
        msg = "cache entry fingerprint differs"
        raise ValueError(msg)
    return decode_result(payload.get("result"))


def _storable(result: CachedResult) -> bool:
    # Execution failures are not findings; they must run again.
    return all(report.completion is Completion.COMPLETE and not report.issues for report in result.reports)


def _store(
    entry: Path,
    analyzer: str,
    fingerprint: str,
    result: CachedResult,
    *,
    reads: tuple[tuple[str, str], ...] | None = None,
) -> None:
    entry.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, JsonValue] = {
        "schema": _SCHEMA,
        "analyzer": analyzer,
        "fingerprint": fingerprint,
        "result": encode_result(result),
    }
    if reads is not None:
        document["reads"] = [[path, recorded] for path, recorded in reads]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=entry.parent, delete=False, suffix=".tmp") as stream:
        json.dump(document, stream, sort_keys=True, separators=(",", ":"))
        temporary = Path(stream.name)
    temporary.replace(entry)


def _touch(entry: Path) -> None:
    try:
        entry.touch()
    except OSError:
        return


_PRUNED: set[Path] = set()
_PRUNED_LOCK = threading.Lock()


def _prune_once(directory: Path, keep: int) -> None:
    # Units are stored many times per analysis; one pass per directory suffices.
    with _PRUNED_LOCK:
        if directory in _PRUNED:
            return
        _PRUNED.add(directory)
    entries = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for stale in entries[keep:]:
        stale.unlink(missing_ok=True)


def _notice(analyzer: str, message: str) -> None:
    sys.stderr.write(f"code-standards result cache: {analyzer} {message}\n")


_DATACLASSES: Final[dict[str, type[DataclassInstance]]] = {
    item.__name__: item
    for item in (
        CoverageNotice,
        Diagnostic,
        ExecutionIssue,
        Fix,
        Location,
        Position,
        Region,
        RelatedLocation,
        RuleExecution,
        TextEdit,
        ToolReport,
    )
}
_ENUMS: Final[dict[str, type[StrEnum]]] = {
    item.__name__: item
    for item in (CacheStatus, Completion, CoverageDisposition, FixSafety, RuleExecutionState, Severity)
}


def _encode(value: _Field) -> JsonValue:
    if isinstance(value, StrEnum):
        return {"enum": type(value).__name__, "value": str(value)}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, tuple):
        return {"tuple": [_encode(item) for item in value]}
    if type(value).__name__ in _DATACLASSES:
        return {
            "type": type(value).__name__,
            "fields": {field.name: _encode(_field(value, field.name)) for field in fields(value)},
        }
    msg = f"cannot cache value of type {type(value).__name__}"
    raise TypeError(msg)


def _field(value: DataclassInstance, name: str) -> _Field:
    return attrgetter(name)(value)  # pyright: ignore[reportAny] -- fields of allow-listed report dataclasses.


def _decode_list[T](value: JsonValue, kind: type[T]) -> tuple[T, ...]:
    if not isinstance(value, list):
        msg = "cached collection must be a list"
        raise TypeError(msg)
    decoded = tuple(_decode(item) for item in value)
    if not all(isinstance(item, kind) for item in decoded):
        msg = f"cached collection must contain {kind.__name__}"
        raise TypeError(msg)
    return decoded  # pyright: ignore[reportReturnType] -- checked element by element above.


def _decode(value: JsonValue) -> _Field:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, dict):
        match sorted(value):
            case ["enum", "value"]:
                return _decode_enum(value["enum"], value["value"])
            case ["tuple"]:
                return _decode_tuple(value["tuple"])
            case ["fields", "type"]:
                return _decode_dataclass(value["type"], value["fields"])
            case _:
                pass
    msg = "unsupported cached value"
    raise ValueError(msg)


def _decode_enum(name: JsonValue, member: JsonValue) -> StrEnum:
    enum = _ENUMS.get(str(name))
    if enum is None or not isinstance(member, str):
        msg = f"unknown cached enum {name!r}"
        raise ValueError(msg)
    return enum(member)


def _decode_tuple(items: JsonValue) -> tuple[_Field, ...]:
    if not isinstance(items, list):
        msg = "cached tuple must be a list"
        raise TypeError(msg)
    return tuple(_decode(item) for item in items)


def _decode_dataclass(name: JsonValue, values: JsonValue) -> DataclassInstance:
    kind = _DATACLASSES.get(str(name))
    if kind is None or not isinstance(values, dict):
        msg = f"unknown cached type {name!r}"
        raise ValueError(msg)
    if set(values) != {field.name for field in fields(kind)}:
        msg = f"cached {kind.__name__} fields differ"
        raise ValueError(msg)
    return kind(**{field: _decode(item) for field, item in values.items()})

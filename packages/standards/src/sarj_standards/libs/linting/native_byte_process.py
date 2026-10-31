from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- execute only validated local package entrypoints with fixed stdin-only argv.
import sys
import tempfile
from typing import TYPE_CHECKING, Final, Literal, NoReturn, TypedDict, TypeGuard, overload


if TYPE_CHECKING:
    from collections.abc import Hashable, Iterable, Mapping


type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


_PACKAGES: Final[dict[str, tuple[str, str]]] = {
    "eslint": ("eslint", "eslint"),
    "biome": ("@biomejs/biome", "biome"),
    "prettier": ("prettier", "prettier"),
}
_ESLINT_ARGUMENT_COUNT: Final = 11
_PRETTIER_ARGUMENT_COUNT: Final = 4
_BIOME_CONFIG_ARGUMENT_COUNT: Final = 5
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_PRIVATE_PAYLOAD_MODE: Final = 0o600
_MAX_SOURCE = 64 * 1024 * 1024
_MAX_PAYLOAD = 128 * 1024 * 1024
_FILE_KEYS: Final[frozenset[str]] = frozenset(
    {"path", "dev", "ino", "size", "mtime_ns", "ctime_ns", "mode", "uid", "nlink"}
)
_HASHED_FILE_KEYS: Final[frozenset[str]] = _FILE_KEYS | {"sha256"}
_SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?\Z")
REJECTED_EXIT_CODE: Final = 2
_GENERIC_FAILURE: Final = "native byte bridge rejected its payload or execution\n"
_NODE_PATH_FAILURE_PREFIX: Final = "native Node runtime path rejected: "
_NODE_PATH_FAILURE_REASONS: Final[dict[str, str]] = {
    "native Node runtime is absent from the callback environment": "Node is absent from the callback PATH",
    "native bridge runtime must be a canonical Node path": (
        "selected Node must resolve to a canonical node or node.exe file"
    ),
    "native bridge file is not regular": "selected Node is not a regular file",
    "Node runtime permissions are unsafe": "selected Node must be executable and not writable by group or others",
    "native bridge file changed while reading": "selected Node metadata changed while reading",
    "Node runtime identity changed during inspection": "selected Node identity changed during inspection",
}
_NODE_PATH_OS_FAILURE_REASONS: Final[dict[int, str]] = {
    errno.ENOENT: "selected Node filesystem entry is missing",
    errno.EACCES: "selected Node filesystem metadata is not accessible",
    errno.EPERM: "selected Node filesystem metadata access is not permitted",
    errno.ENOTDIR: "selected Node runtime path has a non-directory component",
    errno.ELOOP: "selected Node runtime path contains a symbolic-link loop",
}


class FileIdentity(TypedDict):
    dev: int
    ino: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    uid: int
    nlink: int


class FileRecord(FileIdentity):
    path: str


class HashedFileRecord(FileRecord):
    sha256: str


class InvocationWire(TypedDict):
    tool: str
    node: str
    entrypoint: str
    cwd: str
    args: list[str]


class StdinWire(TypedDict):
    base64: str
    size: int
    sha256: str


class PackageProof(TypedDict):
    name: str
    version: str
    package_root: str
    manifest: HashedFileRecord
    entrypoint: HashedFileRecord


class InputProofs(TypedDict):
    runtime: FileRecord
    package: PackageProof
    configs: dict[str, HashedFileRecord]


class NativeRequest(TypedDict):
    schema: int
    invocation: InvocationWire
    stdin: StdinWire
    proofs: InputProofs


class ResponseWire(TypedDict):
    schema: int
    returncode: int
    stdout: str
    stderr: str


class NodePathWire(TypedDict):
    schema: int
    path: str
    stat: FileRecord


@dataclass(frozen=True, slots=True)
class ValidatedRequest:
    request: NativeRequest
    source: bytes


@dataclass(frozen=True, slots=True)
class DecodedResponse:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class _RegularInput:
    path: Path
    proof: HashedFileRecord


@dataclass(frozen=True, slots=True)
class _LocalEntrypoint:
    path: Path
    proof: PackageProof


@dataclass(frozen=True, slots=True)
class _Invocation:
    tool: Literal["eslint", "biome", "prettier"]
    node: Path
    entrypoint: Path
    cwd: Path
    args: tuple[str, ...]


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _require(*, condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def load_json(data: str | bytes) -> JsonValue:
    # The configured stdlib decoder produces only JSON values before schema validation.
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)  # pyright: ignore[reportAny] -- stdlib JSON decoder boundary; every field is validated before use.
    except json.JSONDecodeError, UnicodeDecodeError:
        _fail("invalid native bridge JSON")


def _constant(_value: str) -> NoReturn:
    _fail("nonfinite native bridge JSON value")


def _pairs(items: Iterable[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in items:
        _require(condition=key not in result, message="duplicate native bridge JSON key")
        result[key] = value
    return result


def _mapping(value: JsonValue | dict[Hashable, JsonValue]) -> dict[str, JsonValue]:
    if not _is_mapping(value):
        _fail("native bridge value must be an object")
    result: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            _fail("native bridge object key must be text")
        result[key] = item
    return result


def _is_mapping(value: JsonValue | dict[Hashable, JsonValue]) -> TypeGuard[dict[Hashable, JsonValue]]:
    return isinstance(value, dict)


def _object(value: JsonValue, keys: set[str]) -> dict[str, JsonValue]:
    result = _mapping(value)
    _require(condition=set(result) == keys, message="native bridge object schema mismatch")
    return result


def _text(value: JsonValue) -> str:
    if not isinstance(value, str):
        _fail("native bridge value must be text")
    return value


def _integer(value: JsonValue) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail("native bridge value must be an integer")
    return value


def _path(value: JsonValue, *, real: bool = True) -> Path:
    rendered = _text(value)
    _require(condition=bool(rendered) and "\0" not in rendered, message="invalid native bridge path")
    path = Path(rendered)
    _require(
        condition=path.is_absolute() and str(path) == rendered and ".." not in path.parts,
        message="noncanonical native bridge path",
    )
    if real:
        _require(condition=path.resolve() == path, message="native bridge path traverses a link")
    return path


def _invocation(value: JsonValue) -> _Invocation:
    fields = _object(value, {"tool", "node", "entrypoint", "cwd", "args"})
    tool = _tool(fields["tool"])
    return _Invocation(
        tool,
        _path(fields["node"], real=False),
        _path(fields["entrypoint"], real=False),
        _path(fields["cwd"]),
        _strings(fields["args"]),
    )


def _strings(value: JsonValue) -> tuple[str, ...]:
    if not _is_list(value):
        _fail("native bridge argv must be an array")
    result: list[str] = []
    for item in value:
        rendered = _text(item)
        _require(condition="\0" not in rendered, message="native bridge argv contains NUL")
        result.append(rendered)
    return tuple(result)


def _is_list(value: JsonValue) -> TypeGuard[list[JsonValue]]:
    return isinstance(value, list)


def _tool(value: JsonValue) -> Literal["eslint", "biome", "prettier"]:
    rendered = _text(value)
    match rendered:
        case "eslint" | "biome" | "prettier":
            return rendered
        case _:
            _fail("native bridge tool is not approved")


def _identity(metadata: os.stat_result) -> FileIdentity:
    return {
        "dev": metadata.st_dev,
        "ino": metadata.st_ino,
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "ctime_ns": metadata.st_ctime_ns,
        "mode": stat.S_IMODE(metadata.st_mode),
        "uid": metadata.st_uid,
        "nlink": metadata.st_nlink,
    }


@overload
def file_record(path: Path, *, contents: Literal[True]) -> HashedFileRecord: ...


@overload
def file_record(path: Path, *, contents: Literal[False]) -> FileRecord: ...


@overload
def file_record(path: Path, *, contents: bool) -> FileRecord: ...


def file_record(path: Path, *, contents: bool) -> FileRecord:
    before = path.lstat()
    _require(
        condition=stat.S_ISREG(before.st_mode) and not path.is_symlink(), message="native bridge file is not regular"
    )
    record: FileRecord = {"path": str(path), **_identity(before)}
    if contents:
        _require(condition=before.st_size <= _MAX_PAYLOAD, message="native bridge input is too large")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(  # sarj-noqa: SARJ557 -- Probe optional OS capabilities while preserving checked safe-open identity and permission guards.
                os, "O_NOFOLLOW", 0
            ),
        )
        with os.fdopen(descriptor, "rb") as stream:
            _require(
                condition=_identity(os.fstat(stream.fileno())) == _identity(before),
                message="native bridge file identity changed",
            )
            data = stream.read(_MAX_PAYLOAD + 1)
            _require(
                condition=len(data) <= _MAX_PAYLOAD and _identity(os.fstat(stream.fileno())) == _identity(before),
                message="native bridge file changed during read",
            )
        _require(
            condition=_identity(path.lstat()) == _identity(before), message="native bridge file changed while reading"
        )
        hashed: HashedFileRecord = {**record, "sha256": hashlib.sha256(data).hexdigest()}
        return hashed
    _require(condition=_identity(path.lstat()) == _identity(before), message="native bridge file changed while reading")
    return record


def runtime_record(path: Path) -> FileRecord:
    _require(
        condition=path.is_absolute() and path.resolve() == path and path.name in {"node", "node.exe"},
        message="native bridge runtime must be a canonical Node path",
    )
    runtime = file_record(path, contents=False)
    mode = stat.S_IMODE(path.stat().st_mode)
    _require(condition=bool(mode & 0o111) and not mode & 0o022, message="Node runtime permissions are unsafe")
    _require(
        condition=file_record(path, contents=False) == runtime,
        message="Node runtime identity changed during inspection",
    )
    return runtime


def make_request(value: JsonValue, source: bytes) -> NativeRequest:
    invocation = _invocation(value)
    _require(condition=len(source) <= _MAX_SOURCE, message="native stdin bytes exceed the payload limit")
    _require(condition=invocation.cwd.is_dir(), message="native project directory is missing")
    node = invocation.node.resolve()
    runtime = runtime_record(node)
    entrypoint = _local_entrypoint(invocation)
    configs = _arguments(invocation)
    normalized: InvocationWire = {
        "tool": invocation.tool,
        "node": str(node),
        "entrypoint": str(entrypoint.path),
        "cwd": str(invocation.cwd),
        "args": list(invocation.args),
    }
    return {
        "schema": 1,
        "invocation": normalized,
        "stdin": {
            "base64": base64.b64encode(source).decode("ascii"),
            "size": len(source),
            "sha256": hashlib.sha256(source).hexdigest(),
        },
        "proofs": {"runtime": runtime, "package": entrypoint.proof, "configs": configs},
    }


def _file_json(record: FileRecord, *, keys: frozenset[str] = _FILE_KEYS) -> dict[str, JsonValue]:
    _require(condition=set(record) == keys, message="native invocation or input proofs changed")
    return {
        "path": record["path"],
        "dev": record["dev"],
        "ino": record["ino"],
        "size": record["size"],
        "mtime_ns": record["mtime_ns"],
        "ctime_ns": record["ctime_ns"],
        "mode": record["mode"],
        "uid": record["uid"],
        "nlink": record["nlink"],
    }


def _invocation_json(invocation: InvocationWire) -> dict[str, JsonValue]:
    _require(
        condition=set(invocation) == {"tool", "node", "entrypoint", "cwd", "args"},
        message="native bridge object schema mismatch",
    )
    return {
        "tool": invocation["tool"],
        "node": invocation["node"],
        "entrypoint": invocation["entrypoint"],
        "cwd": invocation["cwd"],
        "args": list(invocation["args"]),
    }


def request_json(request: NativeRequest) -> JsonObject:
    _require(
        condition=set(request) == {"schema", "invocation", "stdin", "proofs"},
        message="native bridge object schema mismatch",
    )
    _require(
        condition=set(request["proofs"]) == {"runtime", "package", "configs"},
        message="native invocation or input proofs changed",
    )
    _require(
        condition=set(request["stdin"]) == {"base64", "size", "sha256"},
        message="native bridge object schema mismatch",
    )
    package = request["proofs"]["package"]
    _require(
        condition=set(package) == {"name", "version", "package_root", "manifest", "entrypoint"},
        message="native invocation or input proofs changed",
    )
    package_json: dict[str, JsonValue] = {
        "name": package["name"],
        "version": package["version"],
        "package_root": package["package_root"],
        "manifest": _hashed_file_json(package["manifest"]),
        "entrypoint": _hashed_file_json(package["entrypoint"]),
    }
    configs: dict[str, JsonValue] = {
        path: _hashed_file_json(record) for path, record in request["proofs"]["configs"].items()
    }
    stdin: dict[str, JsonValue] = {
        "base64": request["stdin"]["base64"],
        "size": request["stdin"]["size"],
        "sha256": request["stdin"]["sha256"],
    }
    proofs: dict[str, JsonValue] = {
        "runtime": _file_json(request["proofs"]["runtime"]),
        "package": package_json,
        "configs": configs,
    }
    return {
        "schema": request["schema"],
        "invocation": _invocation_json(request["invocation"]),
        "stdin": stdin,
        "proofs": proofs,
    }


def _hashed_file_json(record: HashedFileRecord) -> dict[str, JsonValue]:
    return {**_file_json(record, keys=_HASHED_FILE_KEYS), "sha256": record["sha256"]}


def _local_entrypoint(invocation: _Invocation) -> _LocalEntrypoint:
    package_name, bin_name = _PACKAGES[invocation.tool]
    selected: Path | None = None
    for ancestor in (invocation.cwd, *invocation.cwd.parents):
        modules = ancestor / "node_modules"
        package = modules.joinpath(*package_name.split("/"))
        if not (package / "package.json").is_file():
            continue
        _require(
            condition=modules.is_dir() and not modules.is_symlink() and modules.resolve() == modules,
            message="local node_modules must not resolve outside its project",
        )
        actual = package.resolve()
        _require(
            condition=actual.is_relative_to(modules), message="installed package resolves outside local node_modules"
        )
        selected = actual
        break
    if selected is None:
        _fail("native bridge has no repository-local installed package")
    manifest = selected / "package.json"
    manifest_proof = file_record(manifest, contents=True)
    metadata = _mapping(load_json(manifest.read_bytes()))
    _require(condition=metadata.get("name") == package_name, message="installed package name differs")
    version = _text(metadata.get("version"))
    _require(condition=_SEMVER.fullmatch(version) is not None, message="invalid installed package version")
    bins = metadata.get("bin")
    relative = _text(_mapping(bins).get(bin_name) if _is_mapping(bins) else bins)
    _require(condition="\0" not in relative, message="installed package has no declared tool bin")
    value = relative.removeprefix("./")
    canonical = PurePosixPath(value)
    _require(
        condition=bool(value)
        and not canonical.is_absolute()
        and canonical.as_posix() == value
        and all(part not in {".", ".."} for part in canonical.parts),
        message="unsafe installed package bin",
    )
    expected = (selected / value).resolve()
    _require(
        condition=expected.is_relative_to(selected) and invocation.entrypoint.resolve() == expected,
        message="native entrypoint differs from installed package bin",
    )
    return _LocalEntrypoint(
        expected,
        {
            "name": package_name,
            "version": version,
            "package_root": str(selected),
            "manifest": manifest_proof,
            "entrypoint": file_record(expected, contents=True),
        },
    )


def _arguments(invocation: _Invocation) -> dict[str, HashedFileRecord]:
    tool, args, cwd = invocation.tool, invocation.args, invocation.cwd
    configs: dict[str, HashedFileRecord] = {}
    match tool:
        case "eslint":
            _require(
                condition=len(args) == _ESLINT_ARGUMENT_COUNT
                and args[0] == "--config"
                and args[2:9]
                == ("--fix-dry-run", "--fix-type", "directive", "--format", "json", "--no-cache", "--stdin")
                and args[9] == "--stdin-filename",
                message="ESLint argv must be exact directive-only stdin mode",
            )
            config = _regular_input(args[1])
            configs[str(config.path)] = config.proof
            _stdin_path(args[10], cwd)
        case "prettier":
            _require(
                condition=len(args) == _PRETTIER_ARGUMENT_COUNT
                and args[0] == "--config"
                and args[2] == "--stdin-filepath",
                message="Prettier argv must be exact stdin-to-stdout mode",
            )
            config = _regular_input(args[1])
            configs[str(config.path)] = config.proof
            _stdin_path(args[3], cwd)
        case "biome":
            _require(
                condition=len(args) in {3, _BIOME_CONFIG_ARGUMENT_COUNT}
                and args[:2] == ("format", "--stdin-file-path"),
                message="Biome argv must be exact stdin-to-stdout mode",
            )
            _stdin_path(args[2], cwd)
            if len(args) == _BIOME_CONFIG_ARGUMENT_COUNT:
                _require(condition=args[3] == "--config-path", message="unknown Biome formatter option")
                config = _regular_input(args[4])
                configs[str(config.path)] = config.proof
    return configs


def _stdin_path(value: str, cwd: Path) -> None:
    path = _path(value, real=False)
    _require(
        condition=path.is_relative_to(cwd) and path != cwd and ".git" not in path.relative_to(cwd).parts,
        message="stdin filename is outside its canonical project",
    )
    # A virtual filename is valid. No source path is ever opened for writing.
    _require(condition=path.resolve() == path, message="stdin filename traverses a link")


def _regular_input(value: JsonValue) -> _RegularInput:
    path = _path(value)
    return _RegularInput(path, file_record(path, contents=True))


def _decode(value: JsonValue) -> bytes:
    rendered = _text(value)
    try:
        decoded = base64.b64decode(rendered, validate=True)
    except binascii.Error, ValueError:
        _fail("invalid native bridge base64")
    _require(
        condition=base64.b64encode(decoded).decode("ascii") == rendered, message="noncanonical native bridge base64"
    )
    return decoded


def _encoded(value: JsonValue | NativeRequest | FileRecord | ResponseWire | NodePathWire) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def validate_request(value: JsonValue) -> ValidatedRequest:
    request = _object(value, {"schema", "invocation", "stdin", "proofs"})
    _require(condition=_integer(request["schema"]) == 1, message="unsupported native bridge schema")
    data = _object(request["stdin"], {"base64", "size", "sha256"})
    source = _decode(data["base64"])
    _require(
        condition=_integer(data["size"]) == len(source) and data["sha256"] == hashlib.sha256(source).hexdigest(),
        message="native stdin payload differs",
    )
    rebuilt = make_request(request["invocation"], source)
    _require(condition=_encoded(rebuilt) == _encoded(request), message="native invocation or input proofs changed")
    return ValidatedRequest(rebuilt, source)


def temp_base() -> Path:
    actual = Path(tempfile.gettempdir()).resolve()
    requested = os.environ.get("TMPDIR")  # ruff: ignore[banned-api] -- reject Python temporary-directory fallback before writing an owned payload.
    if requested is not None:
        _require(
            condition=Path(requested).is_absolute() and Path(requested).resolve() == actual,
            message="Python fell back from the requested temporary directory",
        )
    return actual


def private_directory(path: Path) -> FileIdentity:
    metadata = path.lstat()
    _require(
        condition=path.resolve() == path
        and stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and stat.S_IMODE(metadata.st_mode) == _PRIVATE_DIRECTORY_MODE,
        message="native bridge payload directory is not private",
    )
    return _identity(metadata)


def payload_record(path: Path) -> HashedFileRecord:
    _require(
        condition=path.is_absolute() and path.resolve() == path and path.parent.parent == temp_base(),
        message="native bridge payload is outside verified temporary storage",
    )
    private_directory(path.parent)
    match = re.fullmatch(r"payload\.([0-9a-f]{64})\.json", path.name)
    if match is None:
        _fail("native bridge payload filename has no digest")
    record = file_record(path, contents=True)
    _require(
        condition=record["uid"] == os.geteuid() and record["nlink"] == 1 and record["mode"] == _PRIVATE_PAYLOAD_MODE,
        message="native bridge payload ownership or permissions changed",
    )
    _require(condition=record["sha256"] == match[1], message="native bridge payload digest changed")
    _require(
        condition={item.name for item in path.parent.iterdir()} == {path.name},
        message="native bridge payload directory changed",
    )
    return record


def response(returncode: int, stdout: bytes, stderr: bytes) -> bytes:
    return _encoded(
        {
            "schema": 1,
            "returncode": returncode,
            "stdout": base64.b64encode(stdout).decode("ascii"),
            "stderr": base64.b64encode(stderr).decode("ascii"),
        }
    )


def decode_response(value: JsonValue) -> DecodedResponse:
    data = _object(value, {"schema", "returncode", "stdout", "stderr"})
    _require(condition=_integer(data["schema"]) == 1, message="invalid native bridge response schema")
    return DecodedResponse(_integer(data["returncode"]), _decode(data["stdout"]), _decode(data["stderr"]))


def node_path_response() -> bytes:
    executable = shutil.which("node")
    if executable is None:
        _fail("native Node runtime is absent from the callback environment")
    node = Path(executable).resolve()
    return _encoded({"schema": 1, "path": str(node), "stat": runtime_record(node)})


def node_path_failure_reason(stderr: str) -> str | None:
    for reason in (*_NODE_PATH_FAILURE_REASONS.values(), *_NODE_PATH_OS_FAILURE_REASONS.values()):
        if stderr == f"{_NODE_PATH_FAILURE_PREFIX}{reason}\n":
            return reason
    return None


def decode_node_path(value: JsonValue) -> Path:
    data = _object(value, {"schema", "path", "stat"})
    _require(condition=_integer(data["schema"]) == 1, message="invalid native Node path response schema")
    node = _path(data["path"])
    _require(
        condition=_encoded(data["stat"]) == _encoded(runtime_record(node)),
        message="resolved Node runtime stat proof changed",
    )
    return node


def decode_node_path_text(value: JsonValue) -> Path:
    rendered = _text(value)
    _require(condition=rendered.isascii(), message="native Node runtime response must be ASCII JSON")
    return decode_node_path(load_json(rendered))


def child_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    source = (
        os.environ  # ruff: ignore[banned-api] -- read ambient defaults only at this child boundary.
        if environment is None
        else environment
    )
    selected = {
        key: value
        for key, value in source.items()
        if not key.startswith(("GIT_", "BIOME_"))
        and key
        not in {
            "NODE_OPTIONS",
            "NODE_PATH",
            "NODE_V8_COVERAGE",
            "NODE_REDIRECT_WARNINGS",
            "NODE_COMPILE_CACHE",
        }
    }
    selected.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
    return selected


def main(arguments: list[str] | None = None) -> int:
    supplied = sys.argv[1:] if arguments is None else arguments
    _require(
        condition=sys.flags.isolated == 1 and len(supplied) == 1,
        message="native byte bridge requires isolated fixed invocation",
    )
    if supplied[0] == "--node-path":
        try:
            node_response = node_path_response()
        except (OSError, TypeError, ValueError, KeyError) as error:
            sys.stderr.write(_failure_diagnostic(error))
            return REJECTED_EXIT_CODE
        sys.stdout.buffer.write(node_response)
        return 0
    path = _path(supplied[0])
    before = payload_record(path)
    raw = path.read_bytes()
    _require(
        condition=len(raw) <= _MAX_PAYLOAD
        and hashlib.sha256(raw).hexdigest() == before["sha256"]
        and payload_record(path) == before,
        message="native payload changed while reading",
    )
    validated = validate_request(load_json(raw))
    invocation = _invocation(_invocation_json(validated.request["invocation"]))
    # BaseWatch owns the enclosing budget/process group; no detached timeout.
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- validated local package bin, fixed stdin-only argv and a filtered child environment; shell execution is disabled.
        (str(invocation.node), str(invocation.entrypoint), *invocation.args),
        cwd=invocation.cwd,
        input=validated.source,
        capture_output=True,
        env=child_environment(),
        shell=False,
        check=False,
    )
    _require(condition=payload_record(path) == before, message="native payload changed during execution")
    validate_request(request_json(validated.request))
    sys.stdout.buffer.write(response(completed.returncode, completed.stdout, completed.stderr))
    return 0


def _failure_diagnostic(error: OSError | TypeError | ValueError | KeyError) -> str:
    reason: str | None = None
    if isinstance(error, OSError):
        number = error.errno
        if type(number) is int:
            reason = _NODE_PATH_OS_FAILURE_REASONS.get(number)
    elif isinstance(error, ValueError):
        match error.args:
            case (str() as message,) if type(message) is str:
                reason = _NODE_PATH_FAILURE_REASONS.get(message)
            case _:
                return _GENERIC_FAILURE
    if reason is not None:
        return f"{_NODE_PATH_FAILURE_PREFIX}{reason}\n"
    return _GENERIC_FAILURE


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError, TypeError, ValueError, KeyError:
        sys.stderr.write(_GENERIC_FAILURE)
        raise SystemExit(REJECTED_EXIT_CODE) from None

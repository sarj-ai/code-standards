from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import PurePosixPath
import tokenize
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.release.process import ProcessFailureError


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.release.process import ProcessBinaryRunner

MAX_MODULES: Final = 4096
MAX_OBJECT_BYTES: Final = 64 * 1024 * 1024
MAX_BLOB_BYTES: Final = 8 * 1024 * 1024
_OID_LENGTH: Final = 40
_BATCH_HEADER_FIELDS: Final = 3
_JS_SUFFIXES: Final = frozenset({".js", ".mjs", ".cjs"})
_CODE_SUFFIXES: Final = frozenset({".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"})
_INVENTORY: Final = "packages/standards/src/sarj_standards/configs/rule-inventory.v1.json"
_CATALOG: Final = "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json"


@dataclass(frozen=True, slots=True)
class GitBlob:
    mode: str
    oid: str
    size: int


def git_argv(*arguments: str) -> tuple[str, ...]:
    return ("git", "--no-replace-objects", "--no-lazy-fetch", *arguments)


def valid_oid(value: str) -> bool:
    return len(value) == _OID_LENGTH and all(character in "0123456789abcdef" for character in value)


class _PythonSourceEncodingError(ValueError):
    pass


class ImmutableGit:
    def __init__(self, root: Path, sha: str, *, runner: ProcessBinaryRunner, objects: dict[str, bytes]) -> None:
        self.root = root
        self.sha = sha
        self.runner = runner
        self.objects = objects
        tree_argv = git_argv("ls-tree", "-r", "-z", "--long", sha)
        result = runner(tree_argv, cwd=root)
        if result.returncode != 0:
            raise ProcessFailureError(tree_argv, result.returncode)
        self.entries = _tree_entries(result.stdout)
        modules = [
            path
            for path in self.entries
            if ("/src/" in path or "/tests/" in path) and PurePosixPath(path).suffix in _CODE_SUFFIXES
        ]
        if len(modules) > MAX_MODULES or sum(self.entries[path].size for path in modules) > MAX_OBJECT_BYTES:
            msg = "immutable module snapshot exceeds file/byte limits"
            raise ValueError(msg)
        self._read_objects([*modules, _INVENTORY, _CATALOG])
        self.modules: dict[str, str] = {}
        self.encoding_errors: dict[str, str] = {}
        for path in modules:
            try:
                self.modules[path] = self.text(path)
            except _PythonSourceEncodingError as error:
                # Keep import identity; the existing closure check rejects this recorded error.
                self.modules[path] = ""
                self.encoding_errors[path] = str(error)

    def _read_objects(self, paths: list[str]) -> None:
        new_sizes: dict[str, int] = {}
        for path in paths:
            oid = self.oid(path)
            size = self.entries[path].size
            if size > MAX_BLOB_BYTES:
                msg = "immutable Git blob exceeds byte limit"
                raise ValueError(msg)
            if oid not in self.objects:
                new_sizes[oid] = size
        if sum(map(len, self.objects.values())) + sum(new_sizes.values()) > MAX_OBJECT_BYTES:
            msg = "combined immutable object cache exceeds byte limit"
            raise ValueError(msg)
        oids = tuple(new_sizes)
        if not oids:
            return
        argv = git_argv("cat-file", "--batch")
        result = self.runner(argv, cwd=self.root, input_bytes=("\n".join(oids) + "\n").encode())
        if result.returncode != 0:
            raise ProcessFailureError(argv, result.returncode)
        self.objects.update(_batch_blobs(result.stdout, oids))
        if sum(map(len, self.objects.values())) > MAX_OBJECT_BYTES:
            msg = "combined immutable object cache exceeds byte limit"
            raise ValueError(msg)

    def read_blobs(self, paths: list[str]) -> None:
        self._read_objects(paths)

    def oid(self, path: str) -> str:
        if path.startswith("/") or ".." in path.split("/"):
            msg = f"implementation path must be repository-relative: {path!r}"
            raise ValueError(msg)
        blob = self.entries.get(path)
        if blob is None or blob.mode not in {"100644", "100755"}:
            msg = f"missing/nonregular immutable implementation blob: {path}"
            raise ValueError(msg)
        return blob.oid

    def text(self, path: str) -> str:
        payload = self.objects[self.oid(path)]
        if path.endswith(".py"):
            try:
                encoding = tokenize.detect_encoding(BytesIO(payload).readline)[0]
                return payload.decode(encoding)
            except (SyntaxError, UnicodeError) as error:
                msg = f"invalid immutable Python source encoding: {path}"
                raise _PythonSourceEncodingError(msg) from error
        return payload.decode("utf-8", errors="replace" if PurePosixPath(path).suffix in _JS_SUFFIXES else "strict")


def _tree_entries(payload: bytes) -> dict[str, GitBlob]:
    if payload and not payload.endswith(b"\0"):
        msg = "truncated immutable Git tree"
        raise ValueError(msg)
    entries: dict[str, GitBlob] = {}
    for record in payload.split(b"\0"):
        if not record:
            continue
        header, path_bytes = record.split(b"\t", 1)
        mode, kind, oid_bytes, size_bytes = header.split()
        path = path_bytes.decode("utf-8")
        if path.startswith("/") or ".." in path.split("/") or path in entries:
            msg = "invalid immutable Git tree path"
            raise ValueError(msg)
        if kind != b"blob":
            continue
        oid = oid_bytes.decode("ascii")
        size = int(size_bytes)
        if not valid_oid(oid) or size < 0:
            msg = "invalid immutable Git blob metadata"
            raise ValueError(msg)
        entries[path] = GitBlob(mode.decode("ascii"), oid, size)
    return entries


def _batch_blobs(payload: bytes, oids: tuple[str, ...]) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}
    cursor = 0
    for wanted in oids:
        end = payload.find(b"\n", cursor)
        if end < 0:
            msg = "truncated immutable Git batch header"
            raise ValueError(msg)
        fields = payload[cursor:end].split()
        if len(fields) != _BATCH_HEADER_FIELDS or fields[0] != wanted.encode("ascii") or fields[1] != b"blob":
            msg = "invalid or missing immutable Git batch blob"
            raise ValueError(msg)
        size = int(fields[2])
        if not 0 <= size <= MAX_BLOB_BYTES:
            msg = "immutable Git blob exceeds byte limit"
            raise ValueError(msg)
        cursor = end + 1
        body = payload[cursor : cursor + size]
        cursor += size
        if len(body) != size or payload[cursor : cursor + 1] != b"\n":
            msg = "truncated immutable Git batch blob"
            raise ValueError(msg)
        cursor += 1
        digest = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0" + body, usedforsecurity=False).hexdigest()
        if digest != wanted:
            msg = "immutable Git batch blob identity mismatch"
            raise ValueError(msg)
        blobs[wanted] = body
    if cursor != len(payload):
        msg = "unexpected immutable Git batch trailer"
        raise ValueError(msg)
    return blobs

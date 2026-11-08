from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed, bounded Git reads and the bundled formatter adapter.
from typing import TYPE_CHECKING

from sarj_standards.libs.diagnostics import initial_import
from sarj_standards.libs.filesystem import is_link_like
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.staged_git import isolated_environment, staged_environment

from . import directive_formatter, suppression_descriptions


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_INPUT_BYTES = 32 * 1024 * 1024
_MAX_FILES = 512
_GIT_OID_LENGTHS = frozenset({40, 64})


@dataclass(frozen=True, slots=True)
class _Revisions:
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class _Request:
    path: str
    before: str
    after: str
    entrypoint: str


@dataclass(frozen=True, slots=True)
class _FormatterInputs:
    owners: list[directive_formatter.FormatterOwner]
    requests: list[_Request]


def equivalent_paths(root: Path, paths: Iterable[str], *, staged: bool) -> frozenset[str]:
    try:
        selected = sorted(
            {_relative_path(root, Path(path)) for path in paths if Path(path).suffix in _SUFFIXES | {".py", ".pyi"}}
        )
        if not selected:
            return frozenset()
        return _equivalent_paths(root, selected, staged=staged)
    except OSError, TypeError, ValueError, UnicodeError, RecursionError, subprocess.SubprocessError:
        return frozenset()


def _relative_path(root: Path, path: Path) -> str:
    relative = (root / path).relative_to(root)
    if ".." in relative.parts:
        msg = "format-only source must stay inside the repository"
        raise ValueError(msg)
    return relative.as_posix()


def _equivalent_paths(root: Path, selected: list[str], *, staged: bool) -> frozenset[str]:
    environment = staged_environment(root) if staged else isolated_environment()
    context = initial_import.load(root, staged=staged)
    revisions = _revisions(root, staged=staged, environment=environment)
    tracked = frozenset(_git(root, environment, "ls-files", "-z").decode().split("\0"))
    owners: dict[Path, directive_formatter.FormatterOwner] = {}
    postimages: dict[str, str] = {}
    equivalent: set[str] = set()
    python = [path for path in selected if Path(path).suffix in {".py", ".pyi"}]
    equivalent.update(_python_descriptions(root, python, revisions, environment, postimages))
    selected = [path for path in selected if path not in python]
    requests = _formatter_requests(root, selected, tracked, environment, revisions, owners=owners)
    for inputs, raw in _batches(requests, postimages):
        equivalent.update(_compare(root, inputs, raw))
    directive_formatter.validate_all(owners.values())
    initial_import.validate(root, context, staged=staged)
    if _revisions(root, staged=staged, environment=environment) != revisions:
        return frozenset()
    for path, digest in postimages.items():
        if is_link_like(root / path):
            return frozenset()
        with (root / path).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                return frozenset()
    return frozenset(equivalent)


def _python_descriptions(
    root: Path,
    selected: list[str],
    revisions: _Revisions,
    environment: dict[str, str],
    postimages: dict[str, str],
) -> frozenset[str]:
    equivalent: set[str] = set()
    size = 0
    for relative in selected:
        if is_link_like(root / relative):
            continue
        request = _request(root, relative, revisions, environment, Path())
        if request is None:
            continue
        size += len(request.before.encode("utf-8")) + len(request.after.encode("utf-8"))
        if size > _MAX_INPUT_BYTES:
            return frozenset()
        postimages[relative] = hashlib.sha256(request.after.encode("utf-8")).hexdigest()
        if suppression_descriptions.equivalent(request.before, request.after):
            equivalent.add(relative)
    return frozenset(equivalent)


def _formatter_requests(
    root: Path,
    selected: list[str],
    tracked: frozenset[str],
    environment: dict[str, str],
    revisions: _Revisions,
    *,
    owners: dict[Path, directive_formatter.FormatterOwner],
) -> Iterator[tuple[directive_formatter.FormatterOwner, _Request]]:
    runtimes: dict[Path, directive_formatter.RuntimeProof] = {}
    proofs: dict[Path, directive_formatter.InputProof] = {}
    for relative in selected:
        path = root / relative
        if not path.is_absolute() or not path.is_relative_to(root) or is_link_like(path):
            continue
        owner = owners.get(path.parent)
        if owner is None:
            owner = directive_formatter.select(root, relative, tracked, runtimes=runtimes)
            owner = _shared_owner(owner, proofs)
            owners[path.parent] = owner
        request = _request(root, relative, revisions, environment, owner.invocation.entrypoint)
        if request is None:
            continue
        yield owner, request


def _batches(
    requests: Iterable[tuple[directive_formatter.FormatterOwner, _Request]], postimages: dict[str, str]
) -> Iterator[tuple[_FormatterInputs, bytes]]:
    batch = _FormatterInputs([], [])
    encoded: list[bytes] = []
    size = 2  # JSON array brackets; each subsequent item also needs a comma.
    for owner, request in requests:
        item = json.dumps(asdict(request), ensure_ascii=True, separators=(",", ":")).encode("ascii")
        if len(item) + 2 >= _MAX_INPUT_BYTES:
            continue
        if encoded and (len(encoded) == _MAX_FILES or size + 1 + len(item) >= _MAX_INPUT_BYTES):
            yield batch, b"[" + b",".join(encoded) + b"]"
            batch = _FormatterInputs([], [])
            encoded = []
            size = 2
        size += len(item) + bool(encoded)
        encoded.append(item)
        batch.owners.append(owner)
        batch.requests.append(request)
        postimages[request.path] = hashlib.sha256(request.after.encode("utf-8")).hexdigest()
    if encoded:
        yield batch, b"[" + b",".join(encoded) + b"]"


def _shared_owner(
    owner: directive_formatter.FormatterOwner, proofs: dict[Path, directive_formatter.InputProof]
) -> directive_formatter.FormatterOwner:
    # Many directories share a large lockfile. Retain its bytes only once, while
    # rejecting ownership drift between directory selections.
    shared: list[directive_formatter.InputProof] = []
    for proof in owner.inputs:
        previous = proofs.setdefault(proof.path, proof)
        if previous != proof:
            msg = "formatter ownership changed between batches"
            raise ValueError(msg)
        shared.append(previous)
    return replace(owner, inputs=tuple(shared))


def _compare(root: Path, inputs: _FormatterInputs, raw: bytes) -> frozenset[str]:
    directive_formatter.validate_all(inputs.owners)
    if len({owner.invocation.node for owner in inputs.owners}) != 1:
        return frozenset()
    helper = Path(__file__).parents[2] / "configs" / "format-only.mjs"
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed owned adapter, verified local runtime and formatter; source travels as inert stdin JSON.
        (str(inputs.owners[0].invocation.node), str(helper)),
        input=raw,
        cwd=root,
        env=isolated_environment(),
        capture_output=True,
        check=True,
        timeout=120,
    )
    return _equivalent_response(result.stdout, inputs.requests)


def _equivalent_response(payload: bytes, requests: list[_Request]) -> frozenset[str]:
    values = parse_unique_json(payload.decode("utf-8"))
    allowed = {request.path for request in requests}
    if not isinstance(values, list) or any(not isinstance(value, str) or value not in allowed for value in values):
        return frozenset()
    return frozenset(value for value in values if isinstance(value, str))


def _revisions(root: Path, *, staged: bool, environment: dict[str, str]) -> _Revisions:
    context = initial_import.load(root, staged=staged)
    if context is not None:
        return _Revisions(context.parent, context.source)
    if staged:
        return _Revisions(
            _git(root, environment, "rev-parse", "HEAD").decode().strip(),
            _git(root, environment, "write-tree").decode().strip(),
        )
    base = os.environ.get("SARJ_STANDARDS_BASE", "")  # ruff: ignore[banned-api] -- use the same explicit PR comparison selected by the baseline guard.
    if len(base) not in _GIT_OID_LENGTHS or any(character not in "0123456789abcdef" for character in base):
        msg = "format-only comparison requires an exact Git base"
        raise ValueError(msg)
    head = _git(root, environment, "rev-parse", "HEAD").decode().strip()
    return _Revisions(_git(root, environment, "merge-base", base, head).decode().strip(), head)


def _request(
    root: Path, path: str, revisions: _Revisions, environment: dict[str, str], entrypoint: Path
) -> _Request | None:
    try:
        original = _blob(root, environment, f"{revisions.before}:{path}")
        current = _blob(root, environment, f"{revisions.after}:{path}")
    except subprocess.CalledProcessError:
        return None  # Added and renamed files do not have the same immutable source identity.
    if original is None or current is None:
        return None
    with (root / path).open("rb") as stream:
        postimage = stream.read(_MAX_FILE_BYTES + 1)
    if postimage != current:
        return None
    return _Request(path, original.decode("utf-8"), current.decode("utf-8"), str(entrypoint))


def _blob(root: Path, environment: dict[str, str], identity: str) -> bytes | None:
    if int(_git(root, environment, "cat-file", "-s", identity)) > _MAX_FILE_BYTES:
        return None
    return _git(root, environment, "show", identity)


def _git(root: Path, environment: dict[str, str], *arguments: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        msg = "Git is unavailable for immutable formatter input reads"
        raise ValueError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed read-only Git argv, except materializing the active index tree; no shell or replacement objects.
        (git, "--no-replace-objects", "--no-lazy-fetch", *arguments),
        cwd=root,
        env=environment,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout

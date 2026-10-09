from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import posixpath
import tarfile
from typing import TYPE_CHECKING

from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.schema_boundary import HELM_SCHEMA_PROFILE, schema_references


if TYPE_CHECKING:
    from pathlib import Path


_MAX_MEMBERS = 4096
_MAX_EXPANDED_BYTES = 64 * 1024 * 1024
_MAX_DEPTH = 8
_DEPENDENCY_PATH_PARTS = 2


@dataclass(slots=True)
class _Budget:
    members: int = 0
    expanded: int = 0


def validate_chart_schemas(archive: Path) -> None:
    try:
        with archive.open("rb") as stream:
            _validate_archive(stream.read(_MAX_EXPANDED_BYTES + 1), _Budget(), 0)
    except (tarfile.TarError, UnicodeError) as error:
        msg = f"chart archive cannot be validated: {error}"
        raise ValueError(msg) from error


def _validate_archive(archive: bytes, budget: _Budget, depth: int) -> None:
    if depth > _MAX_DEPTH or len(archive) > _MAX_EXPANDED_BYTES:
        msg = "chart archive exceeds the static validation bound"
        raise ValueError(msg)
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    with tarfile.open(fileobj=BytesIO(archive), mode="r|gz") as chart:
        for member in chart:
            path = _record_member(member, budget, seen)
            if not member.isfile() or path.suffix not in {".json", ".tgz"}:
                continue
            content = _read_member(chart, member)
            chart_path = _chart_path(path)
            if (
                len(chart_path) == _DEPENDENCY_PATH_PARTS
                and chart_path[0] == "charts"
                and path.suffix == ".tgz"
                and not path.name.startswith(("_", "."))
            ):
                _validate_archive(content, budget, depth + 1)
            elif path.suffix == ".json":
                files[path.as_posix()] = content
    for name in files:
        if _chart_path(PurePosixPath(name)) == ("values.schema.json",):
            _closed(name, files, set())


def _chart_path(path: PurePosixPath) -> tuple[str, ...]:
    parts = path.parts[1:]
    while len(parts) > _DEPENDENCY_PATH_PARTS and parts[0] == "charts":
        if parts[1].startswith(("_", ".")) or PurePosixPath(parts[1]).suffix == ".tgz":
            return ()
        parts = parts[2:]
    return parts


def _record_member(member: tarfile.TarInfo, budget: _Budget, seen: set[str]) -> PurePosixPath:
    budget.members += 1
    budget.expanded += member.size
    if budget.members > _MAX_MEMBERS or budget.expanded > _MAX_EXPANDED_BYTES:
        msg = "chart archive exceeds the static validation bound"
        raise ValueError(msg)
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or "\\" in member.name or member.issym() or member.islnk():
        msg = "chart archive contains an escaping or linked entry"
        raise ValueError(msg)
    if member.isfile():
        name = path.as_posix()
        if name in seen:
            msg = "chart archive contains duplicate files"
            raise ValueError(msg)
        seen.add(name)
    return path


def _read_member(chart: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = chart.extractfile(member)
    if stream is None:
        msg = "chart schema cannot be read"
        raise ValueError(msg)
    return stream.read()


def _closed(name: str, files: dict[str, bytes], seen: set[tuple[str, str]], fragment: str = "") -> None:
    key = (name, fragment)
    if key in seen:
        return
    seen.add(key)
    data = parse_unique_json(files[name].decode("utf-8"))
    for reference in schema_references(
        data,
        profile=HELM_SCHEMA_PROFILE,
        fragment=fragment,
    ):
        relative = reference.split("#", 1)[0]
        if not relative:
            continue
        if ":" in relative or "?" in relative or "%" in relative or "\\" in relative or relative.startswith("/"):
            msg = f"chart schema must not resolve network or absolute references: {reference}"
            raise ValueError(msg)
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), relative))
        if resolved not in files or resolved.split("/", 1)[0] != name.split("/", 1)[0]:
            msg = f"chart schema lacks a closed local reference: {reference}"
            raise ValueError(msg)
        _closed(resolved, files, seen, reference.partition("#")[2])

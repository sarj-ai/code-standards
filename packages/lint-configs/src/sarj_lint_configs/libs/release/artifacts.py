"""Policies for TypeScript build output and npm package archives."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import tarfile
from typing import TYPE_CHECKING

from sarj_lint_configs.libs.release._values import is_object_dict, is_object_list, string_object_dict


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if is_object_list(value):
        return [_json_value(item) for item in value]
    if is_object_dict(value):
        return {key: _json_value(item) for key, item in string_object_dict(value, label="JSON").items()}
    msg = "JSON contains an unsupported value"
    raise TypeError(msg)


def required_artifact_paths(package_json: Mapping[str, object]) -> tuple[str, ...]:
    """Return unique package entry points in declaration order."""
    candidates: list[str] = []
    for field in ("main", "module", "types"):
        candidates.extend(_exported_paths(_json_value(package_json.get(field))))
    candidates.extend(_exported_paths(_json_value(package_json.get("exports"))))
    return tuple(dict.fromkeys(_safe_artifact_path(path) for path in candidates))


def _exported_paths(value: JsonValue) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(path for item in value for path in _exported_paths(item))
    if isinstance(value, dict):
        return tuple(path for item in value.values() for path in _exported_paths(item))
    return ()


def _safe_artifact_path(value: str) -> str:
    normalized = value.removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or path.as_posix() != normalized:
        msg = f"unsafe exported entry point: {value}"
        raise ValueError(msg)
    return normalized


def load_package_json(package_root: Path) -> dict[str, JsonValue]:
    """Load a package manifest and require a JSON object."""
    manifest = package_root / "package.json"
    try:
        untyped: object = json.loads(manifest.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        value = _json_value(untyped)
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"could not read {manifest}: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(value, dict):
        msg = f"{manifest} must contain a JSON object"
        raise TypeError(msg)
    return value


def verify_built_package(package_root: Path) -> tuple[str, ...]:
    """Require every exported entry point to be a non-empty file below ``dist``."""
    required = required_artifact_paths(load_package_json(package_root))
    if not required:
        msg = "package.json declares no publishable entry points"
        raise ValueError(msg)
    resolved_root = package_root.resolve()
    for relative in required:
        if PurePosixPath(relative).parts[0] != "dist":
            msg = f"exported entry point must live under dist/: {relative}"
            raise ValueError(msg)
        artifact = package_root / relative
        try:
            artifact.resolve().relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            msg = f"exported entry point escapes the package root: {relative}"
            raise ValueError(msg) from exc
        if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size == 0:
            msg = f"exported entry point is missing or empty: {relative}"
            raise ValueError(msg)
    return required


def verify_package_tarball(tarball: Path, required: Sequence[str]) -> tuple[str, ...]:
    """Inspect an npm tarball and require safe, non-empty regular exported files."""
    expected = {f"package/{path}" for path in required}
    try:
        with tarfile.open(tarball, mode="r:gz") as archive:
            found = _inspect_members(archive, expected)
    except (OSError, tarfile.TarError) as exc:
        msg = f"could not inspect package archive {tarball}: {exc}"
        raise ValueError(msg) from exc
    missing = sorted(expected - found)
    if missing:
        msg = f"packed artifact omits exported entry point: {missing[0].removeprefix('package/')}"
        raise ValueError(msg)
    return tuple(required)


def _inspect_members(archive: tarfile.TarFile, expected: set[str]) -> set[str]:
    found: set[str] = set()
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "package":
            msg = f"unsafe path in package archive: {member.name}"
            raise ValueError(msg)
        if member.name in expected:
            if not member.isfile() or member.size == 0:
                msg = f"packed entry point is missing, empty, or not a regular file: {member.name}"
                raise ValueError(msg)
            found.add(member.name)
    return found

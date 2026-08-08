"""Policies for TypeScript build output and npm package archives."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import tarfile
from typing import TYPE_CHECKING
import zipfile

from sarj_lint_configs.libs.release._values import is_object_dict, is_object_list, string_object_dict


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
_INSTALL_LIFECYCLE_SCRIPTS = frozenset({"preinstall", "install", "postinstall", "prepare"})


def _json_value(value: object) -> JsonValue:
    match value:
        case None | str() | int() | float() | bool():
            return value
        case _ if is_object_list(value):
            return [_json_value(item) for item in value]
        case _ if is_object_dict(value):
            return {key: _json_value(item) for key, item in string_object_dict(value, label="JSON").items()}
        case _:
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
    match value:
        case str():
            return (value,)
        case list():
            return tuple(path for item in value for path in _exported_paths(item))
        case dict():
            return tuple(path for item in value.values() for path in _exported_paths(item))
        case _:
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


def verify_package_tarball(
    tarball: Path,
    required: Sequence[str],
    *,
    expected_name: str | None = None,
    expected_version: str | None = None,
) -> tuple[str, ...]:
    """Inspect an npm tarball and require safe, non-empty regular exported files."""
    expected = {"package/LICENSE", *(f"package/{path}" for path in required)}
    try:
        with tarfile.open(tarball, mode="r:gz") as archive:
            found, identity_verified = _inspect_members(
                archive,
                expected,
                expected_name=expected_name,
                expected_version=expected_version,
            )
    except (OSError, tarfile.TarError) as exc:
        msg = f"could not inspect package archive {tarball}: {exc}"
        raise ValueError(msg) from exc
    missing = sorted(expected - found)
    if missing:
        msg = f"packed artifact omits exported entry point: {missing[0].removeprefix('package/')}"
        raise ValueError(msg)
    if (expected_name is not None or expected_version is not None) and not identity_verified:
        msg = "package archive omits package/package.json identity"
        raise ValueError(msg)
    return tuple(required)


def verify_python_wheel_license(wheel: Path) -> None:
    """Require a non-empty license text in a Python wheel before publication."""
    try:
        with zipfile.ZipFile(wheel) as archive:
            licenses = [name for name in archive.namelist() if PurePosixPath(name).name == "LICENSE"]
            if not licenses or any(not archive.read(name) for name in licenses):
                msg = f"wheel omits a non-empty LICENSE: {wheel.name}"
                raise ValueError(msg)
    except zipfile.BadZipFile as exc:
        msg = f"could not inspect wheel {wheel.name}"
        raise ValueError(msg) from exc


def _inspect_members(
    archive: tarfile.TarFile,
    expected: set[str],
    *,
    expected_name: str | None,
    expected_version: str | None,
) -> tuple[set[str], bool]:
    found: set[str] = set()
    identity_verified = False
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "package":
            msg = f"unsafe path in package archive: {member.name}"
            raise ValueError(msg)
        if member.issym() or member.islnk():
            msg = f"links are forbidden in package archive: {member.name}"
            raise ValueError(msg)
        if member.isfile() and member.name.endswith(".map"):
            msg = f"source maps are forbidden in package archive: {member.name}"
            raise ValueError(msg)
        if member.name == "package/package.json" and member.isfile():
            manifest_file = archive.extractfile(member)
            if manifest_file is None:
                msg = "could not read package/package.json from package archive"
                raise ValueError(msg)
            try:
                manifest: object = json.load(manifest_file)  # pyright: ignore[reportAny]
            except json.JSONDecodeError as exc:
                msg = "package archive contains invalid package/package.json"
                raise ValueError(msg) from exc
            manifest_data = string_object_dict(manifest, label="packed package.json")
            for field, expected_value in (("name", expected_name), ("version", expected_version)):
                if expected_value is not None and manifest_data.get(field) != expected_value:
                    msg = f"packed package {field} does not match source manifest"
                    raise ValueError(msg)
            identity_verified = True
            scripts = manifest_data.get("scripts")
            if is_object_dict(scripts):
                dangerous = _INSTALL_LIFECYCLE_SCRIPTS.intersection(scripts)
                if dangerous:
                    msg = f"install lifecycle script is forbidden in package archive: {min(dangerous)}"
                    raise ValueError(msg)
        if member.name in expected:
            if not member.isfile() or member.size == 0:
                msg = f"packed entry point is missing, empty, or not a regular file: {member.name}"
                raise ValueError(msg)
            found.add(member.name)
    return found, identity_verified

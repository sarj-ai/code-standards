from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import TypeGuard, TypeIs


type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


_NAME = re.compile(r"(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+\Z")
_SKIP = frozenset({"node_modules", ".git"})


@dataclass(frozen=True, slots=True)
class PackageImage:
    source: Path
    root: Path
    name: str
    version: str
    bins: Mapping[str, Path]
    files: Mapping[str, str]
    modes: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class LocalPackages:
    roots: Mapping[str, PackageImage]
    closure: tuple[PackageImage, ...]


@dataclass(frozen=True, slots=True)
class _Package:
    source: Path
    name: str
    version: str
    manifest: Mapping[str, JsonValue]
    dependencies: Mapping[str, Path]


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    mode: int


@dataclass(frozen=True, slots=True)
class _PackageLayout:
    root: Path
    packages: Mapping[Path, _Package]
    destinations: Mapping[Path, Path]


def _name(value: object) -> str:
    if (
        not isinstance(value, str)
        or _NAME.fullmatch(value) is None
        or any(part in {".", "..", "node_modules"} for part in value.split("/"))
    ):
        msg = f"invalid installed package name: {value!r}"
        raise ValueError(msg)
    return value


def _table(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not _is_table(value):
        msg = f"invalid installed package {label}"
        raise ValueError(msg)
    result: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"invalid installed package {label} key"
            raise TypeError(msg)
        result[key] = item
    return result


def _is_table(value: JsonValue) -> TypeGuard[dict[object, JsonValue]]:
    return isinstance(value, dict)


def _is_list(value: JsonValue) -> TypeIs[list[JsonValue]]:
    return isinstance(value, list)


def _manifest(source: Path) -> dict[str, JsonValue]:
    raw: JsonValue = json.loads((source / "package.json").read_bytes())  # pyright: ignore[reportAny] -- standalone stdlib fixture JSON boundary.
    return _table(raw, "manifest")


def _requests(manifest: Mapping[str, JsonValue]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    peer_meta = _table(manifest.get("peerDependenciesMeta", {}), "peer metadata")
    for field in ("dependencies", "peerDependencies", "optionalDependencies"):
        for raw_name, version in _table(manifest.get(field, {}), field).items():
            name = _name(raw_name)
            if not isinstance(version, str):
                msg = f"invalid installed dependency specifier: {name}"
                raise TypeError(msg)
            optional_peer = (
                field == "peerDependencies" and _table(peer_meta.get(name, {}), "peer metadata").get("optional") is True
            )
            required = field != "optionalDependencies" and not optional_peer
            result[name] = result.get(name, False) or required
            if field == "optionalDependencies":
                result[name] = False
    bundled = manifest.get("bundleDependencies", manifest.get("bundledDependencies", []))
    if bundled is not True and bundled is not False:
        if not _is_list(bundled):
            msg = "invalid installed bundled dependency declaration"
            raise ValueError(msg)
        for name in bundled:
            result[_name(name)] = True
    return result


def _resolve_dependency(source: Path, name: str) -> Path | None:
    # Match Node's ancestor node_modules lookup; never consult NODE_PATH or a registry.
    for parent in (source, *source.parents):
        if parent.name == "node_modules":
            continue
        candidate = parent / "node_modules" / name
        if candidate.is_dir() and (candidate / "package.json").is_file():
            return candidate.resolve(strict=True)
    return None


def _closure(roots: Mapping[str, Path]) -> dict[Path, _Package]:
    pending = [path.resolve(strict=True) for path in roots.values()]
    packages: dict[Path, _Package] = {}
    while pending:
        source = pending.pop()
        if source in packages:
            continue
        manifest = _manifest(source)
        name = _name(manifest.get("name"))
        version = manifest.get("version")
        if not isinstance(version, str) or not version:
            msg = f"installed package version is missing: {source}"
            raise ValueError(msg)
        dependencies: dict[str, Path] = {}
        for dependency, required in _requests(manifest).items():
            resolved = _resolve_dependency(source, dependency)
            if resolved is None:
                if required:
                    msg = f"required installed dependency is absent: {name} -> {dependency}"
                    raise ValueError(msg)
                continue
            dependencies[dependency] = resolved
            pending.append(resolved)
        packages[source] = _Package(source, name, version, MappingProxyType(manifest), MappingProxyType(dependencies))
    return packages


def _identity(path: Path) -> _FileIdentity:
    value = path.stat()
    return _FileIdentity(
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, stat.S_IMODE(value.st_mode)
    )


def _copy_file(source: Path, destination: Path) -> None:
    before = _identity(source)
    data = source.read_bytes()
    if _identity(source) != before:
        msg = f"installed package file changed while copying: {source}"
        raise ValueError(msg)
    with destination.open("xb") as output:
        output.write(data)
    destination.chmod(before.mode)
    if destination.read_bytes() != data:
        msg = f"private package copy differs from its installed input: {destination}"
        raise ValueError(msg)


def _copy_tree(source: Path, destination: Path, ancestors: frozenset[Path] = frozenset()) -> None:
    source = source.resolve(strict=True)
    if source in ancestors:
        msg = f"installed package contains a directory-link cycle: {source}"
        raise ValueError(msg)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for entry in sorted(source.iterdir(), key=lambda path: path.name):
        if entry.name in _SKIP:
            continue
        resolved = entry.resolve(strict=True)
        if resolved.is_dir():
            _copy_tree(resolved, destination / entry.name, ancestors | {source})
        elif resolved.is_file():
            _copy_file(resolved, destination / entry.name)
        else:
            msg = f"installed package contains a nonregular entry: {entry}"
            raise ValueError(msg)


def _link(root: Path, path: Path, target: Path) -> None:
    if not target.resolve(strict=True).is_relative_to(root) or not path.parent.resolve().is_relative_to(root):
        msg = "private package dependency link escapes its fixture"
        raise ValueError(msg)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.symlink_to(os.path.relpath(target, path.parent), target_is_directory=target.is_dir())
    if not path.resolve(strict=True).is_relative_to(root):
        msg = "private package dependency link escaped after creation"
        raise ValueError(msg)


def _bins(root: Path, package: _Package, destination: Path) -> Mapping[str, Path]:
    raw = package.manifest.get("bin", {})
    bins = {package.name.rsplit("/", 1)[-1]: raw} if isinstance(raw, str) else _table(raw, "bin")
    result: dict[str, Path] = {}
    for name, value in bins.items():
        if not name or "\0" in name or PurePosixPath(name).parts != (name,) or name in {".", ".."}:
            msg = "installed package bin name must be a single filename"
            raise ValueError(msg)
        if not isinstance(value, str):
            msg = "installed package bin must be a relative path"
            raise TypeError(msg)
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts:
            msg = "installed package bin escapes its package"
            raise ValueError(msg)
        path = (destination / relative).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(root):
            msg = "copied package bin escapes its private fixture"
            raise ValueError(msg)
        result[name] = path
    return MappingProxyType(result)


def materialize_installed_packages(
    destination: Path,
    roots: Mapping[str, Path],
    *,
    expected_versions: Mapping[str, str],
) -> LocalPackages:
    destination = _validate_destination(destination)
    resolved_roots = _resolve_roots(roots, expected_versions)
    packages = _closure(resolved_roots)
    _validate_root_versions(packages, resolved_roots, expected_versions)
    destination = _create_destination(destination)
    local = {
        source: destination
        / "node_modules/.native-fixture"
        / hashlib.sha256(os.fsencode(source)).hexdigest()
        / "node_modules"
        / package.name
        for source, package in packages.items()
    }
    layout = _PackageLayout(destination, MappingProxyType(packages), MappingProxyType(local))
    _copy_packages(layout)
    _link_dependencies(layout)
    _expose_roots(layout, resolved_roots)
    images = _package_images(layout)
    return LocalPackages(
        MappingProxyType({name: images[source] for name, source in resolved_roots.items()}), tuple(images.values())
    )


def _validate_destination(destination: Path) -> Path:
    destination = destination.absolute()
    if destination.is_symlink():
        msg = "package fixture cannot use a symlink"
        raise ValueError(msg)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        msg = "use a new private package fixture and explicit expected versions for every root"
        raise ValueError(msg)
    return destination


def _resolve_roots(roots: Mapping[str, Path], expected_versions: Mapping[str, str]) -> dict[str, Path]:
    if not roots or set(roots) != set(expected_versions):
        msg = "use a new private package fixture and explicit expected versions for every root"
        raise ValueError(msg)
    return {_name(name): path.resolve(strict=True) for name, path in roots.items()}


def _validate_root_versions(
    packages: Mapping[Path, _Package], roots: Mapping[str, Path], expected_versions: Mapping[str, str]
) -> None:
    for name, source in roots.items():
        package = packages[source]
        if package.name != name or package.version != expected_versions[name]:
            msg = f"installed root package identity differs: {name}"
            raise ValueError(msg)


def _create_destination(destination: Path) -> Path:
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_uid != os.getuid() or stat.S_IMODE(destination.stat().st_mode) & 0o077:
        msg = "package fixture must be private to its current user"
        raise ValueError(msg)
    return destination.resolve(strict=True)


def _copy_packages(layout: _PackageLayout) -> None:
    for source, package in layout.packages.items():
        _copy_tree(source, layout.destinations[source])
        if _manifest(layout.destinations[source]) != dict(package.manifest):
            msg = f"private package manifest differs from installed identity: {package.name}"
            raise ValueError(msg)


def _link_dependencies(layout: _PackageLayout) -> None:
    for source, package in layout.packages.items():
        for name, dependency in package.dependencies.items():
            _link(layout.root, layout.destinations[source] / "node_modules" / name, layout.destinations[dependency])


def _expose_roots(layout: _PackageLayout, roots: Mapping[str, Path]) -> None:
    for name, source in roots.items():
        _link(layout.root, layout.root / "node_modules" / name, layout.destinations[source])
    root_bins: dict[str, Path] = {}
    for source in roots.values():
        for name, target in _bins(layout.root, layout.packages[source], layout.destinations[source]).items():
            if name in root_bins:
                msg = f"explicit installed root packages declare the same bin: {name}"
                raise ValueError(msg)
            if not stat.S_IMODE(target.stat().st_mode) & 0o111:
                msg = f"installed root package bin is not executable: {name}"
                raise ValueError(msg)
            root_bins[name] = target
    for name, target in root_bins.items():
        _link(layout.root, layout.root / "node_modules/.bin" / name, target)


def _package_images(layout: _PackageLayout) -> dict[Path, PackageImage]:
    images: dict[Path, PackageImage] = {}
    for source, package in layout.packages.items():
        files: dict[str, str] = {}
        modes: dict[str, int] = {}
        for path in layout.destinations[source].rglob("*"):
            if path.is_symlink():
                if not path.resolve(strict=True).is_relative_to(layout.root):
                    msg = "materialized package retained an external symlink"
                    raise ValueError(msg)
                continue
            if path.is_file():
                relative = path.relative_to(layout.destinations[source]).as_posix()
                files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
                modes[relative] = stat.S_IMODE(path.stat().st_mode)
        images[source] = PackageImage(
            source,
            layout.destinations[source],
            package.name,
            package.version,
            _bins(layout.root, package, layout.destinations[source]),
            MappingProxyType(files),
            MappingProxyType(modes),
        )
    return images

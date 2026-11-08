from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
from typing import TYPE_CHECKING, Final, Literal

import yaml

from sarj_standards.libs.adoption import packagemanager, transaction
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.typed_containers import is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml_documents

from .native_byte_bridge import NativeInvocation
from .oxfmt import CONFIG_NAMES as _OXFMT_CONFIGS


if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

    from pydantic import JsonValue


_EXACT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?")
_OXFMT_POLICY: Final = "oxfmt.strict.mts"


@dataclass(frozen=True, slots=True)
class InputProof:
    path: Path
    contents: bytes
    mode: int
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class RuntimeProof:
    path: Path
    sha256: str
    mode: int
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _LocalTool:
    node: Path
    entrypoint: Path
    version: str
    runtime: RuntimeProof


@dataclass(frozen=True, slots=True)
class _InstalledTool:
    entrypoint: Path
    version: str


@dataclass(frozen=True, slots=True)
class FormatterOwner:
    invocation: NativeInvocation
    version: str
    inputs: tuple[InputProof, ...]
    runtimes: tuple[RuntimeProof, ...]
    missing: tuple[Path, ...] = ()


class OwnershipChangedError(ValueError):
    pass


def _read(path: Path) -> InputProof:
    before = path.lstat()
    if path.is_symlink() or path.is_junction() or not stat.S_ISREG(before.st_mode):
        msg = "formatter ownership requires regular, nonlinked input files"
        raise ValueError(msg)
    contents = path.read_bytes()
    msg = "formatter ownership input changed while reading"
    try:
        after = path.lstat()
    except OSError as exc:
        raise OwnershipChangedError(msg) from exc
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise OwnershipChangedError(msg)
    return InputProof(path, contents, stat.S_IMODE(before.st_mode), identity)


def validate(owner: FormatterOwner) -> None:
    validate_all((owner,))


def validate_all(owners: Iterable[FormatterOwner]) -> None:
    inputs: dict[Path, InputProof] = {}
    runtimes: dict[Path, RuntimeProof] = {}
    missing: set[Path] = set()
    for owner in owners:
        _collect_owner_proofs(owner, inputs, runtimes)
        missing.update(owner.missing)
    if (
        any(_read(proof.path) != proof for proof in inputs.values())
        or any(not _runtime_unchanged(proof) for proof in runtimes.values())
        or any(os.path.lexists(path) for path in missing)
    ):
        msg = "formatter owner, configuration or installed pin changed during native planning"
        raise ValueError(msg)


def _collect_owner_proofs(
    owner: FormatterOwner, inputs: dict[Path, InputProof], runtimes: dict[Path, RuntimeProof]
) -> None:
    for proof in owner.inputs:
        if inputs.setdefault(proof.path, proof) != proof:
            msg = "formatter ownership changed during native planning"
            raise ValueError(msg)
    for proof in owner.runtimes:
        if runtimes.setdefault(proof.path, proof) != proof:
            msg = "native runtime changed during native planning"
            raise ValueError(msg)


def _runtime_unchanged(proof: RuntimeProof) -> bool:
    current = proof.path.lstat()
    return (
        stat.S_ISREG(current.st_mode)
        and not proof.path.is_symlink()
        and not proof.path.is_junction()
        and stat.S_IMODE(current.st_mode) == proof.mode
        and (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns)
        == proof.identity
    )


def _bounded(start: Path, root: Path) -> tuple[Path, ...]:
    return (start, *(parent for parent in start.parents if parent == root or root in parent.parents))


def _tracked(path: Path, root: Path, tracked: Collection[str], inputs: dict[Path, InputProof]) -> InputProof:
    transaction.validate_targets(root, (path,))
    if path.relative_to(root).as_posix() not in tracked:
        msg = "formatter owner and configuration must be tracked repository inputs"
        raise ValueError(msg)
    if path not in inputs:
        inputs[path] = _read(path)
    return inputs[path]


def configured(root: Path, relative: str) -> bool:
    return any(
        os.path.lexists(parent / name) for parent in _bounded((root / relative).parent, root) for name in _OXFMT_CONFIGS
    )


def select(
    root: Path,
    relative: str,
    tracked: Collection[str],
    *,
    runtimes: dict[Path, RuntimeProof] | None = None,
    _node: Callable[[Path], Path] | None = None,
) -> FormatterOwner:
    # oxfmt formats a source with the nearest oxfmt config, as `oxfmt` run in that directory would.
    path = root / relative
    inputs: dict[Path, InputProof] = {}
    missing: set[Path] = set()
    ancestors = _bounded(path.parent, root)
    config = _configuration(root, ancestors, tracked, inputs, missing)
    _format_inputs(root, ancestors, tracked, inputs, missing)
    local = _local_tool(
        root,
        config.parent,
        "oxfmt",
        tracked=tracked,
        inputs=inputs,
        runtimes={} if runtimes is None else runtimes,
        resolve_node=_node,
    )
    return FormatterOwner(
        NativeInvocation(
            "oxfmt", local.node, local.entrypoint, config.parent, (f"--config={config}", f"--stdin-filepath={path}")
        ),
        local.version,
        tuple(inputs.values()),
        (local.runtime,),
        tuple(sorted(missing)),
    )


def _local_tool(
    root: Path,
    project: Path,
    tool: Literal["oxfmt"],
    *,
    tracked: Collection[str],
    inputs: dict[Path, InputProof],
    runtimes: dict[Path, RuntimeProof],
    resolve_node: Callable[[Path], Path] | None,
) -> _LocalTool:
    installed = _installed_tool(root, project, tool, tracked, inputs)
    if resolve_node is None:
        executable = shutil.which("node")
        if executable is None:
            msg = "the declared native Node runtime must already be provisioned"
            raise ValueError(msg)
        node = Path(executable).resolve()
    else:
        node = resolve_node(project).resolve()
    runtime = runtimes.get(node)
    if runtime is None:
        runtime = _runtime(node)
        runtimes[node] = runtime
    else:
        msg = "native Node runtime changed during directive planning"
        try:
            unchanged = _runtime_unchanged(runtime)
        except OSError as exc:
            raise OwnershipChangedError(msg) from exc
        if not unchanged:
            raise OwnershipChangedError(msg)
    return _LocalTool(node, installed.entrypoint, installed.version, runtime)


def _runtime(path: Path) -> RuntimeProof:
    before = path.lstat()
    if path.is_symlink() or path.is_junction() or not stat.S_ISREG(before.st_mode):
        msg = "native runtime must resolve to a regular executable"
        raise ValueError(msg)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = RuntimeProof(
        path,
        digest,
        stat.S_IMODE(before.st_mode),
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns),
    )
    msg = "native runtime changed while establishing its immutable identity"
    try:
        unchanged = _runtime_unchanged(result)
    except OSError as exc:
        raise OwnershipChangedError(msg) from exc
    if not unchanged:
        raise OwnershipChangedError(msg)
    return result


def _installed_tool(
    root: Path,
    project: Path,
    tool: Literal["oxfmt"],
    tracked: Collection[str],
    inputs: dict[Path, InputProof],
) -> _InstalledTool:
    package_name = tool
    owner = _installation_owner(root, project, package_name)
    declaration = owner / "package.json"
    _tracked(declaration, root, tracked, inputs)
    version = _dependency(
        _object(declaration, inputs), package_name, project=owner, root=root, tracked=tracked, inputs=inputs
    )
    package_file = _installed_package_file(root, owner, package_name, inputs)
    installed = _object(package_file, inputs)
    if installed.get("name") != package_name or installed.get("version") != version:
        msg = "installed native formatter does not match the declared immutable pin"
        raise ValueError(msg)
    entrypoint = _package_entrypoint(package_file, installed, tool)
    inputs[entrypoint] = _read(entrypoint)
    return _InstalledTool(entrypoint, version)


def _object(path: Path, inputs: dict[Path, InputProof]) -> dict[str, JsonValue]:
    if path not in inputs:
        inputs[path] = _read(path)
    proof = inputs[path]
    try:
        parsed = parse_unique_json(proof.contents.decode("utf-8"))
    except RecursionError as exc:
        msg = "formatter ownership metadata is too deeply nested"
        raise ValueError(msg) from exc
    if type(parsed) is not dict:
        msg = "formatter ownership metadata must be a unique JSON object"
        raise ValueError(msg)
    return parsed


def _dependency(
    package: Mapping[str, JsonValue],
    name: str,
    *,
    project: Path,
    root: Path,
    tracked: Collection[str],
    inputs: dict[Path, InputProof],
) -> str:
    version = _declared_dependency(package, name)
    workspace = packagemanager.workspace_root(project, root)
    if version.startswith("catalog:"):
        proof = _tracked(workspace / "pnpm-workspace.yaml", root, tracked, inputs)
        version = _catalog_dependency(version, name, proof)
    if _EXACT_VERSION.fullmatch(version) is None:
        msg = "native formatter requires an exact immutable package version"
        raise ValueError(msg)
    locks = [workspace / name for name, _client in packagemanager.LOCKFILES if (workspace / name).is_file()]
    if len(locks) != 1:
        msg = "native formatter requires one canonical tracked lockfile"
        raise ValueError(msg)
    _tracked(locks[0], root, tracked, inputs)
    return version


def _declared_dependency(package: Mapping[str, JsonValue], name: str) -> str:
    declarations: list[str] = []
    for section in ("dependencies", "devDependencies"):
        values = package.get(section)
        if isinstance(values, dict) and name in values:
            value = values[name]
            if not isinstance(value, str):
                msg = "native formatter dependency must have an exact declared pin"
                raise ValueError(msg)
            declarations.append(value)
    if len(declarations) != 1:
        msg = "native formatter requires one unambiguous declared dependency"
        raise ValueError(msg)
    return declarations[0]


def _catalog_dependency(version: str, name: str, proof: InputProof) -> str:
    try:
        documents = parse_yaml_documents(proof.contents.decode("utf-8"))
    except yaml.YAMLError as exc:
        msg = "native formatter catalog is malformed YAML"
        raise ValueError(msg) from exc
    parsed = documents[0] if len(documents) == 1 else None
    if not is_object_mapping(parsed):
        msg = "native formatter catalog must be one valid unique-key YAML object"
        raise ValueError(msg)
    catalog_name = version.removeprefix("catalog:")
    catalogs = parsed.get("catalogs")
    catalog = (
        parsed.get("catalog")
        if not catalog_name
        else catalogs.get(catalog_name)
        if is_object_mapping(catalogs)
        else None
    )
    selected = catalog.get(name) if is_object_mapping(catalog) else None
    if not isinstance(selected, str):
        msg = "native formatter catalog has no exact package pin"
        raise TypeError(msg)
    return selected


def _installation_owner(root: Path, project: Path, package_name: str) -> Path:
    owner = next(
        (
            parent
            for parent in _bounded(project, root)
            if (parent / "node_modules" / package_name / "package.json").is_file()
        ),
        None,
    )
    if owner is None:
        msg = "native formatter must already be installed locally"
        raise ValueError(msg)
    return owner


def _installed_package_file(root: Path, owner: Path, package_name: str, inputs: dict[Path, InputProof]) -> Path:
    modules = (owner / "node_modules").resolve()
    package_file = (modules / package_name / "package.json").resolve()
    if not modules.is_relative_to(root) or not (
        package_file.is_relative_to(modules) or _in_pnpm_global_virtual_store(modules, package_file, inputs)
    ):
        msg = "native formatter package resolves outside repository-local node_modules"
        raise ValueError(msg)
    return package_file


def _in_pnpm_global_virtual_store(modules: Path, package_file: Path, inputs: dict[Path, InputProof]) -> bool:
    # pnpm's global virtual store links packages from its content-addressed store, outside the
    # repository. Accept that location only where this install's own state records it.
    state = modules / ".modules.yaml"
    if not os.path.lexists(state):
        return False
    metadata = _object(state, inputs)
    store = metadata.get("virtualStoreDir")
    if metadata.get("nodeLinker") != "isolated" or not isinstance(store, str) or not store:
        return False
    links = (modules / store).resolve()
    return links.name == "links" and package_file.is_relative_to(links)


def _package_entrypoint(package_file: Path, installed: Mapping[str, JsonValue], tool: Literal["oxfmt"]) -> Path:
    bins = installed.get("bin")
    binary = bins.get(tool) if isinstance(bins, dict) else bins if isinstance(bins, str) else None
    if not isinstance(binary, str) or Path(binary).is_absolute() or ".." in Path(binary).parts:
        msg = "native formatter has no canonical local package entrypoint"
        raise ValueError(msg)
    entrypoint = (package_file.parent / binary).resolve()
    if not entrypoint.is_relative_to(package_file.parent):
        msg = "native formatter entrypoint escapes its installed package"
        raise ValueError(msg)
    return entrypoint


def _configuration(
    root: Path,
    ancestors: tuple[Path, ...],
    tracked: Collection[str],
    inputs: dict[Path, InputProof],
    missing: set[Path],
) -> Path:
    for parent in ancestors:
        present: list[Path] = []
        for name in _OXFMT_CONFIGS:
            candidate = parent / name
            if os.path.lexists(candidate):
                present.append(candidate)
            else:
                missing.add(candidate)
        if len(present) > 1:
            msg = "directive cleanup requires one unambiguous oxfmt configuration"
            raise ValueError(msg)
        if present:
            config = present[0]
            _tracked(config, root, tracked, inputs)
            # The managed TypeScript config spreads the synced policy module next to it.
            if config.suffix in {".ts", ".mts"}:
                strict = parent / _OXFMT_POLICY
                if os.path.lexists(strict):
                    _tracked(strict, root, tracked, inputs)
                else:
                    missing.add(strict)
            return config
    msg = "directive cleanup requires an oxfmt configuration"
    raise ValueError(msg)


def _format_inputs(
    root: Path,
    ancestors: tuple[Path, ...],
    tracked: Collection[str],
    inputs: dict[Path, InputProof],
    missing: set[Path],
) -> None:
    for parent in ancestors:
        for name in (
            ".editorconfig",
            ".gitignore",
            ".ignore",
            ".prettierignore",
            ".mise.toml",
            "mise.toml",
            ".mise.local.toml",
            "mise.local.toml",
            ".tool-versions",
            ".node-version",
            ".nvmrc",
        ):
            path = parent / name
            if os.path.lexists(path):
                _tracked(path, root, tracked, inputs)
            else:
                missing.add(path)
    for parent in root.parents:
        editor = parent / ".editorconfig"
        if os.path.lexists(editor):
            msg = "external EditorConfig ownership is unsupported for directive projection"
            raise ValueError(msg)
        missing.add(editor)
    gitdir = root / ".git"
    if gitdir.is_file():
        marker = _read(gitdir)
        inputs[gitdir] = marker
        value = marker.contents.decode("utf-8").strip()
        if not value.startswith("gitdir: "):
            msg = "formatter ignore ownership has an unsupported Git marker"
            raise ValueError(msg)
        gitdir = (root / value.removeprefix("gitdir: ")).resolve()
    common_marker = gitdir / "commondir"
    if common_marker.is_file():
        marker = _read(common_marker)
        inputs[common_marker] = marker
        gitdir = (gitdir / marker.contents.decode("utf-8").strip()).resolve()
    else:
        missing.add(common_marker)
    exclude = gitdir / "info/exclude"
    if os.path.lexists(exclude):
        inputs[exclude] = _read(exclude)
    else:
        missing.add(exclude)

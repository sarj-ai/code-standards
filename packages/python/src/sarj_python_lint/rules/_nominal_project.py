from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeGuard, final

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from sarj_python_lint.rules._first_party import distribution_root
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from sarj_python_lint.rules._first_party import FirstPartyFacts


_MAX_FILES = 5_000
_MAX_DIRECTORIES = 3_000
_MAX_BYTES = 500_000
_MAX_TOTAL_BYTES = 25_000_000
_SKIP = frozenset({"node_modules", "vendor", "vendored", "build", "dist", "__pycache__", "venv"})


@dataclass(frozen=True)
class NominalSource:
    path: Path
    text: str

    @cached_property
    def tree(self) -> ast.Module | None:
        try:
            tree = ast.parse(self.text, filename=str(self.path))
        except SyntaxError:
            return None
        if any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
            for node in ast.walk(tree)
        ):
            return None
        return tree

    @cached_property
    def imports(self) -> ImportIndex:
        tree = self.tree
        if tree is None:
            return ImportIndex(MappingProxyType({}), frozenset())
        imports = ImportIndex.from_tree(tree)
        mutated = {
            ast.unparse(node).partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
        }
        return ImportIndex(
            MappingProxyType({name: target for name, target in imports.bindings.items() if name not in mutated}),
            imports.shadowed_names | mutated,
        )


@dataclass(frozen=True, slots=True)
class _Workspace:
    root: Path
    members: tuple[str, ...]
    excludes: tuple[str, ...]

    def contains(self, path: Path) -> bool:
        if path == self.root:
            return True
        if not path.is_relative_to(self.root):
            return False
        relative = path.relative_to(self.root)
        return any(relative.full_match(pattern) for pattern in self.members) and not any(
            relative.full_match(pattern) for pattern in self.excludes
        )


@dataclass(frozen=True, slots=True)
class _Distribution:
    root: Path
    name: str | None
    dependencies: frozenset[str]
    workspace: _Workspace | None


@final
class NominalProjectFacts:
    # One request owns these caches; subsequent requests see source changes.
    def __init__(self) -> None:
        self._distributions: dict[Path, tuple[_Distribution, ...]] = {}
        self._sources: dict[Path, dict[str, NominalSource]] = {}
        self._scopes: dict[Path, dict[str, NominalSource]] = {}

    def sources(self, path: Path, first_party: FirstPartyFacts) -> dict[str, NominalSource]:
        owner = distribution_root(path, facts=first_party)
        root = first_party.project_root(path)
        if owner is None or root is None:
            return {}
        if owner in self._scopes:
            return self._scopes[owner]
        distributions = self._accessible_distributions(owner, root)
        sources = self._merge_sources(distributions)
        self._scopes[owner] = sources
        return sources

    def _accessible_distributions(self, owner: Path, root: Path) -> tuple[_Distribution, ...]:
        if root not in self._distributions:
            self._distributions[root] = tuple(
                distribution
                for manifest in _files(root, "pyproject.toml")
                if (distribution := _distribution(manifest)) is not None
            )
        distributions = self._distributions[root]
        own = next(
            (
                distribution
                for distribution in distributions
                if distribution.root == owner and distribution.name is not None
            ),
            None,
        )
        if own is None:
            return ()
        distributions = _workspace_distributions(distributions, owner)
        return tuple(
            distribution
            for distribution in distributions
            if distribution == own
            or (
                distribution.name in own.dependencies
                and sum(candidate.name == distribution.name for candidate in distributions) == 1
            )
        )

    def _merge_sources(self, distributions: tuple[_Distribution, ...]) -> dict[str, NominalSource]:
        sources: dict[str, NominalSource] = {}
        ambiguous: set[str] = set()
        for distribution in distributions:
            if distribution.root not in self._sources:
                self._sources[distribution.root] = _sources(distribution.root)
            for module, source in self._sources[distribution.root].items():
                if module in sources:
                    ambiguous.add(module)
                sources[module] = source
        return {module: source for module, source in sources.items() if module not in ambiguous}


def _workspace_distributions(distributions: tuple[_Distribution, ...], owner: Path) -> tuple[_Distribution, ...]:
    workspaces = [
        distribution.workspace
        for distribution in distributions
        if distribution.workspace is not None and distribution.workspace.contains(owner)
    ]
    if workspaces:
        workspace = max(workspaces, key=lambda scope: len(scope.root.parts))
        distributions = tuple(distribution for distribution in distributions if workspace.contains(distribution.root))
    return distributions


def _distribution(manifest: Path) -> _Distribution | None:
    try:
        if manifest.is_symlink() or manifest.stat().st_size > _MAX_BYTES:
            return None
        document: object = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not _is_mapping(document):
        return None
    workspace = _workspace(manifest.parent, document)
    project = document.get("project")
    if not _is_mapping(project):
        return _Distribution(manifest.parent, None, frozenset(), workspace) if workspace is not None else None
    name = project.get("name")
    dependencies = project.get("dependencies", [])
    if not isinstance(name, str) or not _is_list(dependencies):
        return None
    names: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        try:
            names.add(canonicalize_name(Requirement(dependency).name))
        except InvalidRequirement:
            continue
    return _Distribution(manifest.parent, canonicalize_name(name), frozenset(names), workspace)


def _workspace(root: Path, document: dict[object, object]) -> _Workspace | None:
    value: object = document
    for key in ("tool", "uv", "workspace"):
        if not _is_mapping(value):
            return None
        value = value.get(key)
    if not _is_mapping(value):
        return None
    members = _patterns(value.get("members"))
    excludes = _patterns(value.get("exclude", []))
    if members is None or excludes is None:
        return None
    return _Workspace(root, members, excludes)


def _patterns(value: object) -> tuple[str, ...] | None:
    if not _is_list(value) or any(not isinstance(item, str) for item in value):
        return None
    return tuple(item for item in value if isinstance(item, str))


def _files(root: Path, pattern: str) -> list[Path]:
    found: list[Path] = []
    try:
        for count, (directory, directories, filenames) in enumerate(root.walk()):
            if count >= _MAX_DIRECTORIES or len(found) >= _MAX_FILES:
                # A partial inventory cannot establish uniqueness.
                return []
            directories[:] = sorted(name for name in directories if not name.startswith(".") and name not in _SKIP)
            found.extend(directory / name for name in sorted(filenames) if Path(name).match(pattern))
            if len(found) > _MAX_FILES:
                return []
    except OSError:
        return []
    return found


def _sources(root: Path) -> dict[str, NominalSource]:
    sources: dict[str, NominalSource] = {}
    ambiguous: set[str] = set()
    total_bytes = 0
    for path in _files(root, "*.py"):
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
        if total_bytes > _MAX_TOTAL_BYTES:
            return {}
        module = _module_name(root, path)
        if not module:
            continue
        source = _source(path)
        if source is None:
            continue
        if module in sources:
            ambiguous.add(module)
        sources[module] = source
    return {module: source for module, source in sources.items() if module not in ambiguous}


def _module_name(root: Path, path: Path) -> str | None:
    # A nested manifest owns its sources even when it uses the same namespace.
    if any(
        (parent / "pyproject.toml").is_file() for parent in path.parents if parent != root and root in parent.parents
    ):
        return None
    relative = path.relative_to(root)
    parts = relative.parts[1:] if relative.parts[0] == "src" else relative.parts
    return ".".join(parts[:-1] if parts[-1] == "__init__.py" else (*parts[:-1], path.stem)) or None


def _source(path: Path) -> NominalSource | None:
    try:
        if path.is_symlink() or path.stat().st_size > _MAX_BYTES:
            return None
        text = path.read_text(encoding="utf-8")
        if is_generated(path, text):
            return None
    except OSError, UnicodeError:
        return None
    return NominalSource(path, text)


def _is_mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)

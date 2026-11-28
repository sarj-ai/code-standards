from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeGuard, final

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from sarj_python_lint._source import read_python_source
from sarj_python_lint.rules._ast_index import NodeIndex, import_statements
from sarj_python_lint.rules._first_party import distribution_root, has_distribution_marker
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._literal_domains import LiteralDomainIndex, StringDomain, string_domains
from sarj_python_lint.rules._paths import GeneratedPathFacts
from sarj_python_lint.rules._project_index import ProjectIndexSet, parsed_tree


if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Never

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
    parsed: ast.Module | None = field(default=None, compare=False, repr=False)

    @cached_property
    def constructor_names(self) -> frozenset[str]:
        if "NewType" not in self.text or (tree := self._parse_tree()) is None:
            return frozenset()
        return nominal_constructor_names(tree)

    @cached_property
    def closed_string_domains(self) -> tuple[StringDomain, ...]:
        if not ("Literal" in self.text or ("enum" in self.text and "Enum" in self.text)):
            return ()
        tree = self.tree
        if tree is None:
            return ()
        imports = _without_namespace_writes(ImportIndex.from_tree(tree, module_scope_only=True), ast.walk(tree))
        return string_domains(tree, imports, self.path)

    @cached_property
    def node_index(self) -> NodeIndex | None:
        tree = self.tree
        if tree is None:
            return None
        shared = NodeIndex.shared(tree)
        return shared if shared is not None else NodeIndex(tree)

    @cached_property
    def tree(self) -> ast.Module | None:
        tree = self._parse_tree()
        if tree is None or any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
            for node in import_statements(tree)
        ):
            return None
        return tree

    def _parse_tree(self) -> ast.Module | None:
        if self.parsed is not None:
            return self.parsed
        try:
            return ast.parse(self.text, filename=str(self.path))
        except SyntaxError:
            return None

    @cached_property
    def imports(self) -> ImportIndex:
        tree = self.tree
        node_index = self.node_index
        if tree is None or node_index is None:
            return ImportIndex(MappingProxyType({}), frozenset())
        return _without_namespace_writes(ImportIndex.from_tree(tree), node_index.query((ast.Attribute,)))


def _without_namespace_writes(imports: ImportIndex, nodes: Iterable[ast.AST]) -> ImportIndex:
    mutated = {
        ast.unparse(node).partition(".")[0]
        for node in nodes
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
    }
    return ImportIndex(
        MappingProxyType({name: target for name, target in imports.bindings.items() if name not in mutated}),
        imports.shadowed_names | mutated,
    )


def nominal_constructor_names(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for statement in tree.body:
        if (declaration := nominal_factory_call(statement)) is not None:
            target, _, _ = declaration
            names.add(target.id)
    return frozenset(names)


def nominal_factory_call(statement: ast.AST) -> tuple[ast.Name, ast.expr, ast.expr] | None:
    match statement:
        case ast.Assign(
            targets=[ast.Name(id=name) as target],
            value=ast.Call(func=factory, args=[ast.Constant(value=title), carrier], keywords=[]),
        ) if title == name:
            return target, factory, carrier
        case _:
            return None


def _unique_source(candidates: Iterable[NominalSource | None]) -> NominalSource | None:
    source = None
    for candidate in candidates:
        if candidate is None:
            continue
        if source is not None:
            return None
        source = candidate
    return source


@final
class _DistributionSources:
    def __init__(
        self, entries: list[tuple[str, NominalSource]], generated_paths: GeneratedPathFacts, *, include_generated: bool
    ) -> None:
        self._entries = entries
        self._generated_paths = generated_paths
        self._include_generated = include_generated
        self._modules: dict[str, list[NominalSource]] = defaultdict(list)
        self._resolved: dict[str, NominalSource | None] = {}
        for module, source in entries:
            self._modules[module].append(source)

    @cached_property
    def nominal_modules(self) -> frozenset[str]:
        return frozenset(module for module, source in self._entries if "NewType" in source.text)

    @cached_property
    def paths(self) -> dict[Path, str]:
        return {source.path: module for module, source in self._entries}

    def get(self, module: str) -> NominalSource | None:
        if module not in self._resolved:
            self._resolved[module] = _unique_source(
                source
                for source in self._modules.get(module, ())
                if self._include_generated or not self._generated_paths.is_generated(source.path, source.text)
            )
        return self._resolved[module]

    @cached_property
    def sources(self) -> dict[str, NominalSource]:
        return {module: source for module, source in self._entries if self.get(module) is source}

    @cached_property
    def declaration_sources(self) -> tuple[NominalSource, ...]:
        return tuple(
            source
            for _, source in self._entries
            if self._include_generated or not self._generated_paths.is_generated(source.path, source.text)
        )

    @cached_property
    def literal_domains(self) -> LiteralDomainIndex:
        return LiteralDomainIndex.build(self.sources)


@final
class NominalScope:
    def __init__(self, distributions: tuple[_DistributionSources, ...]) -> None:
        self._distributions = distributions
        self._resolved: dict[str, NominalSource | None] = {}

    def get(self, module: str) -> NominalSource | None:
        if module not in self._resolved:
            self._resolved[module] = _unique_source(distribution.get(module) for distribution in self._distributions)
        return self._resolved[module]

    def module_for(self, path: Path) -> str | None:
        for distribution in self._distributions:
            if (module := distribution.paths.get(path)) is None:
                continue
            source = self.get(module)
            if source is not None and source.path == path:
                return module
        return None

    @cached_property
    def constructor_names(self) -> frozenset[str]:
        modules = {module for distribution in self._distributions for module in distribution.nominal_modules}
        return frozenset(
            name for module in modules if (source := self.get(module)) is not None for name in source.constructor_names
        )

    @cached_property
    def sources(self) -> dict[str, NominalSource]:
        return {
            module: source
            for distribution in self._distributions
            for module, source in distribution.sources.items()
            if self.get(module) is source
        }

    @cached_property
    def declaration_sources(self) -> dict[Path, NominalSource]:
        return {
            source.path: source for distribution in self._distributions for source in distribution.declaration_sources
        }


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
    def __init__(self, generated_paths: GeneratedPathFacts | None = None) -> None:
        self._generated_paths = generated_paths if generated_paths is not None else GeneratedPathFacts()
        self._distributions: dict[Path, tuple[_Distribution, ...]] = {}
        self._entries: dict[Path, list[tuple[str, NominalSource]]] = {}
        self._sources: dict[tuple[Path, bool], _DistributionSources] = {}
        self._scopes: dict[tuple[Path, bool], NominalScope] = {}
        self._directory_scopes: dict[tuple[Path, bool], NominalScope] = {}

    def literal_domains(self, owner: Path, *, project: ProjectIndexSet | None = None) -> LiteralDomainIndex:
        return self._distribution_sources(owner, project, include_generated=False).literal_domains

    def sources(
        self,
        path: Path,
        first_party: FirstPartyFacts,
        *,
        include_generated: bool = False,
        project: ProjectIndexSet | None = None,
    ) -> dict[str, NominalSource]:
        return self.scope(path, first_party, include_generated=include_generated, project=project).sources

    def scope(
        self,
        path: Path,
        first_party: FirstPartyFacts,
        *,
        include_generated: bool = False,
        project: ProjectIndexSet | None = None,
    ) -> NominalScope:
        try:
            path = path.resolve()
        except OSError:
            return NominalScope(())
        key = (path.parent, include_generated)
        if key not in self._directory_scopes:
            self._directory_scopes[key] = self._scope(
                path, first_party, include_generated=include_generated, project=project
            )
        return self._directory_scopes[key]

    def _scope(
        self, path: Path, first_party: FirstPartyFacts, *, include_generated: bool, project: ProjectIndexSet | None
    ) -> NominalScope:
        owner = distribution_root(path, facts=first_party)
        root = first_party.project_root(path)
        if owner is None or root is None:
            return NominalScope(())
        key = (owner, include_generated)
        if key in self._scopes:
            return self._scopes[key]
        distributions = self._accessible_distributions(owner, root)
        scope = NominalScope(
            tuple(
                self._distribution_sources(distribution.root, project, include_generated=include_generated)
                for distribution in distributions
            )
        )
        self._scopes[key] = scope
        return scope

    def owns_source(self, path: Path, source: Path, first_party: FirstPartyFacts) -> bool:
        owner = distribution_root(path, facts=first_party)
        root = first_party.project_root(path)
        target = distribution_root(source, facts=first_party)
        if owner is None or root is None or target is None:
            return False
        return any(distribution.root == target for distribution in self._accessible_distributions(owner, root))

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

    def _distribution_sources(
        self, root: Path, project: ProjectIndexSet | None, *, include_generated: bool
    ) -> _DistributionSources:
        key = (root, include_generated)
        if key not in self._sources:
            if root not in self._entries:
                self._entries[root] = _source_entries(root, project)
            self._sources[key] = _DistributionSources(
                self._entries[root], self._generated_paths, include_generated=include_generated
            )
        return self._sources[key]


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


def _workspace(
    root: Path,
    document: dict[  # sarj-noqa: SARJ528 -- preserve unchecked TOML children while the cursor validates each nested table.
        object, object
    ],
) -> _Workspace | None:
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


def _raise_walk_error(error: OSError) -> Never:
    raise error


def _files(root: Path, pattern: str, *, distribution_only: bool = False) -> list[Path]:
    found: list[Path] = []
    try:
        for count, (directory, directories, filenames) in enumerate(root.walk(on_error=_raise_walk_error)):
            if count >= _MAX_DIRECTORIES or len(found) >= _MAX_FILES:
                return []
            directories[:] = sorted(
                name
                for name in directories
                if not name.startswith(".")
                and name not in _SKIP
                and (not distribution_only or not has_distribution_marker(directory / name))
            )
            found.extend(directory / name for name in sorted(filenames) if Path(name).match(pattern))
            if len(found) > _MAX_FILES:
                return []
    except OSError:
        return []
    return found


def _source_entries(root: Path, project: ProjectIndexSet | None) -> list[tuple[str, NominalSource]]:
    sources: list[tuple[str, NominalSource]] = []
    total_bytes = 0
    for path in _files(root, "*.py", distribution_only=True):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_bytes += size
        if total_bytes > _MAX_TOTAL_BYTES:
            return []
        if size > _MAX_BYTES:
            continue
        module = _module_name(root, path)
        if not module:
            continue
        source = _source(path, project)
        if source is None:
            continue
        sources.append((module, source))
    return sources


def _module_name(root: Path, path: Path) -> str | None:
    relative = path.relative_to(root)
    parts = relative.parts[1:] if relative.parts[0] == "src" else relative.parts
    return ".".join(parts[:-1] if parts[-1] == "__init__.py" else (*parts[:-1], path.stem)) or None


def _source(path: Path, project: ProjectIndexSet | None) -> NominalSource | None:
    try:
        if path.is_symlink():
            return None
        text = read_python_source(path)
    except OSError, UnicodeError, SyntaxError:
        return None
    return NominalSource(path, text, parsed_tree(project, path, text) if project is not None else None)


def _is_mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)

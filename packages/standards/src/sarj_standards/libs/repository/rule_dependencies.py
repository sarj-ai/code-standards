from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.resources import as_file, files
import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, Literal, override

from pydantic import BaseModel, ConfigDict, Field, RootModel

from sarj_standards.libs.json_boundary import parse_json, parse_unique_json
from sarj_standards.libs.release.process import ProcessFailureError, ProcessInputRunner
from sarj_standards.libs.repository.immutable_git import MAX_MODULES, ImmutableGit


if TYPE_CHECKING:
    from pathlib import Path


_TS_SUFFIXES: Final = frozenset({".ts", ".tsx", ".js", ".mjs", ".cjs"})
type ModuleFingerprint = tuple[tuple[str, str], ...]


class _LockedParserPackage(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str
    version: str


class _ParserLock(BaseModel):
    model_config = ConfigDict(strict=True)
    lockfile_version: Literal[3] = Field(alias="lockfileVersion")
    packages: dict[str, object]


@dataclass(frozen=True, slots=True)
class _ParserPins:
    node: str
    package: str
    runtime: str


def _parser_pins(root: Path) -> _ParserPins:
    try:
        node = "v" + (root / ".node-version").read_text(encoding="utf-8").strip().removeprefix("v")
        locked = _ParserLock.model_validate(
            parse_unique_json((root / "packages/typescript/package-lock.json").read_text(encoding="utf-8"))
        )
        package = _LockedParserPackage.model_validate(locked.packages["node_modules/typescript"])
        runtime = _LockedParserPackage.model_validate(locked.packages["node_modules/@typescript/old"])
    except (OSError, UnicodeError, ValueError, KeyError) as error:
        msg = "rule comparison requires preinstalled Node/compiler matching authoring .node-version and package-lock.json; use documented repository setup"
        raise ValueError(msg) from error
    if package.name != "@typescript/typescript6" or runtime.name != "typescript":
        msg = "rule comparison requires the locked @typescript/typescript6 compiler and its typescript runtime"
        raise ValueError(msg)
    return _ParserPins(node, package.version, runtime.version)


class _ImportReference(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    specifier: str
    resolved: str | None


class _ModuleReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    error: str | None
    imports: list[_ImportReference]


class _ParserReport(RootModel[dict[str, _ModuleReport]]):
    model_config = ConfigDict(strict=True)


@dataclass(frozen=True, slots=True)
class _ImportFacts:
    proven: dict[str, str]
    shadowed: frozenset[str]
    mutated_attributes: dict[str, frozenset[str]]


class RuleDependencies:
    def __init__(
        self,
        snapshot: ImmutableGit,
        authored_sources: frozenset[str],
        *,
        parser_runner: ProcessInputRunner,
        owned_roots: frozenset[str],
    ) -> None:
        self.snapshot = snapshot
        self.authored_sources = authored_sources
        self.authored_leaves = frozenset(PurePosixPath(path).stem for path in authored_sources if path.endswith(".py"))
        self.modules: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.graph: dict[str, set[str]] = {}
        self.errors: dict[str, str] = dict(snapshot.encoding_errors)
        self.registries: set[str] = set()
        for path in snapshot.modules:
            if not path.endswith(".py"):
                continue
            name = (path.split("/src/", 1)[1] if "/src/" in path else path)[:-3].replace("/", ".")
            name = name.removesuffix(".__init__")
            if name in self.modules:
                msg = f"ambiguous immutable Python module: {name}"
                raise ValueError(msg)
            self.modules[name] = path
            self.names[path] = name
        self.roots = frozenset(name.split(".")[0] for name in self.modules)
        self.namespaces = frozenset(
            name.rsplit(".", level)[0] for name in self.modules for level in range(1, name.count(".") + 1)
        )
        for path, source in snapshot.modules.items():
            if path.endswith(".py"):
                self._python(path=path, source=source)
        if any(PurePosixPath(path).suffix in _TS_SUFFIXES for path in owned_roots):
            self._typescript(parser_runner)
        self._prepare_data_leaves(owned_roots)

    def _prepare_data_leaves(self, roots: frozenset[str]) -> None:
        pending = list(roots)
        seen: set[str] = set()
        leaves: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            if current.startswith("<missing>"):
                continue
            if PurePosixPath(current).suffix == ".json":
                leaves.add(current)
            else:
                pending.extend(self.graph.get(current, ()))
        if leaves:
            self.snapshot.read_blobs(sorted(leaves))

    def fingerprint(self, path: str) -> ModuleFingerprint:
        pending = [path]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            if current.startswith("<missing>"):
                msg = f"missing immutable local import: {current[9:]}"
                raise ValueError(msg)
            if current in self.errors:
                raise ValueError(self.errors[current])
            self.snapshot.oid(current)
            seen.add(current)
            if len(seen) > MAX_MODULES:
                msg = "immutable import closure exceeds module limit"
                raise ValueError(msg)
            pending.extend(self.graph.get(current, ()))
        return tuple(sorted((current, self.snapshot.oid(current)) for current in seen))

    def _qualified(self, name: str, context: str) -> str:
        if "/tests/" not in context:
            return name
        prefix = context.split("/tests/", 1)[0].replace("/", ".")
        if name == "tests" or name.startswith("tests."):
            return prefix + "." + name
        local = prefix + ".tests." + name
        return local if name.split(".", maxsplit=1)[0] not in self.roots and local in self.modules else name

    def _python(self, *, path: str, source: str) -> None:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            self.errors[path] = f"malformed immutable Python module: {path}"
            return
        collector = _PythonImports(tree)
        collector.visit(tree)
        module = self.names[path]
        package = module if PurePosixPath(path).name == "__init__.py" else module.rsplit(".", 1)[0]
        dependencies = self._resolve(module, path)
        dependencies.discard(path)
        for node in collector.imports:
            for name in self._python_names(node, package=package, path=path):
                dependencies.update(self._resolve(name, path))
        for name in collector.dynamic_names:
            dependencies.update(self._resolve(name, path))
        if _data_registry(tree, collector, self.authored_leaves):
            self.registries.add(path)
            dependencies.difference_update(self.authored_sources)
        self.graph[path] = dependencies

    def _python_names(self, node: ast.Import | ast.ImportFrom, *, package: str, path: str) -> list[str]:
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        if node.module == "__future__":
            return []
        name = _relative_name(node.module or "", node.level, package)
        if name is None:
            self.errors[path] = f"invalid relative immutable Python import: {path}"
            return []
        names = [name]
        names.extend(
            name + "." + alias.name
            for alias in node.names
            if self._qualified(name + "." + alias.name, path) in self.modules
        )
        return names

    def _resolve(self, name: str, context: str) -> set[str]:
        name = self._qualified(name, context)
        if name not in self.modules and name not in self.namespaces:
            return {"<missing>" + name} if name.split(".")[0] in self.roots else set()
        targets: set[str] = set()
        pieces = name.split(".")
        for length in range(1, len(pieces) + 1):
            target = self.modules.get(".".join(pieces[:length]))
            if target is not None:
                targets.add(target)
        return targets

    def _typescript(self, runner: ProcessInputRunner) -> None:
        sources = {
            path: source for path, source in self.snapshot.modules.items() if PurePosixPath(path).suffix in _TS_SUFFIXES
        }
        if not sources:
            return
        compiler = self.snapshot.root / "packages/typescript/node_modules/typescript/lib/typescript.js"
        pins = _parser_pins(self.snapshot.root)
        prerequisite = f"rule comparison requires preinstalled Node {pins.node} and locked @typescript/typescript6 {pins.package} (compiler {pins.runtime}); use documented repository setup; no automatic installation or fallback"
        if not compiler.is_file():
            raise ValueError(prerequisite)
        resource = files("sarj_standards.libs.repository").joinpath("rule_imports.cjs")
        try:
            with as_file(resource) as frontend:
                result = runner(
                    ("node", str(frontend), str(compiler), pins.node, pins.package, pins.runtime),
                    cwd=self.snapshot.root,
                    input_text=json.dumps(sources),
                )
        except (FileNotFoundError, ProcessFailureError) as error:
            raise ValueError(prerequisite) from error
        if result.returncode != 0:
            raise ValueError(prerequisite)
        reports = _ParserReport.model_validate(parse_json(result.stdout)).root
        if set(reports) != set(sources):
            msg = "TypeScript frontend returned invalid module ownership map"
            raise ValueError(msg)
        for path, report in reports.items():
            self.graph[path] = self._typescript_dependencies(path, report)

    def _typescript_dependencies(self, path: str, report: _ModuleReport) -> set[str]:
        if report.error is not None:
            self.errors[path] = report.error
            return set()
        dependencies: set[str] = set()
        for reference in report.imports:
            if not reference.specifier.startswith("."):
                continue
            if reference.resolved is None:
                self.errors[path] = f"missing immutable TypeScript import: {path} {reference.specifier}"
                continue
            if PurePosixPath(reference.resolved).suffix == ".json":
                dependencies.add(reference.resolved)
                continue
            if reference.resolved not in self.snapshot.modules:
                msg = "TypeScript frontend returned escaping or missing module"
                raise ValueError(msg)
            dependencies.add(reference.resolved)
        return dependencies


def _relative_name(name: str, level: int, package: str) -> str | None:
    if not level:
        return name
    pieces = package.split(".")
    if level > len(pieces):
        return None
    prefix = ".".join(pieces[: len(pieces) - level + 1])
    return ".".join(part for part in (prefix, name) if part)


class _PythonImports(ast.NodeVisitor):
    def __init__(self, tree: ast.Module) -> None:
        facts = _bindings(tree)
        self.bindings = facts.proven
        self.shadowed = facts.shadowed
        self.mutated_attributes = facts.mutated_attributes
        self.imports: list[ast.Import | ast.ImportFrom] = []
        self.dynamic_names: set[str] = set()

    @override
    def visit_If(self, node: ast.If) -> None:
        guard = self._target(node.test)
        if guard == "typing.TYPE_CHECKING":
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    @override
    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append(node)

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append(node)

    @override
    def visit_Call(self, node: ast.Call) -> None:
        name = self._dynamic_name(node)
        if name is not None:
            self.dynamic_names.add(name)
        self.generic_visit(node)

    def _dynamic_name(self, node: ast.Call) -> str | None:
        if not node.args:
            return None
        builtin = isinstance(node.func, ast.Name) and node.func.id == "__import__" and "__import__" not in self.shadowed
        if self._target(node.func) != "importlib.import_module" and not builtin:
            return None
        name = _literal(node.args[0])
        if name is None:
            return None
        if builtin and any(
            keyword.arg == "level" and not (isinstance(keyword.value, ast.Constant) and keyword.value.value == 0)
            for keyword in node.keywords
        ):
            return None
        package = _package_argument(node) if not builtin else None
        level = len(name) - len(name.lstrip("."))
        if level and package is None:
            return None
        return _relative_name(name.lstrip("."), level, package or "") if level else name

    def _target(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.attr in self.mutated_attributes.get(node.value.id, frozenset()):
                return None
            target = self.bindings.get(node.value.id)
            return target + "." + node.attr if target is not None else None
        return None


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _package_argument(node: ast.Call) -> str | None:
    for keyword in node.keywords:
        if keyword.arg == "package":
            return _literal(keyword.value)
    return _literal(node.args[1]) if len(node.args) > 1 else None


def _bindings(tree: ast.Module) -> _ImportFacts:
    bindings: dict[str, str] = {}
    counts: dict[str, int] = {}
    overwritten: set[str] = set()
    mutated_attributes: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        match node:
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                overwritten.add(name)
            case ast.Attribute(value=ast.Name(id=owner), attr=attribute, ctx=ast.Store() | ast.Del()):
                mutated_attributes.setdefault(owner, set()).add(attribute)
            case ast.Import() | ast.ImportFrom():
                targets = _import_bindings(node)
                for name in targets:
                    counts[name] = counts.get(name, 0) + 1
                if node in tree.body:
                    bindings.update(targets)
            case _:
                pass
    proven = {name: target for name, target in bindings.items() if counts[name] == 1 and name not in overwritten}
    return _ImportFacts(
        proven,
        frozenset(overwritten | set(counts)),
        {owner: frozenset(attributes) for owner, attributes in mutated_attributes.items()},
    )


def _import_bindings(node: ast.Import | ast.ImportFrom) -> dict[str, str]:
    if isinstance(node, ast.Import):
        return {
            alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0]
            for alias in node.names
        }
    return {alias.asname or alias.name: (node.module or "") + "." + alias.name for alias in node.names}


def _data_registry(tree: ast.Module, collector: _PythonImports, leaves: frozenset[str]) -> bool:
    rule_names = _registry_names(collector.imports, leaves)
    registration = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            registration |= any(_rule_id_key(key, rule_names) for key in node.keys)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return False
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Name) and collector.bindings.get(node.func.id) == "types.MappingProxyType"
        ):
            return False
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in rule_names
            and node.attr != "id"
        ):
            return False
    return registration


def _registry_names(imports: list[ast.Import | ast.ImportFrom], leaves: frozenset[str]) -> set[str]:
    rule_names: set[str] = set()
    for imported in imports:
        if isinstance(imported, ast.ImportFrom) and (imported.module or "").rsplit(".", 1)[-1] in leaves:
            rule_names.update(alias.asname or alias.name for alias in imported.names)
    return rule_names


def _rule_id_key(node: ast.expr | None, rule_names: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "id"
        and isinstance(node.value, ast.Name)
        and node.value.id in rule_names
    )

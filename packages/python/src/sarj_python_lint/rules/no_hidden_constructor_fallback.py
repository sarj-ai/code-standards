from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._first_party import distribution_root
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator


_MIGRATION_PARTS = frozenset({"alembic", "migration", "migrations", "versions"})
_DESCRIPTOR_DECORATORS = frozenset({"classmethod", "staticmethod"})
_QUALIFIED_NAME_PARTS = 2
_SCAN_SKIP_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".uv-cache",
        ".venv",
        "build",
        "dist",
        "generated",
        "node_modules",
        "site-packages",
        "vendor",
        "venv",
    }
)


@dataclass(frozen=True, slots=True)
class _Binding:
    module: str
    symbol: str | None


@dataclass(frozen=True, slots=True)
class _HiddenParameter:
    parameter: ast.arg
    uses_boolean_or: bool


class _LoadedModule(NamedTuple):
    tree: ast.Module
    path: Path


class _CanonicalSymbol(NamedTuple):
    module: str
    symbol: str


@final
class NoHiddenConstructorFallback(Rule):
    id = "no-hidden-constructor-fallback"
    code = "SARJ095"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Constructor option silently falls back to application settings when omitted.",
        rationale="Hidden configuration lookup obscures dependencies and makes construction vary with ambient application state.",
        remediation="Require the constructor argument and resolve any default at the composition root or call site.",
        category=RuleCategory.ARCHITECTURE,
        limitations=(
            "Detection requires a proven local settings provider, a keyword-only optional parameter, and a first-party composition call.",
            "Tests, generated files, migrations, descriptors, library environment fallbacks, and unconstructed classes are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="ambient-settings-fallback",
                title="Constructor reads an implicit default from settings",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("pyproject.toml", "[project]\nname = 'example'\nversion = '0.1.0'\n"),
                    ExampleFile.python("app/__init__.py", "\n"),
                    ExampleFile.python(
                        "app/config.py",
                        "from pydantic_settings import BaseSettings\n"
                        "class Settings(BaseSettings):\n"
                        "    MODEL: str = 'model'\n"
                        "settings = Settings()\n",
                    ),
                    ExampleFile.python(
                        "app/service.py",
                        "from app.config import settings\n\n"
                        "class Generator:\n"
                        "    def __init__(self, *, model: str | None = None) -> None:\n"
                        "        self.model = model or settings.MODEL\n\n"
                        "generator = Generator(model='explicit')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-constructor-dependency",
                title="Constructor requires its dependency",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("pyproject.toml", "[project]\nname = 'example'\nversion = '0.1.0'\n"),
                    ExampleFile.python("app/__init__.py", "\n"),
                    ExampleFile.python(
                        "app/config.py",
                        "from pydantic_settings import BaseSettings\n"
                        "class Settings(BaseSettings):\n"
                        "    MODEL: str = 'model'\n"
                        "settings = Settings()\n",
                    ),
                    ExampleFile.python(
                        "app/service.py",
                        "class Generator:\n"
                        "    def __init__(self, *, model: str) -> None:\n"
                        "        self.model = model\n\n"
                        "generator = Generator(model='explicit')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_generated(path, source)
            or any(part.lower() in _MIGRATION_PARTS for part in path.parts)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        resolver = _RuntimeConfigResolver(path, tree)
        diagnostics: list[Diagnostic] = []
        for class_node in nodes(tree, ast.ClassDef):
            init = next(
                (
                    statement
                    for statement in reversed(class_node.body)
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == "__init__"
                ),
                None,
            )
            if init is None or _is_descriptor(init):
                continue
            hidden = _hidden_parameters(init, resolver)
            if not hidden or not _has_composition_call(path, class_node.name):
                continue
            names = ", ".join(f"`{match.parameter.arg}`" for match in hidden)
            noun = "parameter" if len(hidden) == 1 else "parameters"
            verb = "falls" if len(hidden) == 1 else "fall"
            falsey_warning = (
                " A boolean `or` also treats explicit falsey values as omitted."
                if any(match.uses_boolean_or for match in hidden)
                else ""
            )
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=hidden[0].parameter.lineno,
                    col=hidden[0].parameter.col_offset + 1,
                    code=self.code,
                    message=(
                        f"Constructor {noun} {names} {verb} back to application settings when omitted; "
                        "make the argument required and resolve the fallback at the call site or composition root."
                        f"{falsey_warning}"
                    ),
                    severity=Severity.WARNING,
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _is_descriptor(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_tail(decorator) in _DESCRIPTOR_DECORATORS for decorator in node.decorator_list)


def _hidden_parameters(
    init: ast.FunctionDef | ast.AsyncFunctionDef,
    resolver: _RuntimeConfigResolver,
) -> list[_HiddenParameter]:
    candidates = {
        parameter.arg: parameter
        for parameter, default in zip(init.args.kwonlyargs, init.args.kw_defaults, strict=True)
        if isinstance(default, ast.Constant) and default.value is None
    }
    if not candidates:
        return []

    hidden: dict[str, bool] = {}
    rebound: set[str] = set()
    # Python decides every local binding for the whole function before it
    # executes. Seed the resolver with that complete scope so a branch-local
    # `settings = ...` cannot be mistaken for the imported settings object.
    shadowed = set(_scope_bindings(init))
    for statement in init.body:
        available = candidates.keys() - rebound
        for name, uses_boolean_or in _statement_fallbacks(statement, available, resolver, shadowed).items():
            hidden[name] = hidden.get(name, False) or uses_boolean_or
        rebound.update(_directly_bound_names(statement) & candidates.keys())
        shadowed.update(_directly_bound_names(statement))
    return [_HiddenParameter(parameter, hidden[name]) for name, parameter in candidates.items() if name in hidden]


def _statement_fallbacks(
    statement: ast.stmt,
    candidates: set[str],
    resolver: _RuntimeConfigResolver,
    shadowed: set[str],
) -> dict[str, bool]:
    if isinstance(statement, ast.Assign):
        return _expression_fallbacks(statement.value, candidates, resolver, shadowed)
    if isinstance(statement, ast.AnnAssign) and statement.value is not None:
        return _expression_fallbacks(statement.value, candidates, resolver, shadowed)
    if not isinstance(statement, ast.If) or statement.orelse or len(statement.body) != 1:
        return {}
    parameter = _none_comparison_parameter(statement.test, candidates, expect_not=False)
    if parameter is None:
        return {}
    body = statement.body[0]
    if isinstance(body, ast.Assign):
        value = body.value if len(body.targets) == 1 and _is_name(body.targets[0], parameter) else None
    elif isinstance(body, ast.AnnAssign):
        value = body.value if _is_name(body.target, parameter) else None
    else:
        value = None
    return {parameter: False} if value is not None and resolver.is_runtime_config(value, shadowed) else {}


def _expression_fallbacks(
    expression: ast.expr,
    candidates: set[str],
    resolver: _RuntimeConfigResolver,
    shadowed: set[str],
) -> dict[str, bool]:
    if isinstance(expression, ast.BoolOp) and isinstance(expression.op, ast.Or):
        match expression.values:
            case [ast.Name(id=parameter), fallback] if parameter in candidates:
                return {parameter: True} if resolver.is_runtime_config(fallback, shadowed) else {}
            case _:
                return {}
    if not isinstance(expression, ast.IfExp):
        return {}
    not_none = _none_comparison_parameter(expression.test, candidates, expect_not=True)
    if (
        not_none is not None
        and isinstance(expression.body, ast.Name)
        and expression.body.id == not_none
        and resolver.is_runtime_config(expression.orelse, shadowed)
    ):
        return {not_none: False}
    is_none = _none_comparison_parameter(expression.test, candidates, expect_not=False)
    if (
        is_none is not None
        and isinstance(expression.orelse, ast.Name)
        and expression.orelse.id == is_none
        and resolver.is_runtime_config(expression.body, shadowed)
    ):
        return {is_none: False}
    return {}


def _none_comparison_parameter(test: ast.expr, candidates: set[str], *, expect_not: bool) -> str | None:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return None
    operator = test.ops[0]
    if expect_not != isinstance(operator, ast.IsNot):
        return None
    if not isinstance(operator, (ast.Is, ast.IsNot)):
        return None
    pairs = ((test.left, test.comparators[0]), (test.comparators[0], test.left))
    return next(
        (
            name.id
            for name, none_value in pairs
            if isinstance(name, ast.Name)
            and name.id in candidates
            and isinstance(none_value, ast.Constant)
            and none_value.value is None
        ),
        None,
    )


def _directly_bound_names(statement: ast.stmt) -> set[str]:
    match statement:
        case ast.Assign(targets=targets):
            return {name for target in targets for name in _target_names(target)}
        case ast.AnnAssign(target=target):
            return _target_names(target)
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return {statement.name}
        case _:
            return set()


def _argument_names(arguments: ast.arguments) -> set[str]:
    names = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _target_names(element)}
    return set()


def _is_name(expression: ast.expr, name: str) -> bool:
    return isinstance(expression, ast.Name) and expression.id == name


@final
class _RuntimeConfigResolver:
    def __init__(self, path: Path, tree: ast.Module) -> None:
        self._path = path
        self._tree = tree
        self._root = distribution_root(path)
        self._module = _module_name(path, self._root)
        self._imports = _imports(tree, self._module, is_package=path.name == "__init__.py")
        self._settings_cache: dict[tuple[str, str], bool] = {}
        self._settings_class_cache: dict[tuple[str, str], bool] = {}

    def is_runtime_config(self, expression: ast.expr, shadowed: set[str]) -> bool:
        return self._is_settings_attribute(expression, shadowed)

    def _is_settings_attribute(self, expression: ast.expr, shadowed: set[str]) -> bool:
        parts = _attribute_parts(expression)
        if parts is None or len(parts) < _QUALIFIED_NAME_PARTS:
            return False
        if parts[0] in shadowed:
            return False
        resolved = _resolve_expression(expression, self._imports)
        if resolved is None:
            if self._module is None:
                return False
            resolved = (*self._module.split("."), *parts)
        for symbol_index in range(len(resolved) - 2, 0, -1):
            module = ".".join(resolved[:symbol_index])
            symbol = resolved[symbol_index]
            if self._is_settings_symbol(module, symbol):
                return True
        return False

    def _is_settings_symbol(self, module: str, symbol: str, seen: frozenset[tuple[str, str]] = frozenset()) -> bool:
        key = (module, symbol)
        cached = self._settings_cache.get(key)
        if cached is not None:
            return cached
        if key in seen:
            return False
        loaded = self._load_module(module)
        if loaded is None:
            self._settings_cache[key] = False
            return False
        tree = loaded.tree
        module_path = loaded.path
        imports = _imports(tree, module, is_package=module_path.name == "__init__.py")
        classes = _base_settings_classes(tree, imports)
        factory = _assigned_factory(tree, symbol)
        if factory is not None:
            resolved_factory = _resolve_expression(factory, imports)
            if isinstance(factory, ast.Name) and factory.id in classes:
                self._settings_cache[key] = True
                return True
            if resolved_factory is not None and len(resolved_factory) >= _QUALIFIED_NAME_PARTS:
                factory_module = ".".join(resolved_factory[:-1])
                if self._is_settings_class(factory_module, resolved_factory[-1]):
                    self._settings_cache[key] = True
                    return True
        binding = imports.get(symbol)
        result = (
            binding is not None
            and binding.symbol is not None
            and self._is_settings_symbol(binding.module, binding.symbol, seen | {key})
        )
        del module_path
        self._settings_cache[key] = result
        return result

    def _is_settings_class(
        self,
        module: str,
        symbol: str,
        seen: frozenset[tuple[str, str]] = frozenset(),
    ) -> bool:
        key = (module, symbol)
        cached = self._settings_class_cache.get(key)
        if cached is not None:
            return cached
        if key in seen:
            return False
        loaded = self._load_module(module)
        if loaded is None:
            self._settings_class_cache[key] = False
            return False
        tree = loaded.tree
        module_path = loaded.path
        imports = _imports(tree, module, is_package=module_path.name == "__init__.py")
        if symbol in _base_settings_classes(tree, imports):
            self._settings_class_cache[key] = True
            return True
        class_node = next(
            (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == symbol),
            None,
        )
        result = False
        if class_node is not None:
            for base in class_node.bases:
                resolved = _resolve_expression(base, imports)
                if resolved is None or len(resolved) < _QUALIFIED_NAME_PARTS:
                    continue
                base_module, base_symbol = ".".join(resolved[:-1]), resolved[-1]
                if self._is_settings_class(base_module, base_symbol, seen | {key}):
                    result = True
                    break
        self._settings_class_cache[key] = result
        return result

    def _load_module(self, module: str) -> _LoadedModule | None:
        if module == self._module:
            return _LoadedModule(self._tree, self._path)
        path = _module_path(module, self._root)
        if path is None:
            return None
        return _LoadedModule(_read_module(path), path)


def _imports(tree: ast.Module, current_module: str | None, *, is_package: bool = False) -> dict[str, _Binding]:
    bindings: dict[str, _Binding] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                bound = alias.asname or alias.name.partition(".")[0]
                module = alias.name if alias.asname else alias.name.partition(".")[0]
                bindings[bound] = _Binding(module, None)
        elif isinstance(statement, ast.ImportFrom):
            module = _absolute_module(statement, current_module, is_package=is_package)
            if module is None:
                continue
            for alias in statement.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = _Binding(module, alias.name)
        else:
            for name in _directly_bound_names(statement):
                bindings.pop(name, None)
    return bindings


def _absolute_module(node: ast.ImportFrom, current_module: str | None, *, is_package: bool) -> str | None:
    if node.level == 0:
        return node.module
    if current_module is None:
        return None
    package = current_module.split(".") if is_package else current_module.split(".")[:-1]
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return None
    suffix = node.module.split(".") if node.module else []
    return ".".join([*package[:keep], *suffix])


def _resolve_expression(expression: ast.expr, imports: dict[str, _Binding]) -> tuple[str, ...] | None:
    parts = _attribute_parts(expression)
    if parts is None:
        return None
    binding = imports.get(parts[0])
    if binding is None:
        return None
    prefix = (*binding.module.split("."),) if binding.symbol is None else (*binding.module.split("."), binding.symbol)
    return (*prefix, *parts[1:])


def _attribute_parts(expression: ast.expr) -> tuple[str, ...] | None:
    if isinstance(expression, ast.Name):
        return (expression.id,)
    if isinstance(expression, ast.Attribute):
        parent = _attribute_parts(expression.value)
        return (*parent, expression.attr) if parent is not None else None
    return None


def _base_settings_classes(tree: ast.Module, imports: dict[str, _Binding]) -> set[str]:
    classes = [statement for statement in tree.body if isinstance(statement, ast.ClassDef)]
    found = {
        node.name
        for node in classes
        if any(_resolve_expression(base, imports) == ("pydantic_settings", "BaseSettings") for base in node.bases)
    }
    changed = True
    while changed:
        changed = False
        for node in classes:
            if node.name not in found and any(isinstance(base, ast.Name) and base.id in found for base in node.bases):
                found.add(node.name)
                changed = True
    return found


def _assigned_factory(tree: ast.Module, symbol: str) -> ast.expr | None:
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        else:
            continue
        if value is not None and isinstance(value, ast.Call) and any(_is_name(target, symbol) for target in targets):
            return value.func
    return None


def _module_name(path: Path, root: Path | None) -> str | None:
    if root is None:
        return None
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    source_root = resolved_root / "src"
    try:
        relative = resolved_path.relative_to(source_root)
        is_package_root = False
    except ValueError:
        try:
            relative = resolved_path.relative_to(resolved_root)
        except ValueError:
            return None
        is_package_root = (resolved_root / "__init__.py").is_file()
    except OSError:
        return None
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if is_package_root:
        parts.insert(0, root.name)
    return ".".join(parts) if parts else None


def _module_path(module: str, root: Path | None) -> Path | None:
    if root is None:
        return None
    parts = module.split(".")
    if (root / "__init__.py").is_file() and parts and parts[0] == root.name:
        parts = parts[1:]
    roots = (root, root / "src")
    relatives = (source_root.joinpath(*parts) for source_root in roots)
    candidates = (
        candidate for relative in relatives for candidate in (relative.with_suffix(".py"), relative / "__init__.py")
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


@lru_cache(maxsize=4096)
def _read_module(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except OSError, SyntaxError:
        return ast.Module(body=[], type_ignores=[])


def _tail(expression: ast.expr) -> str | None:
    parts = _attribute_parts(expression)
    return parts[-1] if parts else None


def _has_composition_call(path: Path, class_name: str) -> bool:
    root = distribution_root(path)
    module = _module_name(path, root)
    if root is None or module is None:
        return False
    return _distribution_calls_class(root, module, class_name)


@lru_cache(maxsize=1024)
def _distribution_calls_class(root: Path, target_module: str, class_name: str) -> bool:
    skip_directories = _SCAN_SKIP_PARTS | _MIGRATION_PARTS | {"test", "tests"}
    for directory, directory_names, file_names in os.walk(root):
        directory_names[:] = [name for name in directory_names if name.lower() not in skip_directories]
        for file_name in file_names:
            if not file_name.endswith(".py"):
                continue
            candidate = Path(directory) / file_name
            if is_test_path(candidate):
                continue
            try:
                source = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if class_name not in source or is_generated(candidate, source):
                continue
            try:
                tree = ast.parse(source, filename=str(candidate))
            except SyntaxError:
                continue
            module = _module_name(candidate, root)
            if module is None:
                continue
            imports = _imports(tree, module, is_package=candidate.name == "__init__.py")
            for node, shadowed in _calls_with_shadowing(tree):
                parts = _attribute_parts(node.func)
                if parts is not None and parts[0] in shadowed:
                    continue
                resolved = _resolve_expression(node.func, imports)
                if resolved is None and isinstance(node.func, ast.Name):
                    called_module, called_symbol = module, node.func.id
                elif resolved is not None and len(resolved) >= _QUALIFIED_NAME_PARTS:
                    called_module, called_symbol = ".".join(resolved[:-1]), resolved[-1]
                else:
                    continue
                if called_symbol != class_name:
                    continue
                canonical = _canonical_symbol(root, called_module, called_symbol)
                if canonical == _CanonicalSymbol(target_module, class_name):
                    return True
    return False


@lru_cache(maxsize=4096)
def _canonical_symbol(root: Path, module: str, symbol: str) -> _CanonicalSymbol:
    return _canonical_symbol_inner(root, module, symbol, frozenset())


def _canonical_symbol_inner(
    root: Path,
    module: str,
    symbol: str,
    seen: frozenset[tuple[str, str]],
) -> _CanonicalSymbol:
    key = (module, symbol)
    if key in seen:
        return _CanonicalSymbol(module, symbol)
    path = _module_path(module, root)
    if path is None:
        return _CanonicalSymbol(module, symbol)
    binding = _imports(_read_module(path), module, is_package=path.name == "__init__.py").get(symbol)
    if binding is None or binding.symbol is None:
        return _CanonicalSymbol(module, symbol)
    return _canonical_symbol_inner(root, binding.module, binding.symbol, seen | {key})


def _calls_with_shadowing(
    node: ast.AST,
    shadowed: frozenset[str] = frozenset(),
    nested_scope_base: frozenset[str] | None = None,
) -> Iterator[tuple[ast.Call, frozenset[str]]]:
    match node:
        case ast.ListComp() | ast.SetComp() | ast.GeneratorExp():
            lexical_parent = nested_scope_base if nested_scope_base is not None else shadowed
            comprehension_shadowed = lexical_parent
            for index, generator in enumerate(node.generators):
                iterable_shadowed = shadowed if index == 0 else comprehension_shadowed
                yield from _calls_with_shadowing(generator.iter, iterable_shadowed)
                comprehension_shadowed |= frozenset(_target_names(generator.target))
                for condition in generator.ifs:
                    yield from _calls_with_shadowing(condition, comprehension_shadowed)
            yield from _calls_with_shadowing(node.elt, comprehension_shadowed)
            return
        case ast.DictComp(generators=generators, key=key, value=value):
            lexical_parent = nested_scope_base if nested_scope_base is not None else shadowed
            comprehension_shadowed = lexical_parent
            for index, generator in enumerate(generators):
                iterable_shadowed = shadowed if index == 0 else comprehension_shadowed
                yield from _calls_with_shadowing(generator.iter, iterable_shadowed)
                comprehension_shadowed |= frozenset(_target_names(generator.target))
                for condition in generator.ifs:
                    yield from _calls_with_shadowing(condition, comprehension_shadowed)
            yield from _calls_with_shadowing(key, comprehension_shadowed)
            yield from _calls_with_shadowing(value, comprehension_shadowed)
            return
        case ast.Lambda(args=args, body=body):
            outer_nodes = [*args.defaults, *(default for default in args.kw_defaults if default is not None)]
            for outer in outer_nodes:
                yield from _calls_with_shadowing(outer, shadowed, nested_scope_base)
            lexical_parent = nested_scope_base if nested_scope_base is not None else shadowed
            yield from _calls_with_shadowing(body, lexical_parent | _scope_bindings(node))
            return
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            outer_nodes = [
                *node.decorator_list,
                *node.args.defaults,
                *(default for default in node.args.kw_defaults if default is not None),
            ]
            for outer in outer_nodes:
                yield from _calls_with_shadowing(outer, shadowed, nested_scope_base)
            lexical_parent = nested_scope_base if nested_scope_base is not None else shadowed
            local_shadowed = lexical_parent | _scope_bindings(node)
            for statement in node.body:
                yield from _calls_with_shadowing(statement, local_shadowed)
            return
        case ast.ClassDef(decorator_list=decorators, bases=bases, keywords=keywords, body=body):
            for outer in (*decorators, *bases, *keywords):
                yield from _calls_with_shadowing(outer, shadowed, nested_scope_base)
            lexical_parent = nested_scope_base if nested_scope_base is not None else shadowed
            class_shadowed = lexical_parent | _class_bindings(node)
            for statement in body:
                yield from _calls_with_shadowing(statement, class_shadowed, lexical_parent)
            return
        case ast.Call():
            yield node, shadowed
        case _:
            pass
    for child in ast.iter_child_nodes(node):
        yield from _calls_with_shadowing(child, shadowed, nested_scope_base)


def _scope_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> frozenset[str]:
    collector = _LocalBindingCollector()
    for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
        collector.names.add(argument.arg)
    if node.args.vararg is not None:
        collector.names.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        collector.names.add(node.args.kwarg.arg)
    body = [node.body] if isinstance(node, ast.Lambda) else node.body
    for statement in body:
        collector.visit(statement)
    return frozenset(collector.names - collector.globals)


def _class_bindings(node: ast.ClassDef) -> frozenset[str]:
    collector = _LocalBindingCollector()
    for statement in node.body:
        collector.visit(statement)
    return frozenset(collector.names)


class _LocalBindingCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.globals: set[str] = set()

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    @override
    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    @override
    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    @override
    def visit_ListComp(self, node: ast.ListComp) -> None:
        del node

    @override
    def visit_SetComp(self, node: ast.SetComp) -> None:
        del node

    @override
    def visit_DictComp(self, node: ast.DictComp) -> None:
        del node

    @override
    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        del node

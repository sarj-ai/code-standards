"""SARJ095 — Constructor options must not hide runtime configuration fallback.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_hidden_constructor_fallback.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._first_party import distribution_root
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


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


@final
class NoHiddenConstructorFallback(Rule):
    id = "no-hidden-constructor-fallback"
    code = "SARJ095"
    description = (
        "A keyword-only constructor option defaults to `None` and silently resolves from application settings."
    )

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
                    for statement in class_node.body
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == "__init__"
                ),
                None,
            )
            if init is None or _is_descriptor(init):
                continue
            hidden = _hidden_parameters(init, resolver)
            if not hidden or not _has_composition_call(path, class_node.name):
                continue
            names = ", ".join(f"`{parameter.arg}`" for parameter in hidden)
            noun = "parameter" if len(hidden) == 1 else "parameters"
            verb = "falls" if len(hidden) == 1 else "fall"
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=hidden[0].lineno,
                    col=hidden[0].col_offset + 1,
                    code=self.code,
                    message=(
                        f"Constructor {noun} {names} {verb} back to application settings when omitted; "
                        "make the argument required and resolve the fallback at the call site or composition root. "
                        "A boolean `or` also treats explicit falsey values as omitted."
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
) -> list[ast.arg]:
    candidates = {
        parameter.arg: parameter
        for parameter, default in zip(init.args.kwonlyargs, init.args.kw_defaults, strict=True)
        if isinstance(default, ast.Constant) and default.value is None
    }
    if not candidates:
        return []

    hidden: set[str] = set()
    rebound: set[str] = set()
    shadowed = _argument_names(init.args)
    for statement in init.body:
        available = candidates.keys() - rebound
        hidden.update(_statement_fallbacks(statement, available, resolver, shadowed))
        rebound.update(_directly_bound_names(statement) & candidates.keys())
        shadowed.update(_directly_bound_names(statement))
    return [parameter for name, parameter in candidates.items() if name in hidden]


def _statement_fallbacks(
    statement: ast.stmt,
    candidates: set[str],
    resolver: _RuntimeConfigResolver,
    shadowed: set[str],
) -> set[str]:
    if isinstance(statement, ast.Assign):
        return _expression_fallbacks(statement.value, candidates, resolver, shadowed)
    if isinstance(statement, ast.AnnAssign) and statement.value is not None:
        return _expression_fallbacks(statement.value, candidates, resolver, shadowed)
    if not isinstance(statement, ast.If) or statement.orelse or len(statement.body) != 1:
        return set()
    parameter = _none_comparison_parameter(statement.test, candidates, expect_not=False)
    if parameter is None:
        return set()
    body = statement.body[0]
    if isinstance(body, ast.Assign):
        value = body.value if len(body.targets) == 1 and _is_name(body.targets[0], parameter) else None
    elif isinstance(body, ast.AnnAssign):
        value = body.value if _is_name(body.target, parameter) else None
    else:
        value = None
    return {parameter} if value is not None and resolver.is_runtime_config(value, shadowed) else set()


def _expression_fallbacks(
    expression: ast.expr,
    candidates: set[str],
    resolver: _RuntimeConfigResolver,
    shadowed: set[str],
) -> set[str]:
    if isinstance(expression, ast.BoolOp) and isinstance(expression.op, ast.Or):
        match expression.values:
            case [ast.Name(id=parameter), fallback] if parameter in candidates:
                return {parameter} if resolver.is_runtime_config(fallback, shadowed) else set()
            case _:
                return set()
    if not isinstance(expression, ast.IfExp):
        return set()
    not_none = _none_comparison_parameter(expression.test, candidates, expect_not=True)
    if (
        not_none is not None
        and isinstance(expression.body, ast.Name)
        and expression.body.id == not_none
        and resolver.is_runtime_config(expression.orelse, shadowed)
    ):
        return {not_none}
    is_none = _none_comparison_parameter(expression.test, candidates, expect_not=False)
    if (
        is_none is not None
        and isinstance(expression.orelse, ast.Name)
        and expression.orelse.id == is_none
        and resolver.is_runtime_config(expression.body, shadowed)
    ):
        return {is_none}
    return set()


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
    if isinstance(statement, ast.Assign):
        return {name for target in statement.targets for name in _target_names(target)}
    if isinstance(statement, ast.AnnAssign):
        return _target_names(statement.target)
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {statement.name}
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
        self._imports = _imports(tree, self._module)
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
        tree, _ = loaded
        imports = _imports(tree, module)
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
        tree, module_path = loaded
        imports = _imports(tree, module)
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

    def _load_module(self, module: str) -> tuple[ast.Module, Path] | None:
        if module == self._module:
            return self._tree, self._path
        path = _module_path(module, self._root)
        if path is None:
            return None
        return _read_module(path), path


def _imports(tree: ast.Module, current_module: str | None) -> dict[str, _Binding]:
    bindings: dict[str, _Binding] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                bound = alias.asname or alias.name.partition(".")[0]
                module = alias.name if alias.asname else alias.name.partition(".")[0]
                bindings[bound] = _Binding(module, None)
        elif isinstance(statement, ast.ImportFrom):
            module = _absolute_module(statement, current_module)
            if module is None:
                continue
            for alias in statement.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = _Binding(module, alias.name)
        else:
            for name in _directly_bound_names(statement):
                bindings.pop(name, None)
    return bindings


def _absolute_module(node: ast.ImportFrom, current_module: str | None) -> str | None:
    if node.level == 0:
        return node.module
    if current_module is None:
        return None
    package = current_module.split(".")[:-1]
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
    return (module, class_name) in _distribution_constructor_calls(root)


@lru_cache(maxsize=32)
def _distribution_constructor_calls(root: Path) -> frozenset[tuple[str, str]]:
    calls: set[tuple[str, str]] = set()
    for candidate in root.rglob("*.py"):
        if any(part.lower() in _SCAN_SKIP_PARTS | _MIGRATION_PARTS for part in candidate.parts) or is_test_path(
            candidate
        ):
            continue
        try:
            source = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if is_generated(candidate, source):
            continue
        try:
            tree = ast.parse(source, filename=str(candidate))
        except SyntaxError:
            continue
        module = _module_name(candidate, root)
        if module is None:
            continue
        imports = _imports(tree, module)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            resolved = _resolve_expression(node.func, imports)
            if resolved is None and isinstance(node.func, ast.Name):
                calls.add((module, node.func.id))
            elif resolved is not None and len(resolved) >= _QUALIFIED_NAME_PARTS:
                calls.add((".".join(resolved[:-1]), resolved[-1]))
    return frozenset(calls)

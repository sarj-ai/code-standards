"""SARJ095 — Constructor options must not hide runtime configuration fallback.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_hidden_constructor_fallback.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._first_party import distribution_root
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIGRATION_PARTS = frozenset({"alembic", "migration", "migrations", "versions"})
_DESCRIPTOR_DECORATORS = frozenset({"classmethod", "staticmethod"})
_SCAN_SKIP_PARTS = frozenset({".git", ".venv", "build", "dist", "node_modules", "site-packages", "venv"})


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
            if not hidden or not _has_composition_call(path, tree, class_node.name):
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
    for statement in init.body:
        available = candidates.keys() - rebound
        hidden.update(_statement_fallbacks(statement, available, resolver))
        rebound.update(_directly_bound_names(statement) & candidates.keys())
    return [parameter for name, parameter in candidates.items() if name in hidden]


def _statement_fallbacks(
    statement: ast.stmt,
    candidates: set[str],
    resolver: _RuntimeConfigResolver,
) -> set[str]:
    if isinstance(statement, ast.Assign):
        return _expression_fallbacks(statement.value, candidates, resolver)
    if isinstance(statement, ast.AnnAssign) and statement.value is not None:
        return _expression_fallbacks(statement.value, candidates, resolver)
    if not isinstance(statement, ast.If) or statement.orelse or len(statement.body) != 1:
        return set()
    parameter = _none_comparison_parameter(statement.test, candidates, expect_not=False)
    if parameter is None:
        return set()
    body = statement.body[0]
    value = body.value if isinstance(body, (ast.Assign, ast.AnnAssign)) else None
    return {parameter} if value is not None and resolver.is_runtime_config(value) else set()


def _expression_fallbacks(
    expression: ast.expr,
    candidates: set[str],
    resolver: _RuntimeConfigResolver,
) -> set[str]:
    if isinstance(expression, ast.BoolOp) and isinstance(expression.op, ast.Or):
        match expression.values:
            case [ast.Name(id=parameter), fallback] if parameter in candidates:
                return {parameter} if resolver.is_runtime_config(fallback) else set()
            case _:
                return set()
    if not isinstance(expression, ast.IfExp):
        return set()
    not_none = _none_comparison_parameter(expression.test, candidates, expect_not=True)
    if (
        not_none is not None
        and isinstance(expression.body, ast.Name)
        and expression.body.id == not_none
        and resolver.is_runtime_config(expression.orelse)
    ):
        return {not_none}
    is_none = _none_comparison_parameter(expression.test, candidates, expect_not=False)
    if (
        is_none is not None
        and isinstance(expression.orelse, ast.Name)
        and expression.orelse.id == is_none
        and resolver.is_runtime_config(expression.body)
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


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _target_names(element)}
    return set()


@final
class _RuntimeConfigResolver:
    def __init__(self, path: Path, tree: ast.Module) -> None:
        self._path = path
        self._tree = tree
        self._root = distribution_root(path)
        self._module = _module_name(path, self._root)
        self._imports = _imports(tree, self._module)
        self._settings_cache: dict[tuple[str, str], bool] = {}

    def is_runtime_config(self, expression: ast.expr) -> bool:
        return self._is_settings_attribute(expression)

    def _is_settings_attribute(self, expression: ast.expr) -> bool:
        parts = _attribute_parts(expression)
        if parts is None:
            return False
        root, *attributes = parts
        if not attributes:
            return False
        binding = self._imports.get(root)
        if binding is None:
            return self._module is not None and self._is_settings_symbol(self._module, root)
        if binding.symbol is not None:
            return self._is_settings_symbol(binding.module, binding.symbol)
        symbol, *setting_attributes = attributes
        return bool(setting_attributes) and self._is_settings_symbol(binding.module, symbol)

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
        if _assigned_from_class(tree, symbol, classes):
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


def _assigned_from_class(tree: ast.Module, symbol: str, classes: set[str]) -> bool:
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        else:
            continue
        if (
            value is not None
            and isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in classes
            and any(isinstance(target, ast.Name) and target.id == symbol for target in targets)
        ):
            return True
    return False


def _module_name(path: Path, root: Path | None) -> str | None:
    if root is None:
        return None
    try:
        relative = path.resolve().relative_to(root.resolve())
    except OSError, ValueError:
        return None
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if (root / "__init__.py").is_file():
        parts.insert(0, root.name)
    return ".".join(parts) if parts else None


def _module_path(module: str, root: Path | None) -> Path | None:
    if root is None:
        return None
    parts = module.split(".")
    if (root / "__init__.py").is_file() and parts and parts[0] == root.name:
        parts = parts[1:]
    relative = root.joinpath(*parts)
    candidates = (relative.with_suffix(".py"), relative / "__init__.py")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


@cache
def _read_module(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except OSError, SyntaxError:
        return ast.Module(body=[], type_ignores=[])


def _tail(expression: ast.expr) -> str | None:
    parts = _attribute_parts(expression)
    return parts[-1] if parts else None


def _has_composition_call(path: Path, tree: ast.Module, class_name: str) -> bool:
    if _tree_calls_class(tree, class_name):
        return True
    root = distribution_root(path)
    if root is None:
        return False
    return _distribution_calls_class(root, class_name)


@cache
def _distribution_calls_class(root: Path, class_name: str) -> bool:
    for candidate in root.rglob("*.py"):
        if any(part in _SCAN_SKIP_PARTS for part in candidate.parts) or is_test_path(candidate):
            continue
        if _tree_calls_class(_read_module(candidate), class_name):
            return True
    return False


def _tree_calls_class(tree: ast.Module, class_name: str) -> bool:
    return any(isinstance(node, ast.Call) and _tail(node.func) == class_name for node in ast.walk(tree))

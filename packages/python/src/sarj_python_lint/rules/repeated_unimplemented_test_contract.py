from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._imports import ABC_SOURCES, TYPING_SOURCES, ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


type _Method = ast.FunctionDef | ast.AsyncFunctionDef
_BUILTINS = frozenset({"str", "bytes", "int", "float", "bool", "object", "list", "dict", "tuple", "set", "frozenset"})
_REFLECTION = frozenset({"globals", "locals", "vars", "eval", "exec", "getattr", "setattr", "delattr", "__import__"})
_IDENTITY = frozenset(
    {"__dict__", "__mro__", "__base__", "__bases__", "__func__", "__code__", "__annotations__", "__defaults__"}
)
_MRO_HOOKS = frozenset({"__init_subclass__", "__mro_entries__"})


@final
class RepeatedUnimplementedTestContract(ProjectRule):
    id = "repeated-unimplemented-test-contract"
    code = "SARJ490"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Share repeated typed fail-fast abstract operations between test fakes.",
        rationale="Copied unconfigured operations add test support code and drift independently when a contract changes.",
        remediation="Use one explicit typed strict test base for the contract. Preserve each leaf fake's configured behavior and failure timing; verify that the complete base and wiring reduce maintained code.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored test classes directly inheriting one resolved first-party ABC are considered; decorated classes, metaclasses, generic classes and reflective modules are excluded.",
            "Duplicate operations must implement the same abstract member with identical resolved typed signatures and immutable literal defaults. Only bare built-in raise NotImplementedError bodies, optionally with typing.override, qualify.",
            "Methods with messages, side effects, generator bodies, other decorators, captured defaults or super dispatch remain leaf-owned. Signatures must match the abstract contract; unresolved names are not guessed.",
            "Visible non-call observations of abstract operations, imported namespace writes and subclass/MRO hooks exclude a contract family. String annotation references are unresolved; external or dynamic observations still require review.",
            "One advisory is emitted per duplicate class, retaining the first source occurrence as the comparison owner. No autofix or dynamic mock generation; intentional independent contracts require a reasoned exception.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-strict-operation",
                title="Two test fakes repeat one unconfigured operation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_store.py",
                        "from abc import ABC, abstractmethod\nclass Store(ABC):\n    @abstractmethod\n    def read(self, key: str) -> str:\n        pass\nclass First(Store):\n    def read(self, key: str) -> str:\n        raise NotImplementedError\nclass Second(Store):\n    def read(self, key: str) -> str:\n        raise NotImplementedError\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="configured-operation",
                title="Configured fake behavior belongs to the leaf",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_store.py",
                        "from abc import ABC, abstractmethod\nclass Store(ABC):\n    @abstractmethod\n    def read(self, key: str) -> str:\n        pass\nclass First(Store):\n    def read(self, key: str) -> str:\n        raise NotImplementedError\nclass Second(Store):\n    def read(self, key: str) -> str:\n        return key\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def __init__(self) -> None:
        self._duplicates: dict[SymbolRef, dict[tuple[Path, str], list[str]]] = {}

    @override
    def prepare(self, indexes: ProjectIndexSet) -> None:
        super().prepare(indexes)
        self._duplicates.clear()

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        indexes = self.project_indexes
        if indexes is None or not is_test_path(context.path) or context.generated or context.tree is None:
            return []
        unit = indexes.unit(context.path)
        if unit is None or not _usable_unit(unit):
            return []
        imports = ImportIndex.from_tree(context.tree, module_scope_only=True)
        findings: list[Diagnostic] = []
        for node in context.tree.body:
            if not isinstance(node, ast.ClassDef) or not _plain_class(node, imports):
                continue
            base = indexes.class_for(unit, node.bases[0])
            if base is None or not _stable_base(unit, node.bases[0]):
                continue
            if base.symbol not in self._duplicates:
                self._duplicates[base.symbol] = _duplicates(indexes, base.symbol)
            methods = self._duplicates[base.symbol].get((unit.path, node.name), [])
            if methods and not is_suppressed(context.source_lines, node.lineno, self.code):
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=f"Test fake repeats fail-fast `{base.symbol.name}` operations: {', '.join(methods)}. Share an explicit typed strict test base, preserving configured leaf behavior and failure timing.",
                    )
                )
        return findings


def _usable_unit(unit: SourceUnit) -> bool:
    if unit.tree is None or is_generated(unit.path, unit.source) or _namespace_writes(unit.tree):
        return False
    return not any(
        (isinstance(node, ast.Name) and node.id in _REFLECTION)
        or (isinstance(node, ast.Attribute) and node.attr in _IDENTITY | _REFLECTION)
        or (isinstance(node, ast.alias) and node.name == "*")
        for node in ast.walk(unit.tree)
    )


def _namespace_writes(tree: ast.Module) -> bool:
    imports = ImportIndex.from_tree(tree, module_scope_only=True)
    namespaces = {name for name, target in imports.bindings.items() if target.symbol is None}
    return any(
        isinstance(node, ast.Attribute)
        and not isinstance(node.ctx, ast.Load)
        and any(isinstance(root, ast.Name) and root.id in namespaces for root in ast.walk(node.value))
        for node in ast.walk(tree)
    )


def _plain_class(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return (
        len(node.bases) == 1
        and not (node.decorator_list or node.keywords or node.type_params)
        and not _mro_sensitive(node, imports)
        and all(
            isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.Pass)
            or (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
            for statement in node.body
        )
    )


def _mro_sensitive(node: ast.ClassDef, imports: ImportIndex) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name in _MRO_HOOKS:
            return True
        if isinstance(child, ast.Name) and child.id == "super":
            return True
        if isinstance(child, ast.Attribute) and child.attr == "super":
            return True
        if isinstance(child, ast.expr) and imports.resolves(child, sources=frozenset({"builtins"}), symbol="super"):
            return True
        if (
            isinstance(child, ast.ImportFrom)
            and child.module == "builtins"
            and any(alias.name == "super" for alias in child.names)
        ):
            return True
    return False


def _duplicates(indexes: ProjectIndexSet, symbol: SymbolRef) -> dict[tuple[Path, str], list[str]]:
    contract = _abstract_contract(indexes, symbol)
    if contract is None:
        return {}
    unit, abstract = contract
    operations = frozenset(abstract)
    if _observed_operations(unit, operations):
        return {}
    groups: dict[str, list[tuple[Path, str]]] = {}
    for path, name in sorted(indexes.direct_subclasses(unit, symbol.name), key=lambda item: (str(item[0]), item[1])):
        candidate = indexes.unit(path)
        if candidate is None or candidate.tree is None:
            continue
        if not _usable_unit(candidate) or _observed_operations(candidate, operations):
            return {}
        node = _test_fake(candidate, name)
        if node is None:
            continue
        for method in _strict_operations(node, candidate, abstract):
            groups.setdefault(method, []).append((candidate.path, name))
    duplicates: dict[tuple[Path, str], list[str]] = {}
    for method, owners in sorted(groups.items()):
        for owner in owners[1:]:
            duplicates.setdefault(owner, []).append(method)
    return duplicates


def _abstract_contract(indexes: ProjectIndexSet, symbol: SymbolRef) -> tuple[SourceUnit, dict[str, str | None]] | None:
    unit = indexes.source_unit(symbol.module)
    if unit is None or unit.tree is None or not _usable_unit(unit):
        return None
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    contract = next(
        (node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == symbol.name), None
    )
    if (
        contract is None
        or not _stable_local_class(unit, symbol.name)
        or not _plain_class(contract, imports)
        or not imports.resolves(contract.bases[0], sources=ABC_SOURCES, symbol="ABC")
    ):
        return None
    abstract = {
        method.name: _signature(method, unit, imports)
        for method in contract.body
        if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
        and len(method.decorator_list) == 1
        and imports.resolves(method.decorator_list[0], sources=ABC_SOURCES, symbol="abstractmethod")
    }
    return unit, abstract


def _test_fake(unit: SourceUnit, name: str) -> ast.ClassDef | None:
    if unit.tree is None or not is_test_path(unit.path) or not _stable_local_class(unit, name):
        return None
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    node = next((child for child in unit.tree.body if isinstance(child, ast.ClassDef) and child.name == name), None)
    if node is None or not _plain_class(node, imports) or not _stable_base(unit, node.bases[0]):
        return None
    return node


def _observed_operations(unit: SourceUnit, operations: frozenset[str]) -> bool:
    return unit.tree is None or any(
        isinstance(child, ast.Attribute)
        and child.attr in operations
        and not (isinstance(parent, ast.Call) and parent.func is child)
        for parent in ast.walk(unit.tree)
        for child in ast.iter_child_nodes(parent)
    )


def _strict_operations(node: ast.ClassDef, unit: SourceUnit, abstract: dict[str, str | None]) -> list[str]:
    if unit.tree is None:
        return []
    imports = ImportIndex.from_tree(unit.tree)
    if not imports.builtin_is_unshadowed("NotImplementedError"):
        return []
    return [
        method.name
        for method in node.body
        if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
        and abstract.get(method.name) is not None
        and _bare_stub(method, imports)
        and _signature(method, unit, imports) == abstract[method.name]
    ]


def _bare_stub(method: _Method, imports: ImportIndex) -> bool:
    if any(
        not imports.resolves(decorator, sources=TYPING_SOURCES, symbol="override")
        for decorator in method.decorator_list
    ):
        return False
    if len(method.body) != 1 or not isinstance(method.body[0], ast.Raise):
        return False
    error = method.body[0]
    return error.cause is None and isinstance(error.exc, ast.Name) and error.exc.id == "NotImplementedError"


def _stable_local_class(unit: SourceUnit, name: str) -> bool:
    if unit.tree is None:
        return False
    return sum(
        isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
        for node in ast.walk(unit.tree)
    ) == 1 and not any(
        (isinstance(node, ast.Name) and node.id == name and not isinstance(node.ctx, ast.Load))
        or (isinstance(node, ast.arg) and node.arg == name)
        for node in ast.walk(unit.tree)
    )


def _stable_base(unit: SourceUnit, expression: ast.expr) -> bool:
    if unit.tree is None:
        return False
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    return imports.resolved_qualified_name(expression) is not None or (
        isinstance(expression, ast.Name) and _stable_local_class(unit, expression.id)
    )


def _signature(method: _Method, unit: SourceUnit, imports: ImportIndex) -> str | None:
    arguments = method.args
    if method.type_params or arguments.vararg is not None or arguments.kwarg is not None or method.returns is None:
        return None
    positional = [*arguments.posonlyargs, *arguments.args]
    if not positional or positional[0].arg != "self" or positional[0].annotation is not None:
        return None
    keys = [_type_key(argument.annotation, unit, imports) for argument in (*positional[1:], *arguments.kwonlyargs)]
    result = _type_key(method.returns, unit, imports)
    defaults = [*arguments.defaults, *(default for default in arguments.kw_defaults if default is not None)]
    if (
        result is None
        or any(key is None for key in keys)
        or any(not isinstance(default, ast.Constant) for default in defaults)
    ):
        return None
    return repr(
        (
            type(method).__name__,
            len(arguments.posonlyargs),
            tuple(argument.arg for argument in (*positional, *arguments.kwonlyargs)),
            keys,
            result,
            tuple(ast.dump(default) for default in arguments.defaults),
            tuple(None if default is None else ast.dump(default) for default in arguments.kw_defaults),
        )
    )


def _type_key(node: ast.expr | None, unit: SourceUnit, imports: ImportIndex) -> str | None:
    if node is None or unit.tree is None:
        return None
    match node:
        case ast.Name():
            return _name_type_key(node, unit, imports)
        case ast.Attribute():
            return imports.resolved_qualified_name(node)
        case ast.Constant(value=str()):
            return None
        case ast.Constant():
            return ast.dump(node)
        case _:
            return _compound_type_key(node, unit, imports)


def _name_type_key(node: ast.Name, unit: SourceUnit, imports: ImportIndex) -> str | None:
    if unit.tree is None:
        return None
    name = node.id
    if name in _BUILTINS and imports.builtin_is_unshadowed(name):
        return f"builtins.{name}"
    imported = imports.resolved_qualified_name(node)
    if imported is not None:
        return imported
    if any(isinstance(child, ast.ClassDef) and child.name == name for child in unit.tree.body) and _stable_local_class(
        unit, name
    ):
        return f"{unit.module}.{name}"
    return None


def _compound_type_key(node: ast.expr, unit: SourceUnit, imports: ImportIndex) -> str | None:
    match node:
        case ast.Subscript(value=value, slice=argument):
            kind, parts = "subscript", (value, argument)
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            kind, parts = "union", (left, right)
        case ast.Tuple(elts=elements):
            kind, parts = "tuple", tuple(elements)
        case _:
            return None
    keys = tuple(_type_key(part, unit, imports) for part in parts)
    return repr((kind, keys)) if all(key is not None for key in keys) else None
